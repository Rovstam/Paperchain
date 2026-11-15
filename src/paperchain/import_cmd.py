from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import Finding, PaperchainError
from .extract import extract
from .project import Project
from .util import backup_path, is_link, now_iso, rel_posix, sha256_file, word_count

DOCX_SUFFIXES = {".docx"}
PLAIN_SUFFIXES = {".md", ".markdown", ".txt"}
IMPORT_SUFFIXES = DOCX_SUFFIXES | PLAIN_SUFFIXES | {".pdf"}


def _pandoc() -> str:
    executable = shutil.which("pandoc")
    if not executable:
        raise PaperchainError(
            "pandoc_missing",
            "pandoc is not installed or not on PATH",
            hint="install it from https://pandoc.org/installing.html; `import` needs it to convert DOCX without editing it",
        )
    return executable


def _import_docx(source: Path, project: Project) -> str:
    executable = _pandoc()
    temp = project.paper_dir / ".import.md"
    # `--extract-media=Paper` makes Pandoc write `Paper/media/...` and links
    # relative to the project root. Passing the absolute Paper/media path made
    # Pandoc write `Paper/media/media/...` and absolute links, which failed at
    # build time.
    project.ensure_media_dir()
    command = [
        executable,
        str(source),
        "--from",
        "docx",
        "--to",
        "markdown",
        "--wrap=none",
        "--markdown-headings=atx",
        "--extract-media=Paper",
        "--output",
        str(temp),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(project.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise PaperchainError(
            "import_failed",
            f"cannot run pandoc: {exc}",
            hint="run `paperchain doctor` and check that pandoc is on PATH",
        ) from exc
    if completed.returncode != 0:
        temp.unlink(missing_ok=True)
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PaperchainError(
            "import_failed",
            f"pandoc could not convert {source.name}",
            hint=detail[-800:] or "export the manuscript as .docx again",
        )
    text = temp.read_text(encoding="utf-8", errors="replace")
    temp.unlink(missing_ok=True)
    # Pandoc writes links relative to the project root. paper.md lives in
    # Paper/, so make them relative to the draft instead. Older Pandoc
    # versions and an absolute --extract-media target can still produce
    # absolute Windows paths, so strip the Paper/ prefix as well. Only link
    # targets are rewritten: prose that mentions a path is left alone.
    prefix = re.escape(str(project.paper_dir))
    text = re.sub(r"(\]\(\s*<?)" + prefix + r"[\\/]+", r"\1", text)
    text = re.sub(r"""(src\s*=\s*["'])""" + prefix + r"[\\/]+", r"\1", text)
    text = re.sub(r"(\]\(\s*<?)Paper/media/", r"\1media/", text)
    text = re.sub(r"""(src\s*=\s*["'])Paper/media/""", r"\1media/", text)
    return text


def _import_pdf(source: Path) -> tuple[str, list[Finding]]:
    extraction = extract(source)
    warnings: list[Finding] = [
        Finding(
            "pdf_import_plain_text",
            "a PDF manuscript is imported as plain paragraphs; headings and styles are not reconstructed",
            severity="warning",
            file=source.name,
            hint="export the manuscript as .docx if you need headings, tables or images",
        )
    ]
    text = "\n\n".join(page.rstrip() for page in extraction.pages if page.strip())
    return text, warnings


def _import_plain(source: Path) -> str:
    try:
        return source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return source.read_text(encoding="utf-8", errors="replace")


def run_import(
    project: Project,
    source: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    manuscript = project.find_manuscript(source)
    if manuscript is None:
        raise PaperchainError(
            "manuscript_missing",
            "no original manuscript found",
            hint="put one .docx or .pdf in the project root or Manuscript/, or pass its path to `paperchain import`",
        )
    if not manuscript.is_file():
        raise PaperchainError(
            "manuscript_missing",
            f"{manuscript} does not exist",
            hint="pass an existing .docx or .pdf",
        )
    suffix = manuscript.suffix.lower()
    if suffix not in IMPORT_SUFFIXES:
        raise PaperchainError(
            "unsupported_manuscript",
            f"cannot import {manuscript.name}: {suffix or 'no extension'} is not supported",
            hint="supported manuscript types are DOCX, PDF, MD and TXT",
        )
    try:
        resolved = manuscript.resolve()
    except OSError as exc:
        raise PaperchainError("manuscript_unreadable", f"cannot resolve {manuscript}: {exc}") from exc
    if not resolved.is_relative_to(project.root.resolve()):
        raise PaperchainError(
            "manuscript_outside_project",
            f"{manuscript} is outside the project folder",
            hint="copy the original into the project so the import hash can be checked later",
        )

    existing = ""
    if project.paper_md.exists():
        try:
            existing = project.paper_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            existing = ""
        if not force and "paperchain:template" not in existing:
            raise PaperchainError(
                "paper_exists",
                "Paper/paper.md already exists",
                hint="edit it directly, or pass --force to replace it from the original manuscript (the current draft is saved as paper.md.bak)",
            )

    backups: list[str] = []
    if force and existing and "paperchain:template" not in existing:
        saved = backup_path(project.paper_md)
        if saved is not None:
            backups.append(project.relative(saved))

    project.paper_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[Finding] = []
    if suffix in DOCX_SUFFIXES:
        text = _import_docx(resolved, project)
    elif suffix == ".pdf":
        text, warnings = _import_pdf(resolved)
    else:
        text = _import_plain(resolved)

    if not text.strip():
        raise PaperchainError(
            "manuscript_empty",
            f"the imported manuscript has no text: {manuscript.name}",
            hint="check that the file is not a scan and is not empty",
        )
    project.paper_md.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")

    # Pandoc creates the media folder even when the manuscript has no images.
    # A junction or symlink points at the cache and is never removed here.
    media = project.paper_media_dir
    if media.is_dir() and not is_link(media) and not any(media.iterdir()):
        try:
            media.rmdir()
        except OSError:
            pass

    digest = sha256_file(resolved)
    project.manifest.manuscript_path = rel_posix(resolved, project.root)
    project.manifest.manuscript_sha256 = digest
    project.manifest.manuscript_imported_at = now_iso()
    project.save()

    return {
        "source": project.relative(resolved),
        "paper": project.relative(project.paper_md),
        "sha256": digest,
        "words": word_count(text),
        "backups": backups,
        "warnings": warnings,
    }
