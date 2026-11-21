"""R4/R5: the Zotero export is hash-locked and a configured style cannot be skipped."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperchain.build import run_build
from paperchain.check import run_check
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.init_cmd import run_init
from paperchain.library import style_problem
from paperchain.locking import run_lock
from paperchain.project import Project

from .conftest import add_pdf, make_project, write_paper


CSL = """<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">
  <info><title>{title}</title><id>{ident}</id></info>
  <macro name="num"><text variable="citation-number"/></macro>
  <citation><layout prefix="(" suffix=")"><text macro="num"/></layout></citation>
  <bibliography><layout><text variable="citation-number" suffix=". "/><text variable="title"/></layout></bibliography>
</style>
"""

LIBRARY = [
    {
        "id": "study2024",
        "type": "article-journal",
        "title": "A Study",
        "author": [{"family": "Doe", "given": "J"}],
        "issued": {"date-parts": [[2024]]},
    }
]


def write_csl(path: Path, title: str = "Vancouver", ident: str = "http://www.zotero.org/styles/vancouver") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CSL.format(title=title, ident=ident), encoding="utf-8")


def vancouver_project(tmp_path: Path, csl: bool = True) -> Project:
    root = tmp_path / "paper"
    run_init(str(root), title="T", agent="opencode", style="vancouver")
    project = Project.open(root)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(root)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    (project.references_dir / "library.json").write_text(json.dumps(LIBRARY), encoding="utf-8")
    if csl:
        write_csl(root / "styles" / "vancouver.csl")
    return Project.open(root)


def codes(project: Project) -> set[str]:
    return {finding.code for finding in run_check(Project.open(project.root)).errors}


def test_init_style_pins_vancouver_in_the_manifest(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    assert project.manifest.style == "vancouver"
    assert project.manifest.csl == "styles/vancouver.csl"
    assert project.manifest.bibliography == "References/library.json"


def test_init_rejects_an_unknown_style(tmp_path: Path) -> None:
    with pytest.raises(PaperchainError) as error:
        run_init(str(tmp_path / "x"), title="T", agent="opencode", style="apa")
    assert error.value.code == "style_unknown"


def test_valid_vancouver_project_checks_clean(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    run_lock(Project.open(project.root))
    assert codes(project) == set()


def test_missing_csl_is_an_error(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path, csl=False)
    assert "style_requires_csl" in codes(project)


def test_missing_library_is_an_error_not_an_author_year_fallback(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    (project.references_dir / "library.json").unlink()
    assert "style_requires_bibliography" in codes(project)


@pytest.mark.parametrize(
    "title,ident",
    [
        ("Chicago Manual of Style", "http://www.zotero.org/styles/chicago-author-date"),
        ("TEST numeric (not Vancouver)", "http://example.org/test"),
    ],
)
def test_a_csl_that_is_not_vancouver_is_rejected(tmp_path: Path, title: str, ident: str) -> None:
    project = vancouver_project(tmp_path, csl=False)
    write_csl(project.root / "styles" / "vancouver.csl", title=title, ident=ident)
    assert "csl_not_vancouver" in codes(project)


def test_an_author_date_style_named_vancouver_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.csl"
    path.write_text(
        '<style xmlns="http://purl.org/net/xbiblio/csl"><info><title>Vancouver</title>'
        "<id>http://www.zotero.org/styles/vancouver</id></info>"
        '<citation><layout><text variable="title"/></layout></citation></style>',
        encoding="utf-8",
    )
    assert "citation-number" in (style_problem(path, "vancouver") or "")


def test_vancouver_variants_and_macros_are_accepted(tmp_path: Path) -> None:
    path = tmp_path / "s.csl"
    write_csl(path, title="Vancouver (brackets)", ident="http://www.zotero.org/styles/vancouver-brackets")
    assert style_problem(path, "vancouver") is None


def test_current_nlm_vancouver_style_is_accepted(tmp_path: Path) -> None:
    # https://www.zotero.org/styles/vancouver currently serves the NLM style.
    path = tmp_path / "s.csl"
    write_csl(
        path,
        title="NLM/Vancouver: Citing Medicine 2nd edition (citation-sequence)",
        ident="http://www.zotero.org/styles/nlm-citation-sequence",
    )
    assert style_problem(path, "vancouver") is None


def test_not_xml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.csl"
    path.write_text("not xml", encoding="utf-8")
    assert style_problem(path, "vancouver")


def test_a_reexported_library_is_detected_after_lock(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    run_lock(Project.open(project.root))
    library = project.references_dir / "library.json"
    entries = json.loads(library.read_text(encoding="utf-8"))
    entries[0]["title"] = "A Different Title"
    library.write_text(json.dumps(entries), encoding="utf-8")
    assert "bibliography_hash_mismatch" in codes(project)


def test_lock_refuses_a_changed_library_without_accept_changes(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    run_lock(Project.open(project.root))
    library = project.references_dir / "library.json"
    library.write_text(json.dumps(LIBRARY + [{"id": "other", "type": "book", "title": "Y"}]), encoding="utf-8")
    with pytest.raises(PaperchainError) as error:
        run_lock(Project.open(project.root))
    assert error.value.code == "lock_changes"
    run_lock(Project.open(project.root), accept_changes=True)
    assert codes(project) == set()


def test_a_deleted_library_is_detected_after_lock(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    run_lock(Project.open(project.root))
    (project.references_dir / "library.json").unlink()
    assert "bibliography_missing" in codes(project)


def test_an_edited_csl_is_detected_after_lock(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    run_lock(Project.open(project.root))
    write_csl(project.root / "styles" / "vancouver.csl", title="Vancouver", ident="http://www.zotero.org/styles/vancouver-x")
    assert "csl_hash_mismatch" in codes(project)


def test_lock_refuses_a_style_project_without_the_library(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    (project.references_dir / "library.json").unlink()
    with pytest.raises(PaperchainError) as error:
        run_lock(Project.open(project.root))
    assert error.value.code == "lock_failed"
    assert "Zotero export" in error.value.message


def test_lock_refuses_a_style_project_without_the_csl(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path, csl=False)
    with pytest.raises(PaperchainError) as error:
        run_lock(Project.open(project.root))
    assert error.value.code == "lock_failed"
    assert "vancouver.csl" in error.value.message
    assert "CSL" in (error.value.hint or "")
    assert "convert` first" not in (error.value.hint or "")


def test_an_edited_style_sidecar_is_detected_after_lock(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    sidecar = project.root / "styles" / "accepted-csl-ids.txt"
    sidecar.write_text("http://example.org/styles/vancouver\n", encoding="utf-8")
    run_lock(Project.open(project.root))
    sidecar.write_text("http://example.org/styles/other\n", encoding="utf-8")
    assert "csl_hash_mismatch" in codes(project)


def test_an_unhashed_library_after_lock_is_an_error(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    run_lock(Project.open(project.root))
    opened = Project.open(project.root)
    opened.manifest.bibliography_sha256 = ""
    opened.save()
    assert "bibliography_not_locked" in codes(project)


def test_an_unhashed_csl_after_lock_is_an_error(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    run_lock(Project.open(project.root))
    opened = Project.open(project.root)
    opened.manifest.csl_sha256 = ""
    opened.save()
    assert "csl_not_locked" in codes(project)


def test_build_with_a_style_refuses_even_with_force_when_the_csl_is_missing(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path, csl=False)
    with pytest.raises(PaperchainError) as error:
        run_build(Project.open(project.root), force=True)
    assert error.value.code == "style_requires_csl"


def test_build_with_a_style_refuses_the_author_year_fallback(tmp_path: Path) -> None:
    project = vancouver_project(tmp_path)
    (project.references_dir / "library.json").unlink()
    with pytest.raises(PaperchainError) as error:
        run_build(Project.open(project.root), force=True)
    # init --style records the library path, so the missing file is reported as such.
    assert error.value.code in {"bibliography_missing", "style_requires_bibliography"}


def test_project_without_a_style_is_unchanged(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    assert project.manifest.style == ""
    assert "styles" not in {path.name for path in project.root.iterdir()}


def test_no_style_project_hashes_the_zotero_export(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    library = project.references_dir / "library.json"
    library.write_text(json.dumps(LIBRARY), encoding="utf-8")
    run_lock(Project.open(project.root))
    assert Project.open(project.root).manifest.bibliography_sha256
    library.write_text(json.dumps(LIBRARY + [{"id": "other", "type": "book", "title": "Y"}]), encoding="utf-8")
    report = run_check(Project.open(project.root))
    assert "bibliography_hash_mismatch" in {finding.code for finding in report.errors}


def test_style_error_is_reported_before_pandoc_missing(tmp_path: Path, monkeypatch) -> None:
    project = vancouver_project(tmp_path, csl=False)
    monkeypatch.setattr("paperchain.build.shutil.which", lambda name: None)
    with pytest.raises(PaperchainError) as error:
        run_build(Project.open(project.root), force=True)
    assert error.value.code == "style_requires_csl"
