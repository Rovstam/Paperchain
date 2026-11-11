from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import PaperchainError
from .manifest import MANIFEST_NAME, Manifest
from .util import slugify

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Files under References/ that are generated or that hold bibliography data.
# They are not reference documents and must never be tracked as sources.
REFERENCE_SKIP_DIRS = {"_text"}
REFERENCE_SKIP_NAMES = {
    "library.json",
    "library.bib",
    "library.csl",
    "index.md",
    "readme.md",
}
REFERENCE_METADATA_SUFFIXES = {".json", ".bib", ".csl", ".ris", ".yaml", ".yml"}


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
        references = (self.root / "References").resolve()
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
            if not resolved.is_relative_to(references):
                raise PaperchainError(
                    "manifest_invalid",
                    f"{source.path} points outside References/",
                    hint="reference paths must stay inside the project's References folder",
                )
            relative = resolved.relative_to(references)
            if relative.parts and relative.parts[0] == "_text":
                raise PaperchainError(
                    "manifest_invalid",
                    f"{source.path} points at generated text, not an original reference",
                    hint="put the PDF or DOCX under References/ and run `paperchain convert`",
                )

        manuscript = self.manifest.manuscript_path
        if manuscript:
            raw = Path(manuscript)
            if raw.is_absolute():
                raise PaperchainError(
                    "manifest_invalid",
                    f"{manuscript} is an absolute path",
                    hint="the manuscript path is relative to the paper folder",
                )
            resolved = (self.root / raw).resolve()
            if not resolved.is_relative_to(self.root.resolve()):
                raise PaperchainError(
                    "manifest_invalid",
                    f"{manuscript} points outside the project",
                    hint="keep the original manuscript inside the project folder",
                )

        for label, value in (
            ("bibliography", self.manifest.bibliography),
            ("csl", self.manifest.csl),
        ):
            if not value:
                continue
            raw = Path(value)
            if raw.is_absolute():
                raise PaperchainError(
                    "manifest_invalid",
                    f"[build] {label} is an absolute path",
                    hint="paths in paper.toml are relative to the paper folder",
                )
            if not (self.root / raw).resolve().is_relative_to(self.root.resolve()):
                raise PaperchainError(
                    "manifest_invalid",
                    f"[build] {label} points outside the project",
                    hint="keep bibliography and CSL files inside the project folder",
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
    def paper_media_dir(self) -> Path:
        return self.paper_dir / "media"

    @property
    def manuscript_dir(self) -> Path:
        return self.root / "Manuscript"

    @property
    def candidates_dir(self) -> Path:
        return self.root / "Candidates"

    @property
    def output_dir(self) -> Path:
        return self.root / "Output"

    @property
    def bibliography_path(self) -> Path | None:
        """The CSL JSON export from Zotero, if the project has one."""
        configured = self.manifest.bibliography.strip()
        if configured:
            return (self.root / configured).resolve()
        default = self.references_dir / "library.json"
        return default.resolve() if default.is_file() else None

    @property
    def csl_path(self) -> Path | None:
        configured = self.manifest.csl.strip()
        if not configured:
            return None
        return (self.root / configured).resolve()

    def iter_reference_files(self) -> list[Path]:
        """All candidate reference documents under References/, recursively.

        `References/_text` is generated, and bibliography exports such as
        `library.json` are metadata. Neither is a reference document.
        """
        if not self.references_dir.is_dir():
            return []
        found: list[Path] = []
        for path in sorted(self.references_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.references_dir)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if relative.parts and relative.parts[0] in REFERENCE_SKIP_DIRS:
                continue
            if path.name.casefold() in REFERENCE_SKIP_NAMES:
                continue
            if path.suffix.lower() in REFERENCE_METADATA_SUFFIXES:
                continue
            found.append(path)
        return found

    def reference_key(self, path: Path) -> str:
        """A stable key for a reference, derived from its folder and filename.

        Files directly in `References/` or `References/originals/` keep the old
        filename-only key. A file in `References/topic/name.pdf` becomes
        `topic-name`, so two subjects can both contain `review.pdf`.
        """
        relative = path.resolve().relative_to(self.references_dir.resolve())
        parent = path.parent.resolve()
        if len(relative.parts) <= 1 or parent in {
            self.references_dir.resolve(),
            self.originals_dir.resolve(),
        }:
            return slugify(path.stem)
        return f"{slugify(path.parent.name)}-{slugify(path.stem)}"

    def find_manuscript(self, explicit: str | None = None) -> Path | None:
        """Find the one original manuscript in the project, without editing it."""
        if explicit:
            candidate = (self.root / explicit).resolve() if not Path(explicit).is_absolute() else Path(explicit).resolve()
            return candidate
        if self.manifest.manuscript_path:
            # Do not silently switch to a different file if the recorded
            # manuscript disappeared. The human can pass an explicit path.
            return (self.root / self.manifest.manuscript_path).resolve()
        candidates: list[Path] = []
        for folder in (self.root, self.manuscript_dir):
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                if not path.is_file() or path.name.startswith((".", "~$")):
                    continue
                # Auto-detection deliberately ignores Markdown/text: AGENTS.md
                # and other project files are not manuscripts. A human can still
                # import one explicitly by passing its path.
                if path.suffix.lower() in {".docx", ".pdf"}:
                    candidates.append(path)
        unique = sorted({path.resolve() for path in candidates})
        if len(unique) > 1:
            listing = ", ".join(path.name for path in unique)
            raise PaperchainError(
                "manuscript_ambiguous",
                f"found more than one possible manuscript: {listing}",
                hint="keep one original in the project root or Manuscript/, or pass its path to `paperchain import`",
            )
        return unique[0] if unique else None

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
