from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .citations import find_unrecognized, parse_citations, scan_markdown
from .errors import Finding, PaperchainError
from .extract import SUPPORTED_SUFFIXES, Extraction, extract, render_text_file
from .library import bibliography_keys
from .project import Project
from .util import normalize_for_match, sha256_file, word_count

PLACEHOLDER_RE = re.compile(r"\b(TODO|TKTK|FIXME|XXX)\b|\[\[|lorem ipsum", re.IGNORECASE)


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


def _find_span(haystack: str, needle: str) -> int | None:
    """Find needle as a whole-word-ish span, not inside a larger word."""
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            return None
        before = haystack[index - 1] if index > 0 else " "
        after_index = index + len(needle)
        after = haystack[after_index] if after_index < len(haystack) else " "
        left_ok = not (before.isalnum() and needle[0].isalnum())
        right_ok = not (after.isalnum() and needle[-1].isalnum())
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
        elif project.manifest.manuscript_sha256:
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
                        hint="re-run `paperchain import --force` to regenerate Paper/paper.md, then review it",
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
                        hint=f"run `paperchain convert --force --only {source.key}`",
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
                                hint=f"run `paperchain convert --force --only {source.key}`",
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
                        hint="run `paperchain unlock`, then `paperchain convert --force`, then `paperchain lock`",
                    )
                )
                normalized_hash_ok = False

            txt_path = project.text_dir / f"{source.key}.txt"
            if not txt_path.is_file():
                report.errors.append(
                    Finding(
                        "text_file_missing",
                        f"References/_text/{source.key}.txt is missing",
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
                            f"References/_text/{source.key}.txt does not match the anchored page map",
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
    cited_keys: set[str] = set()

    bibliography = project.bibliography_path
    bibliography_key_set: set[str] | None = None
    if bibliography is not None:
        try:
            bibliography_key_set = bibliography_keys(bibliography)
        except PaperchainError as exc:
            report.errors.append(
                Finding(
                    exc.code,
                    exc.message,
                    file=project.relative(bibliography),
                    hint=exc.hint,
                )
            )

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

        cited_keys.add(citation.key)
        source = manifest.source(citation.key)
        if source is None:
            record["ok"] = False
            report.errors.append(
                Finding(
                    "unknown_citation_key",
                    f"no source with key {citation.key!r}",
                    file="Paper/paper.md",
                    line=citation.line,
                    data={"key": citation.key},
                    hint=f"add it under References/ and run `paperchain convert`, or use one of: {', '.join(manifest.source_keys) or '(none)'}",
                )
            )
            report.citations.append(record)
            continue

        if bibliography_key_set is not None and citation.key not in bibliography_key_set:
            record["ok"] = False
            report.errors.append(
                Finding(
                    "citation_not_in_bibliography",
                    f"{citation.key} is not in {project.relative(bibliography)}",
                    file="Paper/paper.md",
                    line=citation.line,
                    data={"key": citation.key},
                    hint="add the reference in Zotero and export CSL JSON again, or fix the citation key",
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

        pages, _, text_error = cache.get(citation.key)
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
                    cache.normalized(citation.key, join_hyphenation=True),
                    citation.quote,
                    citation.pages,
                    join_hyphenation=True,
                )
                if found is None:
                    # "well-\nknown" joins to "wellknown" for matching, but a
                    # quote written as "well-known" should still verify.
                    found = verify_quote(
                        cache.normalized(citation.key, join_hyphenation=False),
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
                            hint=f"copy the words exactly from References/_text/{citation.key}.txt; extraction may need fixing for this page",
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

    # -- unused sources --------------------------------------------------
    for source in manifest.sources:
        if source.key not in cited_keys:
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
    report.data = {
        "project": str(project.root),
        "title": manifest.title,
        "locked_at": manifest.locked_at,
    }
    return report
