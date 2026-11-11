from __future__ import annotations

from paperchain.citations import format_citation, parse_citations, render_markdown
from paperchain.manifest import Source


def test_parses_the_four_forms() -> None:
    text = (
        "One [@smith2024]. "
        "Two [@smith2024, p. 12]. "
        "Three [@smith2024, pp. 12-14]. "
        'Four [@smith2024, p. 12: "exact words here"].'
    )
    citations = parse_citations(text)
    assert [c.key for c in citations] == ["smith2024"] * 4
    assert citations[0].page_first is None
    assert (citations[1].page_first, citations[1].page_last) == (12, 12)
    assert citations[2].pages == [12, 13, 14]
    assert citations[3].quote == "exact words here"
    assert all(c.error is None for c in citations)


def test_accepts_smart_quotes_and_no_comma() -> None:
    citations = parse_citations('Claim [@doe2023 p. 7: \u201cquoted text\u201d] and [@roe2022, p.9]')
    assert citations[0].quote == "quoted text"
    assert citations[0].page_first == 7
    assert citations[1].page_first == 9


def test_reports_multiple_citations_in_one_bracket() -> None:
    citation = parse_citations("[@a, p. 1; @b, p. 2]")[0]
    assert citation.error == "multiple_citations"


def test_reports_malformed_body() -> None:
    citation = parse_citations("[@key, page twelve]")[0]
    assert citation.error == "citation_malformed"


def test_rejects_reversed_and_huge_page_ranges() -> None:
    assert parse_citations("[@key, pp. 14-12]")[0].error == "citation_malformed"
    assert parse_citations("[@key, pp. 1-99]")[0].error == "citation_malformed"


def test_ignores_code_comments_and_escaped_brackets() -> None:
    text = (
        "```\n[@inside2024, p. 1]\n```\n"
        "Inline `[@code2024]` is literal.\n"
        "<!-- [@comment2024] -->\n"
        "Escaped \\[@escaped2024] is literal.\n"
        "Real [@real2024, p. 2].\n"
    )
    citations = parse_citations(text)
    assert [c.key for c in citations] == ["real2024"]
    assert citations[0].line == 7


def test_line_numbers_are_one_based() -> None:
    citations = parse_citations("line one\nline two [@key, p. 1]\n")
    assert citations[0].line == 2


def test_formats_author_year_with_page() -> None:
    source = Source(key="smith2024", path="References/originals/smith2024.pdf", authors="Smith, J.", year=2024)
    citation = parse_citations("[@smith2024, p. 12]")[0]
    assert format_citation(citation, source) == "(Smith, J., 2024, p. 12)"


def test_falls_back_to_the_key() -> None:
    source = Source(key="smith2024", path="References/originals/smith2024.pdf")
    citation = parse_citations("[@smith2024, pp. 3-4]")[0]
    assert format_citation(citation, source) == "(smith2024, pp. 3-4)"


def test_render_leaves_malformed_citations_alone() -> None:
    sources = {"key": Source(key="key", path="x.pdf")}
    assert render_markdown("[@key; @other]", sources) == "[@key; @other]"


def test_render_replaces_in_place() -> None:
    sources = {"key": Source(key="key", path="x.pdf", authors="Doe", year=2020)}
    rendered = render_markdown("A claim [@key, p. 2] and another [@key, p. 3].", sources)
    assert rendered == "A claim (Doe, 2020, p. 2) and another (Doe, 2020, p. 3)."
