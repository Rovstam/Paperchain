from __future__ import annotations

import hashlib
import json
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

from .errors import PaperchainError


def bibtex_conversion_hint(path: Path) -> str:
    return (
        "Paperchain reads CSL JSON, not BibTeX; convert the export first: "
        f'pandoc -f bibtex -t csljson "{path.as_posix()}" -o References/library.json '
        "and point [build] bibliography at References/library.json"
    )


def load_csl(path: Path) -> list[dict]:
    """Load a CSL JSON bibliography exported by Zotero or Better BibTeX."""
    if path.suffix.lower() in {".bib", ".bibtex"}:
        raise PaperchainError(
            "bibliography_bibtex_unsupported",
            f"{path} is a BibTeX file; Paperchain reads CSL JSON",
            hint=bibtex_conversion_hint(path),
        )
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
            hint="export it again from Zotero as CSL JSON; a BibTeX export must be converted with "
            f'pandoc -f bibtex -t csljson "{path.as_posix()}" -o References/library.json',
        ) from exc
    if not isinstance(data, list) or not all(isinstance(entry, dict) for entry in data):
        raise PaperchainError(
            "bibliography_invalid",
            f"{path} is not a CSL JSON list of references",
            hint=bibtex_conversion_hint(path),
        )
    return data


def duplicate_bibliography_ids(path: Path) -> list[str]:
    """Ids that appear more than once; the first entry wins when loading."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for entry in load_csl(path):
        key = str(entry.get("id", "")).strip()
        if not key:
            continue
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)
    return duplicates


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


def title_key(value: object) -> str:
    """A comparison key that ignores case, punctuation, accents and width.

    NFKC folds compatibility forms, then NFKD plus removing combining marks
    makes a decomposed accent (`preparacion` + combining acute) equal to the
    composed form. macOS tools often write NFD into metadata.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.split()).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char for char in text if char.isalnum() or char.isspace()).strip()


def titles_equal(manifest_title: str, bibliography_title: object) -> bool:
    """True when two titles are the same after whitespace and punctuation folding.

    An empty title cannot be judged, so it is not equal to anything. Matching
    and the metadata check use this stricter test; containment is only a hint.
    """
    left = title_key(manifest_title)
    right = title_key(bibliography_title)
    return bool(left and right and left == right)


def titles_agree(manifest_title: str, bibliography_title: object) -> bool:
    """True when two titles are compatible enough not to warn.

    Extraction often adds or drops a subtitle or a filename prefix, so
    containment counts as agreement. A completely different title does not.
    An empty title cannot be judged and is not reported here.
    """
    left = title_key(manifest_title)
    right = title_key(bibliography_title)
    if not left or not right:
        return True
    return left in right or right in left


KNOWN_STYLES = {"vancouver"}
# The current Zotero/CSL Vancouver style identifies itself as NLM/Vancouver
# with the id `nlm-citation-sequence`. Older exports used `vancouver`.
STYLE_ALIASES = {
    "vancouver": {"vancouver", "nlm-citation-sequence"},
}
# A legitimate variant with a new id can be accepted without editing the
# package: list its id (or full URL) in this file beside the CSL file.
ACCEPTED_STYLE_IDS_FILE = "accepted-csl-ids.txt"
# Known Vancouver file identities. This is an id allow-list, not a content
# hash: it stops a differently named numeric style from passing just because
# its <title> says "Vancouver". A fork with a new id belongs in the sidecar
# file above, or in this list when it is widely used.
KNOWN_STYLE_IDS = {
    "vancouver",
    "nlm-citation-sequence",
    "vancouver-superscript",
    "vancouver-superscript-brackets",
    "vancouver-brackets",
    "elsevier-vancouver",
}
# A style that identifies itself as one of these is not Vancouver, whatever its
# title claims. Keeping the list short avoids rejecting a legitimate variant.
OTHER_STYLE_IDS = {
    "ieee",
    "apa",
    "chicago-author-date",
    "chicago-note-bibliography",
    "chicago-fullnote-bibliography",
    "modern-language-association",
    "harvard-cite-them-right",
    "nature",
    "science",
    "cell",
    "jama",
    "bmj",
    "american-medical-association",
    "elsevier-harvard",
    "springer-basic",
}
_CSL_MAX_BYTES = 2 * 1024 * 1024


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _style_id_slug(value: str) -> str:
    return value.strip().rstrip("/").rsplit("/", 1)[-1].casefold()


def _accepted_style_ids(path: Path) -> set[str]:
    """Ids a human explicitly accepted beside this CSL file.

    The file is optional. One id or full URL per line; blank lines and lines
    starting with `#` are ignored. This is the escape hatch for a legitimate
    variant whose id is newer than the package's allow-list.
    """
    sidecar = path.parent / ACCEPTED_STYLE_IDS_FILE
    try:
        # utf-8-sig accepts a BOM written by older Windows editors.
        lines = sidecar.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return set()
    accepted: set[str] = set()
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        # Allow `id  # reason`; a bare `#` inside an id is left alone.
        value = value.split(" #", 1)[0].strip()
        if not value:
            continue
        slug = _style_id_slug(value)
        if slug:
            accepted.add(slug)
    return accepted


def style_sha256(path: Path | None) -> str:
    """Hash the CSL file and its optional accepted-ids sidecar together.

    The sidecar is a trust input: it widens the id allow-list. It has no field
    of its own in `paper.toml`, so folding it into `csl_sha256` makes a changed
    sidecar visible after `lock` without a schema change.
    """
    if path is None or not path.is_file():
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    sidecar = path.parent / ACCEPTED_STYLE_IDS_FILE
    if sidecar.is_file():
        digest.update(b"\0paperchain-accepted-csl-ids\0")
        digest.update(sidecar.read_bytes())
    return digest.hexdigest()


def style_problem(
    path: Path, style: str, accepted_ids: set[str] | None = None
) -> str | None:
    """Why `path` is not a CSL file for `style`, or None when it is.

    This reads the style file, not the built document. It proves the project
    points at an independent numeric style whose id is a known Vancouver
    variant; it cannot prove how Word will lay out a given locator.
    """
    try:
        if path.stat().st_size > _CSL_MAX_BYTES:
            return "the CSL file is larger than 2 MB"
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError) as exc:
        return f"the CSL file cannot be read as XML ({exc})"
    if _local(root.tag) != "style":
        return "the file is not a CSL style (root element is not <style>)"

    title = ident = ""
    parent = ""
    for node in root.iter():
        name = _local(node.tag)
        if name == "title" and not title:
            title = (node.text or "").strip()
        elif name == "id" and not ident:
            ident = (node.text or "").strip()
        elif name == "link" and node.get("rel") == "independent-parent":
            parent = (node.get("href") or "").strip()
    if parent:
        return (
            "this is a dependent CSL style; it only points at "
            f"{parent or 'an independent parent'}. Download the independent style instead"
        )
    slug = _style_id_slug(ident)
    if slug in OTHER_STYLE_IDS:
        return f"the CSL file identifies itself as the {slug} style, not a Vancouver style"
    accepted = _accepted_style_ids(path)
    if accepted_ids:
        accepted |= {_style_id_slug(item) for item in accepted_ids}
    aliases = STYLE_ALIASES.get(style, {style})
    known = aliases | KNOWN_STYLE_IDS
    if slug not in known and slug not in accepted:
        return (
            f"the CSL style is called {title or ident or '(no title)'!r} "
            f"(id {ident or '(missing)'!r}), which is not a known {style} style; "
            f"if it is a legitimate {style} variant, add its id to "
            f"{ACCEPTED_STYLE_IDS_FILE} beside the CSL file"
        )

    macros = {n.get("name"): n for n in root.iter() if _local(n.tag) == "macro"}

    def numbers_citations(node: ET.Element, seen: frozenset[str]) -> bool:
        for child in node.iter():
            if child.get("variable") == "citation-number" and _local(child.tag) in {
                "text",
                "number",
                "label",
            }:
                return True
            if _local(child.tag) == "text":
                name = child.get("macro")
                if name and name in macros and name not in seen:
                    if numbers_citations(macros[name], seen | {name}):
                        return True
        return False

    for citation in (n for n in root.iter() if _local(n.tag) == "citation"):
        if numbers_citations(citation, frozenset()):
            if not any(_local(node.tag) == "bibliography" for node in root.iter()):
                return "the CSL style has no <bibliography> element, so citeproc cannot write a reference list"
            return None
    return f"the {style} style must number its citations, and this one does not use citation-number"
