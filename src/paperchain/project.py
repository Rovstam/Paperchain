from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import PaperchainError
from .locations import project_cache
from .manifest import MANIFEST_NAME, Manifest
from .util import shorten_key, slugify

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Better BibTeX / Zotero ids are not lowercase and may contain `_`, `:` and `.`.
# Zotero permits letters outside ASCII (`Peña2022`), so this accepts any Unicode
# letter or digit after the first character. It must stay in step with
# citations.CITATION_RE, or a citation parses and then cannot match its source.
CITATION_KEY_RE = re.compile(r"^[^\W_](?:[\w.:/+-]*[^\W_])?$")

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
REFERENCE_METADATA_SUFFIXES = {".json", ".bib", ".csl", ".ris", ".yaml", ".yml", ".xlsx", ".csv"}

# Subject categories are chosen by the human or the agent, not hardcoded here.
# This small file lists the folder names under References/ that `organize`
# should treat as reference collections at the project root.
CATEGORIES_FILE = ".paperchain-categories.json"


def category_name(value: str) -> str:
    """Normalise and validate a category folder name."""
    name = " ".join(value.split())
    drive = Path(name).drive
    if (
        not name
        or name in {".", ".."}
        or name.startswith(".")
        or "/" in name
        or "\\" in name
        or drive
    ):
        raise PaperchainError(
            "invalid_category",
            f"{value!r} is not a folder name",
            hint="pass one folder name such as --into Articulos (no slashes or drive letters)",
        )
    return name


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
        project_id = self.manifest.project_id
        if project_id and not re.fullmatch(r"[0-9a-f]{32}", project_id):
            raise PaperchainError(
                "manifest_invalid",
                f"invalid project_id {project_id!r}",
                hint="project_id is the 32-character uuid hex written by `paperchain init`; restore it or delete the line and re-run `paperchain convert`",
            )
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
            if source.citation_key:
                if not CITATION_KEY_RE.match(source.citation_key):
                    raise PaperchainError(
                        "manifest_invalid",
                        f"invalid citation_key {source.citation_key!r} for {source.key}",
                        hint="citation_key is the Better BibTeX id; letters (including accented letters), digits and _ . : / + - are allowed in the middle, but the key must start and end with a letter or digit, e.g. Amaeze2021 or Peña2022",
                    )
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

        citation_owners: dict[str, str] = {}
        for source in self.manifest.sources:
            if not source.citation_key:
                continue
            if source.citation_key in citation_owners:
                raise PaperchainError(
                    "manifest_invalid",
                    f"duplicate citation_key {source.citation_key!r}",
                    hint=f"{citation_owners[source.citation_key]} and {source.key} would both answer a citation for it",
                )
            if source.citation_key in seen and source.citation_key != source.key:
                raise PaperchainError(
                    "manifest_invalid",
                    f"citation_key {source.citation_key!r} collides with another source key",
                    hint="give each source a distinct citation_key so a citation is never ambiguous",
                )
            citation_owners[source.citation_key] = source.key

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
            ("reference_doc", self.manifest.reference_doc),
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
                    hint="keep the reference doc, bibliography and CSL files inside the project folder",
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
    def cache_dir(self) -> Path:
        """Derived files live outside the project, in the OS cache folder."""
        project_id = self.manifest.project_id
        if not project_id:
            digest = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:12]
            project_id = f"legacy-{digest}"
        return project_cache(project_id)

    @property
    def text_dir(self) -> Path:
        # Projects created before 0.3.0 kept generated text in References/_text.
        # Keep using it for those projects so an upgrade does not invalidate
        # every existing hash.
        legacy = self.references_dir / "_text"
        if not self.manifest.project_id and legacy.is_dir():
            return legacy
        return self.cache_dir / "text"

    @property
    def tmp_dir(self) -> Path:
        return self.cache_dir / "tmp"

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
    def media_cache_dir(self) -> Path:
        return self.cache_dir / "media"

    def ensure_media_dir(self) -> Path:
        """Make Paper/media usable, with the bytes in the cache when possible.

        On Windows a directory junction is used; on POSIX a symlink. If the OS
        refuses, fall back to a normal folder inside Paper/ so import still works.
        Set PAPERCHAIN_NO_LINKS=1 to force the fallback.
        """
        link = self.paper_media_dir
        target = self.media_cache_dir
        target.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            return link
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.environ.get("PAPERCHAIN_NO_LINKS"):
            link.mkdir(parents=True, exist_ok=True)
            return link
        try:
            if os.name == "nt":
                completed = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if completed.returncode != 0:
                    raise OSError((completed.stderr or completed.stdout or "").strip())
            else:
                link.symlink_to(target, target_is_directory=True)
        except OSError:
            link.mkdir(parents=True, exist_ok=True)
        return link

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
        """The project bibliography: CSL JSON, or a BibTeX export to convert.

        `library.bib` is returned only so `check` and `build` can report the
        conversion command. Nothing parses BibTeX; consumers raise
        `bibliography_bibtex_unsupported` with the `pandoc -f bibtex` hint.
        """
        configured = self.manifest.bibliography.strip()
        if configured:
            return (self.root / configured).resolve()
        default = self.references_dir / "library.json"
        if default.is_file():
            return default.resolve()
        bibtex = self.references_dir / "library.bib"
        return bibtex.resolve() if bibtex.is_file() else None

    @property
    def csl_path(self) -> Path | None:
        configured = self.manifest.csl.strip()
        if not configured:
            return None
        return (self.root / configured).resolve()

    @property
    def categories_path(self) -> Path:
        return self.references_dir / CATEGORIES_FILE

    @property
    def categories(self) -> list[str]:
        """Folder names the agent uses to group references.

        Paperchain does not hardcode subject categories such as articles or
        norms. The agent writes a small JSON file next to the references; the
        names in it are treated like the built-in reference folder names.
        """
        path = self.categories_path
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        raw = data.get("categories") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            return []
        categories: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            try:
                name = category_name(item)
            except PaperchainError:
                continue
            folded = name.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            categories.append(name)
        return categories

    def is_category(self, name: str) -> bool:
        return any(category.casefold() == name.casefold() for category in self.categories)

    def iter_reference_files(self) -> list[Path]:
        """All candidate reference documents under References/, recursively.

        Legacy `References/_text` is generated, and bibliography exports such
        as `library.json` are metadata. Neither is a reference document.
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
            if path.name.casefold().endswith(".context.md"):
                continue
            if path.suffix.lower() in REFERENCE_METADATA_SUFFIXES:
                continue
            found.append(path)
        return found

    def reference_key(self, path: Path) -> str:
        """A stable key for a reference, derived from its folder and filename.

        Files directly in `References/` or `References/originals/` keep the old
        filename-only key. A file in `References/topic/name.pdf` becomes
        `topic-name`, so two subjects can both contain `review.pdf`. Long
        titles are trimmed with a digest suffix so a citation stays typeable.
        """
        relative = path.resolve().relative_to(self.references_dir.resolve())
        parent = path.parent.resolve()
        if len(relative.parts) <= 1 or parent in {
            self.references_dir.resolve(),
            self.originals_dir.resolve(),
        }:
            return shorten_key(slugify(path.stem))
        # References/study2024/study2024.pdf is the organized form: keep the
        # key clean instead of turning it into study2024-study2024.
        if slugify(path.parent.name) == slugify(path.stem):
            return shorten_key(slugify(path.stem))
        # Known issue left for a future audit: when the folder name is a
        # truncated copy of a long filename, this branch does not recognise it
        # as the organized form and the key repeats part of the title.
        return shorten_key(f"{slugify(path.parent.name)}-{slugify(path.stem)}")

    def reference_key_candidates(self, path: Path) -> list[str]:
        """Keys to try, starting with the normal key and adding ancestors.

        Two files can share a filename and even a subfolder name in different
        categories, for example `Articulos/2024/review.pdf` and
        `Normas/2024/review.pdf`. The later candidates include more of the
        folder path so those files still get distinct keys.
        """
        relative = path.resolve().relative_to(self.references_dir.resolve())
        parts = relative.parts[:-1]
        candidates = [self.reference_key(path)]
        parent = path.parent.resolve()
        if len(relative.parts) > 1 and parent not in {
            self.references_dir.resolve(),
            self.originals_dir.resolve(),
        }:
            stem = slugify(path.stem)
            for depth in range(2, len(parts) + 1):
                prefix = "-".join(slugify(part) for part in parts[-depth:])
                candidate = shorten_key(f"{prefix}-{stem}")
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

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
