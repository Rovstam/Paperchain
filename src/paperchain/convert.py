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
from .project import Project
from .util import now_iso, rel_posix, sha256_file


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


def organize_loose_references(project: Project) -> tuple[list[str], list[Finding]]:
    """Move loose PDF/DOCX files into References/<key>/<file>.

    Only files directly in References/ are moved. Nested files, legacy
    References/originals/ layouts and bibliography exports are left alone.
    """
    moved: list[str] = []
    warnings: list[Finding] = []
    if not project.references_dir.is_dir():
        return moved, warnings

    for path in sorted(project.references_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in {".pdf", ".docx"}:
            continue
        key = project.reference_key(path)
        target_dir = project.references_dir / key
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


def run_convert(
    project: Project,
    force: bool = False,
    only: str | None = None,
    prune: bool = False,
    organize: bool = True,
) -> dict:
    manifest = project.manifest
    if manifest.locked_at:
        raise PaperchainError(
            "project_locked",
            "the reference set is locked; conversion would rewrite hashed files",
            hint="run `paperchain unlock`, convert, then `paperchain lock`",
        )

    moved: list[str] = []
    warnings: list[Finding] = []
    if organize and not only:
        moved, warnings = organize_loose_references(project)

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
    keyed: dict[str, Path] = {}
    collisions: list[str] = []
    for path in supported:
        key = project.reference_key(path)
        if key in keyed:
            collisions.append(f"{keyed[key].name} and {path.name} both map to key {key!r}")
            continue
        existing = manifest.source(key)
        if existing and existing.path != rel_posix(path, project.root):
            collisions.append(
                f"{path.name} wants key {key!r}, already used by {existing.path}"
            )
            continue
        keyed[key] = path
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

    converted: list[str] = []
    skipped: list[str] = []
    project.text_dir.mkdir(parents=True, exist_ok=True)

    for key, path in sorted(keyed.items()):
        if only and key != only:
            continue
        original_rel = rel_posix(path, project.root)
        size = path.stat().st_size
        digest = sha256_file(path)
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
            source.title = extraction.title
        if not source.authors and extraction.authors:
            source.authors = extraction.authors
        source.sha256 = digest
        source.size = size
        source.pages = extraction.page_count
        source.converter = extraction.converter
        source.converted_at = now_iso()
        source.text_sha256 = sha256_file(json_path)
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
