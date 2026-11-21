from __future__ import annotations

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib  # type: ignore[no-redef]

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .errors import PaperchainError
from .util import now_iso, slugify, write_text as write_text_file

MANIFEST_NAME = "paper.toml"


def toml_string(value: str) -> str:
    out = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{out}"'


def _int_field(data: dict[str, Any], name: str, key: str) -> int:
    value = data.get(name, 0)
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise PaperchainError(
            "manifest_invalid",
            f"{name} for source {key!r} must be a number",
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value.strip())
    raise PaperchainError(
        "manifest_invalid",
        f"{name} for source {key!r} must be a number, not {value!r}",
        hint=f"edit {MANIFEST_NAME} by hand, or delete the entry and run `paperchain convert`",
    )


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PaperchainError(
            "manifest_invalid",
            f"[{name}] in {MANIFEST_NAME} must be a TOML table",
        )
    return value


def _string(
    data: dict[str, Any], name: str, *, owner: str = MANIFEST_NAME
) -> str:
    value = data.get(name, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PaperchainError(
            "manifest_invalid",
            f"{name} in {owner} must be a string, not {value!r}",
        )
    return value


@dataclass
class Source:
    key: str
    path: str
    # The Better BibTeX / Zotero id used in paper.md. Empty means "same as key".
    # `key` stays the internal, filename-derived name so hashes and text files
    # never move when a Zotero export is re-imported.
    citation_key: str = ""
    title: str = ""
    authors: str = ""
    year: int | None = None
    sha256: str = ""
    size: int = 0
    pages: int = 0
    text_sha256: str = ""
    converter: str = ""
    converted_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Source":
        key = _string(data, "key", owner="a [[sources]] entry").strip()
        path = _string(data, "path", owner="a [[sources]] entry").strip()
        if not key or not path:
            raise PaperchainError(
                "manifest_invalid",
                "every [[sources]] entry needs a key and a path",
                hint=f"edit {MANIFEST_NAME} by hand, or delete the entry and run `paperchain convert`",
            )
        year = data.get("year")
        if isinstance(year, str) and year.strip().isdigit():
            year = int(year.strip())
        elif year is None or year == "":
            year = None
        elif isinstance(year, bool) or not isinstance(year, int):
            raise PaperchainError(
                "manifest_invalid",
                f"year for source {key!r} must be a number",
                hint=f"edit {MANIFEST_NAME} by hand, or delete the entry and run `paperchain convert`",
            )
        return cls(
            key=key,
            path=path,
            citation_key=_string(data, "citation_key", owner=f"source {key!r}").strip(),
            title=_string(data, "title", owner=f"source {key!r}"),
            authors=_string(data, "authors", owner=f"source {key!r}"),
            year=year,
            sha256=_string(data, "sha256", owner=f"source {key!r}"),
            size=_int_field(data, "size", key),
            pages=_int_field(data, "pages", key),
            text_sha256=_string(data, "text_sha256", owner=f"source {key!r}"),
            converter=_string(data, "converter", owner=f"source {key!r}"),
            converted_at=_string(data, "converted_at", owner=f"source {key!r}"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "citation_key": self.citation_key,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "sha256": self.sha256,
            "size": self.size,
            "pages": self.pages,
            "text_sha256": self.text_sha256,
            "converter": self.converter,
            "converted_at": self.converted_at,
        }


@dataclass
class Manifest:
    title: str = ""
    slug: str = ""
    project_id: str = ""
    created: str = ""
    locked_at: str = ""
    build_output: str = ""
    reference_doc: str = ""
    bibliography: str = ""
    csl: str = ""
    style: str = ""
    bibliography_sha256: str = ""
    csl_sha256: str = ""
    manuscript_path: str = ""
    manuscript_sha256: str = ""
    manuscript_imported_at: str = ""
    require_quotes: bool = False
    sources: list[Source] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    # -- loading ---------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if not path.is_file():
            raise PaperchainError(
                "manifest_missing",
                f"no {MANIFEST_NAME} in {path.parent}",
                hint="run `paperchain init` here, or pass --project <paper folder>",
            )
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise PaperchainError("manifest_invalid", f"cannot read {path}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise PaperchainError(
                "manifest_invalid",
                f"{path.name} is not valid TOML: {exc}",
                hint="TOML strings need double quotes; check for a stray comment or bracket",
            ) from exc

        version = data.get("schema_version", SCHEMA_VERSION)
        if isinstance(version, bool) or not isinstance(version, int):
            raise PaperchainError(
                "manifest_invalid",
                "schema_version in paper.toml must be an integer",
            )
        if version > SCHEMA_VERSION:
            raise PaperchainError(
                "manifest_version",
                f"{path.name} was written by a newer paperchain (schema {version!r})",
                hint="upgrade paperchain, or restore the file from version control",
            )

        build = _table(data, "build")
        check = _table(data, "check")
        manuscript = _table(data, "manuscript")
        raw_sources = data.get("sources", [])
        if raw_sources is None:
            raw_sources = []
        if not isinstance(raw_sources, list) or not all(isinstance(s, dict) for s in raw_sources):
            raise PaperchainError("manifest_invalid", "[[sources]] must be a list of tables")

        require_quotes = check.get("require_quotes", False)
        if not isinstance(require_quotes, bool):
            raise PaperchainError(
                "manifest_invalid",
                "check.require_quotes in paper.toml must be true or false",
            )

        return cls(
            title=_string(data, "title"),
            slug=_string(data, "slug"),
            project_id=_string(data, "project_id"),
            created=_string(data, "created"),
            locked_at=_string(data, "locked_at"),
            build_output=_string(build, "output", owner="[build]"),
            reference_doc=_string(build, "reference_doc", owner="[build]"),
            bibliography=_string(build, "bibliography", owner="[build]"),
            csl=_string(build, "csl", owner="[build]"),
            style=_string(build, "style", owner="[build]").strip().lower(),
            bibliography_sha256=_string(
                build, "bibliography_sha256", owner="[build]"
            ),
            csl_sha256=_string(build, "csl_sha256", owner="[build]"),
            manuscript_path=_string(manuscript, "path", owner="[manuscript]"),
            manuscript_sha256=_string(
                manuscript, "sha256", owner="[manuscript]"
            ),
            manuscript_imported_at=_string(
                manuscript, "imported_at", owner="[manuscript]"
            ),
            require_quotes=require_quotes,
            sources=[Source.from_dict(item) for item in raw_sources],
            schema_version=version,
        )

    # -- saving ----------------------------------------------------------

    def save(self, path: Path) -> None:
        lines: list[str] = [f"schema_version = {self.schema_version}"]
        if self.title:
            lines.append(f"title = {toml_string(self.title)}")
        if self.slug:
            lines.append(f"slug = {toml_string(self.slug)}")
        if self.project_id:
            lines.append(f"project_id = {toml_string(self.project_id)}")
        if self.created:
            lines.append(f"created = {toml_string(self.created)}")
        if self.locked_at:
            lines.append(f"locked_at = {toml_string(self.locked_at)}")

        if (
            self.build_output
            or self.reference_doc
            or self.bibliography
            or self.csl
            or self.style
            or self.bibliography_sha256
            or self.csl_sha256
        ):
            lines += ["", "[build]"]
            if self.build_output:
                lines.append(f"output = {toml_string(self.build_output)}")
            if self.reference_doc:
                lines.append(f"reference_doc = {toml_string(self.reference_doc)}")
            if self.bibliography:
                lines.append(f"bibliography = {toml_string(self.bibliography)}")
            if self.csl:
                lines.append(f"csl = {toml_string(self.csl)}")
            if self.style:
                lines.append(f"style = {toml_string(self.style)}")
            if self.bibliography_sha256:
                lines.append(f"bibliography_sha256 = {toml_string(self.bibliography_sha256)}")
            if self.csl_sha256:
                lines.append(f"csl_sha256 = {toml_string(self.csl_sha256)}")

        if self.manuscript_path or self.manuscript_sha256 or self.manuscript_imported_at:
            lines += ["", "[manuscript]"]
            if self.manuscript_path:
                lines.append(f"path = {toml_string(self.manuscript_path)}")
            if self.manuscript_sha256:
                lines.append(f"sha256 = {toml_string(self.manuscript_sha256)}")
            if self.manuscript_imported_at:
                lines.append(f"imported_at = {toml_string(self.manuscript_imported_at)}")

        if self.require_quotes:
            lines += ["", "[check]", "require_quotes = true"]

        for source in self.sources:
            lines += ["", "[[sources]]"]
            lines.append(f"key = {toml_string(source.key)}")
            lines.append(f"path = {toml_string(source.path)}")
            if source.citation_key:
                lines.append(f"citation_key = {toml_string(source.citation_key)}")
            for field_name in ("title", "authors"):
                value = getattr(source, field_name)
                if value:
                    lines.append(f"{field_name} = {toml_string(value)}")
            if source.year is not None:
                lines.append(f"year = {source.year}")
            for field_name in (
                "sha256",
                "size",
                "pages",
                "text_sha256",
                "converter",
                "converted_at",
            ):
                value = getattr(source, field_name)
                if value:
                    lines.append(f"{field_name} = {value if isinstance(value, int) else toml_string(value)}")

        write_text_file(path, "\n".join(lines) + "\n")

    # -- helpers ---------------------------------------------------------

    @property
    def source_keys(self) -> list[str]:
        return [source.key for source in self.sources]

    def source(self, key: str) -> Source | None:
        for source in self.sources:
            if source.key == key:
                return source
        return None

    def source_for_citation(self, key: str) -> Source | None:
        """Resolve a citation key to its source.

        `citation_key` wins when set, so a Zotero id such as `Amaeze2021`
        works without renaming the internal, filename-derived key. The
        internal key stays a valid fallback for projects without Zotero.
        """
        for source in self.sources:
            if source.citation_key and source.citation_key == key:
                return source
        return self.source(key)

    @staticmethod
    def citation_key_for(source: Source) -> str:
        return source.citation_key or source.key

    @property
    def citation_keys(self) -> list[str]:
        return [self.citation_key_for(source) for source in self.sources]

    def upsert(self, source: Source) -> None:
        for index, existing in enumerate(self.sources):
            if existing.key == source.key:
                self.sources[index] = source
                return
        self.sources.append(source)

    def remove(self, key: str) -> None:
        self.sources = [source for source in self.sources if source.key != key]

    def output_path(self) -> str:
        return self.build_output or f"Output/{self.slug or 'paper'}.docx"


def new_manifest(title: str, style: str = "", require_quotes: bool = False) -> Manifest:
    slug = slugify(title)
    style = style.strip().lower()
    return Manifest(
        title=title,
        slug=slug,
        project_id=uuid.uuid4().hex,
        created=now_iso(),
        build_output=f"Output/{slug}.docx",
        style=style,
        bibliography="References/library.json" if style else "",
        csl=f"styles/{style}.csl" if style else "",
        require_quotes=require_quotes,
    )
