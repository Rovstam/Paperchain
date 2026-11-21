"""Context cards (step 3): a cheap map of each reference that survives regeneration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperchain import cli
from paperchain.check import run_check
from paperchain.context import PENDING, RESUME_MARKER, STALE_NOTICE, has_resume, write_cards
from paperchain.convert import run_convert
from paperchain.locking import run_lock
from paperchain.project import Project

from .conftest import make_project
from .helpers import write_pdf

PAGES = [
    "Introduction",
    "Enzyme induction was fourfold in the treated group.",
    "Methods",
    "Results",
    "Clearance doubled after treatment with the extract.",
    "References",
]
RESUME = (
    "Purpose: shows that the extract induces CYP3A4 in rats, relevant to our interaction section.\n"
    "Key finding: fourfold induction on p. 2.\n"
)


def filed(tmp_path: Path, title: str = "Enzyme Map") -> tuple[Project, Path]:
    project = make_project(tmp_path)
    write_pdf(project.references_dir / "x.pdf", PAGES, title=title, author="Doe J")
    run_convert(project)
    project = Project.open(project.root)
    card = project.references_dir / title / f"{title}.context.md"
    return project, card


def card_with_resume(card: Path) -> None:
    text = card.read_text(encoding="utf-8")
    card.write_text(text.replace(PENDING, RESUME), encoding="utf-8")


def test_convert_writes_a_card_beside_the_reference(tmp_path: Path) -> None:
    project, card = filed(tmp_path)
    assert card.is_file()
    text = card.read_text(encoding="utf-8")
    source = project.manifest.sources[0]
    assert f'key: "{source.key}"' in text
    assert "pages: 6" in text
    assert f'sha256: "{source.sha256}"' in text
    assert "- p. 2 (~8 words): Enzyme induction was fourfold in the treated group." in text
    assert "- Introduction: p. 1" in text and "- Methods: p. 3" in text and "- Results: p. 4" in text
    assert RESUME_MARKER in text and PENDING in text


def test_a_card_is_not_mistaken_for_a_reference(tmp_path: Path) -> None:
    project, card = filed(tmp_path)
    assert len(project.manifest.sources) == 1
    run_convert(project)
    run_convert(Project.open(project.root))
    assert len(Project.open(project.root).manifest.sources) == 1
    assert card not in Project.open(project.root).iter_reference_files()


def test_regenerating_an_unchanged_card_changes_nothing(tmp_path: Path) -> None:
    project, card = filed(tmp_path)
    before = card.read_text(encoding="utf-8")
    result = write_cards(project)
    assert [c["status"] for c in result["cards"]] == ["unchanged"]
    assert card.read_text(encoding="utf-8") == before


def test_the_writers_resume_survives_regeneration(tmp_path: Path) -> None:
    project, card = filed(tmp_path)
    card_with_resume(card)
    card.write_text(card.read_text(encoding="utf-8").replace("- p. 2", "- p. 2 EDITED BY HAND"), encoding="utf-8")
    result = write_cards(project)
    text = card.read_text(encoding="utf-8")
    assert RESUME in text
    assert "EDITED BY HAND" not in text  # the generated top is rebuilt
    assert result["cards"][0]["status"] == "updated"
    assert result["cards"][0]["has_resume"] and not result["pending"]


def test_a_new_card_is_pending_and_a_written_resume_is_not(tmp_path: Path) -> None:
    project, card = filed(tmp_path)
    assert write_cards(project)["pending"] == [project.manifest.sources[0].key]
    card_with_resume(card)
    assert write_cards(project)["pending"] == []
    assert has_resume(card.read_text(encoding="utf-8"))


def test_a_changed_reference_marks_the_resume_stale_once(tmp_path: Path) -> None:
    project, card = filed(tmp_path)
    card_with_resume(card)
    pdf = next(project.references_dir.rglob("*.pdf"))
    write_pdf(pdf, ["Introduction", "A different fact now.", "Methods", "Results", "More.", "References"], title="Enzyme Map")
    run_convert(Project.open(project.root), accept_changes=True)
    text = card.read_text(encoding="utf-8")
    assert text.count(STALE_NOTICE) == 1 and RESUME in text
    run_convert(Project.open(project.root), accept_changes=True)
    write_cards(Project.open(project.root))
    assert card.read_text(encoding="utf-8").count(STALE_NOTICE) == 1
    pending = write_cards(Project.open(project.root))["pending"]
    assert pending  # still needs a rewrite
    card.write_text(card.read_text(encoding="utf-8").replace(STALE_NOTICE + "\n", ""), encoding="utf-8")
    assert write_cards(Project.open(project.root))["pending"] == []


def test_a_file_without_the_marker_is_never_overwritten(tmp_path: Path) -> None:
    project, card = filed(tmp_path)
    card.write_text("my own notes, no marker\n", encoding="utf-8")
    result = write_cards(project)
    assert card.read_text(encoding="utf-8") == "my own notes, no marker\n"
    assert [w.code for w in result["warnings"]] == ["context_card_unrecognised"]
    assert result["cards"][0]["status"] == "kept"


def test_a_long_document_gets_a_capped_page_map(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_pdf(project.references_dir / "big.pdf", [f"Page text number {n}." for n in range(1, 251)], title="Big Book")
    run_convert(project)
    text = (project.references_dir / "Big Book" / "Big Book.context.md").read_text(encoding="utf-8")
    assert sum(1 for line in text.splitlines() if line.startswith("- p. ")) <= 125
    assert "one page in every 3 is listed (250 pages in total)" in text


def test_pages_with_no_text_are_flagged(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_pdf(project.references_dir / "scan.pdf", ["Introduction", ""], title="Scanned Paper")
    run_convert(project)
    text = (project.references_dir / "Scanned" / "Scanned.context.md").read_text(encoding="utf-8")
    assert "p. 2 (~0 words): (no text; scanned or image-only?)" in text
    assert "p. 1 (~1 word): Introduction" in text


def test_estimated_page_numbers_are_called_out(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.references_dir / "notes.txt").write_text("Some long plain text. " * 200, encoding="utf-8")
    run_convert(project)
    cards = list(project.references_dir.rglob("*.context.md"))
    assert cards and "estimated" in cards[0].read_text(encoding="utf-8")


def test_cards_are_outside_the_lock_and_context_works_while_locked(tmp_path: Path) -> None:
    project, card = filed(tmp_path)
    write_paper_text = '# T\n\nClaim [@enzyme-map, p. 2: "fourfold in the treated group"].\n'
    (project.root / "Paper" / "paper.md").write_text(write_paper_text, encoding="utf-8")
    run_lock(Project.open(project.root))
    card.chmod(0o644)
    card.write_text(card.read_text(encoding="utf-8") + "\nedited after lock\n", encoding="utf-8")
    write_cards(Project.open(project.root))  # not refused while locked
    errors = {f.code for f in run_check(Project.open(project.root)).errors}
    assert not {c for c in errors if "hash" in c or "unhashed" in c or "locked" in c}


def test_only_filters_and_unknown_keys_warn(tmp_path: Path) -> None:
    project, _ = filed(tmp_path)
    result = write_cards(project, only=["nope"])
    assert result["cards"] == [] and [w.code for w in result["warnings"]] == ["context_unknown_source"]


def test_the_cli_reports_cards_and_pending_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project, _ = filed(tmp_path)
    code = cli.main(["context", "--json", "--project", str(project.root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"]
    assert payload["data"]["pending"] == [project.manifest.sources[0].key]
    assert payload["data"]["cards"][0]["card"].endswith("Enzyme Map.context.md")


def test_the_card_is_writable_in_opencode_but_nothing_else_in_references() -> None:
    import paperchain

    rules = json.loads(
        (Path(paperchain.__file__).parent / "adapters" / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )["permissions"]
    index = {(r["action"], r["resource"]): n for n, r in enumerate(rules)}
    deny = index[("edit", "References/**")]
    allow = index[("edit", "References/**/*.context.md")]
    assert allow > deny  # the later rule wins
    assert ("shell", "paperchain* context*") in index
