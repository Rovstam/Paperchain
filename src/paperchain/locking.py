from __future__ import annotations

import json
import os
import stat

from .errors import PaperchainError
from .extract import Extraction, extract, render_text_file
from .library import style_sha256
from .project import Project
from .reference_log import append_event, reference_fingerprint
from .util import now_iso, sha256_file


def _set_mode(path, readonly: bool) -> None:
    """Remove or restore the write bits without granting extra permissions."""
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        target = (current & ~0o222) if readonly else (current | 0o200)
        if target != current:
            os.chmod(path, target)
    except OSError as exc:
        raise PaperchainError(
            "permission_failed",
            f"cannot change permissions on {path}: {exc}",
            hint="check that you own the file and that it is not open in another program",
        ) from exc


def _locked_files(project: Project):
    for source in project.manifest.sources:
        yield project.root / source.path
        yield project.text_dir / f"{source.key}.json"
        yield project.text_dir / f"{source.key}.txt"


def run_lock(project: Project, accept_changes: bool = False) -> dict:
    manifest = project.manifest
    if not manifest.sources:
        raise PaperchainError(
            "no_sources",
            "there are no sources to lock",
            hint="put files under References/ and run `paperchain convert`",
        )

    problems: list[str] = []
    page_counts: dict[str, int] = {}
    source_hashes: dict[str, str] = {}
    text_hashes: dict[str, str] = {}

    for source in manifest.sources:
        path = project.root / source.path
        if not path.is_file():
            problems.append(f"{source.path} is missing")
            continue
        json_path = project.text_dir / f"{source.key}.json"
        txt_path = project.text_dir / f"{source.key}.txt"
        if not json_path.is_file() or not txt_path.is_file():
            problems.append(f"{source.key} has not been converted")
            continue
        source_hashes[source.key] = sha256_file(path)
        text_hashes[source.key] = sha256_file(json_path)
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            pages = [entry["text"] for entry in payload["pages"]]
            page_counts[source.key] = len(pages)
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(f"{source.key} has an unreadable text file")
            continue
        if str(payload.get("sha256", "")) != source_hashes[source.key]:
            problems.append(
                f"{source.key}: converted text was built from a different original; run `convert --force --accept-changes`"
            )
            continue
        try:
            fresh = extract(path)
        except PaperchainError as exc:
            problems.append(f"{source.key}: cannot re-extract the original ({exc.message})")
            continue
        if fresh.pages != pages:
            problems.append(
                f"{source.key}: converted text does not match a fresh extraction; run `convert --force --accept-changes`"
            )
            continue
        expected = render_text_file(
            source.key,
            path.name,
            Extraction(
                pages=pages,
                converter=str(payload.get("converter", "") or "unknown"),
                page_map_estimated=bool(payload.get("page_map_estimated", False)),
            ),
        )
        try:
            actual_txt = txt_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            actual_txt = None
        if actual_txt != expected:
            problems.append(
                f"{source.key}: .txt does not match the converted page map; run `convert --force --accept-changes`"
            )

    if manifest.style:
        # Locking a style project without the export or the CSL would record an
        # empty hash and report "locked" while nothing about the style is
        # protected. Fail instead, like a missing conversion.
        bibliography = project.bibliography_path
        if bibliography is None or not bibliography.is_file():
            problems.append("the style is set but the Zotero export is missing")
        csl = project.csl_path
        if csl is None or not csl.is_file():
            problems.append(f"the style is set but {manifest.csl or 'the CSL file'} is missing")

    if problems:
        style_missing = any(problem.startswith("the style is set but") for problem in problems)
        hint = (
            "restore the bibliography and CSL files named in the message"
            if style_missing
            else "run `paperchain convert` first, and restore any missing originals"
        )
        raise PaperchainError("lock_failed", "; ".join(problems), hint=hint)

    changes: list[str] = []
    # The Zotero export is hashed whenever it exists, with or without a style:
    # citeproc reads titles, authors and years from it.
    bibliography = project.bibliography_path
    bibliography_hash = sha256_file(bibliography) if bibliography and bibliography.is_file() else ""
    if manifest.bibliography_sha256 and manifest.bibliography_sha256 != bibliography_hash:
        changes.append("bibliography: the Zotero export changed")
    if manifest.style:
        csl_hash = style_sha256(project.csl_path)
        if manifest.csl_sha256 and manifest.csl_sha256 != csl_hash:
            changes.append("csl: the style file or accepted-csl-ids.txt changed")
    else:
        csl_hash = ""
    for source in manifest.sources:
        if source.sha256 and source.sha256 != source_hashes[source.key]:
            changes.append(f"{source.key}: original changed")
        if source.text_sha256 and source.text_sha256 != text_hashes[source.key]:
            changes.append(f"{source.key}: converted text changed")

    if changes and not accept_changes:
        raise PaperchainError(
            "lock_changes",
            "the reference set changed since it was last hashed: " + "; ".join(changes),
            hint="inspect the files, then re-run `paperchain lock --accept-changes` to bless them",
        )

    for source in manifest.sources:
        path = project.root / source.path
        source.sha256 = source_hashes[source.key]
        source.size = path.stat().st_size
        source.text_sha256 = text_hashes[source.key]
        source.pages = page_counts[source.key]

    # The bibliography and the style are hashed, not made read-only: Zotero must be
    # able to overwrite the export, and a re-export is then reported by check.
    # Without a configured style they are not part of the lock, so existing
    # projects keep their previous behaviour.
    manifest.bibliography_sha256 = bibliography_hash
    manifest.csl_sha256 = csl_hash

    for path in _locked_files(project):
        if path.is_file():
            _set_mode(path, readonly=True)

    manifest.locked_at = now_iso()
    project.save()
    append_event(
        project,
        "accept_changes" if changes else "lock",
        source="lock",
        changes=changes,
        fingerprint=reference_fingerprint(manifest),
    )

    return {
        "locked_at": manifest.locked_at,
        "sources": len(manifest.sources),
        "changes": changes,
        "data": {
            "files": sum(1 for path in _locked_files(project) if path.is_file()),
            "manifest": "paper.toml",
        },
    }


def run_unlock(project: Project, additive: bool = False) -> dict:
    manifest = project.manifest
    changed = 0
    for path in _locked_files(project):
        if path.is_file():
            _set_mode(path, readonly=False)
            changed += 1
    manifest.locked_at = ""
    project.save()
    append_event(project, "unlock", fingerprint=reference_fingerprint(manifest), additive=additive)
    return {
        "data": {
            "files": changed,
            "note": "hashes are kept so a later `paperchain check` can still detect changes",
        }
    }
