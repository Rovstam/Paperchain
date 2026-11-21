from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from paperchain.build import run_build
from paperchain.check import run_check
from paperchain.cli import main
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.init_cmd import run_init
from paperchain.locking import run_lock, run_unlock
from paperchain.project import Project

from .conftest import add_pdf, make_project, write_paper


def _clean_paper(page_one: str = "The sample contains forty two cases.") -> str:
    return (
        "# Test Paper\n\n"
        f'## Introduction\n\nA claim [@study2024, p. 1: "{page_one}"].\n'
    )


def test_init_creates_the_layout_and_adapter(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    root = project.root
    for name in [
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "paper.toml",
        ".gitignore",
        ".gitattributes",
        "opencode.json",
        ".opencode/agents/writer.md",
        ".opencode/agents/scout.md",
        ".github/copilot-instructions.md",
        "Paper/paper.md",
        "Candidates/index.md",
    ]:
        assert (root / name).is_file(), name
    assert "paperchain check" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "{{" not in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "{{" not in (root / "Paper/paper.md").read_text(encoding="utf-8")


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "paper"
    run_init(str(root), title="One")
    with pytest.raises(PaperchainError) as error:
        run_init(str(root), title="Two")
    assert error.value.code == "already_initialized"


def test_convert_lock_and_clean_check(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["The sample contains forty two cases.", "A second page."])
    run_convert(project)

    project = Project.open(project.root)
    write_paper(project, _clean_paper())
    run_lock(project)

    report = run_check(Project.open(project.root))
    assert report.ok, [finding.message for finding in report.errors]
    assert report.stats["quotes_verified"] == 1
    assert report.stats["sources"] == 1


def test_check_reports_quote_on_the_wrong_page(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one.", "Beta text two."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(
        project,
        '# T\n\nA claim [@study2024, p. 1: "Beta text two."].\n',
    )
    report = run_check(project)
    codes = [finding.code for finding in report.errors]
    assert "quote_wrong_page" in codes
    finding = next(f for f in report.errors if f.code == "quote_wrong_page")
    assert finding.data["found_page"] == 2


def test_check_reports_a_quote_that_does_not_exist(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "words never written"].\n')
    report = run_check(project)
    assert [finding.code for finding in report.errors] == ["quote_not_found"]


def test_check_reports_unknown_keys_and_pages(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(
        project,
        "# T\n\n[@ghost2025, p. 1]\n\n[@study2024, p. 9]\n",
    )
    codes = [finding.code for finding in run_check(project).errors]
    assert "unknown_citation_key" in codes
    assert "page_out_of_range" in codes


def test_check_reports_a_page_range_past_the_end(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, "# T\n\nA claim [@study2024, pp. 1-3].\n")
    assert "page_out_of_range" in [finding.code for finding in run_check(project).errors]


def test_check_ignores_placeholders_in_comments_and_code(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(
        project,
        "# T\n\n<!-- TODO later -->\n\n```\nFIXME\n```\n\n"
        'A claim [@study2024, p. 1: "Alpha text one."].\n',
    )
    report = run_check(project)
    assert report.ok, [finding.message for finding in report.errors]


def test_check_reports_an_unmanaged_source(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    add_pdf(project, "late2025.pdf", ["Added after conversion."])
    report = run_check(Project.open(project.root))
    assert "unmanaged_source" in [finding.code for finding in report.errors]


def test_check_detects_a_changed_reference(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, _clean_paper("Alpha text one."))
    run_lock(project)

    original = project.originals_dir / "study2024.pdf"
    os.chmod(original, 0o644)
    original.write_bytes(original.read_bytes() + b"\n% changed\n")

    report = run_check(Project.open(project.root))
    assert "source_hash_mismatch" in [finding.code for finding in report.errors]


def test_lock_makes_files_read_only_and_unlock_restores_them(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, _clean_paper("Alpha text one."))
    run_lock(project)

    source = project.originals_dir / "study2024.pdf"
    assert not os.stat(source).st_mode & stat.S_IWRITE

    run_unlock(Project.open(project.root))
    assert os.stat(source).st_mode & stat.S_IWRITE


def test_convert_refuses_while_locked(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, _clean_paper("Alpha text one."))
    run_lock(project)

    with pytest.raises(PaperchainError) as error:
        run_convert(Project.open(project.root))
    assert error.value.code == "project_locked"


def test_build_is_blocked_by_a_failed_check(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, "# T\n\nUnfinished TODO [@ghost2025].\n")

    result = run_build(project)
    assert result.output is None
    assert result.report.errors


@pytest.mark.skipif(
    not shutil.which("pandoc"),
    reason="pandoc is not installed",
)
def test_build_writes_a_docx(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, _clean_paper("Alpha text one."))

    result = run_build(project)
    assert result.output is not None
    assert result.output.is_file()
    assert result.output.suffix == ".docx"

    import zipfile

    with zipfile.ZipFile(result.output) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "References" in xml
    assert "study2024" in xml


def test_cli_emits_one_json_object(tmp_path: Path, capsys) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, _clean_paper("Alpha text one."))

    exit_code = main(["--project", str(project.root), "check", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "check"
    assert payload["schema_version"] == 1
    assert payload["data"]["stats"]["quotes_verified"] == 1


def test_cli_exits_two_outside_a_project(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["check", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"][0]["code"] == "project_not_found"
