"""Title-based folders for loose references (step 2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperchain.check import run_check
from paperchain.convert import run_convert
from paperchain.folders import MAX_FOLDER_CHARS, MAX_WORD_CHARS, folder_name, usable_title
from paperchain.locking import run_lock, run_unlock
from paperchain.project import Project
from paperchain.util import slugify

from .conftest import make_project, write_paper
from .helpers import write_pdf

LONG = (
    "Assessment of Herb-Drug Interaction Potential of Five Common Species of "
    "Licorice and Their Phytochemical Constituents"
)


# -- the name itself ----------------------------------------------------------


def test_the_default_limit_is_ten_characters() -> None:
    assert MAX_FOLDER_CHARS == 10


def test_a_title_within_the_limit_is_kept_as_written() -> None:
    assert folder_name("Enzyme Map") == "Enzyme Map"
    assert folder_name("A Study of Enzyme Induction", limit=50) == "A Study of Enzyme Induction"


def test_a_long_title_is_cut_at_a_word_and_never_ends_on_a_filler_word() -> None:
    name = folder_name(LONG)
    assert len(name) <= MAX_FOLDER_CHARS
    assert LONG.startswith(name)
    assert name.split()[-1].casefold() not in {"of", "and", "the", "in", "for"}
    assert name == "Assessment"
    assert folder_name(LONG, limit=50) == "Assessment of Herb-Drug Interaction Potential"
    assert folder_name("Effects of the drug", limit=10) == "Effects"  # "of" is not left dangling


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ('What is "bias"? A <review>', "What is bias A review"),
        ("Cells: a primer", "Cells - a primer"),
        ("Path\\to/file|name*", "Path to file name"),
        ("  .hidden title.  ", "hidden title"),
        ("Title with trailing dots...", "Title with trailing dots"),
        ("CON", "CON_"),
        ("nul", "nul_"),
        ("Tab\tand\nnewline", "Tab and newline"),
    ],
)
def test_names_are_safe_on_every_operating_system(title: str, expected: str) -> None:
    assert folder_name(title, limit=50) == expected


@pytest.mark.parametrize("title", ["", "   ", "...", "///", ":::"])
def test_a_title_with_nothing_usable_gives_no_name(title: str) -> None:
    assert folder_name(title) == ""


def test_a_long_first_word_is_kept_whole_up_to_a_cap() -> None:
    assert folder_name("Dolutegravir clearance study") == "Dolutegravir"
    assert folder_name("Pharmacokinetics of licorice") == "Pharmacokinetics"
    assert len(folder_name("x" * 200)) == MAX_WORD_CHARS


def test_later_long_words_are_not_split() -> None:
    assert folder_name("Study of Dolutegravir") == "Study"


def test_decomposed_accents_are_normalised() -> None:
    decomposed = "Preparacio\u0301n del cafe\u0301"
    assert folder_name(decomposed, limit=50) == "Preparaci\u00f3n del caf\u00e9"


@pytest.mark.parametrize(
    "raw",
    ["", "Untitled", "untitled document", "Microsoft Word - draft", "smith2024.pdf", "report.docx", "123 45"],
)
def test_metadata_that_is_not_a_title_is_ignored(raw: str) -> None:
    assert usable_title(raw) == ""


def test_a_real_title_is_used() -> None:
    assert usable_title("  Enzyme   induction in rats ") == "Enzyme induction in rats"


# -- filing a loose reference ------------------------------------------------------


def loose(project: Project, name: str, title: str = "", text: str = "Alpha text one.") -> Path:
    path = project.references_dir / name
    write_pdf(path, [text], title=title)
    return path


def test_a_loose_titled_pdf_goes_into_a_folder_named_after_its_title(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    loose(project, "1-s2.0-S094471132200185X-main.pdf", title=LONG)
    result = run_convert(project)

    folder = project.references_dir / "Assessment"
    assert (folder / f"{folder.name}.pdf").is_file()
    assert not (project.references_dir / "1-s2.0-S094471132200185X-main.pdf").exists()
    assert result["moved"]
    source = Project.open(project.root).manifest.sources[0]
    assert source.key == slugify(folder.name)
    assert source.path == f"References/{folder.name}/{folder.name}.pdf"


def test_the_filed_reference_works_end_to_end(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    loose(project, "download (3).pdf", title="Enzyme induction in rats")
    run_convert(project)
    project = Project.open(project.root)
    key = project.manifest.sources[0].key
    write_paper(project, f'# T\n\nA claim [@{key}, p. 1: "Alpha text one."].\n')
    report = run_check(Project.open(project.root))
    assert not [f for f in report.errors if f.code in {"quote_not_found", "source_hash_mismatch", "text_missing"}]


def test_a_file_without_a_usable_title_keeps_the_filename_folder(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    loose(project, "study2024.pdf", title="")
    run_convert(project)
    assert (project.references_dir / "study2024" / "study2024.pdf").is_file()


def test_a_file_already_in_a_folder_is_left_alone(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    folder = project.references_dir / "A Perfectly Good Title Here"
    folder.mkdir()
    write_pdf(folder / "paper.pdf", ["Alpha text one."], title="A Perfectly Good Title Here")
    run_convert(project)
    assert (folder / "paper.pdf").is_file()
    assert sorted(p.name for p in project.references_dir.iterdir() if p.is_dir()) == [
        "A Perfectly Good Title Here"
    ]


def test_a_reference_in_an_arbitrary_shelf_gets_its_own_folder(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    shelf = project.references_dir / "Research Materials"
    shelf.mkdir()
    write_pdf(shelf / "study.pdf", ["Alpha text one."], title="A Clinical Trial")

    run_convert(project)

    project = Project.open(project.root)
    source = project.manifest.sources[0]
    assert source.path == "References/Research Materials/A Clinical Trial/study.pdf"
    assert (
        project.references_dir
        / "Research Materials"
        / "A Clinical Trial"
        / "study.context.md"
    ).is_file()
    assert run_convert(Project.open(project.root))["moved"] == []
    write_paper(
        project,
        f'# T\n\nA claim [@{source.key}, p. 1: "Alpha text one."].\n',
    )
    run_lock(project)
    assert run_check(Project.open(project.root)).ok


def test_a_markdown_reference_in_an_arbitrary_folder_is_filed(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    shelf = project.references_dir / "Research Materials"
    shelf.mkdir()
    (shelf / "notes.md").write_text("A reference note with useful evidence.\n", encoding="utf-8")

    run_convert(project)

    assert (shelf / "notes" / "notes.md").is_file()


def test_refiling_an_article_preserves_its_key_and_scoped_resume(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    shelf = project.references_dir / "Articulos"
    shelf.mkdir()
    pdf = shelf / "study.pdf"
    write_pdf(pdf, ["Alpha text one."], title="A Clinical Trial")

    run_convert(project, organize=False)
    project = Project.open(project.root)
    source = project.manifest.sources[0]
    key = source.key
    card = shelf / "study.context.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "<!-- PENDING: scoped resume not written yet -->",
            "This study reports the finding needed for the paper and its limitations.",
        ),
        encoding="utf-8",
    )
    run_lock(project)

    run_unlock(Project.open(project.root))
    run_convert(Project.open(project.root))
    run_lock(Project.open(project.root))

    project = Project.open(project.root)
    source = project.manifest.source(key)
    moved_card = shelf / "A Clinical Trial" / "study.context.md"
    assert source is not None
    assert source.key == key
    assert source.path == "References/Articulos/A Clinical Trial/study.pdf"
    assert moved_card.is_file()
    assert "This study reports the finding needed for the paper" in moved_card.read_text(encoding="utf-8")
    assert run_check(project).ok


def test_refiling_a_multi_source_category_preserves_keys_and_context_cards(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    shelf = project.references_dir / "Resoluciones y Normativas"
    shelf.mkdir()
    files = {
        "decreto.pdf": ("Decreto 0780 de 2016", "Decree text."),
        "ley.pdf": ("Ley 485 de 1998", "Law text."),
    }
    for name, (title, text) in files.items():
        write_pdf(shelf / name, [text], title=title)

    run_convert(project, organize=False)
    project = Project.open(project.root)
    keys = {source.path.rsplit("/", 1)[-1]: source.key for source in project.manifest.sources}
    for name in files:
        card = shelf / f"{Path(name).stem}.context.md"
        card.write_text(
            card.read_text(encoding="utf-8").replace(
                "<!-- PENDING: scoped resume not written yet -->",
                "Keep this source's scoped note.",
            ),
            encoding="utf-8",
        )
    run_lock(project)

    run_unlock(Project.open(project.root))
    run_convert(Project.open(project.root))
    run_lock(Project.open(project.root))

    project = Project.open(project.root)
    for name, (title, _) in files.items():
        source = next(source for source in project.manifest.sources if source.key == keys[name])
        folder = shelf / title
        assert source.path == f"References/Resoluciones y Normativas/{title}/{name}"
        assert (folder / f"{Path(name).stem}.context.md").is_file()
        assert "Keep this source's scoped note." in (
            folder / f"{Path(name).stem}.context.md"
        ).read_text(encoding="utf-8")


def test_two_different_papers_with_the_same_title_get_numbered_folders(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    loose(project, "a.pdf", title="Same Title Here", text="First paper text.")
    loose(project, "b.pdf", title="Same Title Here", text="Second paper text.")
    run_convert(project)
    names = sorted(p.name for p in project.references_dir.iterdir() if p.is_dir())
    assert names == ["Same Title", "Same Title (2)"]
    keys = {s.key for s in Project.open(project.root).manifest.sources}
    assert len(keys) == 2


def test_a_folder_name_that_differs_only_by_case_is_not_reused(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.references_dir / "same title").mkdir()
    write_pdf(project.references_dir / "same title" / "x.pdf", ["Other text."])
    loose(project, "a.pdf", title="Same Title Here")
    run_convert(project)
    assert (project.references_dir / "Same Title (2)").is_dir()


def test_an_identical_copy_is_not_filed_twice_and_is_not_deleted(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    loose(project, "a.pdf", title="Duplicate Title Here")
    run_convert(project)
    again = loose(project, "again.pdf", title="Duplicate Title Here")
    result = run_convert(Project.open(project.root))
    assert again.is_file()  # left where it was, never removed
    assert not (project.references_dir / "Duplicate (2)").exists()
    assert any(w.code == "organize_skipped" for w in result["warnings"])


def test_the_zotero_spelling_of_a_title_is_used_when_one_entry_matches(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.references_dir / "library.json").write_text(
        json.dumps([{"id": "doe2024", "type": "article-journal", "title": "Enzyme Map"}]),
        encoding="utf-8",
    )
    loose(project, "x.pdf", title="enzyme map.")
    run_convert(Project.open(project.root))
    assert (project.references_dir / "Enzyme Map" / "Enzyme Map.pdf").is_file()


def test_a_broken_library_never_blocks_filing(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.references_dir / "library.json").write_text("{ not json", encoding="utf-8")
    loose(project, "x.pdf", title="Resilient Title Here")
    run_convert(Project.open(project.root))
    assert (project.references_dir / "Resilient").is_dir()


def test_into_keeps_the_category_behaviour(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    loose(project, "x.pdf", title="Some Title That Is Long Enough")
    run_convert(project, into="Articulos")
    assert (project.references_dir / "Articulos" / "Some Title That Is Long" / "x.pdf").is_file()


def test_many_papers_that_start_alike_are_numbered_not_lost(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    for index in range(3):
        loose(project, f"p{index}.pdf", title="Effects of Drug Number Something", text=f"Distinct text {index}.")
    run_convert(project)
    names = sorted(p.name for p in project.references_dir.iterdir() if p.is_dir())
    assert names == ["Effects", "Effects (2)", "Effects (3)"]
    assert len({s.key for s in Project.open(project.root).manifest.sources}) == 3
