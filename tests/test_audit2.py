"""Regression tests for the second external audit."""

from __future__ import annotations

import json
import os
import re
import stat
import warnings
import zipfile
from pathlib import Path

import pytest

from paperchain.check import run_check
from paperchain.cli import main
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.extract import Extraction, extract, render_text_file
from paperchain.locking import run_lock, run_unlock
from paperchain.manifest import Source
from paperchain.project import Project

from .conftest import make_project, write_paper

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STRICT = "http://purl.oclc.org/ooxml/wordprocessingml/main"


def _project_with_page(tmp_path: Path, text: str = "Alpha text one.") -> Project:
    from .conftest import add_pdf

    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", [text])
    run_convert(project)
    return Project.open(project.root)


def _codes(report) -> set[str]:
    return {finding.code for finding in report.errors}


def _write_docx(
    path: Path,
    body: str,
    namespace: str = W,
    core: bytes | None = None,
    duplicate: bool = False,
) -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{namespace}"><w:body>{body}</w:body></w:document>'
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", document)
            if duplicate:
                archive.writestr("word/document.xml", document)
            if core is not None:
                archive.writestr("docProps/core.xml", core)


# -- 1. scanner still hides citations -------------------------------------


def test_escaped_backtick_does_not_open_a_code_span(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(
        project,
        '# T\n\n\\`[@study2024, p. 9: "Water boils at one hundred degrees."]`\n',
    )
    assert "page_out_of_range" in _codes(run_check(project))


def test_a_fence_with_backticks_in_the_info_string_is_inline_code(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, "# T\n\n```x``` inline.\n\n[@study2024, p. 9]\n")
    assert "page_out_of_range" in _codes(run_check(project))


# -- 2. keys outside the ASCII slug alphabet -------------------------------


@pytest.mark.parametrize(
    "citation",
    [
        '[@Ünknown2020, p. 3: "fabricated words are here"]',
        '[@_nobody, p. 1: "fabricated words are here"]',
        "@{nobody}",
    ],
)
def test_non_slug_keys_are_reported_not_ignored(tmp_path: Path, citation: str) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, f"# T\n\n{citation}\n")
    assert "citation_unrecognized" in _codes(run_check(project))


# -- 3. removing the lock state must not disable hash checks ---------------


def test_missing_hashes_are_errors_even_without_locked_at(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(project)

    project = Project.open(project.root)
    project.manifest.locked_at = ""
    project.manifest.sources[0].sha256 = ""
    project.manifest.sources[0].text_sha256 = ""
    project.save()

    codes = _codes(run_check(Project.open(project.root)))
    assert {"source_unhashed", "text_unhashed"} <= codes


# -- 4. the page map must match a fresh extraction -------------------------


def test_lock_rejects_a_forged_page_map(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(project)

    project = Project.open(project.root)
    run_unlock(project)
    json_path = project.text_dir / "study2024.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    forged = "The drug cured every patient in the trial."
    payload["pages"][0]["text"] = forged
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    (project.text_dir / "study2024.txt").write_text(
        render_text_file(
            "study2024",
            Path(payload["original"]).name,
            Extraction(
                pages=[forged],
                converter=payload["converter"],
                page_map_estimated=payload.get("page_map_estimated", False),
            ),
        ),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(PaperchainError) as error:
        run_lock(Project.open(project.root), accept_changes=True)
    assert error.value.code == "lock_failed"
    assert "fresh extraction" in error.value.message


# -- 5. manifest paths and keys cannot escape the project ------------------


def test_manifest_path_outside_originals_is_rejected(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.manifest.sources.append(Source(key="evil", path="../victim"))
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"


def test_manifest_absolute_path_is_rejected(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("secret", encoding="utf-8")
    project.manifest.sources.append(Source(key="evil", path=str(victim)))
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"


def test_manifest_key_cannot_contain_path_separators(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.manifest.sources.append(
        Source(key="../../notes", path="References/originals/study.pdf")
    )
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_lock_preserves_the_original_mode(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    original = project.originals_dir / "study2024.pdf"
    os.chmod(original, 0o600)

    run_lock(project)
    assert stat.S_IMODE(original.stat().st_mode) == 0o400

    run_unlock(Project.open(project.root))
    assert stat.S_IMODE(original.stat().st_mode) == 0o600


# -- 6. build output must stay in Output/ ----------------------------------


@pytest.mark.parametrize("output", ["../escape.docx", "/tmp/escape.docx"])
def test_output_outside_output_folder_is_rejected(tmp_path: Path, output: str) -> None:
    project = make_project(tmp_path)
    project.manifest.build_output = output
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root).output_path
    assert error.value.code == "invalid_output"


# -- 7. argument abbreviation ---------------------------------------------


def test_long_options_cannot_be_abbreviated() -> None:
    with pytest.raises(SystemExit) as error:
        main(["build", "--fo"])
    assert error.value.code == 2


# -- 8-9. DOCX extraction --------------------------------------------------


def test_docx_hidden_text_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "hidden.docx"
    _write_docx(
        path,
        "<w:p><w:r><w:t>Visible text.</w:t></w:r>"
        "<w:r><w:rPr><w:vanish/></w:rPr><w:t>Hidden text.</w:t></w:r></w:p>",
    )
    result = extract(path)
    assert "Visible text." in result.pages[0]
    assert "Hidden" not in result.pages[0]
    assert "docx_hidden_text_skipped" in {finding.code for finding in result.warnings}


def test_docx_non_breaking_hyphen_is_a_hyphen(tmp_path: Path) -> None:
    path = tmp_path / "hyphen.docx"
    _write_docx(
        path,
        "<w:p><w:r><w:t>A well</w:t><w:noBreakHyphen/><w:t>known result.</w:t></w:r></w:p>",
    )
    assert "A well-known result." in extract(path).pages[0]


def test_docx_textbox_text_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "textbox.docx"
    _write_docx(
        path,
        "<w:p><w:r><w:t>Before </w:t></w:r><w:r><w:drawing><w:txbxContent>"
        "<w:p><w:r><w:t>Inside box</w:t></w:r></w:p>"
        "</w:txbxContent></w:drawing></w:r><w:r><w:t>after.</w:t></w:r></w:p>",
    )
    result = extract(path)
    assert "Inside box" not in result.pages[0]
    assert "Before" in result.pages[0]
    assert "docx_textbox_skipped" in {finding.code for finding in result.warnings}


def test_duplicate_document_part_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.docx"
    _write_docx(path, "<w:p><w:r><w:t>Text.</w:t></w:r></w:p>", duplicate=True)
    with pytest.raises(PaperchainError) as error:
        extract(path)
    assert error.value.code == "docx_unreadable"


def test_strict_ooxml_namespace_is_read(tmp_path: Path) -> None:
    path = tmp_path / "strict.docx"
    _write_docx(path, "<w:p><w:r><w:t>Strict text.</w:t></w:r></w:p>", namespace=STRICT)
    assert "Strict text." in extract(path).pages[0]


def test_corrupt_core_properties_do_not_abort(tmp_path: Path) -> None:
    path = tmp_path / "core.docx"
    _write_docx(
        path,
        "<w:p><w:r><w:t>Text.</w:t></w:r></w:p>",
        core=b"<not-valid-xml",
    )
    result = extract(path)
    assert result.pages[0] == "Text."
    assert result.title == ""


def test_oversized_document_part_is_rejected(tmp_path: Path, monkeypatch) -> None:
    import paperchain.extract as module

    monkeypatch.setattr(module, "MAX_DOCX_XML", 10)
    path = tmp_path / "big.docx"
    _write_docx(path, "<w:p><w:r><w:t>Text.</w:t></w:r></w:p>")
    with pytest.raises(PaperchainError) as error:
        extract(path)
    assert error.value.code == "docx_too_large"


# -- 10. boundary cases ----------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="symlink creation may need privileges")
def test_symlink_outside_originals_is_rejected(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("outside", encoding="utf-8")
    os.symlink(victim, project.originals_dir / "linked.txt")
    with pytest.raises(PaperchainError) as error:
        run_convert(project)
    assert error.value.code == "source_outside_project"


def test_an_at_sign_inside_a_quote_is_not_multiple_citations(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.originals_dir.mkdir(parents=True, exist_ok=True)
    (project.originals_dir / "study2024.txt").write_text(
        "Contact @bob today.", encoding="utf-8"
    )
    run_convert(project)
    project = Project.open(project.root)
    write_paper(project, '# T\n\nA [@study2024, p. 1: "Contact @bob today"].\n')
    report = run_check(project)
    assert report.ok, [finding.message for finding in report.errors]


def test_non_numeric_manifest_size_is_invalid(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    manifest_path = project.root / "paper.toml"
    text = manifest_path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^size = \d+$", 'size = "big"', text, count=1)
    manifest_path.write_text(text, encoding="utf-8")
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"


def test_lock_drift_includes_the_txt_copy(tmp_path: Path) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')
    run_lock(project)

    txt_path = project.text_dir / "study2024.txt"
    os.chmod(txt_path, 0o644)
    report = run_check(Project.open(project.root))
    assert "lock_drift" in {finding.code for finding in report.warnings}


def test_check_reextract_detects_a_forged_page_map(tmp_path: Path) -> None:
    from paperchain.util import sha256_file

    project = _project_with_page(tmp_path)
    write_paper(
        project,
        '# T\n\nA claim [@study2024, p. 1: "The drug cured every patient in the trial."].\n',
    )
    run_lock(project)

    project = Project.open(project.root)
    run_unlock(project)
    json_path = project.text_dir / "study2024.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    forged = "The drug cured every patient in the trial."
    payload["pages"][0]["text"] = forged
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    (project.text_dir / "study2024.txt").write_text(
        render_text_file(
            "study2024",
            Path(payload["original"]).name,
            Extraction(
                pages=[forged],
                converter=payload["converter"],
                page_map_estimated=payload.get("page_map_estimated", False),
            ),
        ),
        encoding="utf-8",
        newline="\n",
    )
    # A forged folder can update the manifest too. Only re-extraction notices.
    project.manifest.sources[0].text_sha256 = sha256_file(json_path)
    project.save()

    assert run_check(Project.open(project.root)).ok
    assert "text_stale" in _codes(run_check(Project.open(project.root), reextract=True))


def test_a_chmod_failure_does_not_leave_the_project_locked(tmp_path: Path, monkeypatch) -> None:
    project = _project_with_page(tmp_path)
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n')

    real_chmod = os.chmod
    calls = {"count": 0}

    def flaky_chmod(path, mode):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated failure")
        return real_chmod(path, mode)

    monkeypatch.setattr(os, "chmod", flaky_chmod)
    with pytest.raises(PaperchainError) as error:
        run_lock(project)
    assert error.value.code == "permission_failed"
    monkeypatch.undo()

    assert Project.open(project.root).manifest.locked_at == ""
