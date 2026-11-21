"""`paperchain start`: one safe, repeatable setup command (step 4)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperchain import cli
from paperchain.check import run_check
from paperchain.project import Project
from paperchain.reference_log import read_events
from paperchain.start import run_start

from .helpers import write_pdf


def messy(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    root.mkdir()
    write_pdf(root / "manuscript.pdf", ["Licorice review draft. Licorice induces CYP3A4 in rats."], title="My draft")
    write_pdf(root / "1-s2.0-main.pdf", ["Extracts induced CYP3A4 fourfold."], title="Assessment of Licorice Extracts")
    write_pdf(root / "download (3).pdf", ["Dolutegravir clearance rose."], title="Dolutegravir clearance study")
    (root / "notes.md").write_text("my scratch notes\n", encoding="utf-8")
    return root


def statuses(result: dict) -> dict[str, str]:
    return {item["step"]: item["status"] for item in result["steps"]}


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_several_possible_manuscripts_ask_once_and_move_nothing(tmp_path: Path) -> None:
    root = messy(tmp_path)
    before = {p.name for p in root.iterdir() if p.is_file()}
    result = run_start(str(root))
    assert [e.code for e in result["errors"]] == ["start_manuscript_ambiguous"]
    assert statuses(result)["organize"] == "needs_human"
    assert len(result["data"]["needs_human"]) == 1
    assert before <= {p.name for p in root.iterdir() if p.is_file()}  # every original file is still where it was
    assert (root / "manuscript.pdf").is_file() and (root / "1-s2.0-main.pdf").is_file()
    assert not (root / "Dump" / "notes.md").exists()


def test_an_ambiguous_manuscript_does_not_touch_existing_references(tmp_path: Path) -> None:
    root = messy(tmp_path)
    references = root / "References"
    references.mkdir()
    write_pdf(references / "loose.pdf", ["A study waiting to be filed."], title="Loose Study")

    result = run_start(str(root))

    assert [e.code for e in result["errors"]] == ["start_manuscript_ambiguous"]
    assert "references" not in statuses(result)
    assert (references / "loose.pdf").is_file()
    assert not (references / "Loose").exists()


def test_a_messy_folder_becomes_a_ready_project(tmp_path: Path) -> None:
    root = messy(tmp_path)
    result = run_start(str(root), manuscript="manuscript.pdf")
    assert not result["errors"], [e.message for e in result["errors"]]
    state = statuses(result)
    assert state["project"] == "done" and state["organize"] == "done" and state["import"] == "done"
    assert state["references"] == "done" and state["context cards"] == "done" and state["doctor"] == "done"

    project = Project.open(root)
    assert project.manifest.locked_at and len(project.manifest.sources) == 2
    assert "paperchain:template" not in project.paper_md.read_text(encoding="utf-8")
    assert (root / "Manuscript" / "manuscript.pdf").is_file()
    assert (root / "Dump" / "notes.md").is_file()  # moved aside, never deleted
    assert (root / "References" / "Assessment" / "Assessment.pdf").is_file()
    assert (root / "References" / "Dolutegravir" / "Dolutegravir.context.md").is_file()
    assert sorted(result["data"]["pending_cards"]) == sorted(s.key for s in project.manifest.sources)
    assert result["data"]["reference_fingerprint"]
    assert any("Context cards" in item for item in result["data"]["next"])


def test_running_it_again_changes_nothing(tmp_path: Path) -> None:
    root = messy(tmp_path)
    run_start(str(root), manuscript="manuscript.pdf")
    before = {name: (root / name).read_bytes() for name in tree(root) if not name.startswith(".paperchain")}
    second = run_start(str(root))
    assert not second["errors"]
    state = statuses(second)
    assert state["organize"] == "skipped" and state["import"] == "skipped" and state["references"] == "skipped"
    assert before == {name: (root / name).read_bytes() for name in before}


def test_a_new_reference_is_added_without_a_warning_about_re_blessing(tmp_path: Path) -> None:
    root = messy(tmp_path)
    run_start(str(root), manuscript="manuscript.pdf")
    write_pdf(root / "References" / "new.pdf", ["Another study."], title="Glycyrrhizin pharmacokinetics")
    result = run_start(str(root))
    assert not result["errors"] and statuses(result)["references"] == "done"
    project = Project.open(root)
    assert len(project.manifest.sources) == 3 and project.manifest.locked_at
    events = read_events(project)
    assert any(e["event"] == "unlock" and e.get("additive") for e in events)
    assert "reference_set_reblessed" not in {w.code for w in run_check(project).warnings}
    assert (root / "References" / "Glycyrrhizin" / "Glycyrrhizin.pdf").is_file()


def test_a_changed_locked_reference_is_never_blessed(tmp_path: Path) -> None:
    root = messy(tmp_path)
    run_start(str(root), manuscript="manuscript.pdf")
    pdf = root / "References" / "Assessment" / "Assessment.pdf"
    pdf.chmod(0o644)
    write_pdf(pdf, ["Forged: induction tenfold."], title="Assessment of Licorice Extracts")
    forged = pdf.read_bytes()
    result = run_start(str(root))
    assert "start_reference_changed" in [e.code for e in result["errors"]]
    assert statuses(result)["references"] == "needs_human"
    assert pdf.read_bytes() == forged  # untouched
    project = Project.open(root)
    assert project.manifest.locked_at  # still locked
    assert not any(e["event"] == "accept_changes" for e in read_events(project))
    assert "source_hash_mismatch" in {e.code for e in run_check(project).errors}


def test_a_zotero_export_added_later_is_locked_but_a_changed_one_is_not_blessed(tmp_path: Path) -> None:
    root = messy(tmp_path)
    library = root / "References" / "library.json"
    run_start(str(root), manuscript="manuscript.pdf")
    library.write_text(json.dumps([{"id": "a", "type": "book", "title": "Assessment of Licorice Extracts"}]), encoding="utf-8")
    added = run_start(str(root))
    assert not added["errors"], [e.message for e in added["errors"]]
    assert Project.open(root).manifest.bibliography_sha256
    library.write_text(json.dumps([{"id": "a", "type": "book", "title": "Changed Title"}]), encoding="utf-8")
    result = run_start(str(root))
    assert "start_reference_changed" in [e.code for e in result["errors"]]
    assert not any(e["event"] == "accept_changes" for e in read_events(Project.open(root)))


def test_an_existing_draft_is_never_replaced(tmp_path: Path) -> None:
    root = messy(tmp_path)
    run_start(str(root), manuscript="manuscript.pdf")
    draft = root / "Paper" / "paper.md"
    draft.write_text("# My own words\n\nWritten by hand.\n", encoding="utf-8")
    run_start(str(root))
    assert draft.read_text(encoding="utf-8") == "# My own words\n\nWritten by hand.\n"


def test_an_empty_folder_becomes_an_empty_project(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    result = run_start(str(root), title="Fresh paper")
    assert not result["errors"]
    state = statuses(result)
    assert state["project"] == "done" and state["references"] == "skipped"
    assert Project.open(root).manifest.title == "Fresh paper"
    assert any("Paper/paper.md" in item for item in result["data"]["next"])


def test_the_cli_reports_steps_and_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = messy(tmp_path)
    code = cli.main(["start", "--json", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1 and not payload["ok"] and payload["command"] == "start"
    assert payload["data"]["needs_human"]
    code = cli.main(["start", "--json", str(root), "--manuscript", "manuscript.pdf"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"]
    assert {item["step"] for item in payload["data"]["steps"]} >= {"project", "organize", "import", "references", "doctor"}


def test_the_opencode_adapter_allows_start() -> None:
    import paperchain

    rules = json.loads(
        (Path(paperchain.__file__).parent / "adapters" / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )["permissions"]
    assert {"action": "shell", "resource": "paperchain* start*", "effect": "allow"} in rules
