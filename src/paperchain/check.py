from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .citations import (
    find_hidden_citations,
    find_unrecognized,
    mask_code,
    parse_citations,
    scan_markdown,
)
from .reference_log import (
    LOG_RELATIVE,
    read_events,
    reblessed_since_last_build,
    reference_fingerprint,
)
from .errors import Finding, PaperchainError
from .extract import SUPPORTED_SUFFIXES, Extraction, extract, render_text_file
from .library import (
    KNOWN_STYLES,
    bibtex_conversion_hint,
    duplicate_bibliography_ids,
    load_csl_entries,
    style_problem,
    style_sha256,
    titles_equal,
)
from .project import Project
from .util import normalize_for_match, sha256_file, word_count

PLACEHOLDER_RE = re.compile(r"\b(TODO|TKTK|FIXME)\b|\[\[|lorem ipsum", re.IGNORECASE)
# XXX is also a Roman numeral ("Super Bowl XXX"), so only treat it as a
# placeholder when it stands alone on a line or sits in brackets.
XXX_PLACEHOLDER_RE = re.compile(r"(?m)^\s{0,3}(?:#{1,6}\s+|[-*+]\s+)?XXX\s*$|\[\s*XXX\s*\]")

# Pandoc reads document metadata from YAML. An allow-list is safer than a
# deny-list: `references:` can define a whole bibliography inline, and a key
# with an escape or a complex-key form should not slip past the check.
FRONT_MATTER_ALLOW = {
    "abstract",
    "abstract-title",
    "author",
    "authors",
    "category",
    "classoption",
    "colorlinks",
    "date",
    "description",
    "dir",
    "documentclass",
    "fontsize",
    "geometry",
    "indent",
    "keywords",
    "lang",
    "language",
    "linestretch",
    "linkcolor",
    "lof",
    "lot",
    "margin",
    "number-sections",
    "numbersections",
    "papersize",
    "section-numbering",
    "subject",
    "subtitle",
    "title",
    "title-prefix",
    "titlepage",
    "toc",
    "toc-depth",
    "toccolor",
    "urlcolor",
}


_YAML_OPEN_RE = re.compile(r"^ {0,3}-{3,}\s*$")
_YAML_CLOSE_RE = re.compile(r"^ {0,3}(?:-{3,}|\.{3})\s*$")
_YAML_KEY_RE = re.compile(r"""^(["']?)(.+?)\1\s*:""")


def _strip_blockquote(line: str) -> str:
    """Remove `> ` markers from the front of a line, keeping its indent."""
    while True:
        match = re.match(r"^ {0,3}> ?", line)
        if not match:
            return line
        line = line[match.end() :]


def _strip_container(line: str) -> str:
    """Remove blockquote and list markers for block-delimiter detection."""
    while True:
        stripped = _strip_blockquote(line)
        if stripped != line:
            line = stripped
            continue
        match = re.match(r"^ {0,3}(?:[-*+]|\d+[.)])\s+", line)
        if not match:
            return line
        line = line[match.end() :]


def _flow_mapping_keys(line: str) -> list[str]:
    """Top-level keys of a one-line `{key: value, ...}` YAML mapping."""
    value = line.strip()
    if not (value.startswith("{") and value.endswith("}")):
        return []
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    for char in value[1:-1]:
        if quote:
            if char == quote:
                quote = ""
            current.append(char)
            continue
        if char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    keys: list[str] = []
    for part in parts:
        match = _YAML_KEY_RE.match(part.strip())
        if match:
            keys.append(match.group(2).strip().lower())
    return keys


def _yaml_key_entries(lines: list[str], start: int, end: int) -> list[tuple[str, int]]:
    """Top-level (key, line) pairs between two metadata delimiters.

    `lines` already have blockquote markers removed but retain list markers and
    indentation, so a YAML sequence under an allowed key is not mistaken for a
    second top-level key.
    """
    content = lines[start + 1 : end]
    key_indent: int | None = None
    for line in content:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "- ")):
            continue
        key_indent = len(line) - len(line.lstrip(" "))
        break
    if key_indent is None:
        return []

    found: list[tuple[str, int]] = []
    for offset, line in enumerate(content, start=start + 2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent != key_indent:
            continue
        value = line[key_indent:]
        if value.startswith("- "):
            continue
        if value.startswith("?"):
            # YAML complex key: `? key` or a lone `?` with the key below.
            name = value[1:].strip().strip("'\"") or "?"
            found.append((name.lower(), offset))
            continue
        match = _YAML_KEY_RE.match(value)
        if match:
            found.append((match.group(2).strip().lower(), offset))
            continue
        for key in _flow_mapping_keys(value):
            found.append((key, offset))
    return found


def front_matter_keys(text: str) -> dict[str, int] | None:
    """Top-level keys of every YAML metadata block, mapped to their lines.

    Pandoc accepts a YAML block anywhere in the document, not only at the top,
    and a block can sit in a blockquote or a list item. A block that is not
    first must be preceded by a blank line. Code fences are masked first so a
    `---` inside one is not read as metadata.
    """
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    detect_lines = [_strip_container(line) for line in lines]
    masked_lines = mask_code("\n".join(detect_lines)).split("\n")
    content_lines = [_strip_blockquote(line) for line in lines]
    keys: dict[str, int] = {}
    index = 0
    while index < len(lines):
        if not _YAML_OPEN_RE.match(masked_lines[index]):
            index += 1
            continue
        if index > 0 and detect_lines[index - 1].strip():
            # A setext underline or a thematic break, not a metadata block.
            index += 1
            continue
        closing = next(
            (
                end
                for end in range(index + 1, len(lines))
                if _YAML_CLOSE_RE.match(masked_lines[end])
            ),
            None,
        )
        if closing is None:
            # An unclosed block is not metadata to Pandoc either.
            index += 1
            continue
        for name, line in _yaml_key_entries(content_lines, index, closing):
            keys.setdefault(name, line)
        index = closing + 1
    return keys or None


@dataclass
class Report:
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    citations: list[dict] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_text(
    project: Project, key: str
) -> tuple[list[str] | None, dict | None, str | None]:
    json_path = project.text_dir / f"{key}.json"
    if not json_path.is_file():
        return None, None, "text_missing"
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, "text_invalid"
    if not isinstance(payload, dict):
        return None, None, "text_invalid"
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        return None, None, "text_invalid"
    pages: list[str] = []
    for entry in raw_pages:
        if isinstance(entry, dict) and isinstance(entry.get("text"), str):
            pages.append(entry["text"])
        elif isinstance(entry, str):
            pages.append(entry)
        else:
            return None, None, "text_invalid"
    return pages, payload, None


class _TextCache:
    def __init__(self, project: Project):
        self.project = project
        self._raw: dict[str, tuple[list[str] | None, dict | None, str | None]] = {}
        self._normalized: dict[tuple[str, bool], list[str]] = {}

    def get(self, key: str) -> tuple[list[str] | None, dict | None, str | None]:
        if key not in self._raw:
            self._raw[key] = _load_text(self.project, key)
        return self._raw[key]

    def normalized(self, key: str, join_hyphenation: bool = True) -> list[str]:
        cache_key = (key, join_hyphenation)
        if cache_key not in self._normalized:
            pages, _, _ = self.get(key)
            self._normalized[cache_key] = [
                normalize_for_match(page, join_hyphenation=join_hyphenation)
                for page in (pages or [])
            ]
        return self._normalized[cache_key]


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _starts_wordish(needle: str) -> bool:
    first = needle[0]
    if _is_word_char(first):
        return True
    # "-5" and ".5" are number fragments: they must not match inside "1-5" or
    # "1.5" just because their first character is punctuation.
    return first in "-.+" and len(needle) > 1 and needle[1].isdigit()


def _ends_wordish(needle: str) -> bool:
    last = needle[-1]
    if _is_word_char(last):
        return True
    return last in "-.+" and len(needle) > 1 and needle[-2].isdigit()


def _find_span(haystack: str, needle: str) -> int | None:
    """Find needle as a whole-word-ish span, not inside a larger word."""
    if not needle:
        return None
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            return None
        before = haystack[index - 1] if index > 0 else " "
        after_index = index + len(needle)
        after = haystack[after_index] if after_index < len(haystack) else " "
        left_ok = not (_is_word_char(before) and _starts_wordish(needle))
        right_ok = not (_is_word_char(after) and _ends_wordish(needle))
        if left_ok and right_ok:
            return index
        start = index + 1


def verify_quote(
    normalized_pages: list[str],
    quote: str,
    wanted_pages: list[int],
    join_hyphenation: bool = True,
) -> int | None:
    needle = normalize_for_match(quote, join_hyphenation=join_hyphenation)
    if not needle:
        return None
    for number in wanted_pages:
        if 1 <= number <= len(normalized_pages) and _find_span(
            normalized_pages[number - 1], needle
        ) is not None:
            return number
    for number, page in enumerate(normalized_pages, start=1):
        if _find_span(page, needle) is not None:
            return number
    return None


def _check_bibliography_and_style(project: Project, report: Report, bibliography: Path | None) -> None:
    """Zotero export drift and the project's citation style.

    The CSL JSON is metadata, not evidence, so it is hashed rather than made
    read-only. A re-export that changes titles or authors changes the built
    bibliography; this makes that change visible instead of silent.
    """
    manifest = project.manifest
    style = manifest.style

    # The export is hashed whether or not a style is set: citeproc takes titles,
    # authors and years from it whenever it exists, so an unnoticed edit would
    # change the built bibliography.
    if manifest.bibliography_sha256:
        if bibliography is None or not bibliography.is_file():
            report.errors.append(
                Finding(
                    "bibliography_missing",
                    "the Zotero export recorded by `lock` is gone",
                    file="paper.toml",
                    hint="restore References/library.json, or run `paperchain lock --accept-changes` if you removed it on purpose",
                )
            )
        elif sha256_file(bibliography) != manifest.bibliography_sha256:
            report.errors.append(
                Finding(
                    "bibliography_hash_mismatch",
                    f"{project.relative(bibliography)} changed since `lock`",
                    file=project.relative(bibliography),
                    hint="a Zotero re-export changes titles, authors and the reference list; review it, then run `paperchain lock --accept-changes`",
                )
            )
    elif manifest.locked_at and bibliography is not None and bibliography.is_file():
        report.errors.append(
            Finding(
                "bibliography_not_locked",
                f"{project.relative(bibliography)} was not hashed by `lock`",
                file="paper.toml",
                hint="run `paperchain lock --accept-changes` so a later re-export is detected",
            )
        )

    if not style:
        # Without a style there is no CSL to verify.
        return

    csl = project.csl_path
    if manifest.csl_sha256 and csl is not None and csl.is_file() and style_sha256(csl) != manifest.csl_sha256:
        report.errors.append(
            Finding(
                "csl_hash_mismatch",
                f"{project.relative(csl)} changed since `lock`",
                file=project.relative(csl),
                hint="review the style file and any accepted-csl-ids.txt beside it, then run `paperchain lock --accept-changes`",
            )
        )
    elif manifest.locked_at and csl is not None and csl.is_file() and not manifest.csl_sha256:
        report.errors.append(
            Finding(
                "csl_not_locked",
                f"{project.relative(csl)} was not hashed by `lock`",
                file="paper.toml",
                hint="run `paperchain lock --accept-changes` so a changed style is detected",
            )
        )

    if style not in KNOWN_STYLES:
        report.errors.append(
            Finding(
                "style_unknown",
                f"[build] style = {style!r} is not supported",
                file="paper.toml",
                hint=f"supported: {', '.join(sorted(KNOWN_STYLES))}; or remove the line",
            )
        )
        return
    if bibliography is None or not bibliography.is_file():
        report.errors.append(
            Finding(
                "style_requires_bibliography",
                f"style {style} needs the Zotero export; without it the built-in author-year citations would be used",
                file="paper.toml",
                hint="export CSL JSON (Better BibTeX keys) from Zotero to References/library.json",
            )
        )
    if csl is None or not csl.is_file():
        report.errors.append(
            Finding(
                "style_requires_csl",
                f"style {style} needs a CSL file, and [build] csl is not set or does not exist",
                file="paper.toml",
                hint=f"download the NLM/Vancouver CSL from https://www.zotero.org/styles/vancouver (the current name of the style it serves), save it as styles/{style}.csl and set csl = \"styles/{style}.csl\" under [build]",
            )
        )
    else:
        problem = style_problem(csl, style)
        if problem:
            report.errors.append(
                Finding(
                    "csl_not_vancouver" if style == "vancouver" else "csl_style_mismatch",
                    f"{project.relative(csl)} is not a {style} style: {problem}",
                    file=project.relative(csl),
                    hint="use the NLM/Vancouver CSL from https://www.zotero.org/styles/vancouver, or list a confirmed variant id in styles/accepted-csl-ids.txt",
                )
            )


def run_check(
    project: Project,
    strict: bool = False,
    include_candidates: bool = True,
    reextract: bool = False,
) -> Report:
    report = Report()
    manifest = project.manifest
    stats = {
        "sources": len(manifest.sources),
        "pages": 0,
        "citations": 0,
        "citations_with_page": 0,
        "citations_with_quote": 0,
        "quotes_verified": 0,
        "words": 0,
    }

    # -- the paper -------------------------------------------------------
    text = ""
    if not project.paper_md.is_file():
        report.errors.append(
            Finding(
                "paper_missing",
                "Paper/paper.md does not exist",
                file="Paper/paper.md",
                hint="create the draft there; Output/*.docx is generated from it",
            )
        )
    else:
        text = project.paper_md.read_text(encoding="utf-8")
        if not text.strip():
            report.errors.append(
                Finding("paper_empty", "Paper/paper.md is empty", file="Paper/paper.md")
            )
        stats["words"] = word_count(text)
        for name, line in (front_matter_keys(text) or {}).items():
            if name not in FRONT_MATTER_ALLOW:
                report.errors.append(
                    Finding(
                        "front_matter_overrides_citations",
                        f"YAML metadata sets {name!r}, which is not in the allowed metadata list",
                        file="Paper/paper.md",
                        line=line,
                        data={"key": name},
                        hint="remove it; only document metadata such as title, author, date, abstract and keywords is allowed, and style, csl, bibliography and references belong in paper.toml or the Zotero export",
                    )
                )

    # -- the original manuscript -----------------------------------------
    # The manuscript is never converted in place or locked. Import records its
    # hash so a replacement is visible instead of silently leaving paper.md stale.
    manuscript = project.manifest.manuscript_path
    if manuscript:
        manuscript_path = project.root / manuscript
        if not manuscript_path.is_file():
            report.errors.append(
                Finding(
                    "manuscript_missing",
                    f"the original manuscript is missing: {manuscript}",
                    file=manuscript,
                    hint="restore it, or run `paperchain import` to register a new one",
                )
            )
        elif not project.manifest.manuscript_sha256:
            report.errors.append(
                Finding(
                    "manuscript_unhashed",
                    f"{manuscript} has no recorded hash",
                    file=manuscript,
                    hint="run `paperchain import --force` so a later replacement is detectable",
                )
            )
        else:
            actual = sha256_file(manuscript_path)
            if actual != project.manifest.manuscript_sha256:
                report.errors.append(
                    Finding(
                        "manuscript_hash_mismatch",
                        f"{manuscript} changed after it was imported",
                        file=manuscript,
                        data={
                            "expected": project.manifest.manuscript_sha256,
                            "actual": actual,
                        },
                        hint="re-run `paperchain import --force` (the current draft is saved as paper.md.bak), then review Paper/paper.md",
                    )
                )

    # -- sources and their hashes ---------------------------------------
    cache = _TextCache(project)
    normalized_hash_ok = True
    for source in manifest.sources:
        path = project.root / source.path
        if not path.is_file():
            report.errors.append(
                Finding(
                    "source_missing",
                    f"reference file is missing: {source.path}",
                    file=source.path,
                    data={"key": source.key},
                    hint=f"restore the file, or remove the [[sources]] entry for {source.key} and run `paperchain convert`",
                )
            )
            normalized_hash_ok = False
            continue

        actual = sha256_file(path)
        if not source.sha256:
            report.errors.append(
                Finding(
                    "source_unhashed",
                    f"{source.key} has no recorded hash",
                    file=source.path,
                    hint="run `paperchain convert`, or restore paper.toml from version control; an unhashed reference cannot be verified",
                )
            )
        elif actual != source.sha256:
            report.errors.append(
                Finding(
                    "source_hash_mismatch",
                    f"{source.path} changed after it was locked",
                    file=source.path,
                    data={"key": source.key, "expected": source.sha256, "actual": actual},
                    hint="references are read-only for a reason: restore the original, or ask the human to unlock and relock",
                )
            )
            normalized_hash_ok = False

        json_path = project.text_dir / f"{source.key}.json"
        pages, payload, text_error = cache.get(source.key)
        if text_error:
            report.errors.append(
                Finding(
                    text_error,
                    f"converted text is missing or unreadable for {source.key}",
                    file=project.relative(json_path),
                    data={"key": source.key},
                    hint=f"run `paperchain convert --only {source.key}`",
                )
            )
        else:
            stats["pages"] += len(pages or [])
            recorded_source = str((payload or {}).get("sha256", "") or "")
            if recorded_source and recorded_source != actual:
                report.errors.append(
                    Finding(
                        "text_stale",
                        f"converted text for {source.key} was built from a different version of the original",
                        file=project.relative(json_path),
                        data={"key": source.key},
                        hint=f"run `paperchain convert --force --accept-changes --only {source.key}`",
                    )
                )
                normalized_hash_ok = False
            if reextract:
                try:
                    fresh = extract(path)
                except PaperchainError as exc:
                    report.errors.append(
                        Finding(
                            "text_stale",
                            f"cannot re-extract {source.key}: {exc.message}",
                            file=source.path,
                            data={"key": source.key},
                        )
                    )
                    normalized_hash_ok = False
                else:
                    if fresh.pages != (pages or []):
                        report.errors.append(
                            Finding(
                                "text_stale",
                                f"converted text for {source.key} does not match a fresh extraction",
                                file=project.relative(json_path),
                                data={"key": source.key},
                                hint=(
                                    f"run `paperchain convert --force --accept-changes --only {source.key}`; "
                                    f"if the original did not change, the extractor version may differ "
                                    f"(converted with {source.converter or 'unknown'})"
                                ),
                            )
                        )
                        normalized_hash_ok = False
            if not source.text_sha256:
                report.errors.append(
                    Finding(
                        "text_unhashed",
                        f"{source.key} converted text has no recorded hash",
                        file=project.relative(json_path),
                        hint="run `paperchain convert`, or restore paper.toml from version control; unhashed text cannot be verified",
                    )
                )
            elif sha256_file(json_path) != source.text_sha256:
                report.errors.append(
                    Finding(
                        "text_hash_mismatch",
                        f"converted text for {source.key} was edited after conversion",
                        file=project.relative(json_path),
                        data={"key": source.key},
                        hint="run `paperchain unlock`, then `paperchain convert --force --accept-changes`, then `paperchain lock`",
                    )
                )
                normalized_hash_ok = False

            txt_path = project.text_dir / f"{source.key}.txt"
            if not txt_path.is_file():
                report.errors.append(
                    Finding(
                        "text_file_missing",
                        f"{project.relative(txt_path)} is missing",
                        file=project.relative(txt_path),
                        hint="run `paperchain convert --force`; this is the file the writer reads",
                    )
                )
            else:
                expected = render_text_file(
                    source.key,
                    Path(str((payload or {}).get("original", source.path))).name,
                    Extraction(
                        pages=pages or [],
                        converter=str((payload or {}).get("converter", source.converter) or "unknown"),
                        page_map_estimated=bool((payload or {}).get("page_map_estimated", False)),
                    ),
                )
                try:
                    actual_txt = txt_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    actual_txt = None
                if actual_txt != expected:
                    report.errors.append(
                        Finding(
                            "text_file_mismatch",
                            f"{project.relative(txt_path)} does not match the anchored page map",
                            file=project.relative(txt_path),
                            data={"key": source.key},
                            hint="run `paperchain convert --force` to regenerate it from the JSON",
                        )
                    )

    # -- reference files that are not in the manifest ---------------------
    if project.references_dir.is_dir():
        managed = {(project.root / source.path).resolve() for source in manifest.sources}
        for path in project.iter_reference_files():
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                report.warnings.append(
                    Finding(
                        "unsupported_reference",
                        f"{path.name} is not a supported reference type",
                        severity="warning",
                        file=project.relative(path),
                        hint="supported types are PDF, DOCX, TXT and MD; remove or convert the file",
                    )
                )
            elif path.resolve() not in managed:
                report.errors.append(
                    Finding(
                        "unmanaged_source",
                        f"{path.name} is under References/ but was never converted",
                        file=project.relative(path),
                        hint="run `paperchain convert`, then `paperchain lock`",
                    )
                )

    # -- citations -------------------------------------------------------
    masked_text, mask_issues = scan_markdown(text)
    for issue in mask_issues:
        report.errors.append(
            Finding(
                issue.kind,
                "an unterminated "
                + ("HTML comment" if issue.kind == "unterminated_comment" else "code fence")
                + " hides the rest of the document from check",
                file="Paper/paper.md",
                line=issue.line,
                hint="close it, or the citations after it are never verified",
            )
        )

    citations = parse_citations(text)
    stats["citations"] = len(citations)
    cited_source_keys: set[str] = set()

    bibliography = project.bibliography_path
    bibliography_key_set: set[str] | None = None
    bibliography_entries: dict[str, dict] = {}
    duplicate_ids: list[str] = []
    duplicate_ids_used: set[str] = set()
    if bibliography is not None:
        try:
            bibliography_entries = load_csl_entries(bibliography)
            bibliography_key_set = set(bibliography_entries)
            duplicate_ids = duplicate_bibliography_ids(bibliography)
            duplicate_ids_used = {
                manifest.citation_key_for(source)
                for source in manifest.sources
                if manifest.citation_key_for(source) in duplicate_ids
            }
        except PaperchainError as exc:
            code, message, hint = exc.code, exc.message, exc.hint
            bibtex = project.references_dir / "library.bib"
            if code == "bibliography_missing" and bibtex.is_file():
                code = "bibliography_bibtex_unsupported"
                message = (
                    f"{project.relative(bibtex)} is a BibTeX export, "
                    f"but {project.relative(bibliography)} does not exist"
                )
                hint = bibtex_conversion_hint(bibtex)
            report.errors.append(
                Finding(
                    code,
                    message,
                    file=project.relative(bibliography),
                    hint=hint,
                )
            )

    _check_bibliography_and_style(project, report, bibliography)

    # -- source metadata --------------------------------------------------
    # convert fills title/authors from PDF or DOCX metadata, which is often
    # wrong ("Administrator", a filename, no year). A warning keeps that out
    # of the citation and reference list until a human confirms it.
    for source in manifest.sources:
        missing = [
            label
            for label, value in (("authors", source.authors.strip()), ("year", source.year))
            if not value
        ]
        if missing:
            report.warnings.append(
                Finding(
                    "source_metadata_unconfirmed",
                    f"{source.key} has no {' or '.join(missing)} in paper.toml",
                    severity="warning",
                    file="paper.toml",
                    data={"key": source.key, "missing": missing},
                    hint="set authors and year in paper.toml; extraction cannot tell whether the metadata names the right work",
                )
            )
        entry = bibliography_entries.get(manifest.citation_key_for(source))
        if entry and source.title and not titles_equal(source.title, entry.get("title")):
            # Once a citation_key is set, citeproc will print that entry for
            # this source. A different title is then a wrong reference, not a
            # metadata warning; without a key the internal key is only a guess.
            severity = "error" if source.citation_key else "warning"
            finding = Finding(
                "source_metadata_mismatch",
                f"{source.key}: paper.toml title and the bibliography entry describe different works",
                severity=severity,
                file="paper.toml",
                data={
                    "key": source.key,
                    "source_title": source.title,
                    "bibliography_title": str(entry.get("title", "")),
                },
                hint=(
                    "the citation_key points citeproc at a different work; fix the title, "
                    "or set citation_key to the entry that matches this PDF"
                    if source.citation_key
                    else "check that the PDF under this key is the work the CSL entry names"
                ),
            )
            (report.errors if source.citation_key else report.warnings).append(finding)

    for snippet, line in find_unrecognized(masked_text, citations):
        report.errors.append(
            Finding(
                "citation_unrecognized",
                f"{snippet!r} looks like a citation but is not in the supported form",
                file="Paper/paper.md",
                line=line,
                data={"snippet": snippet},
                hint='use [@key, p. 12]; [see @key], [-@key], a bare @key and a bracketed @@key are not supported',
            )
        )

    for snippet, line in find_hidden_citations(masked_text):
        report.errors.append(
            Finding(
                "citation_unrecognized",
                f"{snippet!r} will render as a citation but cannot be verified",
                file="Paper/paper.md",
                line=line,
                data={"snippet": snippet},
                hint="write the citation literally as [@key, p. 12: \"quote\"]; entities and backslash escapes hide it from check",
            )
        )

    for citation in citations:
        record: dict = {
            "key": citation.key,
            "line": citation.line,
            "locator": citation.locator(),
            "quote": bool(citation.quote),
        }
        record["ok"] = True
        if citation.error:
            record["ok"] = False
            report.errors.append(
                Finding(
                    citation.error,
                    citation.error_detail or "invalid citation",
                    file="Paper/paper.md",
                    line=citation.line,
                    data={"raw": citation.raw},
                    hint='use [@key], [@key, p. 12] or [@key, p. 12: "quote"]',
                )
            )
            report.citations.append(record)
            continue

        source = manifest.source_for_citation(citation.key)
        if source is None:
            record["ok"] = False
            report.errors.append(
                Finding(
                    "unknown_citation_key",
                    f"no source with key {citation.key!r}",
                    file="Paper/paper.md",
                    line=citation.line,
                    data={"key": citation.key},
                    hint=(
                        "add it under References/ and run `paperchain convert`; "
                        f"if it is a Zotero key, run `paperchain match` to map it to a source. "
                        f"known keys: {', '.join(manifest.citation_keys) or '(none)'}"
                    ),
                )
            )
            report.citations.append(record)
            continue

        citation_key = manifest.citation_key_for(source)
        record["citation_key"] = citation_key
        cited_source_keys.add(source.key)
        if citation_key in duplicate_ids:
            duplicate_ids_used.add(citation_key)

        if bibliography_key_set is not None and citation_key not in bibliography_key_set:
            record["ok"] = False
            report.errors.append(
                Finding(
                    "citation_not_in_bibliography",
                    f"{citation_key} is not in {project.relative(bibliography)}",
                    file="Paper/paper.md",
                    line=citation.line,
                    data={"key": citation_key, "source": source.key},
                    hint=(
                        f"{source.key} is the source for this citation; set its citation_key in paper.toml "
                        "to the Better BibTeX id, or run `paperchain match` to map sources to Zotero entries"
                    ),
                )
            )
            report.citations.append(record)
            continue

        if citation.has_pages:
            stats["citations_with_page"] += 1
        else:
            report.warnings.append(
                Finding(
                    "citation_without_page",
                    f"citation {citation.key} has no page number",
                    severity="warning",
                    file="Paper/paper.md",
                    line=citation.line,
                    hint="add the page so the claim can be checked",
                )
            )

        pages, _, text_error = cache.get(source.key)
        page_count = len(pages or [])

        if citation.has_pages and page_count and (
            (citation.page_first or 0) > page_count or (citation.page_last or 0) > page_count
        ):
            record["ok"] = False
            report.errors.append(
                Finding(
                    "page_out_of_range",
                    f"{citation.key} has {page_count} page(s), but the citation points at {citation.locator()}",
                    file="Paper/paper.md",
                    line=citation.line,
                    data={"key": citation.key, "pages": page_count},
                    hint="re-read the source and cite an existing page",
                )
            )
        elif citation.quote:
            stats["citations_with_quote"] += 1
            if len(normalize_for_match(citation.quote).split()) < 4:
                severity = "error" if (strict or manifest.require_quotes) else "warning"
                finding = Finding(
                    "quote_too_short",
                    "the quoted span is shorter than four words",
                    severity=severity,
                    file="Paper/paper.md",
                    line=citation.line,
                    hint="quote a full clause so the check is meaningful",
                )
                (report.errors if severity == "error" else report.warnings).append(finding)
            if text_error or pages is None:
                record["ok"] = False
            else:
                found = verify_quote(
                    cache.normalized(source.key, join_hyphenation=True),
                    citation.quote,
                    citation.pages,
                    join_hyphenation=True,
                )
                if found is None:
                    # "well-\nknown" joins to "wellknown" for matching, but a
                    # quote written as "well-known" should still verify.
                    found = verify_quote(
                        cache.normalized(source.key, join_hyphenation=False),
                        citation.quote,
                        citation.pages,
                        join_hyphenation=False,
                    )
                if found is None:
                    record["ok"] = False
                    preview = citation.quote[:60] + ("..." if len(citation.quote) > 60 else "")
                    report.errors.append(
                        Finding(
                            "quote_not_found",
                            f"the quote is not in {citation.key}",
                            file="Paper/paper.md",
                            line=citation.line,
                            data={"key": citation.key, "quote": preview},
                            hint=f"copy the words exactly from {project.relative(project.text_dir / f'{source.key}.txt')}; extraction may need fixing for this page",
                        )
                    )
                elif citation.has_pages and found not in citation.pages:
                    record["ok"] = False
                    report.errors.append(
                        Finding(
                            "quote_wrong_page",
                            f"the quote is on page {found} of {citation.key}, not {citation.locator()}",
                            file="Paper/paper.md",
                            line=citation.line,
                            data={"key": citation.key, "found_page": found},
                            hint="fix the page number and re-read the surrounding text",
                        )
                    )
                else:
                    stats["quotes_verified"] += 1
                    record["verified_page"] = found
        elif strict or manifest.require_quotes:
            record["ok"] = False
            report.errors.append(
                Finding(
                    "citation_without_quote",
                    f"citation {citation.key} has no quoted evidence",
                    file="Paper/paper.md",
                    line=citation.line,
                    hint='add the evidence: [@key, p. 12: "exact words"]',
                )
            )
        else:
            report.warnings.append(
                Finding(
                    "citation_without_quote",
                    f"citation {citation.key} has no quoted evidence",
                    severity="warning",
                    file="Paper/paper.md",
                    line=citation.line,
                    hint='add the evidence: [@key, p. 12: "exact words"]',
                )
            )

        report.citations.append(record)

    # -- duplicate CSL ids ------------------------------------------------
    # Two entries with one id are ambiguous: Paperchain reads the first, while
    # citeproc has been observed to use the last. That is a wrong reference,
    # not a data warning, as soon as a source or citation relies on the id.
    for duplicate in duplicate_ids:
        used = duplicate in duplicate_ids_used
        severity = "error" if used else "warning"
        message = f"{duplicate!r} appears more than once in {project.relative(bibliography)}"
        if used:
            message += "; a source or citation relies on it, and Paperchain and citeproc may choose different entries"
        finding = Finding(
            "bibliography_duplicate_id",
            message,
            severity=severity,
            file=project.relative(bibliography),
            data={"key": duplicate},
            hint="give each Zotero item a unique Better BibTeX key and re-export; do not cite or match a duplicated id",
        )
        (report.errors if used else report.warnings).append(finding)

    # -- bibliography entries no source points at -------------------------
    # A Zotero export normally holds every item in the collection, so an
    # unmatched entry is not automatically wrong. The warning exists so a
    # source with the wrong citation_key is visible instead of silently
    # missing from the built reference list.
    if bibliography_key_set:
        claimed = {
            manifest.citation_key_for(source)
            for source in manifest.sources
            if manifest.citation_key_for(source) in bibliography_key_set
        }
        unused = sorted(bibliography_key_set - claimed)
        if unused:
            # A Zotero collection normally holds more items than the project
            # has converted PDFs. One line keeps `check` readable; `match`
            # lists each entry when the user is pairing sources.
            report.warnings.append(
                Finding(
                    "bibliography_entry_unmatched",
                    f"{len(unused)} CSL entr{'y' if len(unused) == 1 else 'ies'} in "
                    f"{project.relative(bibliography)} {'is' if len(unused) == 1 else 'are'} not used by any source",
                    severity="warning",
                    file=project.relative(bibliography),
                    data={"keys": unused},
                    hint="run `paperchain match` to map them to sources, or cite them after converting the PDF",
                )
            )

    # -- unused sources --------------------------------------------------
    for source in manifest.sources:
        if source.key not in cited_source_keys:
            report.warnings.append(
                Finding(
                    "unused_source",
                    f"{source.key} is in the reference set but never cited",
                    severity="warning",
                    file="paper.toml",
                    hint="cite it, or ask the human to remove it before submitting",
                )
            )

    # -- placeholders ----------------------------------------------------
    for match in PLACEHOLDER_RE.finditer(masked_text):
        line = text.count("\n", 0, match.start()) + 1
        report.errors.append(
            Finding(
                "placeholder",
                f"unfinished text: {match.group(0)!r}",
                file="Paper/paper.md",
                line=line,
                hint="finish the section or remove the marker before building",
            )
        )

    for match in XXX_PLACEHOLDER_RE.finditer(masked_text):
        line = text.count("\n", 0, match.start()) + 1
        report.errors.append(
            Finding(
                "placeholder",
                "unfinished text: 'XXX'",
                file="Paper/paper.md",
                line=line,
                hint="finish the section or remove the marker; inline 'XXX' (as in 'Super Bowl XXX') is left alone",
            )
        )

    # -- candidate sources waiting for a human ---------------------------
    if include_candidates and project.candidates_dir.is_dir():
        for path in sorted(project.candidates_dir.glob("*.md")):
            if path.name.lower() in {"index.md", "readme.md"}:
                continue
            report.warnings.append(
                Finding(
                    "candidate_pending",
                    f"{path.name} is a proposed source that was never added",
                    severity="warning",
                    file=project.relative(path),
                    hint="the human must approve it: download into References/, then convert and lock",
                )
            )

    # -- lock state ------------------------------------------------------
    if not manifest.locked_at:
        report.warnings.append(
            Finding(
                "references_not_locked",
                "the reference set has never been locked",
                severity="warning",
                file="paper.toml",
                hint="run `paperchain lock` once the sources are final",
            )
        )
    elif normalized_hash_ok:
        writable = []
        for source in manifest.sources:
            for path, label in (
                (project.root / source.path, source.path),
                (project.text_dir / f"{source.key}.json", project.relative(project.text_dir / f"{source.key}.json")),
                (project.text_dir / f"{source.key}.txt", project.relative(project.text_dir / f"{source.key}.txt")),
            ):
                if path.is_file() and os.stat(path).st_mode & stat.S_IWRITE:
                    writable.append(label)
        if writable:
            report.warnings.append(
                Finding(
                    "lock_drift",
                    f"{len(writable)} reference file(s) are writable again",
                    severity="warning",
                    file=writable[0],
                    hint="run `paperchain lock` to re-apply read-only protection",
                )
            )

    report.stats = stats
    fingerprint = reference_fingerprint(manifest)
    report.data = {
        "project": str(project.root),
        "title": manifest.title,
        "locked_at": manifest.locked_at,
        "reference_fingerprint": fingerprint,
    }
    reblessed = reblessed_since_last_build(read_events(project))
    if reblessed:
        report.warnings.append(
            Finding(
                "reference_set_reblessed",
                f"the reference set was unlocked or re-blessed {len(reblessed)} time(s) since the last build",
                severity="warning",
                file=LOG_RELATIVE,
                hint="tell the human which references changed; the log lists each event. Review with `git diff paper.toml`",
                data={"events": reblessed[-5:], "fingerprint": fingerprint},
            )
        )
    return report
