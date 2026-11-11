from __future__ import annotations

import re
from dataclasses import dataclass

from .manifest import Source

CITATION_RE = re.compile(r"\[@(?P<key>[A-Za-z0-9][A-Za-z0-9_.:/+-]*)(?P<body>[^\]]*)\]")

_LOCATOR = r"(?:pp?\.)\s*\d+(?:\s*[-\u2013\u2014]\s*\d+)?"
_QUOTE = r'(?:"[^"]*"|\u201c[^\u201d]*\u201d|\'[^\']*\')'
BODY_RE = re.compile(rf"^\s*,?\s*(?P<loc>{_LOCATOR})?\s*[:,-]?\s*(?P<quote>{_QUOTE})?\s*$")
LOCATOR_RE = re.compile(r"(pp?)\.\s*(\d+)(?:\s*[-\u2013\u2014]\s*(\d+))?$")

MAX_PAGE_SPAN = 50


@dataclass
class Citation:
    key: str
    raw: str
    start: int
    end: int
    line: int
    page_first: int | None = None
    page_last: int | None = None
    quote: str | None = None
    error: str | None = None
    error_detail: str | None = None

    @property
    def pages(self) -> list[int]:
        if self.page_first is None or self.page_last is None:
            return []
        return list(range(self.page_first, self.page_last + 1))

    @property
    def has_pages(self) -> bool:
        return self.page_first is not None

    def locator(self) -> str:
        if self.page_first is None or self.page_last is None:
            return ""
        if self.page_first == self.page_last:
            return f"p. {self.page_first}"
        return f"pp. {self.page_first}-{self.page_last}"


def mask_code(text: str) -> str:
    """Replace code and comments with spaces, keeping offsets and newlines."""
    out_lines: list[str] = []
    in_fence = False
    in_comment = False
    for line in text.split("\n"):
        stripped = line.strip()
        if in_comment:
            end = line.find("-->")
            if end == -1:
                out_lines.append(" " * len(line))
                continue
            in_comment = False
            out_lines.append(" " * (end + 3) + line[end + 3 :])
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out_lines.append(" " * len(line))
            continue
        if in_fence:
            out_lines.append(" " * len(line))
            continue
        comment_start = line.find("<!--")
        if comment_start != -1:
            comment_end = line.find("-->", comment_start + 4)
            if comment_end == -1:
                in_comment = True
                out_lines.append(line[:comment_start] + " " * (len(line) - comment_start))
                continue
            masked = (
                line[:comment_start]
                + " " * (comment_end + 3 - comment_start)
                + line[comment_end + 3 :]
            )
            line = masked
        out_lines.append(re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line))
    return "\n".join(out_lines)


def parse_locator(locator: str) -> tuple[int, int] | None:
    match = LOCATOR_RE.match(locator.strip())
    if not match:
        return None
    first = int(match.group(2))
    last = int(match.group(3)) if match.group(3) else first
    return first, last


def parse_citations(text: str) -> list[Citation]:
    masked = mask_code(text)
    citations: list[Citation] = []

    for match in CITATION_RE.finditer(masked):
        start = match.start()
        if start > 0 and masked[start - 1] == "\\":
            continue

        line = masked.count("\n", 0, start) + 1
        body = match.group("body")
        raw = text[match.start() : match.end()]
        citation = Citation(
            key=match.group("key"),
            raw=raw,
            start=match.start(),
            end=match.end(),
            line=line,
        )

        if "@" in body:
            citation.error = "multiple_citations"
            citation.error_detail = "one citation per bracket"
            citations.append(citation)
            continue

        body_match = BODY_RE.match(body)
        if not body_match:
            citation.error = "citation_malformed"
            citation.error_detail = (
                'expected [@key], [@key, p. 12], [@key, pp. 12-14] or [@key, p. 12: "quote"]'
            )
            citations.append(citation)
            continue

        locator = body_match.group("loc")
        if locator:
            parsed = parse_locator(locator)
            if parsed is None:
                citation.error = "citation_malformed"
                citation.error_detail = f"cannot read the page locator {locator!r}"
            else:
                first, last = parsed
                if first < 1:
                    citation.error = "citation_malformed"
                    citation.error_detail = "page numbers start at 1"
                elif last < first:
                    citation.error = "citation_malformed"
                    citation.error_detail = "the page range ends before it starts"
                elif last - first > MAX_PAGE_SPAN:
                    citation.error = "citation_malformed"
                    citation.error_detail = f"page range is wider than {MAX_PAGE_SPAN} pages"
                else:
                    citation.page_first = first
                    citation.page_last = last

        quote = body_match.group("quote")
        if quote:
            citation.quote = quote[1:-1].strip()

        citations.append(citation)

    return citations


def format_citation(citation: Citation, source: Source | None) -> str:
    if source is None:
        return citation.raw
    label = source.authors.strip() or source.key
    if source.year:
        label = f"{label}, {source.year}"
    parts = [label]
    locator = citation.locator()
    if locator:
        parts.append(locator)
    return f"({', '.join(parts)})"


def render_markdown(text: str, sources: dict[str, Source]) -> str:
    """Replace citation syntax with plain text suitable for pandoc/Word."""
    citations = parse_citations(text)
    rendered = text
    for citation in reversed(citations):
        if citation.error:
            continue
        replacement = format_citation(citation, sources.get(citation.key))
        rendered = rendered[: citation.start] + replacement + rendered[citation.end :]
    return rendered
