"""Fixes for the round-5 audit: metadata allow-list, keys, titles and style trust."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from paperchain.build import (
    _check_resources,
    _mask_code_blocks,
    _rewrite_media_links,
    _unresolved_citations,
)
from paperchain.check import front_matter_keys, run_check
from paperchain.citations import parse_citations
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.library import style_problem, titles_equal
from paperchain.match_cmd import run_match
from paperchain.project import Project

from .conftest import add_pdf, make_project, write_paper

LIBRARY = [
    {
        "id": "study2024",
        "type": "article-journal",
        "title": "A Study",
        "author": [{"family": "Doe", "given": "J"}],
        "issued": {"date-parts": [[2024]]},
    }
]


def project_with_source(tmp_path: Path, title: str = "A Study") -> Project:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."], title=title)
    run_convert(project)
    return Project.open(project.root)


def write_library(project: Project, entries: list[dict]) -> Path:
    path = project.references_dir / "library.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def codes(report) -> set[str]:
    return {finding.code for finding in report.errors}


# -- 1. metadata allow-list ------------------------------------------------


def test_inline_references_metadata_is_an_error(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        "---\n"
        "references:\n"
        "- id: Haron2023\n"
        "  title: FORGED INLINE TITLE\n"
        "  author: [{family: Invented, given: Ivan}]\n"
        "  issued: {date-parts: [[1999]]}\n"
        "---\n\n"
        'A claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    report = run_check(Project.open(project.root))
    error = next(f for f in report.errors if f.code == "front_matter_overrides_citations")
    assert error.data["key"] == "references"
    assert error.line == 2


def test_an_unknown_metadata_key_is_an_error(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(project, "---\ncustom-key: value\n---\n\nBody\n")
    assert "front_matter_overrides_citations" in codes(run_check(Project.open(project.root)))


def test_allowed_document_metadata_is_allowed(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        "---\n"
        "title : A paper\n"
        "author: Ada Lovelace\n"
        "date: 2026\n"
        "abstract: A short abstract.\n"
        "keywords: [one, two]\n"
        "lang: en\n"
        "---\n\n"
        'A claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    assert "front_matter_overrides_citations" not in codes(run_check(Project.open(project.root)))


def test_an_escaped_key_is_seen(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        '---\n"suppress\\u002dbibliography": true\n---\n\n'
        'A claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    assert "front_matter_overrides_citations" in codes(run_check(Project.open(project.root)))


def test_a_complex_key_is_seen(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        "---\n? suppress-bibliography\n: true\n---\n\n"
        'A claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    assert "front_matter_overrides_citations" in codes(run_check(Project.open(project.root)))


def test_a_bom_does_not_hide_the_block(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        "\ufeff---\nsuppress-bibliography: true\n---\n\n"
        'A claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    assert "front_matter_overrides_citations" in codes(run_check(Project.open(project.root)))


def test_a_blockquote_block_is_seen(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        "> ---\n> suppress-bibliography: true\n> ---\n\n"
        'A claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    assert "front_matter_overrides_citations" in codes(run_check(Project.open(project.root)))


def test_a_list_item_block_is_seen(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        "- ---\n  suppress-bibliography: true\n  ---\n\n"
        'A claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    assert "front_matter_overrides_citations" in codes(run_check(Project.open(project.root)))


def test_a_nested_author_list_is_not_a_second_key(tmp_path: Path) -> None:
    text = "---\ntitle: T\nauthor:\n- name: Ada\n---\nBody\n"
    assert front_matter_keys(text) == {"title": 2, "author": 3}


# -- 2. keys ending in punctuation -----------------------------------------


def test_a_citation_key_ending_in_punctuation_is_rejected(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "Haron2023."
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"


@pytest.mark.parametrize("citation", ["[@Haron2023.]", "[@Haron2023-]", "[@Haron2023:]"])
def test_a_citation_ending_in_punctuation_is_malformed(citation: str) -> None:
    citations = parse_citations(citation)
    assert citations and citations[0].error


def test_the_citeproc_not_found_warning_is_detected() -> None:
    output = "[WARNING] Citeproc: citation Haron2023 not found\n"
    assert _unresolved_citations(output) == ["Haron2023"]


def test_match_does_not_write_a_key_ending_in_punctuation(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, [{"id": "Haron2023.", "title": "A Study"}])
    result = run_match(Project.open(project.root), apply=True)
    assert result["sources"][0]["status"] == "ambiguous"
    assert "citation_key_ambiguous" in {finding.code for finding in result["warnings"]}
    assert Project.open(project.root).manifest.sources[0].citation_key == ""


# -- 3. NFD titles ----------------------------------------------------------


def test_nfd_and_nfc_titles_are_equal() -> None:
    nfd = unicodedata.normalize("NFD", "Preparación")
    assert titles_equal("Preparacion", nfd) is True
    assert titles_equal(unicodedata.normalize("NFD", "Peña"), "Pena") is True


def test_an_nfd_bibliography_title_is_not_a_metadata_mismatch(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].title = "Preparación"
    project.manifest.sources[0].citation_key = "Pena2020"
    project.save()
    write_library(
        project,
        [
            {
                "id": "Pena2020",
                "title": unicodedata.normalize("NFD", "Preparación"),
            }
        ],
    )
    report = run_check(Project.open(project.root))
    assert "source_metadata_mismatch" not in codes(report)


def test_match_pairs_an_nfd_title(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].title = "Preparación"
    project.save()
    write_library(
        project,
        [{"id": "Pena2020", "title": unicodedata.normalize("NFD", "Preparación")}],
    )
    result = run_match(Project.open(project.root), apply=True)
    assert result["sources"][0]["status"] == "matched"
    assert Project.open(project.root).manifest.sources[0].citation_key == "Pena2020"


# -- 5. style sidecar and adapter -----------------------------------------


def write_style(path: Path, title: str, ident: str) -> Path:
    path.write_text(
        '<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">'
        f"<info><title>{title}</title><id>{ident}</id></info>"
        '<citation><layout><text variable="citation-number"/></layout></citation>'
        '<bibliography><layout><text variable="title"/></layout></bibliography>'
        "</style>",
        encoding="utf-8",
    )
    return path


def test_the_sidecar_accepts_a_bom_and_a_trailing_comment(tmp_path: Path) -> None:
    path = write_style(
        tmp_path / "s.csl",
        "NLM Style Guide (Vancouver): renamed variant",
        "http://example.org/styles/nlm-style-guide-vancouver",
    )
    (tmp_path / "accepted-csl-ids.txt").write_text(
        "\ufeffhttp://example.org/styles/nlm-style-guide-vancouver  # confirmed\n",
        encoding="utf-8",
    )
    assert style_problem(path, "vancouver") is None


def test_the_adapter_denies_writing_the_style_folder() -> None:
    from importlib.resources import files

    config = json.loads(
        files("paperchain").joinpath("adapters/opencode/opencode.json").read_text(encoding="utf-8")
    )
    rules = config["permissions"]
    assert any(
        rule["action"] == "edit"
        and rule["resource"] == "styles/**"
        and rule["effect"] == "deny"
        for rule in rules
    )


# -- 6/7. indented code, data images ---------------------------------------


def test_media_rewrite_skips_indented_code(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    materialized = project.paper_dir / ".paperchain-build-media"
    materialized.mkdir()
    text = "![a](media/a.png)\n\n    ![b](media/b.png)\n"
    rendered = _rewrite_media_links(text, project, materialized)
    assert "](.paperchain-build-media/a.png)" in rendered
    assert "![b](media/b.png)" in rendered


def test_resource_checks_skip_indented_code(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _check_resources(_mask_code_blocks("    ![x](media/missing.png)\n"), project)


def test_a_data_image_is_accepted(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _check_resources("![x](data:image/png;base64,AAAA)", project)


def test_a_non_image_data_uri_is_rejected(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    with pytest.raises(PaperchainError) as error:
        _check_resources("![x](data:text/html;base64,AAAA)", project)
    assert error.value.code == "pandoc_resource_blocked"
