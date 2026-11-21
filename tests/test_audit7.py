"""Gap 2 from the step-1 tamper test: the Zotero export is hashed without a style."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from paperchain.check import run_check
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.locking import run_lock
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


def styleless_project(tmp_path: Path) -> Project:
    project = make_project(tmp_path)
    assert project.manifest.style == ""
    add_pdf(project, "study2024.pdf", ["Alpha text one."], title="A Study")
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    return Project.open(project.root)


def write_library(project: Project, entries: list[dict]) -> Path:
    path = project.references_dir / "library.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def codes(project: Project) -> set[str]:
    return {finding.code for finding in run_check(Project.open(project.root)).errors}


def test_lock_records_the_export_hash_without_a_style(tmp_path: Path) -> None:
    project = styleless_project(tmp_path)
    write_library(project, LIBRARY)
    run_lock(Project.open(project.root))
    assert Project.open(project.root).manifest.bibliography_sha256
    assert not {c for c in codes(project) if c.startswith("bibliography")}


def test_an_edited_export_is_an_error_without_a_style(tmp_path: Path) -> None:
    project = styleless_project(tmp_path)
    path = write_library(project, LIBRARY)
    run_lock(Project.open(project.root))
    forged = copy.deepcopy(LIBRARY)
    forged[0]["author"] = [{"family": "Nobel", "given": "X"}]
    forged[0]["issued"] = {"date-parts": [[1999]]}
    path.write_text(json.dumps(forged), encoding="utf-8")
    assert "bibliography_hash_mismatch" in codes(project)


def test_an_export_added_after_lock_is_an_error_without_a_style(tmp_path: Path) -> None:
    project = styleless_project(tmp_path)
    run_lock(Project.open(project.root))
    write_library(project, LIBRARY)
    assert "bibliography_not_locked" in codes(project)


def test_a_removed_export_is_an_error_without_a_style(tmp_path: Path) -> None:
    project = styleless_project(tmp_path)
    path = write_library(project, LIBRARY)
    run_lock(Project.open(project.root))
    path.chmod(0o644)
    path.unlink()
    assert "bibliography_missing" in codes(project)


def test_lock_needs_accept_changes_for_a_changed_export(tmp_path: Path) -> None:
    project = styleless_project(tmp_path)
    path = write_library(project, LIBRARY)
    run_lock(Project.open(project.root))
    changed = copy.deepcopy(LIBRARY)
    changed[0]["title"] = "A Study, Revised"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(PaperchainError) as error:
        run_lock(Project.open(project.root))
    assert error.value.code == "lock_changes"
    run_lock(Project.open(project.root), accept_changes=True)
    assert "bibliography_hash_mismatch" not in codes(project)


def test_a_project_without_an_export_is_unaffected(tmp_path: Path) -> None:
    project = styleless_project(tmp_path)
    run_lock(Project.open(project.root))
    assert Project.open(project.root).manifest.bibliography_sha256 == ""
    assert not {c for c in codes(project) if c.startswith("bibliography")}
