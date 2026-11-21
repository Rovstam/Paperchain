from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from .check import Report, run_check
from .citations import (
    indented_code_ranges,
    mask_code,
    parse_citations,
    render_markdown,
    scan_markdown,
)
from .errors import Finding, PaperchainError
from .library import bibliography_keys
from .manifest import Source
from .project import Project
from .reference_log import (
    append_event,
    last_build_fingerprint,
    read_events,
    reference_fingerprint,
    short,
)
from .util import human_bytes, is_link

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


def _is_link(path: Path) -> bool:
    """True for a POSIX symlink or a Windows directory junction."""
    return is_link(path)


def _materialize_media(project: Project) -> Path | None:
    """Copy cache media inside Paper/ for the build.

    The media folder is normally a junction or symlink to the cache. Pandoc
    reads the temporary real copy; the cache remains the source and the copy
    is deleted after the build.
    """
    media = project.paper_media_dir
    if not media.exists() or not _is_link(media):
        return None
    source = project.media_cache_dir
    if not source.is_dir():
        return None
    target = project.paper_dir / ".paperchain-build-media"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def _rewrite_media_links(text: str, project: Project, materialized: Path | None) -> str:
    def rewrite(segment: str) -> str:
        # Old imports wrote absolute paths; make them relative to Paper/ first.
        segment = re.sub(re.escape(str(project.paper_dir)) + r"[\\/]+", "", segment)
        # `./media/x.png` names the same file as `media/x.png`. Normalise it so
        # the materialised folder is found and build does not reject a valid image.
        segment = re.sub(r"(\]\(\s*<?)\./", r"\1", segment)
        segment = re.sub(r"""(src\s*=\s*["'])\./""", r"\1", segment)
        if materialized is None:
            return segment
        replacement = materialized.name
        segment = segment.replace("](media/", f"]({replacement}/")
        segment = segment.replace("](<media/", f"](<{replacement}/")
        segment = segment.replace('src="media/', f'src="{replacement}/')
        segment = segment.replace("src='media/", f"src='{replacement}/")
        return segment

    # Code spans, fences and indented code show text, not an image, so leave
    # them byte-for-byte alone; only the surrounding Markdown is rewritten.
    ranges: list[tuple[int, int]] = []
    scan_markdown(text, ranges)
    ranges.extend(indented_code_ranges(text))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    if not merged:
        return rewrite(text)
    parts: list[str] = []
    position = 0
    for start, end in merged:
        parts.append(rewrite(text[position:start]))
        parts.append(text[start:end])
        position = end
    parts.append(rewrite(text[position:]))
    return "".join(parts)


def _mask_code_blocks(text: str) -> str:
    """Mask fences, inline code, comments and indented code for resource checks."""
    masked = mask_code(text)
    ranges = indented_code_ranges(text)
    if not ranges:
        return masked
    buffer = list(masked)
    for start, end in ranges:
        for position in range(start, end):
            if buffer[position] not in "\r\n":
                buffer[position] = " "
    return "".join(buffer)


_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(((?:[^()]|\([^()]*\))*)\)")
_HTML_IMAGE_RE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_TITLE_SUFFIX_RE = re.compile(r"""\s+(?:"[^"]*"|'[^']*'|\([^)]*\))$""")


def _clean_target(raw: str) -> str:
    """The image target as written, without <...> or a trailing title."""
    value = raw.strip()
    if value.startswith("<"):
        end = value.find(">")
        return value[1:end] if end != -1 else value[1:]
    # `path "title"` and `path 'title'` keep a title outside the destination.
    # A bare space is part of the filename, so it is not split on.
    return _TITLE_SUFFIX_RE.sub("", value).strip()


def _image_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in _IMAGE_RE.finditer(text):
        path = _clean_target(match.group(1))
        if path:
            paths.append(path)
    paths.extend(match.group(1) for match in _HTML_IMAGE_RE.finditer(text))
    return paths


_SCHEME_RE = re.compile(r"(?i)^(https?|ftp|file|data):")
_CITEPROC_MISSING_RE = re.compile(r"(?i)Citeproc: citation (.+?) not found")


def _unresolved_citations(output: str) -> list[str]:
    """Citation keys Pandoc reported as not found, sorted and de-duplicated."""
    return sorted(dict.fromkeys(match.strip() for match in _CITEPROC_MISSING_RE.findall(output)))


def _media_cache_empty(project: Project) -> bool:
    try:
        cache = project.media_cache_dir
        return not cache.is_dir() or not any(cache.iterdir())
    except OSError:
        return False


def _image_hint(project: Project, raw: str) -> str:
    under_media = raw.replace("\\", "/").lstrip("./").startswith("media/")
    if under_media and (_is_link(project.paper_media_dir) or _media_cache_empty(project)):
        return (
            "Paper/media is empty or its cache was cleared; "
            "run `paperchain import --force` to extract the images again, or restore the cache"
        )
    return "put images under Paper/ (for example Paper/media/) and use a relative path"


_DATA_IMAGE_RE = re.compile(r"(?i)^data:image/[a-z0-9.+-]+(?:;[^,]*)?,")


def _validate_resource(raw: str, project: Project) -> None:
    """Reject an image target Pandoc would read from outside Paper/ or the web."""
    paper_root = project.paper_dir.resolve()
    if raw.lower().startswith("data:"):
        # An image data URI is self-contained; it cannot read a file or fetch a
        # URL. Other data: payloads are still rejected.
        if _DATA_IMAGE_RE.match(raw):
            return
        raise PaperchainError(
            "pandoc_resource_blocked",
            "only image data: URIs are embedded",
            hint="use a data:image/... URI, or put the image under Paper/ and use a relative path",
        )
    if _SCHEME_RE.match(raw):
        raise PaperchainError(
            "pandoc_resource_blocked",
            "remote or file-url images are not embedded",
            hint=f"{raw!r} is not a local image under Paper/; download it and use a relative path",
        )
    path = Path(raw)
    if path.is_absolute():
        raise PaperchainError(
            "pandoc_resource_blocked",
            "absolute image paths are not embedded",
            hint=f"{raw!r} must be relative to Paper/; re-import the manuscript or fix the link",
        )
    # Pandoc decodes %20 before it reads the file; try the literal name first.
    for candidate in (raw, unquote(raw)):
        resolved = (project.paper_dir / candidate).resolve()
        if resolved.is_relative_to(paper_root) and resolved.is_file():
            return
    resolved = (project.paper_dir / raw).resolve()
    if not resolved.is_relative_to(paper_root):
        raise PaperchainError(
            "pandoc_resource_blocked",
            f"image {raw!r} resolves outside Paper/",
            hint=_image_hint(project, raw)
            + "; a symlink or junction that leaves Paper/ is not read",
        )
    raise PaperchainError(
        "pandoc_resource_blocked",
        f"image {raw!r} is missing",
        hint=_image_hint(project, raw),
    )


def _check_resources(text: str, project: Project) -> None:
    """Validate inline Markdown and HTML image targets before Pandoc runs.

    Build also validates Pandoc's own AST, which sees reference-style images
    and Pandoc's real path parsing. This pass keeps the check usable without
    running Pandoc (tests, doctor) and catches raw HTML.
    """
    for raw in _image_paths(text):
        _validate_resource(raw, project)


def _ast_image_targets(executable: str, path: Path, project: Project) -> list[str]:
    """Every image target Pandoc will actually try to read.

    A Markdown regex cannot see `![alt][id]`, bracketed alt text or Pandoc's
    own percent-decoding. Let Pandoc parse the file and walk the Image nodes.
    """
    completed = subprocess.run(
        [executable, str(path), "--from", "markdown+smart", "--to", "json"],
        cwd=str(project.paper_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PaperchainError(
            "pandoc_failed",
            f"pandoc could not parse the draft (exit code {completed.returncode})",
            hint=detail[-800:] or "run pandoc by hand in Paper/ to see the full error",
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []

    targets: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            kind = node.get("t")
            if kind == "Image":
                content = node.get("c")
                try:
                    target = content[2][0]
                except (IndexError, KeyError, TypeError):
                    target = ""
                if isinstance(target, str) and target:
                    targets.append(target)
            elif kind in {"RawInline", "RawBlock"}:
                content = node.get("c")
                if isinstance(content, list) and len(content) == 2 and isinstance(content[1], str):
                    targets.extend(_HTML_IMAGE_RE.findall(content[1]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    return targets


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

    if project.manifest.style:
        # A configured style is a promise about the output. --force may skip
        # reference errors, but it must not turn Vancouver into author-year.
        # Check this before Pandoc: a missing style is a configuration error,
        # not a missing-tool error.
        blocking = [
            finding
            for finding in report.errors
            if finding.code.startswith(("style_", "csl_", "bibliography_"))
        ]
        if blocking:
            raise PaperchainError(
                blocking[0].code,
                blocking[0].message,
                hint=blocking[0].hint or "run `paperchain check` for details",
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
    for source in project.manifest.sources:
        # A citation may use the internal key or the Zotero id; both resolve.
        if source.citation_key:
            sources[source.citation_key] = source
    original = project.paper_md.read_text(encoding="utf-8")

    bibliography_file = project.bibliography_path
    use_citeproc = bibliography_file is not None
    key_map = citation_key_map(project)
    if use_citeproc:
        cited: set[str] = set()
        for citation in parse_citations(original):
            if citation.error:
                continue
            cited.add(key_map.get(citation.key, citation.key))
        known = bibliography_keys(bibliography_file)
        missing = sorted(cited - known)
        if missing:
            raise PaperchainError(
                "citation_not_in_bibliography",
                f"{', '.join(missing)} is not in {project.relative(bibliography_file)}",
                hint="run `paperchain match` to map Zotero ids to sources, add the reference in Zotero and export CSL JSON again, or fix the citation key",
            )
        rendered = render_markdown_for_citeproc(original, key_map)
    else:
        rendered = render_markdown(original, sources)
        rendered += bibliography(original, sources)

    project.paper_dir.mkdir(parents=True, exist_ok=True)
    project.tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = project.tmp_dir / BUILD_FILENAME
    output = project.output_path
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        executable,
        str(temp_path.resolve()),
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

    materialized = _materialize_media(project)
    try:
        rendered = _rewrite_media_links(rendered, project, materialized)
        # Ignore image syntax inside code spans, fences and indented code:
        # Pandoc does not read it.
        _check_resources(_mask_code_blocks(rendered), project)
        temp_path.write_text(rendered, encoding="utf-8", newline="\n")
        # The regex cannot see `![alt][id]`, bracketed alt text or Pandoc's
        # percent-decoding. Pandoc's AST can, and it is what the writer reads.
        # Skip the extra parse for a draft with no image syntax at all.
        if "![" in rendered or "<img" in rendered.lower():
            for target in _ast_image_targets(executable, temp_path, project):
                _validate_resource(target, project)
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
        if materialized is not None:
            shutil.rmtree(materialized, ignore_errors=True)

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PaperchainError(
            "pandoc_failed",
            f"pandoc failed with exit code {completed.returncode}",
            hint=detail[-800:] or "run pandoc by hand in Paper/ to see the full error",
        )

    # Pandoc exits 0 when citeproc cannot resolve a key; it warns and prints the
    # raw key. A trailing . : / + - is punctuation to Pandoc, not part of the
    # key, so the DOCX can be unresolved even though check saw a matching id.
    unresolved = _unresolved_citations(completed.stderr or completed.stdout or "")
    if unresolved:
        raise PaperchainError(
            "citation_not_in_bibliography",
            "citeproc could not resolve: " + ", ".join(unresolved),
            hint="citation keys must start and end with a letter or digit; Pandoc does not treat a trailing . : / + - as part of the key",
        )

    # _check_resources rejects remote and outside-project images before Pandoc
    # runs. Some Pandoc versions still exit 0 after dropping a resource, so
    # the warning is promoted to a failure as a second line of defence.
    resource_warning = "Could not fetch resource" in (completed.stderr or "")
    if resource_warning:
        detail = (completed.stderr or "").strip()
        raise PaperchainError(
            "pandoc_resource_blocked",
            "a referenced image or file could not be embedded",
            hint=((detail[-800:] + "\n") if detail else "")
            + "put images under Paper/ (for example Paper/media/) and use a relative path; remote URLs are not fetched",
        )

    if not output.is_file():
        raise PaperchainError(
            "build_no_output",
            f"pandoc reported success but {project.relative(output)} was not created",
        )

    if use_citeproc and any(not citation.error for citation in parse_citations(original)):
        if not _docx_has_reference_list(output):
            raise PaperchainError(
                "bibliography_missing_from_output",
                "the document cites sources but contains no reference list",
                hint="a YAML metadata block such as suppress-bibliography can remove it anywhere in Paper/paper.md; delete that key and rebuild",
            )

    result.output = output
    fingerprint = reference_fingerprint(project.manifest)
    previous = last_build_fingerprint(read_events(project))
    if previous and fingerprint and previous != fingerprint:
        report.warnings.append(
            Finding(
                "reference_fingerprint_changed",
                f"the reference set differs from the last build ({short(previous)} -> {short(fingerprint)})",
                severity="warning",
                hint="expected after you add or replace references; otherwise ask the human to review `.paperchain/lock-log.jsonl`",
                data={"previous": previous, "current": fingerprint},
            )
        )
    append_event(project, "build", fingerprint=fingerprint, forced=bool(report.errors))
    return result


def _docx_has_reference_list(path: Path) -> bool:
    """True when the DOCX contains the reference list citeproc emits.

    citeproc marks each reference paragraph with the ``Bibliography`` style.
    It does not add a heading unless the CSL style or ``reference-section-title``
    asks for one. Matching ordinary prose for the word "references" let a
    suppressed list pass whenever the draft mentioned the word, so only the
    paragraph style counts.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return False
    return bool(re.search(r'<w:pStyle[^>]*w:val="Bibliography"', xml))


def _docx_text(path: Path) -> str:
    """Plain text runs from a DOCX, enough to see a reference-list heading."""
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


def citation_key_map(project: Project) -> dict[str, str]:
    """Map every way a source can be cited to the key citeproc knows.

    The internal key is filename-derived; the Zotero id is what citeproc
    matches. Both spellings resolve, and citeproc always receives the Zotero id.
    """
    mapping: dict[str, str] = {}
    for source in project.manifest.sources:
        key = project.manifest.citation_key_for(source)
        mapping[source.key] = key
        if source.citation_key:
            mapping[source.citation_key] = source.citation_key
    return mapping


def render_markdown_for_citeproc(text: str, keys: dict[str, str] | None = None) -> str:
    """Keep Pandoc citations, drop the verification quote, let citeproc format.

    `check` needs the quoted evidence; Pandoc's citation parser cannot read it.
    The page locator is preserved because Pandoc understands `[@key, p. 12]`.
    """
    rendered = text
    for citation in reversed(parse_citations(text)):
        if citation.error:
            continue
        body = f", {citation.locator()}" if citation.locator() else ""
        key = (keys or {}).get(citation.key, citation.key)
        replacement = f"[@{key}{body}]"
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
        "reference_fingerprint": reference_fingerprint(project.manifest),
    }
