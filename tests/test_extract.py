from __future__ import annotations

from pathlib import Path

import pytest

from paperchain.errors import PaperchainError
from paperchain.extract import extract

from .helpers import write_docx, write_pdf


def test_extracts_pdf_pages_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "study.pdf"
    write_pdf(path, ["The sample contains forty two cases.", "A second page."], title="A Study", author="J. Doe")
    result = extract(path)
    assert result.page_count == 2
    assert "forty two cases" in result.pages[0]
    assert "second page" in result.pages[1]
    assert result.converter.startswith("pypdf")
    assert result.title == "A Study"
    assert result.authors == "J. Doe"


def test_extracts_docx_paragraphs(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    write_docx(path, ["First paragraph.", "Second paragraph."], title="Report", author="A. Writer")
    result = extract(path)
    assert result.page_count == 1
    assert "First paragraph." in result.pages[0]
    assert "Second paragraph." in result.pages[0]
    assert result.page_map_estimated is True
    assert result.title == "Report"
    assert result.authors == "A. Writer"


def test_rejects_unsupported_suffix(tmp_path: Path) -> None:
    path = tmp_path / "notes.rtf"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(PaperchainError) as error:
        extract(path)
    assert error.value.code == "unsupported_type"


def test_rejects_invalid_docx(tmp_path: Path) -> None:
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    with pytest.raises(PaperchainError) as error:
        extract(path)
    assert error.value.code == "docx_unreadable"
