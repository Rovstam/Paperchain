"""Fixes for the second audit: Zotero keys, build resources, front matter and hints."""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from paperchain.build import (
    _ast_image_targets,
    _check_resources,
    _docx_has_reference_list,
    _docx_text,
    _validate_resource,
    run_build,
)
from paperchain.locking import run_lock
from paperchain.check import front_matter_keys, run_check
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.library import style_problem
from paperchain.match_cmd import run_match
from paperchain.project import Project

from .conftest import add_pdf, make_project, write_paper

LIBRARY = [
    {"id": "Amaeze2021", "type": "article-journal", "title": "A Study"},
]


def project_with_source(tmp_path: Path, title: str = "A Study") -> Project:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."], title=title)
    run_convert(project)
    return Project.open(project.root)


def write_library(project: Project, entries: list[dict] | None = None) -> Path:
    path = project.references_dir / "library.json"
    path.write_text(json.dumps(entries if entries is not None else LIBRARY), encoding="utf-8")
    return path


def codes(report) -> set[str]:
    return {finding.code for finding in report.errors}


# -- 1. Zotero keys --------------------------------------------------------


def test_a_zotero_key_cites_the_source_it_is_mapped_to(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "Amaeze2021"
    project.save()
    write_library(project)
    write_paper(project, '# T\n\nA claim [@Amaeze2021, p. 1: "Alpha text one."].\n')

    report = run_check(Project.open(project.root))
    assert report.ok
    assert report.citations[0]["citation_key"] == "Amaeze2021"


def test_the_internal_key_still_resolves_through_the_citation_key(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "Amaeze2021"
    project.save()
    write_library(project)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')

    report = run_check(Project.open(project.root))
    assert report.ok
    assert report.citations[0]["citation_key"] == "Amaeze2021"


def test_an_unmapped_zotero_key_points_at_match(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project)
    write_paper(project, "# T\n\nA claim [@Amaeze2021].\n")

    report = run_check(Project.open(project.root))
    error = next(f for f in report.errors if f.code == "unknown_citation_key")
    assert "paperchain match" in (error.hint or "")


def test_a_citation_key_that_is_not_in_the_export_is_actionable(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "Other2020"
    project.save()
    write_library(project)
    write_paper(project, "# T\n\nA claim [@Other2020].\n")

    report = run_check(Project.open(project.root))
    error = next(f for f in report.errors if f.code == "citation_not_in_bibliography")
    assert "citation_key" in (error.hint or "")
    assert error.data["source"] == "study2024"


def test_duplicate_citation_keys_are_rejected(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "Amaeze2021"
    second = copy.copy(project.manifest.sources[0])
    second.key = "other2024"
    second.citation_key = "Amaeze2021"
    project.manifest.sources.append(second)
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"
    assert "citation_key" in error.value.message


def test_an_invalid_citation_key_is_rejected(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "not a key"
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"


def test_match_assigns_a_unique_title(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project)

    result = run_match(Project.open(project.root))
    assert [row["status"] for row in result["sources"]] == ["matched"]
    assert result["sources"][0]["candidates"] == ["Amaeze2021"]
    assert Project.open(project.root).manifest.sources[0].citation_key == ""


def test_match_apply_writes_the_citation_key(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project)

    run_match(Project.open(project.root), apply=True)
    assert Project.open(project.root).manifest.sources[0].citation_key == "Amaeze2021"


def test_match_reports_an_ambiguous_title(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(
        project,
        [
            {"id": "Amaeze2021", "title": "A Study"},
            {"id": "Amaeze2022", "title": "A Study"},
        ],
    )

    result = run_match(Project.open(project.root))
    assert result["sources"][0]["status"] == "ambiguous"
    assert "bibliography_duplicate_title" in {finding.code for finding in result["warnings"]}
    assert Project.open(project.root).manifest.sources[0].citation_key == ""


def test_match_keeps_an_existing_citation_key(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    project.manifest.sources[0].citation_key = "Manual2020"
    project.save()
    write_library(project)

    result = run_match(Project.open(project.root))
    assert result["sources"][0]["status"] == "kept"
    assert Project.open(project.root).manifest.sources[0].citation_key == "Manual2020"


def test_match_ignores_csl_entries_without_a_title(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, [{"id": "NoTitle2020"}])

    result = run_match(Project.open(project.root))
    assert result["sources"][0]["status"] == "unmatched"


def test_match_reports_a_source_without_a_csl_entry(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, [{"id": "Other2020", "title": "Something Else"}])

    result = run_match(Project.open(project.root))
    assert result["sources"][0]["status"] == "unmatched"
    assert "citation_key_unmatched" in {finding.code for finding in result["warnings"]}


def test_match_does_not_reuse_one_entry_for_two_sources(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    second = copy.copy(project.manifest.sources[0])
    second.key = "study2025"
    second.title = "A Study"
    second.citation_key = ""
    project.manifest.sources.append(second)
    project.save()
    write_library(project)

    result = run_match(Project.open(project.root))
    statuses = sorted(row["status"] for row in result["sources"])
    assert statuses == ["ambiguous", "matched"]


def test_an_unused_csl_entry_is_a_warning(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, LIBRARY + [{"id": "Other2020", "title": "Unused"}])
    report = run_check(Project.open(project.root))
    assert "bibliography_entry_unmatched" in {finding.code for finding in report.warnings}


# -- 2. front matter -------------------------------------------------------


def test_front_matter_keys_are_parsed() -> None:
    assert front_matter_keys("---\nlang: en\ntitle: T\n---\nBody") == {"lang": 2, "title": 3}
    assert front_matter_keys("Body\n---\nlang: en\n---") is None


def test_suppress_bibliography_front_matter_is_an_error(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        '---\nsuppress-bibliography: true\n---\n\nA claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    report = run_check(Project.open(project.root))
    error = next(f for f in report.errors if f.code == "front_matter_overrides_citations")
    assert error.line == 2


def test_benign_front_matter_is_allowed(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_paper(
        project,
        "---\nlang: en\n---\n\nA claim [@study2024, p. 1: \"Alpha text one.\"].\n",
    )
    assert "front_matter_overrides_citations" not in codes(run_check(Project.open(project.root)))


# -- 3. build resources ----------------------------------------------------


def test_a_percent_encoded_image_name_is_accepted(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    media = project.paper_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "my img.png").write_bytes(b"x")
    _validate_resource("media/my%20img.png", project)


def test_a_parenthesis_in_an_image_name_is_accepted(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    media = project.paper_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "img(1).png").write_bytes(b"x")
    _check_resources("![x](media/img(1).png)", project)


def test_a_dot_slash_image_path_is_accepted(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    media = project.paper_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "x.png").write_bytes(b"x")
    _check_resources("![x](./media/x.png)", project)


def test_a_dangling_media_link_mentions_the_cache(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.ensure_media_dir()
    with pytest.raises(PaperchainError) as error:
        _validate_resource("media/missing.png", project)
    assert "cache" in (error.value.hint or "")


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_reference_style_image_outside_the_project_is_seen(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (tmp_path / "outside.png").write_bytes(b"x")
    text = "![a][id]\n\n[id]: ../../outside.png\n"
    path = project.paper_dir / "raw.md"
    path.write_text(text, encoding="utf-8")
    targets = _ast_image_targets(shutil.which("pandoc") or "pandoc", path, project)
    assert targets == ["../../outside.png"]
    with pytest.raises(PaperchainError) as error:
        _validate_resource(targets[0], project)
    assert error.value.code == "pandoc_resource_blocked"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are not supported")
def test_a_bracketed_alt_image_outside_the_project_is_seen(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (tmp_path / "secret.png").write_bytes(b"x")
    path = project.paper_dir / "raw.md"
    path.write_text("![fig [1]](../../secret.png)\n", encoding="utf-8")
    targets = _ast_image_targets(shutil.which("pandoc") or "pandoc", path, project)
    assert targets == ["../../secret.png"]


def test_docx_text_reads_runs(tmp_path: Path) -> None:
    from .helpers import write_docx

    path = tmp_path / "d.docx"
    write_docx(path, ["Body", "References"])
    assert "References" in _docx_text(path)


CITED_LIBRARY = [
    {
        "id": "study2024",
        "type": "article-journal",
        "title": "A Study",
        "author": [{"family": "Doe", "given": "J"}],
        "issued": {"date-parts": [[2024]]},
    }
]


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_cited_build_keeps_the_reference_list(tmp_path: Path) -> None:
    project = project_with_source(tmp_path)
    write_library(project, CITED_LIBRARY)
    write_paper(project, "# T\n\nA claim [@study2024].\n")
    run_lock(Project.open(project.root))
    result = run_build(Project.open(project.root))
    assert result.output is not None


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_the_reference_list_detector_reads_citeproc_output(tmp_path: Path) -> None:
    import subprocess

    library = write_library(make_project(tmp_path), CITED_LIBRARY)

    cases = {
        "cited": "# T\n\nA claim [@study2024].\n",
        "suppressed": "---\nsuppress-bibliography: true\n---\n\n# T\n\nA claim [@study2024].\n",
    }
    for name, text in cases.items():
        source = tmp_path / f"{name}.md"
        source.write_text(text, encoding="utf-8")
        output = tmp_path / f"{name}.docx"
        subprocess.run(
            [
                shutil.which("pandoc") or "pandoc",
                str(source),
                "--citeproc",
                f"--bibliography={library}",
                "-o",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        assert _docx_has_reference_list(output) is (name == "cited")


# -- 4. .bib guidance ------------------------------------------------------


def test_a_bibtex_export_is_reported_with_a_conversion_hint(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.manifest.bibliography = "References/library.json"
    project.save()
    (project.references_dir / "library.bib").write_text("@article{,}", encoding="utf-8")

    report = run_check(Project.open(project.root))
    error = next(f for f in report.errors if f.code == "bibliography_bibtex_unsupported")
    assert "csljson" in (error.hint or "")


def test_a_bibtex_path_is_rejected_before_pandoc_sees_it(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.manifest.bibliography = "References/library.bib"
    project.save()
    (project.references_dir / "library.bib").write_text("@article{a, title={T}}", encoding="utf-8")

    report = run_check(Project.open(project.root))
    assert "bibliography_bibtex_unsupported" in codes(report)


def test_a_bibtex_only_project_is_reported_with_the_conversion_hint(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.references_dir / "library.bib").write_text("@article{a, title={T}}", encoding="utf-8")

    report = run_check(Project.open(project.root))
    error = next(f for f in report.errors if f.code == "bibliography_bibtex_unsupported")
    assert "csljson" in (error.hint or "")


def test_lock_points_a_bibtex_export_at_the_conversion(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    project.manifest.style = "vancouver"
    project.save()
    (project.references_dir / "library.bib").write_text("@article{a, title={T}}", encoding="utf-8")

    with pytest.raises(PaperchainError) as error:
        run_lock(Project.open(project.root))
    assert "csljson" in (error.value.hint or "") + error.value.message


# -- 5. style validation ---------------------------------------------------


def style(path: Path, info: str, citation: str) -> Path:
    path.write_text(
        '<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">'
        f"<info>{info}</info>"
        f"<citation><layout>{citation}</layout></citation>"
        "<bibliography><layout><text variable=\"title\"/></layout></bibliography>"
        "</style>",
        encoding="utf-8",
    )
    return path


def test_a_number_element_with_citation_number_is_accepted(tmp_path: Path) -> None:
    path = style(
        tmp_path / "s.csl",
        "<title>Vancouver</title><id>http://www.zotero.org/styles/vancouver</id>",
        '<number variable="citation-number"/>',
    )
    assert style_problem(path, "vancouver") is None


def test_the_current_zotero_vancouver_download_is_accepted(tmp_path: Path) -> None:
    # zotero.org/styles/vancouver now serves this variant; its id is not
    # "vancouver", so the allow-list has to know the alias.
    path = style(
        tmp_path / "official.csl",
        "<title>NLM/Vancouver: Citing Medicine 2nd edition (citation-sequence)</title>"
        "<id>http://www.zotero.org/styles/nlm-citation-sequence</id>",
        '<text variable="citation-number"/>',
    )
    assert style_problem(path, "vancouver") is None


def test_a_dependent_style_names_its_parent(tmp_path: Path) -> None:
    path = style(
        tmp_path / "s.csl",
        "<title>Vancouver (dependent)</title><id>http://example.org/dependent</id>"
        '<link rel="independent-parent" href="http://www.zotero.org/styles/vancouver"/>',
        '<text variable="citation-number"/>',
    )
    problem = style_problem(path, "vancouver")
    assert problem and "dependent" in problem
    assert "zotero.org/styles/vancouver" in problem


def test_an_ieee_style_that_calls_itself_vancouver_is_rejected(tmp_path: Path) -> None:
    path = style(
        tmp_path / "s.csl",
        "<title>Vancouver</title><id>http://www.zotero.org/styles/ieee</id>",
        '<text variable="citation-number"/>',
    )
    problem = style_problem(path, "vancouver")
    assert problem and "ieee" in problem


# -- 6. media layout -------------------------------------------------------


def test_media_is_a_link_by_default_or_a_plain_folder_when_the_os_refuses(tmp_path: Path) -> None:
    from paperchain.util import is_link

    project = make_project(tmp_path)
    media = project.ensure_media_dir()
    assert media.is_dir()
    # Either the OS provided a junction/symlink or ensure_media_dir fell back.
    assert is_link(media) or not media.is_symlink()
