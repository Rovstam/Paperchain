from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .citations import mask_code, parse_citations
from .errors import Finding
from .extract import SUPPORTED_SUFFIXES
from .project import Project
from .util import normalize_for_match, sha256_file, word_count

PLACEHOLDER_RE = re.compile(r"\b(TODO|TKTK|FIXME|XXX)\b|\[\[|lorem ipsum", re.IGNORECASE)
PAGE_LINE_RE = re.compile(r"^===== PAGE (\d+) =====$")


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


def _load_text(project: Project, key: str) -> tuple[list[str] | None, str | None]:
    json_path = project.text_dir / f"{key}.json"
    if not json_path.is_file():
        return None, "text_missing"
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "text_invalid"
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        return None, "text_invalid"
    pages: list[str] = []
    for entry in raw_pages:
        if isinstance(entry, dict) and isinstance(entry.get("text"), str):
            pages.append(entry["text"])
        elif isinstance(entry, str):
            pages.append(entry)
        else:
            return None, "text_invalid"
    return pages, None


def _text_file_pages(path: Path) -> list[str] | None:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    pages: list[str] = []
    current: list[str] | None = None
    for line in content.split("\n"):
        if PAGE_LINE_RE.match(line):
            if current is not None:
                pages.append("\n".join(current).strip("\n"))
            current = []
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        pages.append("\n".join(current).strip("\n"))
    return pages or None


class _TextCache:
    def __init__(self, project: Project):
        self.project = project
        self._raw: dict[str, tuple[list[str] | None, str | None]] = {}
        self._normalized: dict[str, list[str]] = {}

    def get(self, key: str) -> tuple[list[str] | None, str | None]:
        if key not in self._raw:
            self._raw[key] = _load_text(self.project, key)
        return self._raw[key]

    def normalized(self, key: str) -> list[str]:
        if key not in self._normalized:
            pages, _ = self.get(key)
            self._normalized[key] = [normalize_for_match(page) for page in (pages or [])]
        return self._normalized[key]


def verify_quote(
    normalized_pages: list[str], quote: str, wanted_pages: list[int]
) -> int | None:
    needle = normalize_for_match(quote)
    if not needle:
        return None
    for number in wanted_pages:
        if 1 <= number <= len(normalized_pages) and needle in normalized_pages[number - 1]:
            return number
    for number, page in enumerate(normalized_pages, start=1):
        if needle in page:
            return number
    return None


def run_check(
    project: Project,
    strict: bool = False,
    include_candidates: bool = True,
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
            report.warnings.append(
                Finding(
                    "source_unhashed",
                    f"{source.key} has no recorded hash",
                    severity="warning",
                    file=source.path,
                    hint="run `paperchain lock` to freeze the reference set",
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
        pages, text_error = cache.get(source.key)
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
            if not source.text_sha256:
                report.warnings.append(
                    Finding(
                        "text_unhashed",
                        f"{source.key} converted text has no recorded hash",
                        severity="warning",
                        file=project.relative(json_path),
                        hint="run `paperchain lock`",
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
                report.warnings.append(
                    Finding(
                        "text_file_missing",
                        f"References/_text/{source.key}.txt is missing",
                        severity="warning",
                        file=project.relative(txt_path),
                        hint="run `paperchain convert --force`; the agent reads the .txt files",
                    )
                )
            else:
                from_txt = _text_file_pages(txt_path)
                from_json = [page.strip() for page in (pages or [])]
                if from_txt is not None and [page.strip() for page in from_txt] != from_json:
                    report.warnings.append(
                        Finding(
                            "text_inconsistent",
                            f"the .txt and .json copies of {source.key} disagree",
                            severity="warning",
                            file=project.relative(txt_path),
                            hint="run `paperchain convert --force` to regenerate both",
                        )
                    )

    # -- files sitting in originals but not in the manifest --------------
    if project.originals_dir.is_dir():
        managed = {(project.root / source.path).resolve() for source in manifest.sources}
        for path in sorted(project.originals_dir.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                report.warnings.append(
                    Finding(
                        "unsupported_reference",
                        f"{path.name} is not a supported reference type",
                        severity="warning",
                        file=project.relative(path),
                        hint="supported types are PDF, DOCX, TXT and MD",
                    )
                )
            elif path.resolve() not in managed:
                report.errors.append(
                    Finding(
                        "unmanaged_source",
                        f"{path.name} is in References/originals but was never converted",
                        file=project.relative(path),
                        hint="run `paperchain convert`, then `paperchain lock`",
                    )
                )

    # -- citations -------------------------------------------------------
    citations = parse_citations(text)
    stats["citations"] = len(citations)
    cited_keys: set[str] = set()
    normalized_pages_by_key: dict[str, list[str]] = {}

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
                    hint=f"add it to References/originals and run `paperchain convert`, or use one of: {', '.join(manifest.source_keys) or '(none)'}",
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

        pages, text_error = cache.get(citation.key)
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
                report.warnings.append(
                    Finding(
                        "quote_too_short",
                        "the quoted span is shorter than four words",
                        severity="warning",
                        file="Paper/paper.md",
                        line=citation.line,
                        hint="quote a full clause so the check is meaningful",
                    )
                )
            if text_error or pages is None:
                record["ok"] = False
            else:
                if citation.key not in normalized_pages_by_key:
                    normalized_pages_by_key[citation.key] = cache.normalized(citation.key)
                found = verify_quote(
                    normalized_pages_by_key[citation.key],
                    citation.quote,
                    citation.pages,
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
    masked_text = mask_code(text)
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
                    hint="the human must approve it: download into References/originals, then convert and lock",
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
            path = project.root / source.path
            if path.is_file() and os.stat(path).st_mode & stat.S_IWRITE:
                writable.append(source.path)
            json_path = project.text_dir / f"{source.key}.json"
            if json_path.is_file() and os.stat(json_path).st_mode & stat.S_IWRITE:
                writable.append(project.relative(json_path))
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
