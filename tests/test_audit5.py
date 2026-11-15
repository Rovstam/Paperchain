"""Fixes for the third audit: bibliography detection, duplicate ids and matching."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from paperchain.build import _docx_has_reference_list, _rewrite_media_links, run_build
from paperchain.check import front_matter_keys, run_check
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.library import style_problem, titles_equal
from paperchain.locking import run_lock
from paperchain.match_cmd import run_match
from paperchain.project import Project

from .conftest import add_pdf, make_project, write_paper
from .helpers import write_docx

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


# -- 1. YAML metadata blocks anywhere --------------------------------------


def test_a_mid_document_suppress_bibliography_is_an_error(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        '# T\n\n## Related work with references\n\n---\nsuppress-bibliography: true\n---\n'
        '\nA claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    report = run_check(Project.open(project.root))
    error = next(f for f in report.errors if f.code == "front_matter_overrides_citations")
    assert error.line == 6


def test_a_leading_blank_line_does_not_hide_the_block(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        '\n---\nsuppress-bibliography: true\n---\n\nA claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    assert "front_matter_overrides_citations" in codes(run_check(Project.open(project.root)))


@pytest.mark.parametrize(
    "block",
    [
        '"suppress-bibliography": true',
        "{suppress-bibliography: true, lang: en}",
    ],
)
def test_quoted_and_flow_mapping_keys_are_seen(tmp_path: Path, block: str) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        f'# T\n\n---\n{block}\n---\n\nA claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    assert "front_matter_overrides_citations" in codes(run_check(Project.open(project.root)))


def test_a_yaml_block_inside_a_code_fence_is_not_metadata(tmp_path: Path) -> None:
    text = "# T\n\n```\n---\nsuppress-bibliography: true\n---\n```\n\nBody\n"
    assert front_matter_keys(text) is None


def test_a_mid_document_block_cannot_remove_the_reference_list(tmp_path: Path) -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is not installed")
    project = project_with_source(tmp_path)
    write_library(project, LIBRARY)
    write_paper(
        project,
        '# T\n\n## Related work with references\n\n---\nsuppress-bibliography: true\n---\n'
        "\nA claim [@study2024].\n",
    )
    run_lock(Project.open(project.root))
    with pytest.raises(PaperchainError) as error:
        run_build(Project.open(project.root), force=True)
    assert error.value.code == "bibliography_missing_from_output"


def test_prose_with_the_word_references_is_not_a_reference_list(tmp_path: Path) -> None:
    path = tmp_path / "prose.docx"
    write_docx(path, ["Related work with references", "Bibliography and notes"])
    assert _docx_has_reference_list(path) is False


def test_the_bibliography_paragraph_style_is_still_accepted(tmp_path: Path) -> None:
    path = tmp_path / "styled.docx"
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:pPr><w:pStyle w:val=\"Bibliography\"/></w:pPr>"
        "<w:r><w:t>Doe J. A Study. 2024.</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
    assert _docx_has_reference_list(path) is True


# -- 2. duplicate CSL ids ---------------------------------------------------


def test_a_duplicate_id_used_by_a_source_is_an_error(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(
        project,
        [
            {"id": "study2024", "title": "A Study"},
            {"id": "study2024", "title": "A Different Work"},
        ],
    )
    report = run_check(Project.open(project.root))
    error = next(f for f in report.errors if f.code == "bibliography_duplicate_id")
    assert error.data["key"] == "study2024"


def test_an_unused_duplicate_id_stays_a_warning(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(
        project,
        LIBRARY
        + [
            {"id": "Unused2020", "title": "Unused One"},
            {"id": "Unused2020", "title": "Unused Two"},
        ],
    )
    report = run_check(Project.open(project.root))
    assert "bibliography_duplicate_id" not in codes(report)
    assert "bibliography_duplicate_id" in {finding.code for finding in report.warnings}


def test_match_does_not_apply_a_duplicate_id(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(
        project,
        [
            {"id": "Amaeze2021", "title": "A Study"},
            {"id": "Amaeze2021", "title": "Another Work"},
        ],
    )
    result = run_match(Project.open(project.root), apply=True)
    assert result["sources"][0]["status"] == "ambiguous"
    assert Project.open(project.root).manifest.sources[0].citation_key == ""


# -- 3. exact matching and metadata -----------------------------------------


def test_containment_is_only_a_suggestion(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, [{"id": "Long2020", "title": "A Study: Extended Edition"}])
    result = run_match(Project.open(project.root), apply=True)
    assert result["sources"][0]["status"] == "suggestion"
    assert result["sources"][0]["candidates"] == ["Long2020"]
    assert Project.open(project.root).manifest.sources[0].citation_key == ""


def test_an_exact_title_is_still_applied(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, [{"id": "Amaeze2021", "title": "A Study"}])
    run_match(Project.open(project.root), apply=True)
    assert Project.open(project.root).manifest.sources[0].citation_key == "Amaeze2021"


def test_a_mismatched_title_is_an_error_once_a_citation_key_is_set(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "Other2020"
    project.save()
    write_library(project, [{"id": "Other2020", "title": "A Different Work"}])
    report = run_check(Project.open(project.root))
    assert "source_metadata_mismatch" in codes(report)


def test_a_mismatched_title_is_a_warning_without_a_citation_key(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, [{"id": "study2024", "title": "A Different Work"}])
    report = run_check(Project.open(project.root))
    assert "source_metadata_mismatch" not in codes(report)
    assert "source_metadata_mismatch" in {finding.code for finding in report.warnings}
    assert titles_equal("A Study", "A Study") is True
    assert titles_equal("A Study", "A Study: Extended") is False


# -- 4. Unicode citation keys ------------------------------------------------


def test_a_non_ascii_citation_key_works_end_to_end(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "Peña2022"
    project.save()
    write_library(project, [{"id": "Peña2022", "title": "A Study"}])
    write_paper(project, '# T\n\nA claim [@Peña2022, p. 1: "Alpha text one."].\n')
    report = run_check(Project.open(project.root))
    assert report.ok
    assert report.citations[0]["key"] == "Peña2022"


def test_match_writes_a_non_ascii_id_that_project_accepts(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, [{"id": "Peña2022", "title": "A Study"}])
    run_match(Project.open(project.root), apply=True)
    opened = Project.open(project.root)
    assert opened.manifest.sources[0].citation_key == "Peña2022"


# -- 5. style validation -----------------------------------------------------


def write_style(path: Path, title: str, ident: str, citation: str, bibliography: bool = True) -> Path:
    path.write_text(
        '<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">'
        f"<info><title>{title}</title><id>{ident}</id></info>"
        f"<citation><layout>{citation}</layout></citation>"
        + ('<bibliography><layout><text variable="title"/></layout></bibliography>' if bibliography else "")
        + "</style>",
        encoding="utf-8",
    )
    return path


def test_a_custom_numeric_style_named_vancouver_is_rejected(tmp_path: Path) -> None:
    path = write_style(
        tmp_path / "s.csl",
        "Vancouver: my own numeric style",
        "http://example.org/styles/my-numeric",
        '<text variable="citation-number"/>',
    )
    problem = style_problem(path, "vancouver")
    assert problem and "not a known vancouver style" in problem


def test_a_style_without_a_bibliography_element_is_rejected(tmp_path: Path) -> None:
    path = write_style(
        tmp_path / "s.csl",
        "Vancouver",
        "http://www.zotero.org/styles/vancouver",
        '<text variable="citation-number"/>',
        bibliography=False,
    )
    problem = style_problem(path, "vancouver")
    assert problem and "bibliography" in problem


def test_a_named_variant_can_be_accepted_explicitly(tmp_path: Path) -> None:
    path = write_style(
        tmp_path / "s.csl",
        "NLM Style Guide (Vancouver): renamed variant",
        "http://example.org/styles/nlm-style-guide-vancouver",
        '<text variable="citation-number"/>',
    )
    assert style_problem(path, "vancouver") is not None
    (tmp_path / "accepted-csl-ids.txt").write_text(
        "# confirmed against the printed output\n"
        "http://example.org/styles/nlm-style-guide-vancouver\n",
        encoding="utf-8",
    )
    assert style_problem(path, "vancouver") is None


# -- 6/7/8. build details ----------------------------------------------------


def test_media_rewrite_skips_code_fences_and_spans(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    materialized = project.paper_dir / ".paperchain-build-media"
    materialized.mkdir()
    text = (
        "![a](media/a.png)\n\n"
        "```\n![b](media/b.png)\n```\n\n"
        "Inline `![c](media/c.png)` stays.\n"
    )
    rendered = _rewrite_media_links(text, project, materialized)
    assert "](.paperchain-build-media/a.png)" in rendered
    assert "![b](media/b.png)" in rendered
    assert "![c](media/c.png)" in rendered


def test_reference_doc_outside_the_project_is_rejected(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    outside = tmp_path / "outside.docx"
    write_docx(outside, ["Styled"])
    project.manifest.reference_doc = str(outside)
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"
    assert "reference_doc" in error.value.message
