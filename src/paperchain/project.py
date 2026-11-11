from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import PaperchainError
from .manifest import MANIFEST_NAME, Manifest

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def find_root(start: Path | None = None) -> Path:
    """Find the nearest ancestor containing paper.toml."""
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / MANIFEST_NAME).is_file():
            return candidate
    raise PaperchainError(
        "project_not_found",
        f"no {MANIFEST_NAME} found in {current} or any parent folder",
        hint="run `paperchain init` to create a paper project, or pass --project <folder>",
    )


@dataclass
class Project:
    root: Path
    manifest: Manifest

    @classmethod
    def open(cls, path: Path | None = None) -> "Project":
        if path is not None:
            root = Path(path).expanduser().resolve()
            if not (root / MANIFEST_NAME).is_file():
                raise PaperchainError(
                    "project_not_found",
                    f"{root} does not contain {MANIFEST_NAME}",
                    hint="point --project at a folder created by `paperchain init`",
                )
        else:
            root = find_root()
        project = cls(root=root, manifest=Manifest.load(root / MANIFEST_NAME))
        project.validate()
        return project

    def validate(self) -> None:
        """Reject manifests that could steer the tool outside the project."""
        originals = (self.root / "References" / "originals").resolve()
        seen: set[str] = set()
        for source in self.manifest.sources:
            if not KEY_RE.match(source.key):
                raise PaperchainError(
                    "manifest_invalid",
                    f"invalid source key {source.key!r}",
                    hint="keys are lowercase letters, digits and hyphens, e.g. smith2024",
                )
            if source.key in seen:
                raise PaperchainError(
                    "manifest_invalid",
                    f"duplicate source key {source.key!r}",
                    hint="give each source a unique key",
                )
            seen.add(source.key)
            raw = Path(source.path)
            if raw.is_absolute():
                raise PaperchainError(
                    "manifest_invalid",
                    f"{source.path} is an absolute path",
                    hint="reference paths are relative to the paper folder",
                )
            resolved = (self.root / raw).resolve()
            if not resolved.is_relative_to(originals):
                raise PaperchainError(
                    "manifest_invalid",
                    f"{source.path} points outside References/originals",
                    hint="reference paths must stay inside the project's originals folder",
                )

    def save(self) -> None:
        self.manifest.save(self.root / MANIFEST_NAME)

    @property
    def references_dir(self) -> Path:
        return self.root / "References"

    @property
    def originals_dir(self) -> Path:
        return self.references_dir / "originals"

    @property
    def text_dir(self) -> Path:
        return self.references_dir / "_text"

    @property
    def paper_dir(self) -> Path:
        return self.root / "Paper"

    @property
    def paper_md(self) -> Path:
        return self.paper_dir / "paper.md"

    @property
    def candidates_dir(self) -> Path:
        return self.root / "Candidates"

    @property
    def output_dir(self) -> Path:
        return self.root / "Output"

    @property
    def output_path(self) -> Path:
        configured = self.manifest.output_path()
        candidate = (self.root / configured).resolve()
        allowed = self.output_dir.resolve()
        if candidate == allowed or not candidate.is_relative_to(allowed):
            raise PaperchainError(
                "invalid_output",
                f"build output {configured!r} is outside Output/",
                hint="set [build] output to a relative path such as Output/paper.docx",
            )
        return candidate

    def relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)
