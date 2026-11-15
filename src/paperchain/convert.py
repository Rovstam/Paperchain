from __future__ import annotations

import shutil
from pathlib import Path

from .errors import Finding, PaperchainError
from .extract import (
    SUPPORTED_SUFFIXES,
    build_payload,
    dump_payload,
    extract,
    render_text_file,
)
from .manifest import Source
from .project import Project, category_name
from .util import now_iso, rel_posix, sha256_file, shorten_key, sha256_text

# File metadata often names the person who installed the software, not the
# author of the work. Treat these as "unknown" instead of printing them as an
# attribution in the paper.
GENERIC_AUTHORS = {
    "administrator",
    "admin",
    "user",
    "owner",
    "author",
    "unknown",
    "windows user",
    "microsoft office user",
}
GENERIC_TITLES = {"untitled", "untitled document", "document1", "microsoft word"}


def _is_generic(value: str, generic: set[str]) -> bool:
    cleaned = " ".join(value.split()).casefold()
    return not cleaned or cleaned in generic



def _scan_references(project: Project) -> list[Path]:
    if not project.references_dir.is_dir():
        raise PaperchainError(
            "no_references",
            "References/ does not exist",
            hint="create it and put your PDF or DOCX references inside, in as many subfolders as you like",
        )
    files = project.iter_reference_files()
    allowed = project.references_dir.resolve()
    for path in files:
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise PaperchainError(
                "source_unreadable",
                f"cannot resolve {path.name}: {exc}",
            ) from exc
        if not resolved.is_relative_to(allowed):
            raise PaperchainError(
                "source_outside_project",
                f"{path.name} links to a file outside References/",
                hint="copy the file into the folder instead of linking to it",
            )
    return files


def organize_loose_references(
    project: Project, into: str | None = None
) -> tuple[list[str], list[Finding]]:
    """Move loose PDF/DOCX files out of the References root.

    Without `into` each file goes to `References/<key>/<file>`. With a
    category, the files go to `References/<category>/<file>` instead, so the
    reference tree keeps the subject folders the human or agent chose.

    Only files directly in References/ are moved. Nested files, legacy
    References/originals/ layouts and bibliography exports are left alone.
    """
    moved: list[str] = []
    warnings: list[Finding] = []
    if not project.references_dir.is_dir():
        return moved, warnings

    category = category_name(into) if into else ""
    for path in sorted(project.references_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in {".pdf", ".docx"}:
            continue
        key = project.reference_key(path)
        target_dir = (
            project.references_dir / category if category else project.references_dir / key
        )
        target = target_dir / path.name
        if target.exists():
            warnings.append(
                Finding(
                    "organize_skipped",
                    f"{path.name} was not moved because {project.relative(target)} already exists",
                    severity="warning",
                    file=project.relative(path),
                    hint="rename one of the files or move it into a different subfolder",
                )
            )
            continue
        old_rel = rel_posix(path, project.root)
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        new_rel = rel_posix(target, project.root)
        for source in project.manifest.sources:
            if source.path == old_rel:
                source.path = new_rel
        moved.append(f"{old_rel} -> {new_rel}")

    return moved, warnings


def _assign_keys(project: Project, files: list[Path]) -> tuple[dict[str, Path], list[str]]:
    """Map each reference file to a unique, typeable key.

    The normal key is used when it is free. If two files would get the same
    key, candidates that include more of the folder path are tried. An
    existing path keeps the key it already has, so adding a new file does not
    rename old citations.
    """
    rel_paths = {path: rel_posix(path, project.root) for path in files}
    manifest_paths = {source.path: source.key for source in project.manifest.sources}
    manifest_keys = {source.key: source.path for source in project.manifest.sources}
    base_keys = {path: project.reference_key(path) for path in files}
    counts: dict[str, int] = {}
    for key in base_keys.values():
        counts[key] = counts.get(key, 0) + 1

    keyed: dict[str, Path] = {}
    collisions: list[str] = []
    for path in files:
        rel = rel_paths[path]
        existing = manifest_paths.get(rel)
        candidates: list[str] = [existing] if existing else []
        expanded = project.reference_key_candidates(path)
        if existing is None and counts[base_keys[path]] > 1:
            # Both files would start with the same key, so both use the
            # expanded form and the result does not depend on which came first.
            candidates.extend(expanded[1:])
        else:
            candidates.extend(expanded)
        candidates.append(shorten_key(f"{base_keys[path]}-{sha256_text(rel)[:8]}"))

        chosen = None
        for candidate in candidates:
            if not candidate or candidate in keyed:
                continue
            if candidate in manifest_keys and manifest_keys[candidate] != rel:
                continue
            chosen = candidate
            break
        if chosen is None:
            collisions.append(f"{rel} cannot get a unique key; rename the file")
            continue
        keyed[chosen] = path

    return keyed, collisions


def run_convert(
    project: Project,
    force: bool = False,
    only: str | None = None,
    prune: bool = False,
    organize: bool = True,
    accept_changes: bool = False,
    into: str | None = None,
) -> dict:
    manifest = project.manifest
    if manifest.locked_at:
        raise PaperchainError(
            "project_locked",
            "the reference set is locked; conversion would rewrite hashed files",
            hint="run `paperchain unlock`, convert, then `paperchain lock`",
        )
    if into and (not organize or only):
        raise PaperchainError(
            "conflicting_options",
            "--into moves loose files, but the loose-file organizer is disabled",
            hint="drop --no-organize/--only, or run `paperchain organize --into CATEGORY --apply` first",
        )

    moved: list[str] = []
    warnings: list[Finding] = []
    if organize and not only:
        moved, warnings = organize_loose_references(project, into=into)

    files = _scan_references(project)
    supported = [path for path in files if path.suffix.lower() in SUPPORTED_SUFFIXES]
    unsupported = [path for path in files if path.suffix.lower() not in SUPPORTED_SUFFIXES]

    warnings.extend(
        Finding(
            "unsupported_file",
            f"{path.name} is not a supported reference type",
            severity="warning",
            file=project.relative(path),
            hint="supported types are PDF, DOCX, TXT and MD; other files are ignored",
        )
        for path in unsupported
    )

    # Map files to keys and refuse ambiguous names before writing anything.
    keyed, collisions = _assign_keys(project, supported)
    if collisions:
        raise PaperchainError(
            "key_collision",
            "; ".join(collisions),
            hint="rename one of the files so each source gets a unique key",
        )

    if only and only not in keyed:
        raise PaperchainError(
            "unknown_source",
            f"no reference file maps to key {only!r}",
            hint=f"available keys: {', '.join(sorted(keyed)) or '(none)'}",
        )

    targets = [
        (key, path) for key, path in sorted(keyed.items()) if not only or key == only
    ]
    digests = {key: sha256_file(path) for key, path in targets}

    # Re-converting a changed original silently rewrites its hash. That is the
    # sequence `check` recommends after an unlock, so it needs the same
    # explicit confirmation that `lock --accept-changes` already requires.
    changes = [
        f"{key}: original changed"
        for key, _ in targets
        if (existing := manifest.source(key)) is not None
        and existing.sha256
        and existing.sha256 != digests[key]
    ]
    if changes and not accept_changes:
        raise PaperchainError(
            "convert_changes",
            "the reference set changed since it was last converted: " + "; ".join(changes),
            hint="inspect the files, then re-run `paperchain convert --accept-changes` to bless them",
        )

    converted: list[str] = []
    skipped: list[str] = []
    project.text_dir.mkdir(parents=True, exist_ok=True)

    for key, path in targets:
        original_rel = rel_posix(path, project.root)
        size = path.stat().st_size
        digest = digests[key]
        json_path = project.text_dir / f"{key}.json"
        txt_path = project.text_dir / f"{key}.txt"
        existing = manifest.source(key)

        unchanged = (
            not force
            and existing is not None
            and existing.sha256 == digest
            and json_path.is_file()
            and txt_path.is_file()
            and existing.text_sha256 == sha256_file(json_path)
        )
        if unchanged:
            skipped.append(key)
            continue

        extraction = extract(path)
        warnings.extend(extraction.warnings)
        payload = build_payload(
            key=key,
            original_rel=original_rel,
            extraction=extraction,
            source_sha256=digest,
            size=size,
            converted_at=now_iso(),
        )
        json_path.write_text(dump_payload(payload), encoding="utf-8", newline="\n")
        txt_path.write_text(
            render_text_file(key, path.name, extraction), encoding="utf-8", newline="\n"
        )

        source = existing or Source(key=key, path=original_rel)
        source.path = original_rel
        if not source.title and extraction.title:
            if _is_generic(extraction.title, GENERIC_TITLES):
                warnings.append(
                    Finding(
                        "source_metadata_unconfirmed",
                        f"{key}: the file title {extraction.title!r} is a placeholder, not a work title",
                        severity="warning",
                        file=original_rel,
                        hint="set title, authors and year in paper.toml",
                    )
                )
            else:
                source.title = extraction.title
        if not source.authors and extraction.authors:
            if _is_generic(extraction.authors, GENERIC_AUTHORS):
                warnings.append(
                    Finding(
                        "source_metadata_unconfirmed",
                        f"{key}: the file metadata names {extraction.authors!r} as the author",
                        severity="warning",
                        file=original_rel,
                        hint="set authors and year in paper.toml; that name would otherwise appear in the paper",
                    )
                )
            else:
                source.authors = extraction.authors
        source.sha256 = digest
        source.size = size
        source.pages = extraction.page_count
        source.converter = extraction.converter
        source.converted_at = now_iso()
        source.text_sha256 = sha256_file(json_path)
        if source.year is None:
            warnings.append(
                Finding(
                    "source_metadata_unconfirmed",
                    f"{key} has no year in paper.toml",
                    severity="warning",
                    file=original_rel,
                    hint="add year = 2024 under [[sources]]; extracted metadata does not contain a reliable year",
                )
            )
        manifest.upsert(source)
        converted.append(key)

    pruned: list[str] = []
    if prune:
        for source in list(manifest.sources):
            if only and source.key != only:
                continue
            if not (project.root / source.path).is_file():
                manifest.remove(source.key)
                pruned.append(source.key)

    project.save()
    _write_index(project)

    return {
        "converted": converted,
        "skipped": skipped,
        "pruned": pruned,
        "moved": moved,
        "warnings": warnings,
        "data": {
            "sources": len(manifest.sources),
            "originals": len(supported),
            "moved": moved,
            "into": category_name(into) if into else "",
            "cache": str(project.cache_dir),
            "index": str(project.text_dir / "INDEX.md"),
        },
    }


def _write_index(project: Project) -> None:
    manifest = project.manifest
    lines = [
        "# Reference index",
        "",
        "Generated by `paperchain convert`. Do not edit by hand.",
        "",
        "Read `<key>.txt` for the text of a source. Each page starts with a `===== PAGE n =====` marker.",
        "",
        "| key | pages | title | file |",
        "| --- | --- | --- | --- |",
    ]
    if not manifest.sources:
        lines.append("| _(none yet)_ | | | |")
    for source in manifest.sources:
        title = source.title.replace("|", "\\|") if source.title else "-"
        pages = str(source.pages) if source.pages else "?"
        lines.append(f"| `{source.key}` | {pages} | {title} | `{source.path}` |")
    lines.append("")
    (project.text_dir / "INDEX.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
