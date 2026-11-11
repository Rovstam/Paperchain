from __future__ import annotations

import json
from pathlib import Path

from .errors import PaperchainError


def load_csl(path: Path) -> list[dict]:
    """Load a CSL JSON bibliography exported by Zotero or Better BibTeX."""
    if not path.is_file():
        raise PaperchainError(
            "bibliography_missing",
            f"the bibliography {path} does not exist",
            hint="export CSL JSON from Zotero to References/library.json, or fix [build] bibliography in paper.toml",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaperchainError(
            "bibliography_invalid",
            f"cannot read the bibliography {path}: {exc}",
            hint="export it again from Zotero as CSL JSON",
        ) from exc
    if not isinstance(data, list) or not all(isinstance(entry, dict) for entry in data):
        raise PaperchainError(
            "bibliography_invalid",
            f"{path} is not a CSL JSON list of references",
            hint="export CSL JSON from Zotero; a BibTeX file needs `pandoc --citeproc --bibliography` instead",
        )
    return data


def bibliography_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for entry in load_csl(path):
        key = str(entry.get("id", "")).strip()
        if key:
            keys.add(key)
    return keys
