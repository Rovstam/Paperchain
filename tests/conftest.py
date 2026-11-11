from __future__ import annotations

import os
from pathlib import Path

import pytest

from paperchain.init_cmd import run_init
from paperchain.project import Project

from .helpers import write_pdf


@pytest.fixture(autouse=True)
def _writable_after_test(tmp_path: Path):
    yield
    for path in tmp_path.rglob("*"):
        try:
            os.chmod(path, 0o644)
        except OSError:
            pass


def make_project(tmp_path: Path, title: str = "Test Paper") -> Project:
    root = tmp_path / "paper"
    run_init(str(root), title=title, agent="opencode")
    return Project.open(root)


def add_pdf(project: Project, name: str, pages: list[str], **metadata) -> Path:
    path = project.originals_dir / name
    write_pdf(path, pages, **metadata)
    return path


def write_paper(project: Project, text: str) -> None:
    project.paper_md.write_text(text, encoding="utf-8", newline="\n")
