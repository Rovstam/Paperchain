from __future__ import annotations

import os
import sys
from pathlib import Path

CACHE_ENV = "PAPERCHAIN_CACHE_DIR"


def cache_root() -> Path:
    """Where paperchain keeps derived files that do not belong in a project."""
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "paperchain"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "paperchain"
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "paperchain"


def project_cache(project_id: str) -> Path:
    # Defense in depth: Project.validate rejects anything but uuid hex, but an
    # absolute or traversing id must never be able to replace the whole join.
    if not project_id or Path(project_id).name != project_id or project_id in {".", ".."}:
        raise ValueError(f"invalid project_id {project_id!r}")
    return cache_root() / "projects" / project_id
