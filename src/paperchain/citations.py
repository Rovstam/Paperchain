from __future__ import annotations

import re
from dataclasses import dataclass

from .manifest import Source

# Better BibTeX ids may contain letters outside ASCII. `[^\W_]` is a Unicode
# letter or digit (word character without underscore), which keeps the first
# character from being punctuation while allowing names such as Peña2022.
# The last character must also be a letter or digit: Pandoc treats a trailing
# `. : / + -` as punctuation outside the key, so accepting it here made
# `check` and Pandoc disagree.
CITATION_RE = re.compile(
    r"""\[@(?P<key>[^\W_](?:[\w.:/+-]*[^\W_])?)(?![.:/+-])(?P<body>(?:[^\]"'“”]|"[^"]*"|“[^”]*”|'[^']*')*)\]"""
)

_LOCATOR = r"(?:pp?\.)\s*\d+(?:\s*[-\u2013\u2014]\s*\d+)?"
_QUOTE = r'(?:"[^"]*"|\u201c[^\u201d]*\u201d|\'[^\']*\')'
BODY_RE = re.compile(rf"^\s*,?\s*(?P<loc>{_LOCATOR})?\s*[:,-]?\s*(?P<quote>{_QUOTE})?\s*$")
LOCATOR_RE = re.compile(r"(pp?)\.\s*(\d+)(?:\s*[-\u2013\u2014]\s*(\d+))?$")

# Any @key that is not part of a parsed citation. Catches Pandoc forms such as
# [see @key], [-@key] and narrative @key, which would otherwise pass silently.
AT_RE = re.compile(r"(?<![\w@])@(?P<key>[^\s\]])")

MAX_PAGE_SPAN = 50


@dataclass
class MaskIssue:
    kind: str
    line: int


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


def _is_escaped(text: str, position: int) -> bool:
    """True when position is preceded by an odd run of backslashes."""
    count = 0
    index = position - 1
    while index >= 0 and text[index] == "\\":
        count += 1
        index -= 1
    return count % 2 == 1


def _mask_range(buffer: list[str], text: str, start: int, end: int) -> None:
    for position in range(start, end):
        if text[position] != "\n":
            buffer[position] = " "


def _find_fence_end(text: str, start: int, fence: str, run: int) -> tuple[int, int] | None:
    """Return the (start, end) of the closing fence line, or None."""
    position = text.find("\n", start)
    while position != -1:
        line_start = position + 1
        line_end = text.find("\n", line_start)
        if line_end == -1:
            line_end = len(text)
        candidate = text[line_start:line_end]
        stripped = candidate.lstrip(" ")
        indent = len(candidate) - len(stripped)
        if indent <= 3:
            count = 0
            while count < len(stripped) and stripped[count] == fence:
                count += 1
            if count >= run and stripped[count:].strip() == "":
                return line_start, line_end
        if line_end >= len(text):
            break
        position = line_end
    return None


def _find_code_span_end(text: str, start: int, run: int) -> int | None:
    """Index of the closing backtick run on the same line, or None."""
    position = start
    length = len(text)
    while position < length:
        char = text[position]
        if char == "\n":
            return None
        if char == "`":
            count = 0
            cursor = position
            while cursor < length and text[cursor] == "`":
                count += 1
                cursor += 1
            if count == run:
                return position
            position = cursor
            continue
        position += 1
    return None


def scan_markdown(
    text: str, ranges: list[tuple[int, int]] | None = None
) -> tuple[str, list[MaskIssue]]:
    """Mask fenced code, inline code and HTML comments, preserving offsets.

    The scan is left to right so that a comment opener inside a code span is
    inert, and a code span inside a comment is inert. Unterminated constructs
    are reported instead of silently swallowing the rest of the document.
    Pass `ranges` to collect the (start, end) of every masked construct.
    """
    buffer = list(text)
    issues: list[MaskIssue] = []
    length = len(text)
    index = 0
    line = 1
    at_line_start = True

    while index < length:
        char = text[index]

        if char == "\n":
            line += 1
            index += 1
            at_line_start = True
            continue

        if at_line_start:
            cursor = index
            indent = 0
            while cursor < length and text[cursor] == " " and indent < 4:
                cursor += 1
                indent += 1
            if indent <= 3 and cursor < length and text[cursor] in "`~":
                fence = text[cursor]
                run = 0
                probe = cursor
                while probe < length and text[probe] == fence:
                    run += 1
                    probe += 1
                if run >= 3:
                    line_end = text.find("\n", probe)
                    if line_end == -1:
                        line_end = length
                    info = text[probe:line_end]
                    # CommonMark: a backtick fence's info string may not contain
                    # a backtick. "```x```" is inline code, not a fence.
                    if not (fence == "`" and "`" in info):
                        found = _find_fence_end(text, probe, fence, run)
                        if found is None:
                            end = length
                            issues.append(MaskIssue("unterminated_code_block", line))
                        else:
                            end = found[1]
                        if ranges is not None:
                            ranges.append((index, end))
                        _mask_range(buffer, text, index, end)
                        line += text.count("\n", index, end)
                        index = end
                        at_line_start = False
                        continue
            at_line_start = False

        if char == "`":
            if _is_escaped(text, index):
                index += 1
                at_line_start = False
                continue
            run = 0
            probe = index
            while probe < length and text[probe] == "`":
                run += 1
                probe += 1
            close = _find_code_span_end(text, probe, run)
            if close is not None:
                end = close + run
                if ranges is not None:
                    ranges.append((index, end))
                _mask_range(buffer, text, index, end)
                line += text.count("\n", index, end)
                index = end
                at_line_start = False
                continue

        if text.startswith("<!--", index) and not _is_escaped(text, index):
            end = text.find("-->", index + 4)
            if end == -1:
                issues.append(MaskIssue("unterminated_comment", line))
                if ranges is not None:
                    ranges.append((index, length))
                _mask_range(buffer, text, index, length)
                index = length
                break
            end += 3
            if ranges is not None:
                ranges.append((index, end))
            _mask_range(buffer, text, index, end)
            line += text.count("\n", index, end)
            index = end
            at_line_start = False
            continue

        index += 1

    return "".join(buffer), issues


def mask_code(text: str) -> str:
    return scan_markdown(text)[0]


def indented_code_ranges(text: str) -> list[tuple[int, int]]:
    """Ranges of CommonMark indented code blocks.

    A block starts after a blank line with four spaces or a tab and continues
    through blank lines until a less-indented nonblank line. This is only used
    where a caller needs the ranges; citation parsing continues to mask fenced
    and inline code through `scan_markdown`.
    """
    lines = text.splitlines(keepends=True)
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    offset = 0
    previous_blank = True
    for line in lines:
        content = line.rstrip("\r\n")
        blank = not content.strip()
        indented = content.startswith(("    ", "\t"))
        if start is None:
            if not blank and indented and previous_blank:
                start = offset
        elif not blank and not indented:
            ranges.append((start, offset))
            start = None
        previous_blank = blank
        offset += len(line)
    if start is not None:
        ranges.append((start, len(text)))
    return ranges


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
        if _is_escaped(masked, start):
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

        if "@" in re.sub(r'"[^"]*"|“[^”]*”|\'[^\']*\'', "", body):
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


def find_unrecognized(masked: str, citations: list[Citation]) -> list[tuple[str, int]]:
    """Find @key mentions that no strict citation covers."""
    spans = [(citation.start, citation.end) for citation in citations]
    found: list[tuple[str, int]] = []
    for match in AT_RE.finditer(masked):
        position = match.start()
        if any(start <= position < end for start, end in spans):
            continue
        if _is_escaped(masked, position):
            continue
        if position >= 1 and masked[position - 1] == "[" and _is_escaped(masked, position - 1):
            continue
        line = masked.count("\n", 0, position) + 1
        found.append((match.group(0), line))
    return found


_ENTITY_AT_RE = re.compile(r"&#0*64;|&#[xX]0*40;|&commat;", re.IGNORECASE)
_ESCAPED_AT_RE = re.compile(r"(?<!\\)\\@")
_BRACKET_SPAN_RE = re.compile(r"\[[^\]\n]*\]")


def find_hidden_citations(masked: str) -> list[tuple[str, int]]:
    """Find citation-shaped brackets that Pandoc will render literally.

    Pandoc decodes HTML entities and backslash escapes before it writes the
    document, so ``[&#64;key, p. 1]`` and ``[\\@key, p. 1]`` reach the reader as
    citations even though the scanner never parsed them. They cannot be
    verified, so they are reported like any other unrecognised citation.
    """
    found: list[tuple[str, int]] = []
    for match in _BRACKET_SPAN_RE.finditer(masked):
        span = match.group(0)
        escaped_bracket = _is_escaped(masked, match.start()) and "@" in span
        if not (
            _ENTITY_AT_RE.search(span)
            or _ESCAPED_AT_RE.search(span)
            or escaped_bracket
        ):
            continue
        line = masked.count("\n", 0, match.start()) + 1
        found.append((span, line))
    return found


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
