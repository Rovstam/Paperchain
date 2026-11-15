"""Regression tests for the third external audit (0.3.0)."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from paperchain.build import _check_resources, run_build
from paperchain.check import run_check
from paperchain.convert import run_convert
from paperchain.errors import PaperchainError
from paperchain.extract import extract
from paperchain.init_cmd import run_init
from paperchain.import_cmd import run_import
from paperchain.locations import project_cache
from paperchain.project import Project

from .conftest import add_pdf, make_project, write_paper
from .helpers import write_pdf

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _project_with_text(tmp_path: Path, text: str) -> Project:
    project = make_project(tmp_path)
    project.originals_dir.mkdir(parents=True, exist_ok=True)
    (project.originals_dir / "study2024.txt").write_text(text, encoding="utf-8")
    run_convert(project)
    return Project.open(project.root)


def _codes(report) -> set[str]:
    return {finding.code for finding in report.errors}


def _warning_codes(report) -> set[str]:
    return {finding.code for finding in report.warnings}


# -- 1. escaped comment opener and entity-encoded citations ----------------


def test_escaped_comment_opener_does_not_hide_citations(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "Alpha text one.")
    write_paper(
        project,
        "# T\n\n\\<!--\n\n"
        '[@study2024, p. 1: "invented words are here"]\n'
        '[@nosuchsource, p. 3: "fabricated claim"]\n\n-->\n',
    )
    codes = _codes(run_check(project))
    assert "quote_not_found" in codes
    assert "unknown_citation_key" in codes


@pytest.mark.parametrize(
    "citation",
    [
        '[&#64;study2024, p. 1: "Alpha text one."]',
        '[&commat;study2024, p. 1: "Alpha text one."]',
        '[&#x40;study2024, p. 1: "Alpha text one."]',
        '[\\@study2024, p. 1: "Alpha text one."]',
    ],
)
def test_entity_and_escaped_at_citations_are_reported(
    tmp_path: Path, citation: str
) -> None:
    project = _project_with_text(tmp_path, "Alpha text one.")
    write_paper(project, f"# T\n\n{citation}\n")
    assert "citation_unrecognized" in _codes(run_check(project))


def test_entities_outside_brackets_are_not_citations(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "Alpha text one.")
    write_paper(project, "# T\n\nMail me at bob&#64;example.org.\n")
    assert "citation_unrecognized" not in _codes(run_check(project))


# -- 2. style-based hidden DOCX text ---------------------------------------

STYLED_STYLES = (
    f'<w:style w:type="character" w:styleId="HiddenChar">'
    "<w:name w:val=\"Hidden Char\"/><w:rPr><w:vanish/></w:rPr></w:style>"
    f'<w:style w:type="character" w:styleId="Child">'
    '<w:basedOn w:val="HiddenChar"/></w:style>'
    f'<w:style w:type="character" w:styleId="Shown">'
    "<w:name w:val=\"Shown\"/><w:rPr><w:vanish w:val=\"0\"/></w:rPr></w:style>"
    f'<w:style w:type="paragraph" w:styleId="HiddenPara">'
    "<w:name w:val=\"Hidden Para\"/><w:rPr><w:vanish/></w:rPr></w:style>"
)


def _write_styled_docx(path: Path, body: str, styles: str = STYLED_STYLES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{W}">{styles}</w:styles>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles_xml)


def test_docx_character_style_hidden_text_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "hidden-char.docx"
    _write_styled_docx(
        path,
        "<w:p><w:r><w:t>Visible text.</w:t></w:r>"
        '<w:r><w:rPr><w:rStyle w:val="HiddenChar"/></w:rPr>'
        "<w:t>Hidden by style.</w:t></w:r></w:p>",
    )
    result = extract(path)
    assert "Visible text." in result.pages[0]
    assert "Hidden by style" not in result.pages[0]
    assert "docx_hidden_text_skipped" in {finding.code for finding in result.warnings}


def test_docx_paragraph_style_hidden_text_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "hidden-para.docx"
    _write_styled_docx(
        path,
        "<w:p><w:r><w:t>Visible text.</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="HiddenPara"/></w:pPr>'
        "<w:r><w:t>Hidden paragraph.</w:t></w:r></w:p>",
    )
    result = extract(path)
    assert "Visible text." in result.pages[0]
    assert "Hidden paragraph" not in result.pages[0]
    assert "docx_hidden_text_skipped" in {finding.code for finding in result.warnings}


def test_docx_hidden_style_inheritance_and_override(tmp_path: Path) -> None:
    path = tmp_path / "hidden-inherit.docx"
    _write_styled_docx(
        path,
        "<w:p>"
        '<w:r><w:rPr><w:rStyle w:val="Child"/></w:rPr><w:t>Inherited hidden.</w:t></w:r>'
        '<w:r><w:rPr><w:rStyle w:val="Shown"/></w:rPr><w:t>Explicitly shown.</w:t></w:r>'
        "</w:p>",
    )
    text = extract(path).pages[0]
    assert "Inherited hidden" not in text
    assert "Explicitly shown." in text


def test_a_quote_from_style_hidden_text_does_not_verify(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _write_styled_docx(
        project.originals_dir / "study2024.docx",
        "<w:p><w:r><w:t>Visible text.</w:t></w:r>"
        '<w:r><w:rPr><w:rStyle w:val="HiddenChar"/></w:rPr>'
        "<w:t>Hidden fabricated claim.</w:t></w:r></w:p>",
    )
    run_convert(project)
    project = Project.open(project.root)
    write_paper(
        project,
        '# T\n\nA claim [@study2024, p. 1: "Hidden fabricated claim."].\n',
    )
    assert "quote_not_found" in _codes(run_check(project))


# -- 3. quote boundaries and hyphen joins ----------------------------------


def test_a_leading_minus_cannot_match_a_range(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "In the trial, 1-5 degrees were recorded.")
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "-5 degrees were recorded"].\n')
    assert "quote_not_found" in _codes(run_check(project))


def test_a_leading_dot_cannot_match_a_decimal(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "The dose was 1.5 mg per day.")
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: ".5 mg per day"].\n')
    assert "quote_not_found" in _codes(run_check(project))


def test_a_hyphenated_numeric_range_is_not_joined(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "Ages 10-\n20 years were enrolled.")
    write_paper(
        project,
        '# T\n\nA claim [@study2024, p. 1: "ages 1020 years were enrolled"].\n',
    )
    assert "quote_not_found" in _codes(run_check(project))


def test_a_normal_quote_still_verifies_after_the_boundary_fix(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "The trial enrolled 5 degrees of severity.")
    write_paper(project, '# T\n\nA claim [@study2024, p. 1: "5 degrees of severity"].\n')
    assert run_check(project).ok


# -- 4. a manuscript without a hash ----------------------------------------


def test_manuscript_without_a_hash_is_an_error(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    manuscript = project.root / "manuscript.txt"
    manuscript.write_text("original draft", encoding="utf-8")
    project.manifest.manuscript_path = "manuscript.txt"
    project.manifest.manuscript_sha256 = ""
    project.save()
    assert "manuscript_unhashed" in _codes(run_check(Project.open(project.root)))


# -- 5. project_id cannot steer the cache ----------------------------------


@pytest.mark.parametrize("value", ["../../../../tmp/x", "/tmp/x", "not-a-uuid"])
def test_invalid_project_id_is_rejected(tmp_path: Path, value: str) -> None:
    project = make_project(tmp_path)
    project.manifest.project_id = value
    project.save()
    with pytest.raises(PaperchainError) as error:
        Project.open(project.root)
    assert error.value.code == "manifest_invalid"


def test_project_cache_rejects_a_traversing_id() -> None:
    with pytest.raises(ValueError):
        project_cache("../outside")


# -- 6. adapter shell rules ------------------------------------------------


def _decide(rules: list[dict], command: str) -> str:
    decision = "deny"
    for rule in rules:
        if rule["action"] != "shell":
            continue
        pattern = "^" + re.escape(rule["resource"]).replace(r"\*", ".*") + "$"
        if re.match(pattern, command, re.IGNORECASE):
            decision = rule["effect"]
    return decision


def test_adapter_denies_write_through_diff_and_compound_commands() -> None:
    from importlib.resources import files

    config = json.loads(
        files("paperchain")
        .joinpath("adapters/opencode/opencode.json")
        .read_text(encoding="utf-8")
    )
    rules = config["permissions"]
    assert _decide(rules, "paperchain check --json") == "allow"
    assert _decide(rules, "paperchain build") == "allow"
    assert _decide(rules, "git diff --stat") == "allow"
    assert _decide(rules, "git diff --output=paper.toml HEAD") == "deny"
    assert _decide(rules, 'paperchain "unlock"') == "deny"
    assert _decide(rules, "paperchain check; rm -rf /") == "deny"
    assert _decide(rules, "paperchain build && calc") == "deny"
    assert _decide(rules, "paperchain check | tee out.txt") == "deny"


# -- 7. build resources ----------------------------------------------------


def test_build_rejects_a_remote_image(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    with pytest.raises(PaperchainError) as error:
        _check_resources("![x](https://example.com/x.png)", project)
    assert error.value.code == "pandoc_resource_blocked"


def test_build_accepts_a_local_image(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    media = project.paper_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "x.png").write_bytes(b"not an image")
    _check_resources("![x](media/x.png)", project)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_build_does_not_read_an_image_outside_the_project(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    add_pdf(project, "study2024.pdf", ["Alpha text one."])
    run_convert(project)
    project = Project.open(project.root)
    (tmp_path / "outside.png").write_bytes(b"not an image")
    write_paper(
        project,
        '# T\n\nA claim [@study2024, p. 1: "Alpha text one."].\n\n'
        "![x](../../outside.png)\n",
    )
    with pytest.raises(PaperchainError) as error:
        run_build(project)
    assert error.value.code == "pandoc_resource_blocked"


# -- 8. destructive --force keeps a backup ---------------------------------


def test_init_force_saves_the_draft_and_manifest(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_paper(project, "# Mine\n\nDo not lose this.\n")
    root = project.root

    run_init(str(root), title="Replacement", force=True)

    assert (root / "Paper" / "paper.md.bak").read_text(encoding="utf-8") == (
        "# Mine\n\nDo not lose this.\n"
    )
    assert (root / "paper.toml.bak").is_file()


def test_import_force_saves_the_previous_draft(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.root / "manuscript.md").write_text("# Imported\n", encoding="utf-8")
    write_paper(project, "# Mine\n\nKeep me.\n")

    result = run_import(
        Project.open(project.root), source=str(project.root / "manuscript.md"), force=True
    )

    assert result["backups"] == ["Paper/paper.md.bak"]
    assert (project.paper_dir / "paper.md.bak").read_text(encoding="utf-8") == (
        "# Mine\n\nKeep me.\n"
    )
    assert project.paper_md.read_text(encoding="utf-8").startswith("# Imported")


# -- 9. non-Latin filenames get distinct keys ------------------------------


def test_non_latin_filenames_do_not_collide(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_pdf(project.originals_dir / "研究一.pdf", ["First study."])
    write_pdf(project.originals_dir / "研究二.pdf", ["Second study."])

    run_convert(project)

    keys = [source.key for source in Project.open(project.root).manifest.sources]
    assert len(keys) == 2
    assert len(set(keys)) == 2


# -- 10. XXX is not always a placeholder -----------------------------------


def test_roman_numeral_xxx_is_not_a_placeholder(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "Alpha text one.")
    write_paper(project, "# T\n\nSuper Bowl XXX was played.\n")
    assert "placeholder" not in _codes(run_check(project))


def test_standalone_xxx_is_still_a_placeholder(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "Alpha text one.")
    write_paper(project, "# T\n\nResults\n\nXXX\n")
    assert "placeholder" in _codes(run_check(project))


# -- 11. convert must not bless a changed source silently ------------------


def test_convert_refuses_a_changed_original_without_accept_changes(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    write_pdf(project.originals_dir / "study2024.pdf", ["Alpha text one."])
    run_convert(project)

    write_pdf(project.originals_dir / "study2024.pdf", ["A different page now."])
    with pytest.raises(PaperchainError) as error:
        run_convert(Project.open(project.root))
    assert error.value.code == "convert_changes"

    run_convert(Project.open(project.root), accept_changes=True)
    assert Project.open(project.root).manifest.sources[0].sha256


# -- 12. metadata ----------------------------------------------------------


def test_generic_pdf_author_is_not_used_as_attribution(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_pdf(
        project.originals_dir / "study2024.pdf",
        ["Alpha text one."],
        author="Administrator",
        title="Effects of X",
    )
    result = run_convert(project)

    source = Project.open(project.root).manifest.source("study2024")
    assert source is not None
    assert source.authors == ""
    assert "source_metadata_unconfirmed" in {
        finding.code for finding in result["warnings"]
    }


def test_check_warns_when_a_bibliography_entry_is_a_different_work(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    write_pdf(
        project.originals_dir / "study2024.pdf",
        ["Alpha text one."],
        title="Alpha study",
    )
    run_convert(project)
    project = Project.open(project.root)
    project.manifest.sources[0].title = "Alpha study"
    project.manifest.sources[0].authors = "Smith"
    project.manifest.sources[0].year = 2024
    project.save()
    (project.references_dir / "library.json").write_text(
        json.dumps([{"id": "study2024", "title": "A completely unrelated work"}]),
        encoding="utf-8",
    )
    write_paper(project, "# T\n")
    assert "source_metadata_mismatch" in _warning_codes(run_check(project))


def test_check_warns_when_a_source_has_no_year(tmp_path: Path) -> None:
    project = _project_with_text(tmp_path, "Alpha text one.")
    write_paper(project, "# T\n")
    assert "source_metadata_unconfirmed" in _warning_codes(run_check(project))


# -- 13. manifest save is atomic and init does not re-expand a title -------


def test_manifest_save_leaves_no_temp_file(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.save()
    assert not (project.root / ".paper.toml.tmp").exists()


def test_init_does_not_expand_placeholders_inside_the_title(tmp_path: Path) -> None:
    root = tmp_path / "paper"
    run_init(str(root), title="Draft {{date}} {{slug}}", agent="opencode")
    first_line = (root / "Paper" / "paper.md").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "# Draft {{date}} {{slug}}"
