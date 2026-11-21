"""Gap 1 from the step-1 tamper test: re-blessing the reference set is visible, never blocked."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from paperchain.build import run_build
from paperchain.check import run_check
from paperchain.convert import run_convert
from paperchain.locking import run_lock, run_unlock
from paperchain.project import Project
from paperchain.reference_log import LOG_RELATIVE, read_events, reference_fingerprint

from .conftest import add_pdf, make_project, write_paper
from .helpers import write_pdf


def locked_project(tmp_path: Path) -> Project:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."], title="A Study")
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(Project.open(project.root))
    return Project.open(project.root)


def warning_codes(project: Project) -> set[str]:
    return {w.code for w in run_check(Project.open(project.root)).warnings}


def swap_reference(project: Project) -> None:
    source = project.manifest.sources[0]
    path = project.root / source.path
    path.chmod(0o644)
    write_pdf(path, ["Alpha text changed."], title="A Study")


def test_check_reports_a_fingerprint_after_lock(tmp_path: Path) -> None:
    project = locked_project(tmp_path)
    report = run_check(Project.open(project.root))
    fingerprint = report.data["reference_fingerprint"]
    assert len(fingerprint) == 64
    assert fingerprint == reference_fingerprint(Project.open(project.root).manifest)


def test_a_plain_lock_is_logged_and_not_a_warning(tmp_path: Path) -> None:
    project = locked_project(tmp_path)
    events = read_events(project)
    assert [e["event"] for e in events] == ["lock"]
    assert "reference_set_reblessed" not in warning_codes(project)


def test_adding_a_second_reference_is_not_a_rebless(tmp_path: Path) -> None:
    project = locked_project(tmp_path)
    run_unlock(Project.open(project.root))
    add_pdf(Project.open(project.root), "other2024.pdf", ["Beta text."], title="Other")
    run_convert(Project.open(project.root))
    run_lock(Project.open(project.root))
    events = [e["event"] for e in read_events(project)]
    assert events.count("accept_changes") == 0


def test_unlock_swap_and_accept_changes_is_visible_but_not_blocked(tmp_path: Path) -> None:
    project = locked_project(tmp_path)
    before = run_check(Project.open(project.root)).data["reference_fingerprint"]
    run_unlock(Project.open(project.root))
    swap_reference(project)
    run_convert(Project.open(project.root), accept_changes=True)
    run_lock(Project.open(project.root), accept_changes=True)  # nothing prompts or refuses
    report = run_check(Project.open(project.root))
    assert report.data["reference_fingerprint"] != before
    codes = {w.code for w in report.warnings}
    assert "reference_set_reblessed" in codes
    kinds = [e["event"] for e in read_events(project)]
    assert "unlock" in kinds and "accept_changes" in kinds


def test_a_successful_build_acknowledges_and_records_the_fingerprint(tmp_path: Path) -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is not installed")
    project = locked_project(tmp_path)
    first = run_build(Project.open(project.root))
    assert first.ok
    assert "reference_fingerprint_changed" not in {w.code for w in first.report.warnings}
    run_unlock(Project.open(project.root))
    swap_reference(project)
    write_paper(Project.open(project.root), '# T\n\nA claim [@study2024, p. 1: "Alpha text changed."].\n')
    run_convert(Project.open(project.root), accept_changes=True)
    run_lock(Project.open(project.root), accept_changes=True)
    second = run_build(Project.open(project.root))
    codes = {w.code for w in second.report.warnings}
    assert {"reference_set_reblessed", "reference_fingerprint_changed"} <= codes
    # the build is the acknowledgement: the next check is quiet again
    assert "reference_set_reblessed" not in warning_codes(project)


def test_a_corrupt_or_missing_log_does_not_break_check(tmp_path: Path) -> None:
    project = locked_project(tmp_path)
    log = project.root / LOG_RELATIVE
    log.write_text("not json\n{\"event\": 3}\n[1]\n", encoding="utf-8")
    assert read_events(project) == []
    assert run_check(Project.open(project.root)).ok
    log.unlink()
    assert run_check(Project.open(project.root)).ok


def test_an_unwritable_log_location_does_not_break_lock(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."], title="A Study")
    run_convert(project)
    (project.root / ".paperchain").write_text("a file where the folder should be", encoding="utf-8")
    run_lock(Project.open(project.root))  # must not raise


def test_the_adapter_denies_writing_the_log() -> None:
    import paperchain

    config = json.loads(
        (Path(paperchain.__file__).parent / "adapters" / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )
    assert {"action": "edit", "resource": ".paperchain/**", "effect": "deny"} in config["permissions"]
