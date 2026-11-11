from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def write_docx(path: Path, paragraphs: list[str], title: str = "", author: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{W_NS}">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style>'
        "</w:styles>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)
        if title or author:
            core = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties '
                'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f"<dc:title>{escape(title)}</dc:title>"
                f"<dc:creator>{escape(author)}</dc:creator>"
                "</cp:coreProperties>"
            )
            archive.writestr("docProps/core.xml", core)


def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(path: Path, pages: list[str], title: str = "", author: str = "") -> None:
    """Write a small valid PDF with one line of Helvetica text per page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = len(pages)
    font_id = 3 + 2 * count
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(count))
    objects: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {count} >>",
    }
    for index, text in enumerate(pages):
        page_id = 3 + 2 * index
        content_id = page_id + 1
        stream = f"BT /F1 12 Tf 72 720 Td ({_pdf_escape(text)}) Tj ET"
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        objects[content_id] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    info_bits = []
    if title:
        info_bits.append(f"/Title ({_pdf_escape(title)})")
    if author:
        info_bits.append(f"/Author ({_pdf_escape(author)})")
    info_id = font_id + 1
    if info_bits:
        objects[info_id] = "<< " + " ".join(info_bits) + " >>"
    objects[font_id] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    buffer = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(buffer)
        buffer += f"{number} 0 obj\n{objects[number]}\nendobj\n".encode("latin-1")

    xref_offset = len(buffer)
    size = max(objects) + 1
    buffer += f"xref\n0 {size}\n".encode("latin-1")
    buffer += b"0000000000 65535 f \n"
    for number in range(1, size):
        buffer += f"{offsets[number]:010d} 00000 n \n".encode("latin-1")
    trailer = f"<< /Size {size} /Root 1 0 R"
    if info_bits:
        trailer += f" /Info {info_id} 0 R"
    trailer += " >>"
    buffer += f"trailer\n{trailer}\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin-1")
    path.write_bytes(bytes(buffer))
