"""Per-reference context cards: a cheap map of each paper, kept beside its file.

`paperchain context` writes `<name>.context.md` next to every converted
reference so the writer can find the right page without rereading the whole
paper. The top of a card is generated from the cached text (title, authors,
sections found by heading, a one-line preview of every page) and is rewritten
whenever the reference changes. Everything below RESUME_MARKER belongs to the
writer (the scoped resume) and survives regeneration.

A card is a set of leads, never evidence. Only a quote that `paperchain check`
finds on the cited page supports a claim, and cards are not part of the lock.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import Finding
from .manifest import Source
from .project import Project
from .util import write_text

CARD_SUFFIX = ".context.md"
RESUME_MARKER = "<!-- paperchain: everything below this line is yours and survives regeneration -->"
PENDING = "<!-- PENDING: scoped resume not written yet -->"
STALE_NOTICE = "> STALE: the reference file changed after this resume was written. Reread the cached text and rewrite it, then delete this line."
MAX_PAGE_LINES = 120
PREVIEW_CHARS = 80

_SECTION_RE = re.compile(
    r"^\s*(?:(?:\d+|[IVX]+)[.)]?\s+)?"
    r"(abstract|resumen|introduction|introducci[oó]n|background|antecedentes|"
    r"materials? and methods?|materiales y m[eé]todos|methods?|methodology|metodolog[ií]a|"
    r"results?|resultados|discussion|discusi[oó]n|conclusions?|conclusiones|"
    r"acknowledg(?:e)?ments?|agradecimientos|references|referencias|bibliography|bibliograf[ií]a)"
    r"\s*[.:]?\s*$",
    re.IGNORECASE,
)
_SHA_LINE = re.compile(r'^sha256:\s*"([0-9a-f]{64})"\s*$', re.MULTILINE)


def card_path(project: Project, source: Source) -> Path:
    original = project.root / source.path
    return original.with_name(original.stem + CARD_SUFFIX)


def _load_pages(project: Project, source: Source) -> tuple[list[str], bool] | None:
    path = project.text_dir / f"{source.key}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pages = [str(page.get("text", "")) for page in payload["pages"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return pages, bool(payload.get("page_map_estimated"))


def _preview(text: str) -> str:
    if not text.strip():
        return "(no text; scanned or image-only?)"
    for line in text.splitlines():
        line = " ".join(line.split())
        if not line or line.isdigit():
            continue
        return line if len(line) <= PREVIEW_CHARS else line[: PREVIEW_CHARS - 1].rstrip() + "\u2026"
    return "(no readable text)"


def _sections(pages: list[str]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for number, text in enumerate(pages, start=1):
        seen: set[str] = set()
        for line in text.splitlines():
            if len(line) > 60:
                continue
            match = _SECTION_RE.match(line)
            if match:
                label = match.group(1).strip().capitalize()
                if label.casefold() not in seen:
                    seen.add(label.casefold())
                    found.append((label, number))
    return found


def _scaffold(source: Source, pages: list[str], estimated: bool) -> str:
    def q(value: object) -> str:
        return json.dumps("" if value is None else value, ensure_ascii=False)

    head = ["---", f"key: {q(source.key)}"]
    if source.citation_key:
        head.append(f"citation_key: {q(source.citation_key)}")
    head += [f"title: {q(source.title)}", f"authors: {q(source.authors)}"]
    if source.year:
        head.append(f"year: {source.year}")
    head += [
        f"file: {q(source.path)}",
        f"pages: {len(pages)}",
        f'sha256: "{source.sha256}"',
        "---",
        "",
        f"# {source.title or source.key}",
        "",
        "> Navigation only. Everything here is a lead: a claim counts only when `paperchain check` "
        "finds the quoted words on the cited page. Read the cached text for exact wording.",
    ]
    if estimated:
        head.append("> Page numbers for this file are estimated, not read from a fixed layout.")
    head += ["", "## Sections found by heading", ""]
    sections = _sections(pages)
    if sections:
        head += [f"- {label}: p. {number}" for label, number in sections]
    else:
        head.append("_none of the standard headings was detected_")
    head += ["", "## Page map", ""]
    step = max(1, -(-len(pages) // MAX_PAGE_LINES))
    if step > 1:
        head += [f"_one page in every {step} is listed ({len(pages)} pages in total)_", ""]
    for number in range(1, len(pages) + 1, step):
        text = pages[number - 1]
        words = len(text.split())
        head.append(f"- p. {number} (~{words} {'word' if words == 1 else 'words'}): {_preview(text)}")
    head.append("")
    return "\n".join(head) + "\n"


def has_resume(card_text: str) -> bool:
    if RESUME_MARKER not in card_text:
        return False
    tail = card_text.split(RESUME_MARKER, 1)[1]
    if PENDING in tail:
        return False
    body = "".join(
        line for line in tail.splitlines() if not line.startswith("#") and not line.startswith(">")
    )
    return len("".join(body.split())) >= 40


def _is_stale(card_text: str) -> bool:
    return RESUME_MARKER in card_text and STALE_NOTICE in card_text.split(RESUME_MARKER, 1)[1]


def write_cards(project: Project, only: list[str] | None = None) -> dict:
    wanted = {key for key in (only or [])}
    known = {source.key for source in project.manifest.sources}
    unknown = sorted(wanted - known)
    warnings: list[Finding] = [
        Finding("context_unknown_source", f"{key} is not a converted source", severity="warning",
                hint="run `paperchain convert`, then `paperchain context`")
        for key in unknown
    ]
    cards: list[dict] = []
    for source in project.manifest.sources:
        if wanted and source.key not in wanted:
            continue
        loaded = _load_pages(project, source)
        path = card_path(project, source)
        relative = project.relative(path)
        if loaded is None:
            warnings.append(
                Finding("context_text_missing", f"no cached text for {source.key}; no card written",
                        severity="warning", file=source.path,
                        hint="run `paperchain convert` first")
            )
            continue
        pages, estimated = loaded
        top = _scaffold(source, pages, estimated)
        existing = path.read_text(encoding="utf-8") if path.is_file() else None
        if existing is None:
            new = top + RESUME_MARKER + "\n\n## Scoped resume\n\n" + PENDING + "\n"
            status = "created"
        elif RESUME_MARKER in existing:
            head, tail = existing.split(RESUME_MARKER, 1)
            old_sha = _SHA_LINE.search(head)
            if (
                has_resume(existing)
                and old_sha
                and old_sha.group(1) != source.sha256
                and STALE_NOTICE not in tail
            ):
                tail = "\n\n" + STALE_NOTICE + "\n" + tail.lstrip("\n")
            new = top + RESUME_MARKER + tail
            status = "unchanged" if new == existing else "updated"
        else:
            warnings.append(
                Finding("context_card_unrecognised",
                        f"{relative} exists without the paperchain marker; it was left untouched",
                        severity="warning", file=relative,
                        hint="move your notes below the marker line, or rename the file and rerun `paperchain context`")
            )
            cards.append({"key": source.key, "card": relative, "status": "kept", "has_resume": False, "stale": False})
            continue
        if status != "unchanged":
            write_text(path, new)
        cards.append(
            {
                "key": source.key,
                "card": relative,
                "status": status,
                "pages": len(pages),
                "has_resume": has_resume(new),
                "stale": _is_stale(new),
            }
        )
    pending = [c["key"] for c in cards if not c["has_resume"] or c["stale"]]
    return {"cards": cards, "pending": pending, "warnings": warnings}
