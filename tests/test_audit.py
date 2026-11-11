"""Regression tests for the findings in the external audit."""

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path

import pytest

from paperchain.check import run_check
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.locking import run_lock, run_unlock
from paperchain.project import Project
from paperchain.util import sha256_file

from .conftest import add_pdf, make_project, write_paper


def _project_with_page(tmp_path: Path, text: str = "Alpha text one.") -> Project:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", [text])
    run_convert(project)
    return Project.open(project.root)


def _codes(report) -> set[str]:
    return {finding.code for finding in report.errors}


def test_comment_inside_a_code_span_does_not_hide_citations(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(
        project,
        "# T\n\n"
        "Use `<!--` for comments.\n\n"
        '[@study2024, p. 9: "Water boils at one hundred degrees."]\n\n'
        '[@study2024, p. 1: "Grass is purple at night always."]\n\n'
        '[@nobody, p. 3: "whatever words here now"]\n\n'
        "TODO finish this\n",
    )
    report = run_check(project)
    assert not report.ok
    assert {"page_out_of_range", "quote_not_found", "unknown_citation_key", "placeholder"} <= _codes(report)


def test_unterminated_comment_is_an_error(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, "# T\n\n<!-- unfinished note\n\n[@nobody, p. 1]\n")
    report = run_check(project)
    assert "unterminated_comment" in _codes(report)


def test_four_space_indented_backticks_are_not_a_fence(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, "# T\n\nintro\n\n    ```\n\n[@nobody, p. 1]\n")
    report = run_check(project)
    assert "unknown_citation_key" in _codes(report)


def test_closing_fence_must_match_the_opening_length(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, "# T\n\n````\ncode\n```\n\n[@nobody, p. 1]\n")
    report = run_check(project)
    assert "unterminated_code_block" in _codes(report)


@pytest.mark.parametrize(
    "citation",
    [
        "[see @study2024, p. 9]",
        "[ @study2024, p. 9]",
        "[-@study2024, p. 9]",
        "@study2024 says",
    ],
)
def test_pandoc_style_citations_are_rejected_not_ignored(tmp_path: Path, citation: str) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, f"# T\n\n{citation}\n")
    report = run_check(project)
    assert "citation_unrecognized" in _codes(report)


def test_a_double_backslash_citation_is_still_checked(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, "# T\n\n\\\\[@study2024, p. 9]\n")
    assert "page_out_of_range" in _codes(run_check(project))


def test_a_single_backslash_escape_is_left_alone(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, "# T\n\n\\[@study2024, p. 9]\n")
    codes = _codes(run_check(project))
    assert "citation_unrecognized" not in codes
    assert "page_out_of_range" not in codes


def test_missing_hashes_while_locked_are_errors(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(project)

    project = Project.open(project.root)
    project.manifest.sources[0].sha256 = ""
    project.manifest.sources[0].text_sha256 = ""
    project.save()

    codes = _codes(run_check(Project.open(project.root)))
    assert "source_unhashed" in codes
    assert "text_unhashed" in codes


def test_lock_refuses_when_the_converted_text_is_stale(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(project)

    project = Project.open(project.root)
    run_unlock(project)
    original = project.originals_dir / "study2024.pdf"
    original.write_bytes(original.read_bytes() + b"\n% changed\n")

    with pytest.raises(PaperchainError) as error:
        run_lock(Project.open(project.root), accept_changes=True)
    assert error.value.code == "lock_failed"
    assert "different original" in error.value.message


def test_lock_requires_opt_in_for_a_hash_change(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(project)

    project = Project.open(project.root)
    project.manifest.sources[0].sha256 = "0" * 64
    project.save()

    with pytest.raises(PaperchainError) as error:
        run_lock(Project.open(project.root))
    assert error.value.code == "lock_changes"

    result = run_lock(Project.open(project.root), accept_changes=True)
    assert result["changes"]


def test_check_detects_text_built_from_a_different_source(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(project)

    project = Project.open(project.root)
    run_unlock(project)
    original = project.originals_dir / "study2024.pdf"
    original.write_bytes(original.read_bytes() + b"\n% changed\n")
    project.manifest.sources[0].sha256 = sha256_file(original)
    project.save()

    assert "text_stale" in _codes(run_check(Project.open(project.root)))


def test_editing_the_txt_file_is_an_error(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(project)

    txt_path = project.text_dir / "study2024.txt"
    os.chmod(txt_path, 0o644)
    txt_path.write_text("totally different content", encoding="utf-8")

    assert "text_file_mismatch" in _codes(run_check(Project.open(project.root)))


def test_a_quote_cannot_start_or_end_inside_a_word(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path, "The effect cannot be ruled out.")
    write_paper(project, '# T\n\nA [@study2024, p. 1: "not be ruled out"].\n')
    assert "quote_not_found" in _codes(run_check(project))

    write_paper(project, '# T\n\nB [@study2024, p. 1: "e effect cannot"].\n')
    assert "quote_not_found" in _codes(run_check(project))

    write_paper(project, '# T\n\nC [@study2024, p. 1: "The effect cannot be ruled out"].\n')
    assert run_check(project).ok


def test_a_bracket_inside_a_quote_does_not_end_the_citation(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path, "The sky ] is blue.")
    write_paper(project, '# T\n\nA [@study2024, p. 1: "The sky ] is blue"].\n')
    report = run_check(project)
    assert report.ok, [finding.message for finding in report.errors]
    assert report.stats["quotes_verified"] == 1


def test_a_hyphenated_compound_still_matches(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.originals_dir.mkdir(parents=True, exist_ok=True)
    (project.originals_dir / "study2024.txt").write_text(
        "This is a well-\nknown result.", encoding="utf-8"
    )
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA [@study2024, p. 1: "well-known result"].\n')
    assert run_check(project).ok


def test_short_quotes_are_errors_in_strict_mode(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA [@study2024, p. 1: "Alpha text one"].\n')
    assert run_check(project).ok
    assert "quote_too_short" in _codes(run_check(project, strict=True))


def test_adapter_denies_dangerous_command_shapes() -> None:
    config = json.loads(
        files("paperchain").joinpath("adapters/opencode/opencode.json").read_text(encoding="utf-8")
    )
    rules = config["permissions"]

    def index(action: str, resource: str) -> int:
        for position, rule in enumerate(rules):
            if rule["action"] == action and rule["resource"] == resource:
                return position
        raise AssertionError(f"missing rule {action} {resource}")

    allow = index("shell", "paperchain* check*")
    assert rules[allow]["effect"] == "allow"
    assert index("shell", "* --force*") > allow
    assert index("shell", "paperchain* build*") > allow
    assert "paperchain *" not in [rule["resource"] for rule in rules]
    assert index("edit", ".opencode/**") >= 0
    allows = [rule["resource"] for rule in rules if rule["effect"] == "allow"]
    assert all("unlock" not in resource for resource in allows)
