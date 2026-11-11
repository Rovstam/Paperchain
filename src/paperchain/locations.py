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
    return cache_root() / "projects" / project_id
