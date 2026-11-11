from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .errors import Finding, PaperchainError

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Extraction:
    pages: list[str]
    converter: str
    warnings: list[Finding] = field(default_factory=list)
    page_map_estimated: bool = False
    title: str = ""
    authors: str = ""

    @property
    def page_count(self) -> int:
        return len(self.pages)


def extract(path: Path) -> Extraction:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix in {".txt", ".md"}:
        return _extract_plain(path)
    raise PaperchainError(
        "unsupported_type",
        f"cannot read {path.name}: {suffix or 'no extension'} is not supported",
        hint="supported inputs are PDF, DOCX, TXT and MD",
    )


def _extract_pdf(path: Path) -> Extraction:
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - pypdf is a hard dependency
        raise PaperchainError(
            "missing_dependency",
            "pypdf is required to read PDF files",
            hint="pip install pypdf",
        ) from exc

    warnings: list[Finding] = []
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception as exc:
        raise PaperchainError(
            "pdf_unreadable",
            f"cannot open {path.name}: {exc}",
            hint="the file may be corrupt or password protected",
        ) from exc

    if reader.is_encrypted:
        unlocked = False
        try:
            unlocked = bool(reader.decrypt(""))
        except Exception:
            unlocked = False
        if not unlocked:
            raise PaperchainError(
                "pdf_encrypted",
                f"{path.name} is password protected",
                hint="export an unlocked copy, or ask the human for the password",
            )

    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        text = ""
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except TypeError:
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                warnings.append(
                    Finding(
                        "pdf_page_unreadable",
                        f"page {number} could not be read: {exc}",
                        severity="warning",
                        file=path.name,
                        line=number,
                    )
                )
        except Exception as exc:
            warnings.append(
                Finding(
                    "pdf_page_unreadable",
                    f"page {number} could not be read: {exc}",
                    severity="warning",
                    file=path.name,
                    line=number,
                )
            )
        pages.append(text)

    if not pages:
        raise PaperchainError("pdf_empty", f"{path.name} has no pages")

    if not any(page.strip() for page in pages):
        raise PaperchainError(
            "pdf_no_text",
            f"{path.name} contains no extractable text",
            hint="it is probably a scan; run OCR first (for example `ocrmypdf in.pdf out.pdf`)",
        )

    empty_pages = [str(i) for i, page in enumerate(pages, 1) if not page.strip()]
    if empty_pages:
        warnings.append(
            Finding(
                "pdf_blank_pages",
                f"{len(empty_pages)} page(s) produced no text: {', '.join(empty_pages[:10])}",
                severity="warning",
                file=path.name,
                hint="scanned pages need OCR; quotes cannot be verified against them",
            )
        )

    title, authors = _pdf_metadata(reader)
    return Extraction(
        pages=pages,
        converter=f"pypdf {pypdf.__version__}",
        warnings=warnings,
        title=title,
        authors=authors,
    )


def _clean_metadata(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower().endswith((".pdf", ".docx")):
        return ""
    return " ".join(text.split())


def _pdf_metadata(reader) -> tuple[str, str]:
    meta = getattr(reader, "metadata", None)
    if meta is None:
        return "", ""
    try:
        title = _clean_metadata(meta.title)
    except Exception:
        title = ""
    try:
        authors = _clean_metadata(meta.author)
    except Exception:
        authors = ""
    return title, authors


def _extract_docx(path: Path) -> Extraction:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
            names = set(archive.namelist())
    except (zipfile.BadZipFile, KeyError) as exc:
        raise PaperchainError(
            "docx_unreadable",
            f"cannot read {path.name}: not a Word document",
            hint="save or export the file as .docx again",
        ) from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise PaperchainError("docx_unreadable", f"{path.name} has invalid XML: {exc}") from exc

    body = root.find(f"{W}body")
    if body is None:
        raise PaperchainError("docx_empty", f"{path.name} has no document body")

    paragraphs: list[str] = []
    for paragraph in body.iter(f"{W}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{W}tab":
                parts.append("\t")
            elif node.tag in {f"{W}br", f"{W}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    if not paragraphs:
        raise PaperchainError(
            "docx_empty",
            f"{path.name} contains no text",
            hint="Word files made only of images need OCR or a text export",
        )

    warnings: list[Finding] = []
    if "word/footnotes.xml" in names:
        warnings.append(
            Finding(
                "docx_footnotes_ignored",
                "footnotes are not extracted from .docx in this version",
                severity="warning",
                file=path.name,
                hint="move any source text you need to cite into the body",
            )
        )

    title, authors = _docx_metadata(path)
    # Word has no fixed pages, so the whole document is page 1.
    return Extraction(
        pages=["\n".join(paragraphs)],
        converter="docx (stdlib)",
        warnings=warnings,
        page_map_estimated=True,
        title=title,
        authors=authors,
    )


DC = "{http://purl.org/dc/elements/1.1/}"


def _docx_metadata(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            if "docProps/core.xml" not in archive.namelist():
                return "", ""
            root = ElementTree.fromstring(archive.read("docProps/core.xml"))
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError):
        return ""
    title_node = root.find(f"{DC}title")
    author_node = root.find(f"{DC}creator")
    return (
        _clean_metadata(title_node.text if title_node is not None else ""),
        _clean_metadata(author_node.text if author_node is not None else ""),
    )


def _extract_plain(path: Path) -> Extraction:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
        return Extraction(
            pages=[text],
            converter="plain text",
            warnings=[
                Finding(
                    "encoding_replaced",
                    f"{path.name} is not valid UTF-8; some characters were replaced",
                    severity="warning",
                    file=path.name,
                    hint="save the file as UTF-8 so quotes match exactly",
                )
            ],
            page_map_estimated=True,
        )
    return Extraction(pages=[text], converter="plain text", page_map_estimated=True)


PAGE_MARKER = "===== PAGE {number} ====="


def render_text_file(key: str, original_name: str, extraction: Extraction) -> str:
    header = [
        f"# source: {original_name}",
        f"# key: {key}",
        f"# pages: {extraction.page_count}",
        f"# converter: {extraction.converter}",
    ]
    if extraction.page_map_estimated:
        header.append("# note: page numbers are estimated (no fixed pages in this format)")
    chunks = ["\n".join(header)]
    for number, text in enumerate(extraction.pages, start=1):
        chunks.append(PAGE_MARKER.format(number=number))
        chunks.append(text.rstrip())
    return "\n\n".join(chunks) + "\n"


def build_payload(
    key: str,
    original_rel: str,
    extraction: Extraction,
    source_sha256: str,
    size: int,
    converted_at: str,
) -> dict:
    return {
        "schema_version": 1,
        "key": key,
        "original": original_rel,
        "sha256": source_sha256,
        "size": size,
        "pages": [{"n": number, "text": text} for number, text in enumerate(extraction.pages, start=1)],
        "converter": extraction.converter,
        "converted_at": converted_at,
        "page_map_estimated": extraction.page_map_estimated,
    }


def dump_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
