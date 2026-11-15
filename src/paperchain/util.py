from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .errors import PaperchainError


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_link(path: Path) -> bool:
    """True for a POSIX symlink or a Windows directory junction."""
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 with LF endings, atomically where the platform allows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except PermissionError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise PaperchainError(
            "file_read_only",
            f"cannot write {path}: the file or its directory is read-only",
            hint="if this is a reference file, run `paperchain unlock` first",
        ) from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    if slug:
        return slug
    # Names with no ASCII letters (for example 研究一.pdf) still need distinct
    # keys. A short digest of the original value keeps them stable and unique.
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"doc-{digest}"


def shorten_key(value: str, limit: int = 60) -> str:
    """Trim a generated key to a size a human can type in a citation.

    The tail is a digest of the full key, so two different long titles never
    collapse to the same short key. The cut prefers a hyphen boundary when one
    is close, because a key that stops at a word is easier to read.
    """
    if len(value) <= limit:
        return value
    digest = sha256_text(value)[:8]
    head = value[: limit - len(digest) - 1].rstrip("-")
    if "-" in head:
        cut = head.rsplit("-", 1)[0]
        if cut:
            head = cut
    if not head:
        head = "doc"
    return f"{head}-{digest}"


def backup_path(path: Path) -> Path | None:
    """Copy an existing file next to itself before it is overwritten.

    Returns the backup path, or None when there was nothing to save. Existing
    backups are never overwritten: the suffix gets a counter instead.
    """
    if not path.is_file():
        return None
    candidate = path.with_name(f"{path.name}.bak")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak.{counter}")
        counter += 1
    candidate.write_bytes(path.read_bytes())
    return candidate


def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


_QUOTE_TABLE = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
        "\u200b": "",
    }
)


def normalize_for_match(text: str, join_hyphenation: bool = True) -> str:
    """Normalize extracted text and quoted spans before comparing them.

    The normalization exists to absorb differences that are artefacts of PDF
    extraction, not differences in meaning: ligatures, smart punctuation,
    line-break hyphenation and whitespace. It never adds or removes words.

    With join_hyphenation=False, a word broken as "well-\\nknown" keeps its
    hyphen ("well-known"), so a quote that legitimately contains the compound
    still matches.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00ad", "")  # soft hyphen
    text = text.translate(_QUOTE_TABLE)
    # Only letters are joined. A hyphen between digits marks a range
    # ("10-\n20"), not a word broken across a line; joining it would turn
    # "10-20" into "1020" and let a quote match words that were never there.
    letter = r"[^\W\d_]"
    if join_hyphenation:
        # Join words split across a line by a hyphen, e.g. "exam-\nple".
        text = re.sub(rf"({letter})-\s*\n\s*({letter})", r"\1\2", text)
    else:
        text = re.sub(rf"({letter})-\s*\n\s*({letter})", r"\1-\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def word_count(text: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['-][^\W_]+)*", text, flags=re.UNICODE))


def human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
