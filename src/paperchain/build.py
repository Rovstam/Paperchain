from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .check import Report, run_check
from .citations import parse_citations, render_markdown
from .errors import Finding, PaperchainError
from .library import bibliography_keys
from .manifest import Source
from .project import Project
from .util import human_bytes

BUILD_FILENAME = ".paperchain.build.md"


@dataclass
class BuildResult:
    report: Report
    output: Path | None = None
    pandoc_version: str = ""
    warnings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.output is not None


def pandoc_version() -> str | None:
    executable = shutil.which("pandoc")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()[0].strip() if result.stdout else "pandoc"


def run_build(project: Project, force: bool = False) -> BuildResult:
    report = run_check(project, reextract=True)
    result = BuildResult(report=report)

    if report.errors and not force:
        return result

    if not project.paper_md.is_file():
        raise PaperchainError(
            "paper_missing",
            "Paper/paper.md does not exist",
            hint="create the draft before building",
        )

    executable = shutil.which("pandoc")
    if not executable:
        raise PaperchainError(
            "pandoc_missing",
            "pandoc is not installed or not on PATH",
            hint="install it from https://pandoc.org/installing.html, then run `paperchain doctor`",
        )
    version = pandoc_version() or "pandoc"
    result.pandoc_version = version

    sources = {source.key: source for source in project.manifest.sources}
    original = project.paper_md.read_text(encoding="utf-8")

    bibliography_file = project.bibliography_path
    use_citeproc = bibliography_file is not None
    if use_citeproc:
        cited = {
            citation.key
            for citation in parse_citations(original)
            if not citation.error
        }
        known = bibliography_keys(bibliography_file)
        missing = sorted(cited - known)
        if missing:
            raise PaperchainError(
                "citation_not_in_bibliography",
                f"{', '.join(missing)} is not in {project.relative(bibliography_file)}",
                hint="add the reference in Zotero and export CSL JSON again, or fix the citation key",
            )
        rendered = render_markdown_for_citeproc(original)
    else:
        rendered = render_markdown(original, sources)
        rendered += bibliography(original, sources)

    project.paper_dir.mkdir(parents=True, exist_ok=True)
    temp_path = project.paper_dir / BUILD_FILENAME
    output = project.output_path
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        executable,
        BUILD_FILENAME,
        "--from",
        "markdown+smart",
        "--to",
        "docx",
        "--output",
        str(output.resolve()),
    ]

    reference_doc = project.manifest.reference_doc.strip()
    if reference_doc:
        reference_path = project.root / reference_doc
        if not reference_path.is_file():
            raise PaperchainError(
                "reference_doc_missing",
                f"the Word style reference {reference_doc} does not exist",
                hint="fix [build] reference_doc in paper.toml, or remove the line to use pandoc defaults",
            )
        command += ["--reference-doc", str(reference_path.resolve())]

    if use_citeproc and bibliography_file is not None:
        command += [
            "--citeproc",
            "--bibliography",
            str(bibliography_file),
        ]
        csl = project.csl_path
        if csl is not None:
            if not csl.is_file():
                raise PaperchainError(
                    "csl_missing",
                    f"the CSL style {project.manifest.csl} does not exist",
                    hint="fix [build] csl in paper.toml, or remove the line to use pandoc's default style",
                )
            command += ["--csl", str(csl)]

    try:
        temp_path.write_text(rendered, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            command,
            cwd=str(project.paper_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        temp_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PaperchainError(
            "pandoc_failed",
            f"pandoc failed with exit code {completed.returncode}",
            hint=detail[-800:] or "run pandoc by hand in Paper/ to see the full error",
        )

    if not output.is_file():
        raise PaperchainError(
            "build_no_output",
            f"pandoc reported success but {project.relative(output)} was not created",
        )

    result.output = output
    return result


def render_markdown_for_citeproc(text: str) -> str:
    """Keep Pandoc citations, drop the verification quote, let citeproc format.

    `check` needs the quoted evidence; Pandoc's citation parser cannot read it.
    The page locator is preserved because Pandoc understands `[@key, p. 12]`.
    """
    rendered = text
    for citation in reversed(parse_citations(text)):
        if citation.error:
            continue
        body = f", {citation.locator()}" if citation.locator() else ""
        replacement = f"[@{citation.key}{body}]"
        rendered = rendered[: citation.start] + replacement + rendered[citation.end :]
    return rendered


REFERENCES_HEADING_RE = re.compile(r"^#{1,6}\s+References\s*$", re.IGNORECASE | re.MULTILINE)


def bibliography(text: str, sources: dict[str, Source]) -> str:
    """Append a reference list for cited sources, unless the author wrote one."""
    if REFERENCES_HEADING_RE.search(text):
        return ""

    cited: list[str] = []
    for citation in parse_citations(text):
        if not citation.error and citation.key in sources and citation.key not in cited:
            cited.append(citation.key)
    if not cited:
        return ""

    entries: list[str] = []
    for key in cited:
        source = sources[key]
        entry = source.authors.strip() or source.title.strip() or key
        if source.year:
            entry = f"{entry} ({source.year})"
        if source.title.strip() and source.title.strip() != entry:
            entry = f"{entry}. {source.title.strip()}"
        if not source.authors and not source.title:
            entry = key
        entries.append(f"- {entry.rstrip('.')}.")

    return "\n\n## References\n\n" + "\n".join(entries) + "\n"


def describe_output(result: BuildResult, project: Project) -> dict:
    assert result.output is not None
    return {
        "output": project.relative(result.output),
        "bytes": result.output.stat().st_size,
        "size": human_bytes(result.output.stat().st_size),
        "pandoc": result.pandoc_version,
        "warnings": len(result.report.warnings),
    }
