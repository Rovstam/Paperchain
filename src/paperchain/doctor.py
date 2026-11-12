from __future__ import annotations

import shutil
import sys
from dataclasses import asdict, dataclass

from . import __version__
from .build import pandoc_version
from .check import run_check
from .errors import PaperchainError
from .project import Project
from .util import sha256_file

MIN_PYTHON = (3, 10)


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str
    hint: str | None = None


def run_doctor(project: Project) -> dict:
    checks: list[Check] = []

    if sys.version_info >= MIN_PYTHON:
        checks.append(Check("python", "ok", f"{sys.version.split()[0]} ({sys.executable})"))
    else:
        checks.append(
            Check("python", "fail", sys.version.split()[0], "paperchain needs Python 3.10 or newer")
        )

    try:
        import pypdf

        checks.append(Check("pypdf", "ok", pypdf.__version__))
    except ImportError:
        checks.append(
            Check("pypdf", "fail", "not installed", "pip install pypdf")
        )

    version = pandoc_version()
    if version:
        checks.append(Check("pandoc", "ok", version))
    else:
        checks.append(
            Check(
                "pandoc",
                "warn",
                "not found on PATH",
                "needed by `paperchain build`; install from https://pandoc.org/installing.html",
            )
        )

    tesseract = shutil.which("tesseract")
    checks.append(
        Check(
            "tesseract",
            "ok" if tesseract else "warn",
            tesseract or "not found (optional)",
            None if tesseract else "only needed for scanned PDFs; install tesseract and ocrmypdf if you have scans",
        )
    )

    paper = project.paper_md
    checks.append(
        Check(
            "paper.md",
            "ok" if paper.is_file() else "fail",
            project.relative(paper) if paper.is_file() else "missing",
            None if paper.is_file() else "create Paper/paper.md",
        )
    )

    manifest = project.manifest
    checks.append(
        Check(
            "cache",
            "ok",
            str(project.cache_dir),
            "generated text and build temp live here, outside the project",
        )
    )

    if manifest.manuscript_path:
        manuscript = project.root / manifest.manuscript_path
        if not manuscript.is_file():
            checks.append(
                Check(
                    "manuscript",
                    "fail",
                    f"{manifest.manuscript_path} is missing",
                    "restore the original, or run `paperchain import` again",
                )
            )
        elif not manifest.manuscript_sha256:
            checks.append(
                Check(
                    "manuscript",
                    "fail",
                    f"{manifest.manuscript_path} has no recorded hash",
                    "run `paperchain import --force` (the current draft is saved as paper.md.bak)",
                )
            )
        elif sha256_file(manuscript) != manifest.manuscript_sha256:
            checks.append(
                Check(
                    "manuscript",
                    "fail",
                    f"{manifest.manuscript_path} changed since import",
                    "run `paperchain import --force` (the current draft is saved as paper.md.bak), then review Paper/paper.md",
                )
            )
        else:
            checks.append(Check("manuscript", "ok", f"{manifest.manuscript_path} (unchanged since import)"))
    else:
        try:
            manuscript = project.find_manuscript()
        except PaperchainError:
            manuscript = None
        checks.append(
            Check(
                "manuscript",
                "warn",
                "not imported" if manuscript is None else f"{project.relative(manuscript)} is not imported",
                "run `paperchain import` to create Paper/paper.md from the original",
            )
        )

    if not manifest.sources:
        checks.append(
            Check("references", "warn", "no sources converted", "put PDFs or DOCX under References/ and run `paperchain convert`")
        )
    elif manifest.locked_at:
        checks.append(
            Check("references", "ok", f"{len(manifest.sources)} source(s), locked {manifest.locked_at}")
        )
    else:
        checks.append(
            Check(
                "references",
                "warn",
                f"{len(manifest.sources)} source(s), not locked",
                "run `paperchain lock` once the reference set is final",
            )
        )

    adapter_candidates = [
        "opencode.json",
        ".claude/settings.json",
        ".codex/config.toml",
    ]
    found = [name for name in adapter_candidates if (project.root / name).exists()]
    if found:
        checks.append(Check("agent adapter", "ok", ", ".join(found)))
    else:
        checks.append(
            Check(
                "agent adapter",
                "warn",
                "none detected",
                "AGENTS.md still works on its own; re-run `paperchain init --force --agent opencode` to add one (the draft is saved as paper.md.bak)",
            )
        )

    attributes = project.root / ".gitattributes"
    checks.append(
        Check(
            "line endings",
            "ok" if attributes.is_file() else "warn",
            ".gitattributes present" if attributes.is_file() else "missing",
            None if attributes.is_file() else "without it, Windows may rewrite files and trip the hash check",
        )
    )

    report = run_check(project, include_candidates=False)
    if report.errors:
        checks.append(
            Check(
                "check",
                "fail",
                f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)",
                "run `paperchain check` for the details",
            )
        )
    else:
        checks.append(
            Check(
                "check",
                "warn" if report.warnings else "ok",
                f"{report.stats.get('quotes_verified', 0)} quote(s) verified, {len(report.warnings)} warning(s)",
            )
        )

    failed = [check for check in checks if check.status == "fail"]
    return {
        "ok": not failed,
        "version": __version__,
        "checks": [asdict(check) for check in checks],
        "data": {
            "project": str(project.root),
            "sources": len(manifest.sources),
            "cache": {
                "root": str(project.cache_dir),
                "text": str(project.text_dir),
                "index": str(project.text_dir / "INDEX.md"),
                "media": str(project.media_cache_dir),
                "tmp": str(project.tmp_dir),
            },
        },
    }
