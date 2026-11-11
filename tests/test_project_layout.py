from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from paperchain.build import render_markdown_for_citeproc, run_build
from paperchain.check import run_check
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.import_cmd import run_import
from paperchain.init_cmd import run_init
from paperchain.locking import run_lock
from paperchain.project import Project
from paperchain.util import sha256_file

from .conftest import add_pdf, make_project, write_paper
from .helpers import write_pdf

PANDOC = shutil.which("pandoc")


def _pandoc_docx(path: Path, paragraphs: list[str]) -> None:
    assert PANDOC
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [PANDOC, "--from", "markdown", "--to", "docx", "--output", str(path)],
        input="\n\n".join(paragraphs),
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr


def test_init_creates_a_manuscript_folder(tmp_path: Path) -> None:
    root = tmp_path / "My Project"
    run_init(str(root), title="My Project", agent="opencode")
    assert (root / "Manuscript").is_dir()
    assert (root / "References").is_dir()
    assert not (root / "References" / "_text").exists()


def test_init_adopt_keeps_existing_manuscript_and_references(tmp_path: Path) -> None:
    root = tmp_path / "Existing Thesis"
    (root / "References" / "topic").mkdir(parents=True)
    write_docx = root / "Manuscript" / "Thesis.docx"
    write_docx.parent.mkdir(parents=True)
    write_docx.write_bytes(b"original manuscript bytes")
    (root / "References" / "topic" / "study.pdf").write_bytes(b"reference bytes")

    run_init(str(root), title="Existing Thesis", agent="opencode", adopt=True)

    assert write_docx.read_bytes() == b"original manuscript bytes"
    assert (root / "References" / "topic" / "study.pdf").read_bytes() == b"reference bytes"
    assert (root / "paper.toml").is_file()
    assert (root / "AGENTS.md").is_file()
    assert (root / "Paper" / "paper.md").is_file()


def test_generated_text_is_stored_outside_the_project(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)

    assert not project.text_dir.is_relative_to(project.root)
    assert (project.text_dir / "study2024.txt").is_file()
    assert not (project.root / "References" / "_text").exists()


def test_convert_moves_loose_references_into_their_own_folders(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_pdf(project.references_dir / "study2024.pdf", ["Alpha text one."])
    result = run_convert(project)

    moved = project.references_dir / "study2024" / "study2024.pdf"
    assert moved.is_file()
    assert not (project.references_dir / "study2024.pdf").exists()
    assert result["moved"]
    project = Project.open(project.root)
    source = project.manifest.source("study2024")
    assert source is not None
    assert source.path == "References/study2024/study2024.pdf"


def test_convert_scans_reference_subfolders(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.references_dir / "diabetes").mkdir(parents=True)
    write_pdf(
        project.references_dir / "diabetes" / "study2024.pdf",
        ["The sample contains forty two cases."],
    )
    run_convert(project)

    project = Project.open(project.root)
    source = project.manifest.source("diabetes-study2024")
    assert source is not None
    assert source.path == "References/diabetes/study2024.pdf"

    write_paper(project, '# T\n\nA claim [@diabetes-study2024, p. 1: "The sample contains forty two cases."].\n')
    report = run_check(Project.open(project.root))
    assert report.ok, [finding.message for finding in report.errors]
    assert report.stats["quotes_verified"] == 1


def test_check_reports_a_late_file_in_a_subfolder(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    (project.references_dir / "late").mkdir(parents=True)
    add_pdf(project, Path("late") / "late2025.pdf", ["Added after conversion."])
    report = run_check(Project.open(project.root))
    assert "unmanaged_source" in {finding.code for finding in report.errors}


def test_two_subfolders_can_hold_the_same_filename(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    for topic in ("alpha", "beta"):
        (project.references_dir / topic).mkdir(parents=True)
        add_pdf(project, Path(topic) / "review.pdf", [f"{topic} text."])
    run_convert(project)
    project = Project.open(project.root)
    assert project.manifest.source("alpha-review") is not None
    assert project.manifest.source("beta-review") is not None


@pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")
def test_import_docx_does_not_touch_the_original(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    original = project.manuscript_dir / "Thesis.docx"
    _pandoc_docx(original, ["Thesis title", "A body paragraph."])
    before = sha256_file(original)

    result = run_import(project)

    assert result["paper"] == "Paper/paper.md"
    assert sha256_file(original) == before
    paper = (project.root / "Paper/paper.md").read_text(encoding="utf-8")
    assert "A body paragraph." in paper
    project = Project.open(project.root)
    assert project.manifest.manuscript_path == "Manuscript/Thesis.docx"
    assert project.manifest.manuscript_sha256 == before


def test_import_pdf_keeps_the_original_and_writes_markdown(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    original = project.root / "Thesis.pdf"
    write_pdf(original, ["First page.", "Second page."])
    before = sha256_file(original)

    result = run_import(project)

    assert sha256_file(original) == before
    paper = (project.root / "Paper/paper.md").read_text(encoding="utf-8")
    assert "First page." in paper
    assert "Second page." in paper
    assert result["warnings"][0].code == "pdf_import_plain_text"


@pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")
def test_import_refuses_to_overwrite_edits_without_force(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _pandoc_docx(project.manuscript_dir / "Thesis.docx", ["Thesis title"])
    run_import(project)
    project = Project.open(project.root)
    write_paper(project, "# My edited draft\n")

    with pytest.raises(PaperchainError) as error:
        run_import(Project.open(project.root))
    assert error.value.code == "paper_exists"
    assert (project.root / "Paper/paper.md").read_text(encoding="utf-8") == "# My edited draft\n"


def test_import_cli_emits_one_json_object(tmp_path: Path, capsys) -> None:
    from paperchain.cli import main

    project = make_project(tmp_path)
    write_pdf(project.root / "Thesis.pdf", ["First page."])
    exit_code = main(["--project", str(project.root), "import", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"]["paper"] == "Paper/paper.md"
    assert payload["warnings"][0]["code"] == "pdf_import_plain_text"


def test_check_detects_a_changed_manuscript(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    original = project.root / "Thesis.pdf"
    write_pdf(original, ["First page."])
    run_import(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)

    original.write_bytes(original.read_bytes() + b"\n% changed\n")
    codes = {finding.code for finding in run_check(Project.open(project.root)).errors}
    assert "manuscript_hash_mismatch" in codes


def test_citeproc_render_keeps_the_locator_and_drops_the_quote() -> None:
    text = 'A claim [@study2024, p. 12: "exact words"].'
    assert render_markdown_for_citeproc(text) == "A claim [@study2024, p. 12]."


def test_check_requires_citation_keys_in_the_bibliography(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    (project.references_dir / "library.json").write_text(
        json.dumps([{"id": "someone-else", "type": "article-journal", "title": "X"}]),
        encoding="utf-8",
    )
    codes = {finding.code for finding in run_check(Project.open(project.root)).errors}
    assert "citation_not_in_bibliography" in codes


@pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")
def test_build_with_a_zotero_library_uses_citeproc(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    (project.references_dir / "library.json").write_text(
        json.dumps(
            [
                {
                    "id": "study2024",
                    "type": "article-journal",
                    "title": "A Study",
                    "author": [{"family": "Doe", "given": "J"}],
                    "issued": {"date-parts": [[2024]]},
                }
            ]
        ),
        encoding="utf-8",
    )
    run_lock(Project.open(project.root))
    result = run_build(Project.open(project.root))
    assert result.output is not None
    import zipfile

    with zipfile.ZipFile(result.output) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Doe" in xml
    assert "2024" in xml
