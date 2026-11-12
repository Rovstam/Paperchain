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


@dataclass
class Source:
    key: str
    path: str
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
        key = str(data.get("key", "")).strip()
        path = str(data.get("path", "")).strip()
        if not key or not path:
            raise PaperchainError(
                "manifest_invalid",
                "every [[sources]] entry needs a key and a path",
                hint=f"edit {MANIFEST_NAME} by hand, or delete the entry and run `paperchain convert`",
            )
        year = data.get("year")
        if isinstance(year, str) and year.strip().isdigit():
            year = int(year.strip())
        if not isinstance(year, int):
            year = None
        return cls(
            key=key,
            path=path,
            title=str(data.get("title", "") or ""),
            authors=str(data.get("authors", "") or ""),
            year=year,
            sha256=str(data.get("sha256", "") or ""),
            size=_int_field(data, "size", key),
            pages=_int_field(data, "pages", key),
            text_sha256=str(data.get("text_sha256", "") or ""),
            converter=str(data.get("converter", "") or ""),
            converted_at=str(data.get("converted_at", "") or ""),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
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
        if not isinstance(version, int) or version > SCHEMA_VERSION:
            raise PaperchainError(
                "manifest_version",
                f"{path.name} was written by a newer paperchain (schema {version!r})",
                hint="upgrade paperchain, or restore the file from version control",
            )

        build = data.get("build", {}) or {}
        check = data.get("check", {}) or {}
        manuscript = data.get("manuscript", {}) or {}
        raw_sources = data.get("sources", []) or []
        if not isinstance(raw_sources, list) or not all(isinstance(s, dict) for s in raw_sources):
            raise PaperchainError("manifest_invalid", "[[sources]] must be a list of tables")

        return cls(
            title=str(data.get("title", "") or ""),
            slug=str(data.get("slug", "") or ""),
            project_id=str(data.get("project_id", "") or ""),
            created=str(data.get("created", "") or ""),
            locked_at=str(data.get("locked_at", "") or ""),
            build_output=str(build.get("output", "") or ""),
            reference_doc=str(build.get("reference_doc", "") or ""),
            bibliography=str(build.get("bibliography", "") or ""),
            csl=str(build.get("csl", "") or ""),
            manuscript_path=str(manuscript.get("path", "") or ""),
            manuscript_sha256=str(manuscript.get("sha256", "") or ""),
            manuscript_imported_at=str(manuscript.get("imported_at", "") or ""),
            require_quotes=bool(check.get("require_quotes", False)),
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

        if self.build_output or self.reference_doc or self.bibliography or self.csl:
            lines += ["", "[build]"]
            if self.build_output:
                lines.append(f"output = {toml_string(self.build_output)}")
            if self.reference_doc:
                lines.append(f"reference_doc = {toml_string(self.reference_doc)}")
            if self.bibliography:
                lines.append(f"bibliography = {toml_string(self.bibliography)}")
            if self.csl:
                lines.append(f"csl = {toml_string(self.csl)}")

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


def new_manifest(title: str) -> Manifest:
    slug = slugify(title)
    return Manifest(
        title=title,
        slug=slug,
        project_id=uuid.uuid4().hex,
        created=now_iso(),
        build_output=f"Output/{slug}.docx",
    )
