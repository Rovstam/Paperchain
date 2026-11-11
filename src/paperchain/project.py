from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import PaperchainError
from .manifest import MANIFEST_NAME, Manifest


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
        return cls(root=root, manifest=Manifest.load(root / MANIFEST_NAME))

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
        return self.root / self.manifest.output_path()

    def relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)
