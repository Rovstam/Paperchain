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


MAX_DOCX_XML = 32 * 1024 * 1024


def _local(tag: str) -> str:
    """Local part of an XML name, so strict and transitional OOXML both work."""
    return tag.rsplit("}", 1)[-1]


def _attribute(element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return None


def _run_is_hidden(run) -> bool:
    for child in run:
        if _local(child.tag) != "rPr":
            continue
        for prop in child:
            if _local(prop.tag) == "vanish":
                return _attribute(prop, "val") not in {"0", "false", "off"}
    return False


def _append_run_text(run, chunks: list[str]) -> None:
    def walk(element) -> None:
        for child in element:
            name = _local(child.tag)
            if name == "txbxContent":
                continue
            if name == "t":
                chunks.append(child.text or "")
            elif name == "tab":
                chunks.append("\t")
            elif name in {"br", "cr"}:
                chunks.append("\n")
            elif name == "noBreakHyphen":
                chunks.append("-")
            else:
                walk(child)

    walk(run)


def _paragraph_text(paragraph) -> tuple[str, bool]:
    chunks: list[str] = []
    hidden = False

    def walk(element) -> None:
        nonlocal hidden
        for child in element:
            name = _local(child.tag)
            if name == "txbxContent":
                continue
            if name == "r":
                if _run_is_hidden(child):
                    hidden = True
                else:
                    _append_run_text(child, chunks)
                continue
            walk(child)

    walk(paragraph)
    return "".join(chunks).strip(), hidden


def _extract_docx(path: Path) -> Extraction:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if names.count("word/document.xml") != 1:
                raise PaperchainError(
                    "docx_unreadable",
                    f"{path.name} has duplicate or missing document parts",
                    hint="re-export the file as .docx; a zip with two document parts is ambiguous",
                )
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML:
                raise PaperchainError(
                    "docx_too_large",
                    f"{path.name} expands to {info.file_size} bytes of XML",
                    hint="export a text-only copy; this file is too large to read safely",
                )
            xml = archive.read("word/document.xml")
            has_footnotes = "word/footnotes.xml" in names
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

    body = next((child for child in root if _local(child.tag) == "body"), None)
    if body is None:
        raise PaperchainError("docx_empty", f"{path.name} has no document body")

    paragraphs: list[str] = []
    hidden_seen = False
    textbox_seen = any(_local(node.tag) == "txbxContent" for node in root.iter())

    def walk(element) -> None:
        nonlocal hidden_seen
        for child in element:
            name = _local(child.tag)
            if name == "txbxContent":
                continue
            if name == "p":
                text, hidden = _paragraph_text(child)
                hidden_seen = hidden_seen or hidden
                if text:
                    paragraphs.append(text)
                continue
            walk(child)

    walk(body)

    if not paragraphs:
        raise PaperchainError(
            "docx_empty",
            f"{path.name} contains no text",
            hint="Word files made only of images need OCR or a text export",
        )

    warnings: list[Finding] = []
    if has_footnotes:
        warnings.append(
            Finding(
                "docx_footnotes_ignored",
                "footnotes are not extracted from .docx in this version",
                severity="warning",
                file=path.name,
                hint="move any source text you need to cite into the body",
            )
        )
    if hidden_seen:
        warnings.append(
            Finding(
                "docx_hidden_text_skipped",
                "hidden text was skipped",
                severity="warning",
                file=path.name,
                hint="a reader cannot see hidden text; it is not a citable source",
            )
        )
    if textbox_seen:
        warnings.append(
            Finding(
                "docx_textbox_skipped",
                "text inside text boxes was skipped",
                severity="warning",
                file=path.name,
                hint="move the text into the body if you need to cite it",
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


def _docx_metadata(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            if "docProps/core.xml" not in archive.namelist():
                return "", ""
            root = ElementTree.fromstring(archive.read("docProps/core.xml"))
    except (OSError, zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        return "", ""
    title = next((node.text for node in root if _local(node.tag) == "title"), "")
    author = next((node.text for node in root if _local(node.tag) == "creator"), "")
    return _clean_metadata(title or ""), _clean_metadata(author or "")


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
