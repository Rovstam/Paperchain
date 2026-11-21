"""One set of rules, many tools: AGENTS.md is the source, the other markdown files only point at it."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import paperchain
from paperchain.cli import build_parser
from paperchain.init_cmd import run_init

from .conftest import make_project

POINTERS = ["CLAUDE.md", "GEMINI.md"]
TOOL_WORDS = re.compile(r"opencode|copilot|claude|gemini|cursor|codex|vs ?code", re.IGNORECASE)


def commands() -> set[str]:
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001
        if getattr(action, "choices", None) and isinstance(action.choices, dict):
            return set(action.choices)
    raise AssertionError("no subcommands found")


def test_init_writes_every_universal_file(tmp_path: Path) -> None:
    root = make_project(tmp_path).root
    for name in ["AGENTS.md", *POINTERS, ".github/copilot-instructions.md"]:
        assert (root / name).is_file(), name
        assert "{{" not in (root / name).read_text(encoding="utf-8"), name


@pytest.mark.parametrize("name", POINTERS)
def test_a_pointer_imports_agents_md_and_repeats_no_rules(tmp_path: Path, name: str) -> None:
    text = (make_project(tmp_path).root / name).read_text(encoding="utf-8")
    assert text.splitlines()[0] == "@AGENTS.md"
    assert "AGENTS.md" in text.split("\n", 1)[1]  # the fallback for tools without imports
    assert len(text.splitlines()) <= 10
    assert not re.search(r"paperchain (check|build|start|lock|convert)", text)


def test_agents_md_is_free_of_tool_specific_wording(tmp_path: Path) -> None:
    text = (make_project(tmp_path).root / "AGENTS.md").read_text(encoding="utf-8")
    assert not TOOL_WORDS.search(text), TOOL_WORDS.search(text)


def test_the_copilot_file_points_to_agents_md(tmp_path: Path) -> None:
    text = (make_project(tmp_path).root / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in text.split("\n\n", 2)[1]


@pytest.mark.parametrize("name", ["AGENTS.md", ".github/copilot-instructions.md"])
def test_every_command_the_instructions_name_exists(tmp_path: Path, name: str) -> None:
    text = (make_project(tmp_path).root / name).read_text(encoding="utf-8")
    named = set(re.findall(r"paperchain (?!\*)([a-z]+)", text))
    named -= {"adapter", "is", "or", "and", "can", "at", "to", "in", "so"}  # prose, not commands
    unknown = {word for word in named if word not in commands()}
    assert not unknown, unknown


def test_an_existing_claude_md_is_never_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "mine"
    root.mkdir()
    (root / "CLAUDE.md").write_text("my own rules\n", encoding="utf-8")
    (root / "notes.txt").write_text("x\n", encoding="utf-8")
    run_init(str(root), title="Mine", adopt=True)
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "my own rules\n"
    assert (root / "GEMINI.md").is_file()


def test_the_writer_cannot_edit_the_instruction_files() -> None:
    rules = json.loads(
        (Path(paperchain.__file__).parent / "adapters" / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )["permissions"]
    for name in ["AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md"]:
        assert {"action": "edit", "resource": name, "effect": "deny"} in rules, name
