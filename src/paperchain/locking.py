from __future__ import annotations

import json
import os

from .errors import PaperchainError
from .project import Project
from .util import now_iso, sha256_file

READ_ONLY = 0o444
WRITABLE = 0o644


def _set_mode(path, readonly: bool) -> None:
    mode = READ_ONLY if readonly else WRITABLE
    try:
        os.chmod(path, mode)
    except OSError as exc:
        raise PaperchainError(
            "permission_failed",
            f"cannot change permissions on {path}: {exc}",
            hint="check that you own the file and that it is not open in another program",
        ) from exc


def _locked_files(project: Project):
    for source in project.manifest.sources:
        yield project.root / source.path
        yield project.text_dir / f"{source.key}.json"
        yield project.text_dir / f"{source.key}.txt"


def run_lock(project: Project) -> dict:
    manifest = project.manifest
    if not manifest.sources:
        raise PaperchainError(
            "no_sources",
            "there are no sources to lock",
            hint="put files in References/originals and run `paperchain convert`",
        )

    problems: list[str] = []
    page_counts: dict[str, int] = {}
    for source in manifest.sources:
        path = project.root / source.path
        if not path.is_file():
            problems.append(f"{source.path} is missing")
            continue
        json_path = project.text_dir / f"{source.key}.json"
        txt_path = project.text_dir / f"{source.key}.txt"
        if not json_path.is_file() or not txt_path.is_file():
            problems.append(f"{source.key} has not been converted")
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            page_counts[source.key] = len(payload["pages"])
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(f"{source.key} has an unreadable text file")

    if problems:
        raise PaperchainError(
            "lock_failed",
            "; ".join(problems),
            hint="run `paperchain convert` first, and restore any missing originals",
        )

    for source in manifest.sources:
        path = project.root / source.path
        json_path = project.text_dir / f"{source.key}.json"
        source.sha256 = sha256_file(path)
        source.size = path.stat().st_size
        source.text_sha256 = sha256_file(json_path)
        source.pages = page_counts[source.key]

    manifest.locked_at = now_iso()
    project.save()

    for path in _locked_files(project):
        if path.is_file():
            _set_mode(path, readonly=True)

    return {
        "locked_at": manifest.locked_at,
        "sources": len(manifest.sources),
        "data": {
            "files": sum(1 for path in _locked_files(project) if path.is_file()),
            "manifest": "paper.toml",
        },
    }


def run_unlock(project: Project) -> dict:
    manifest = project.manifest
    changed = 0
    for path in _locked_files(project):
        if path.is_file():
            _set_mode(path, readonly=False)
            changed += 1
    manifest.locked_at = ""
    project.save()
    return {
        "data": {
            "files": changed,
            "note": "hashes are kept so a later `paperchain check` can still detect changes",
        }
    }
