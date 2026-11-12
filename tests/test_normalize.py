from __future__ import annotations

from paperchain.util import normalize_for_match, slugify, word_count


def test_folds_ligatures() -> None:
    assert normalize_for_match("the \ufb01nance sector") == "the finance sector"


def test_folds_smart_punctuation() -> None:
    assert normalize_for_match("\u201cwhy?\u201d \u2014 she asked") == '"why?" - she asked'


def test_joins_hyphenated_line_breaks() -> None:
    assert normalize_for_match("exam-\nple") == "example"
    assert normalize_for_match("exam- ple") != "example"


def test_collapses_whitespace_and_case() -> None:
    assert normalize_for_match("  Two\n\twords  ") == "two words"


def test_keeps_word_order() -> None:
    assert normalize_for_match("a b") != normalize_for_match("b a")


def test_slugify() -> None:
    assert slugify("Smith & Jones (2024) — Final") == "smith-jones-2024-final"
    assert slugify("...").startswith("doc-")
    assert slugify("研究一") != slugify("研究二")


def test_word_count() -> None:
    assert word_count("one two-three don't four") == 4
