"""Tests for `paperchain organize`, the plan-first folder sorter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperchain.cli import main
from paperchain.errors import PaperchainError
from paperchain.organize import build_plan, run_organize
from paperchain.project import Project

from .conftest import make_project
from .helpers import write_pdf


def _messy_project(tmp_path: Path) -> Project:
    project = make_project(tmp_path)
    root = project.root

    # A canonical copy already exists under References/.
    write_pdf(root / "References" / "Articulos" / "alpha.pdf", ["Alpha source."])

    # The old reference tree: one duplicate, one new article, one norm, and
    # auxiliary bibliography files.
    write_pdf(root / "Referencias" / "Articulos" / "alpha.pdf", ["Alpha source."])
    write_pdf(root / "Referencias" / "Articulos" / "dup" / "beta.pdf", ["Beta source."])
    write_pdf(root / "Referencias" / "Resoluciones" / "rule.pdf", ["Rule text."])
    (root / "Referencias" / "library.bib").write_text("@article{x}", encoding="utf-8")
    (root / "Referencias" / "desktop.ini").write_text("ini", encoding="utf-8")

    # The original manuscript, still in its old folder.
    write_pdf(root / "1 Monografia" / "draft.pdf", ["Draft text."])
    project.manifest.manuscript_path = "1 Monografia/draft.pdf"
    project.save()

    # Working material and a loose source.
    write_pdf(root / "Ejemplos" / "example.pdf", ["Example thesis."])
    write_pdf(root / "Guia Monografia.pdf", ["Formatting guide."])
    write_pdf(root / "loose-source.pdf", ["Loose source."])
    (root / "agent-reads-this.md").write_text("old plan", encoding="utf-8")
    return Project.open(root)


def _by_source(result: dict) -> dict[str, dict]:
    return {move["source"]: move for move in result["data"]["moves"]}


# -- plan mode ------------------------------------------------------------


def test_plan_moves_nothing_and_maps_every_kind(tmp_path: Path) -> None:
    project = _messy_project(tmp_path)
    result = run_organize(project)

    assert result["applied"] is False
    assert (project.root / "1 Monografia" / "draft.pdf").is_file()
    assert (project.root / "Referencias" / "Articulos" / "alpha.pdf").is_file()

    moves = _by_source(result)
    assert moves["1 Monografia/draft.pdf"]["target"] == "Manuscript/draft.pdf"
    assert moves["1 Monografia/draft.pdf"]["kind"] == "manuscript"

    assert moves["Referencias/Articulos/alpha.pdf"]["kind"] == "duplicate"
    assert moves["Referencias/Articulos/alpha.pdf"]["target"] == (
        "Dump/Referencias/Articulos/alpha.pdf"
    )
    assert moves["Referencias/Articulos/dup/beta.pdf"]["target"] == (
        "References/Articulos/dup/beta.pdf"
    )
    assert moves["Referencias/Resoluciones/rule.pdf"]["target"] == (
        "References/Resoluciones/rule.pdf"
    )
    assert moves["Referencias/library.bib"]["target"] == "References/library.bib"

    assert moves["Ejemplos/example.pdf"]["target"] == "Dump/Ejemplos/example.pdf"
    assert moves["Guia Monografia.pdf"]["target"] == "Dump/Guia Monografia.pdf"
    assert moves["agent-reads-this.md"]["target"] == "Dump/agent-reads-this.md"
    assert moves["loose-source.pdf"]["target"] == "References/loose-source.pdf"


def test_plan_keeps_system_files_out_of_the_reference_set(tmp_path: Path) -> None:
    project = _messy_project(tmp_path)
    moves = _by_source(run_organize(project))
    assert moves["Referencias/desktop.ini"]["kind"] == "dump"
    assert moves["Referencias/desktop.ini"]["target"] == (
        "Dump/Referencias/desktop.ini"
    )


def test_content_dedupe_ignores_the_folder_name(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_pdf(project.root / "References" / "Articulos" / "short.pdf", ["Same text."])
    write_pdf(
        project.root / "Referencias" / "Articulos" / "long folder name" / "short.pdf",
        ["Same text."],
    )

    moves = _by_source(run_organize(project))
    move = moves["Referencias/Articulos/long folder name/short.pdf"]
    assert move["kind"] == "duplicate"
    assert move["target"] == (
        "Dump/Referencias/Articulos/long folder name/short.pdf"
    )


# -- apply ----------------------------------------------------------------


def test_apply_moves_files_and_updates_the_manifest(tmp_path: Path) -> None:
    project = _messy_project(tmp_path)
    result = run_organize(project, apply=True)

    assert result["applied"] is True
    root = project.root
    assert (root / "Manuscript" / "draft.pdf").is_file()
    assert not (root / "1 Monografia").exists()
    assert not (root / "Referencias").exists()
    assert not (root / "Ejemplos").exists()
    assert not (root / "Guia Monografia.pdf").exists()
    assert not (root / "agent-reads-this.md").exists()

    assert (root / "References" / "Articulos" / "alpha.pdf").is_file()
    assert (root / "References" / "Articulos" / "dup" / "beta.pdf").is_file()
    assert (root / "References" / "Resoluciones" / "rule.pdf").is_file()
    assert (root / "References" / "library.bib").is_file()
    assert (root / "References" / "loose-source.pdf").is_file()
    assert (root / "Dump" / "Referencias" / "Articulos" / "alpha.pdf").is_file()
    assert (root / "Dump" / "Referencias" / "desktop.ini").is_file()

    reopened = Project.open(root)
    assert reopened.manifest.manuscript_path == "Manuscript/draft.pdf"


def test_word_lock_file_does_not_keep_the_old_folder(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_pdf(project.root / "Revisiones" / "review.pdf", ["Review copy."])
    (project.root / "Revisiones" / "~$review.docx").write_text("lock", encoding="utf-8")

    run_organize(project, apply=True)

    assert not (project.root / "Revisiones").exists()
    assert (project.root / "Dump" / "Revisiones" / "~$review.docx").is_file()


def test_apply_is_idempotent(tmp_path: Path) -> None:
    project = _messy_project(tmp_path)
    run_organize(project, apply=True)
    second = run_organize(Project.open(project.root), apply=True)
    assert second["data"]["moves"] == []


def test_manuscript_name_conflict_gets_a_new_name(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_pdf(project.root / "Manuscript" / "draft.pdf", ["Already here."])
    write_pdf(project.root / "1 Monografia" / "draft.pdf", ["The original."])
    project.manifest.manuscript_path = "1 Monografia/draft.pdf"
    project.save()

    plan = _by_source(run_organize(Project.open(project.root)))
    assert plan["1 Monografia/draft.pdf"]["kind"] == "manuscript"
    assert plan["1 Monografia/draft.pdf"]["target"] == "Manuscript/draft (2).pdf"

    run_organize(Project.open(project.root), apply=True)
    assert (project.root / "Manuscript" / "draft.pdf").is_file()
    assert (project.root / "Manuscript" / "draft (2).pdf").is_file()
    assert Project.open(project.root).manifest.manuscript_path == (
        "Manuscript/draft (2).pdf"
    )


def test_apply_never_overwrites_a_different_file(tmp_path: Path) -> None:
    project = _messy_project(tmp_path)
    root = project.root
    write_pdf(root / "References" / "Articulos" / "gamma.pdf", ["Canonical text."])
    write_pdf(root / "Referencias" / "Articulos" / "gamma.pdf", ["Different text."])

    plan = _by_source(run_organize(Project.open(root)))
    assert plan["Referencias/Articulos/gamma.pdf"]["kind"] == "conflict"
    assert plan["Referencias/Articulos/gamma.pdf"]["target"] == (
        "Dump/conflicts/Referencias/Articulos/gamma.pdf"
    )

    run_organize(Project.open(root), apply=True)
    assert "Canonical text" in (root / "References" / "Articulos" / "gamma.pdf").read_bytes().decode(
        "latin-1", errors="ignore"
    )
    assert (root / "Dump" / "conflicts" / "Referencias" / "Articulos" / "gamma.pdf").is_file()


# -- ambiguous manuscript -------------------------------------------------


def _two_candidates(tmp_path: Path) -> Project:
    project = make_project(tmp_path)
    write_pdf(project.root / "first.pdf", ["First candidate."])
    write_pdf(project.root / "second.pdf", ["Second candidate."])
    return project


def test_ambiguous_manuscript_is_reported_and_apply_refuses(tmp_path: Path) -> None:
    project = _two_candidates(tmp_path)
    result = run_organize(project)
    assert result["candidates"] == ["first.pdf", "second.pdf"]
    assert (project.root / "first.pdf").is_file()
    assert (project.root / "second.pdf").is_file()

    with pytest.raises(PaperchainError) as error:
        run_organize(Project.open(project.root), apply=True)
    assert error.value.code == "manuscript_ambiguous"


def test_explicit_manuscript_resolves_the_ambiguity(tmp_path: Path) -> None:
    project = _two_candidates(tmp_path)
    run_organize(project, apply=True, manuscript="first.pdf")

    assert (project.root / "Manuscript" / "first.pdf").is_file()
    assert not (project.root / "first.pdf").exists()
    assert (project.root / "References" / "second.pdf").is_file()
    assert Project.open(project.root).manifest.manuscript_path == "Manuscript/first.pdf"


# -- explicit overrides ---------------------------------------------------


def test_reference_and_dump_overrides(tmp_path: Path) -> None:
    project = _messy_project(tmp_path)
    write_pdf(project.root / "Material" / "paper.pdf", ["Extra source."])
    write_pdf(project.root / "extra.pdf", ["Loose document."])

    result = run_organize(
        Project.open(project.root),
        references=["Material"],
        dumps=["extra.pdf"],
    )
    moves = _by_source(result)
    assert moves["Material/paper.pdf"]["target"] == "References/paper.pdf"
    assert moves["extra.pdf"]["target"] == "Dump/extra.pdf"


# -- CLI ------------------------------------------------------------------


def test_cli_organize_prints_a_plan_without_moving(tmp_path: Path, capsys) -> None:
    project = _messy_project(tmp_path)
    assert main(["organize", "--project", str(project.root), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "organize"
    assert payload["ok"] is True
    assert payload["data"]["applied"] is False
    assert payload["data"]["moves"]
    assert (project.root / "1 Monografia" / "draft.pdf").is_file()
