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


def load_csl_entries(path: Path) -> dict[str, dict]:
    """CSL entries keyed by id, first entry wins on a duplicate id."""
    entries: dict[str, dict] = {}
    for entry in load_csl(path):
        key = str(entry.get("id", "")).strip()
        if key and key not in entries:
            entries[key] = entry
    return entries


def _title_key(value: object) -> str:
    text = " ".join(str(value or "").split()).casefold()
    return "".join(char for char in text if char.isalnum() or char.isspace()).strip()


def titles_agree(manifest_title: str, bibliography_title: object) -> bool:
    """True when two titles are compatible enough not to warn.

    Extraction often adds or drops a subtitle or a filename prefix, so
    containment counts as agreement. A completely different title does not.
    An empty title cannot be judged and is not reported here.
    """
    left = _title_key(manifest_title)
    right = _title_key(bibliography_title)
    if not left or not right:
        return True
    return left in right or right in left
