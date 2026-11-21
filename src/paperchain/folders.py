"""Readable folder names for loose references.

A loose PDF or DOCX in `References/` is filed in a folder named after the
paper's title instead of its filename. Titles are cleaned for every operating
system, cut at a word boundary, and never produce an empty, hidden or reserved
name. A file with no usable title keeps the filename-based behaviour.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .library import load_csl, titles_equal

MAX_FOLDER_CHARS = 10
# A first word longer than the limit is kept whole up to this length, never cut mid-word.
MAX_WORD_CHARS = 25

_FORBIDDEN = re.compile(r'[\\/*?"<>|\x00-\x1f\x7f]')
_TRAILING_PUNCT = " .,:;/+-_\u2013\u2014("
_STOP_TAIL = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on",
    "or", "the", "to", "with", "versus", "vs",
}
_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {
    f"lpt{i}" for i in range(1, 10)
}
_GENERIC = {"untitled", "untitled document", "document1", "microsoft word", "title"}
_FILE_LIKE = re.compile(r"\.(pdf|docx?|tex|indd|pages|odt|rtf|txt)\s*$", re.IGNORECASE)


def usable_title(raw: object) -> str:
    """A metadata title worth naming a folder after, or an empty string."""
    text = " ".join(unicodedata.normalize("NFC", str(raw or "")).split())
    if not text:
        return ""
    lowered = text.casefold()
    if lowered in _GENERIC or lowered.startswith(("microsoft word", "untitled")):
        return ""
    if _FILE_LIKE.search(text):
        return ""
    if sum(char.isalpha() for char in text) < 4:
        return ""
    return text


def folder_name(title: str, limit: int = MAX_FOLDER_CHARS) -> str:
    """Sanitise `title` into a folder name of at most `limit` characters.

    Characters Windows, macOS or Linux reject are removed, `: ` becomes ` - `,
    and a long title is cut at a word boundary with dangling words such as
    "of" or "and" dropped. Returns "" when nothing usable is left.
    """
    text = unicodedata.normalize("NFC", title or "")
    text = text.replace(": ", " - ").replace(":", " ")
    text = _FORBIDDEN.sub(" ", text)
    text = " ".join(text.split()).strip(_TRAILING_PUNCT)
    text = text.lstrip(". ")
    if not text:
        return ""

    if len(text) > limit:
        cut = text[:limit]
        if text[limit] != " ":
            if " " in cut:
                cut = cut.rsplit(" ", 1)[0]
            else:
                end = text.find(" ")
                cut = text[: min(len(text) if end == -1 else end, max(limit, MAX_WORD_CHARS))]
        words = cut.rstrip(_TRAILING_PUNCT).split()
        while len(words) > 1 and words[-1].casefold().strip(",;:.") in _STOP_TAIL:
            words.pop()
        text = " ".join(words).rstrip(_TRAILING_PUNCT)
        if not text:
            text = cut.rstrip(_TRAILING_PUNCT)

    text = text.strip(_TRAILING_PUNCT)
    if not text:
        return ""
    if text.casefold() in _RESERVED:
        text = f"{text}_"
    return text


def library_title(bibliography: Path | None, title: str) -> str:
    """The Zotero spelling of `title` when exactly one library entry matches."""
    if bibliography is None or not title:
        return title
    try:
        entries = load_csl(bibliography)
    except Exception:  # an unreadable export must never block filing
        return title
    matches = [
        entry["title"]
        for entry in entries
        if isinstance(entry.get("title"), str) and titles_equal(title, entry["title"])
    ]
    unique = {" ".join(item.split()) for item in matches}
    return unique.pop() if len(unique) == 1 else title


def free_folder(parent: Path, name: str) -> Path:
    """`parent/name`, or `parent/name (2)`, ... when the name is taken.

    The comparison ignores case, because Windows and macOS treat `Study` and
    `study` as the same folder.
    """
    taken = {entry.name.casefold() for entry in parent.iterdir()} if parent.is_dir() else set()
    candidate = name
    counter = 2
    while candidate.casefold() in taken:
        candidate = f"{name} ({counter})"
        counter += 1
    return parent / candidate
