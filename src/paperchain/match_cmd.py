from __future__ import annotations

from typing import Any

from .errors import Finding, PaperchainError
from .library import load_csl, title_key, titles_agree
from .project import CITATION_KEY_RE, Project


def run_match(
    project: Project,
    apply: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Pair every source with a bibliography entry by title and record its id.

    Source keys come from filenames; Zotero ids do not. Without this mapping a
    citation cannot satisfy `check` and citeproc at the same time. Matching is
    deliberately conservative: only an exact normalized title is applied.
    Containment is reported as a suggestion for a human to confirm, and
    anything else is reported instead of guessed.
    """
    bibliography = project.bibliography_path
    if bibliography is None:
        raise PaperchainError(
            "bibliography_missing",
            "there is no bibliography export to match against",
            hint="export the Zotero collection as CSL JSON or BibTeX to References/library.json or References/library.bib",
        )

    entries: dict[str, dict] = {}
    duplicate_ids: list[str] = []
    for entry in load_csl(bibliography):
        key = str(entry.get("id", "")).strip()
        if not key:
            continue
        if key in entries:
            if key not in duplicate_ids:
                duplicate_ids.append(key)
            continue
        entries[key] = entry

    by_title: dict[str, list[str]] = {}
    for key, entry in entries.items():
        title = title_key(entry.get("title"))
        if title:
            by_title.setdefault(title, []).append(key)
    duplicate_titles = {title: ids for title, ids in by_title.items() if len(ids) > 1}

    manifest = project.manifest
    rows: list[dict[str, Any]] = []
    claimed: dict[str, str] = (
        {}
        if overwrite
        else {
            source.citation_key: source.key
            for source in manifest.sources
            if source.citation_key
        }
    )
    unchanged = False

    for source in manifest.sources:
        if source.citation_key and not overwrite:
            rows.append(
                {
                    "key": source.key,
                    "citation_key": source.citation_key,
                    "status": "kept",
                    "candidates": [],
                }
            )
            continue
        if not source.title.strip():
            rows.append(
                {
                    "key": source.key,
                    "citation_key": source.citation_key,
                    "status": "no_title",
                    "candidates": [],
                }
            )
            continue

        exact = sorted(dict.fromkeys(by_title.get(title_key(source.title), [])))
        # An entry with no title agrees with everything; it is never a
        # candidate here, only a manual choice.
        suggested = [
            key
            for key, entry in entries.items()
            if title_key(entry.get("title"))
            and titles_agree(source.title, entry.get("title"))
        ]
        suggested = sorted(dict.fromkeys(suggested))
        candidates = exact or suggested
        # An entry already used by another source must not be assigned twice.
        free = [key for key in candidates if claimed.get(key, source.key) == source.key]

        row = {
            "key": source.key,
            "citation_key": source.citation_key,
            "candidates": candidates,
        }
        if (
            exact
            and len(free) == 1
            and free[0] not in duplicate_ids
            and CITATION_KEY_RE.match(free[0])
        ):
            row["status"] = "matched"
            row["candidates"] = free
            row["citation_key"] = free[0]
            if apply and source.citation_key != free[0]:
                source.citation_key = free[0]
                unchanged = True
            claimed[free[0]] = source.key
        elif exact or (candidates and not free) or len(candidates) > 1:
            # An exact id that is duplicated, already claimed, or shared by
            # several entries cannot be applied safely.
            row["status"] = "ambiguous"
        elif candidates:
            # The titles contain one another, which is common when extraction
            # shortens a subtitle. Show it, but never write it automatically.
            row["status"] = "suggestion"
        else:
            row["status"] = "unmatched"
        rows.append(row)

    if apply and unchanged:
        project.save()

    warnings: list[Finding] = []
    for row in rows:
        if row["status"] == "unmatched":
            warnings.append(
                Finding(
                    "citation_key_unmatched",
                    f"{row['key']} has no CSL entry with a matching title",
                    severity="warning",
                    file="paper.toml",
                    data={"key": row["key"]},
                    hint="check that the PDF is the work the Zotero item names, or set citation_key by hand",
                )
            )
        elif row["status"] == "ambiguous":
            invalid = [
                candidate
                for candidate in row["candidates"]
                if not CITATION_KEY_RE.match(candidate)
            ]
            warnings.append(
                Finding(
                    "citation_key_ambiguous",
                    (
                        f"{row['key']} matches a CSL entry whose id is not a valid citation_key"
                        if invalid
                        else f"{row['key']} matches more than one CSL entry"
                    ),
                    severity="warning",
                    file="paper.toml",
                    data={"key": row["key"], "candidates": row["candidates"]},
                    hint=(
                        "fix the Zotero/Better BibTeX id first: "
                        + ", ".join(invalid)
                        + " must start and end with a letter or digit"
                        if invalid
                        else "set citation_key by hand to one of: " + ", ".join(row["candidates"])
                    ),
                )
            )
        elif row["status"] == "no_title":
            warnings.append(
                Finding(
                    "citation_key_no_title",
                    f"{row['key']} has no title in paper.toml, so it cannot be matched",
                    severity="warning",
                    file="paper.toml",
                    data={"key": row["key"]},
                    hint="set title and authors in paper.toml, or set citation_key by hand",
                )
            )
    for duplicate in duplicate_ids:
        warnings.append(
            Finding(
                "bibliography_duplicate_id",
                f"{duplicate!r} appears more than once in {project.relative(bibliography)}",
                severity="warning",
                file=project.relative(bibliography),
                data={"key": duplicate},
                hint="give each Zotero item a unique Better BibTeX key, then export again",
            )
        )
    for title, ids in sorted(duplicate_titles.items()):
        warnings.append(
            Finding(
                "bibliography_duplicate_title",
                "several CSL entries share one title",
                severity="warning",
                file=project.relative(bibliography),
                data={"title": title, "ids": ids},
                hint="matching by title cannot choose between them; set citation_key by hand",
            )
        )

    used: set[str] = set()
    for row in rows:
        if row["status"] == "matched" and row["candidates"]:
            used.add(row["candidates"][0])
        elif row["citation_key"]:
            used.add(row["citation_key"])
        else:
            used.add(row["key"])
    unused = sorted(set(entries) - used)
    for key in unused:
        warnings.append(
            Finding(
                "bibliography_entry_unmatched",
                f"{key} is in {project.relative(bibliography)} but no source uses it",
                severity="warning",
                file=project.relative(bibliography),
                data={"key": key},
                hint="add and convert the PDF, or remove the item from the Zotero collection",
            )
        )

    return {
        "sources": rows,
        "matched": [row for row in rows if row["status"] == "matched"],
        "kept": [row for row in rows if row["status"] == "kept"],
        "unmatched": [row for row in rows if row["status"] == "unmatched"],
        "ambiguous": [row for row in rows if row["status"] == "ambiguous"],
        "applied": bool(apply and unchanged),
        "warnings": warnings,
    }
