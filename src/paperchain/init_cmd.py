from __future__ import annotations

import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from . import PROGRAM
from .errors import PaperchainError
from .manifest import MANIFEST_NAME, new_manifest
from .util import now_iso, slugify

TEXT_SUFFIXES = {".md", ".toml", ".json", ".jsonc", ".txt", ".yml", ".yaml", ".tmpl", ".example"}
SPECIAL_TEXT_NAMES = {"gitignore", "gitattributes", "AGENTS.md.tmpl"}

DIRECTORIES = [
    "Manuscript",
    "References",
    "Paper",
    "Candidates",
    "Output",
]


def available_adapters() -> list[str]:
    root = files("paperchain").joinpath("adapters")
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir())


def _target_name(name: str) -> str:
    if name.endswith(".tmpl"):
        name = name[: -len(".tmpl")]
    if name == "gitignore":
        return ".gitignore"
    if name == "gitattributes":
        return ".gitattributes"
    return name


def _render(text: str, context: dict[str, str]) -> str:
    for key, value in context.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _is_text(name: str) -> bool:
    if name in SPECIAL_TEXT_NAMES:
        return True
    return Path(name).suffix.lower() in TEXT_SUFFIXES


def _copy_tree(
    source,
    destination: Path,
    context: dict[str, str],
    overwrite: bool,
) -> tuple[int, int]:
    written = 0
    skipped = 0
    for entry in source.iterdir():
        if entry.name in {"__pycache__"}:
            continue
        target = destination / _target_name(entry.name)
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            child_written, child_skipped = _copy_tree(entry, target, context, overwrite)
            written += child_written
            skipped += child_skipped
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            skipped += 1
            continue
        data = entry.read_bytes()
        if _is_text(entry.name):
            text = data.decode("utf-8")
            target.write_text(_render(text, context), encoding="utf-8", newline="\n")
        else:
            target.write_bytes(data)
        written += 1
    return written, skipped


def _copy_adapter(
    name: str, destination: Path, context: dict[str, str], overwrite: bool
) -> tuple[list[str], list[str]]:
    adapters = available_adapters()
    if name not in adapters:
        raise PaperchainError(
            "unknown_adapter",
            f"there is no adapter named {name!r}",
            hint=f"available adapters: {', '.join(adapters) or '(none)'}",
        )

    root = files("paperchain").joinpath("adapters", name)
    config = tomllib.loads(root.joinpath("adapter.toml").read_text(encoding="utf-8"))
    entries = config.get("files", [])
    written: list[str] = []
    skipped: list[str] = []
    for entry in entries:
        source = root.joinpath(entry["source"])
        target = destination / entry["target"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            skipped.append(entry["target"])
            continue
        data = source.read_bytes()
        if _is_text(source.name):
            target.write_text(
                _render(data.decode("utf-8"), context), encoding="utf-8", newline="\n"
            )
        else:
            target.write_bytes(data)
        written.append(entry["target"])
    return written, skipped


def run_init(
    directory: str,
    title: str | None = None,
    agent: str = "opencode",
    force: bool = False,
    git: bool = False,
    adopt: bool = False,
) -> dict[str, Any]:
    destination = Path(directory).expanduser().resolve()

    adapters = available_adapters()
    if agent not in adapters:
        raise PaperchainError(
            "unknown_adapter",
            f"there is no adapter named {agent!r}",
            hint=f"available adapters: {', '.join(adapters) or '(none)'}",
        )

    if (destination / MANIFEST_NAME).is_file() and not force:
        raise PaperchainError(
            "already_initialized",
            f"{destination} already contains {MANIFEST_NAME}",
            hint="pass --force to overwrite the template files, or choose another folder",
        )
    if destination.exists() and any(destination.iterdir()) and not (force or adopt):
        raise PaperchainError(
            "destination_not_empty",
            f"{destination} is not empty",
            hint="choose an empty folder, pass --adopt to keep your files and add only the missing project files, or pass --force to overwrite template files",
        )

    destination.mkdir(parents=True, exist_ok=True)
    resolved_title = (title or "").strip() or destination.name
    slug = slugify(resolved_title)
    context = {
        "program": PROGRAM,
        "title": resolved_title,
        "slug": slug,
        "date": now_iso()[:10],
    }

    template_root = files("paperchain").joinpath("templates", "paper")
    if not template_root.is_dir():
        raise PaperchainError(
            "template_missing",
            "the packaged paper template is missing",
            hint="reinstall paperchain",
        )

    overwrite = bool(force)
    copied, skipped = _copy_tree(template_root, destination, context, overwrite)

    manifest = new_manifest(resolved_title)
    manifest.save(destination / MANIFEST_NAME)

    adapter_files, skipped_adapters = _copy_adapter(
        agent, destination, context, overwrite
    )
    skipped += len(skipped_adapters)

    for name in DIRECTORIES:
        folder = destination / name
        folder.mkdir(parents=True, exist_ok=True)
        keep = folder / ".gitkeep"
        if not any(folder.iterdir()):
            keep.write_text("", encoding="utf-8")

    git_initialized = False
    if git:
        try:
            completed = subprocess.run(
                ["git", "init", "-q"],
                cwd=str(destination),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            git_initialized = completed.returncode == 0
        except OSError:
            git_initialized = False

    return {
        "root": str(destination),
        "title": resolved_title,
        "slug": slug,
        "adapter": agent,
        "git": git_initialized,
        "data": {
            "files": copied + len(adapter_files),
            "skipped": skipped,
            "adopted": adopt and not force,
            "adapter_files": adapter_files,
            "next": [
                "put the original manuscript DOCX/PDF in Manuscript/ (or the project root)",
                "put reference PDFs/DOCX in References/; loose files are moved into their own folders, and subfolders are allowed",
                f"{PROGRAM} import",
                f"{PROGRAM} convert",
                f"{PROGRAM} lock",
                f"{PROGRAM} check",
                f"{PROGRAM} build",
            ],
        },
    }
