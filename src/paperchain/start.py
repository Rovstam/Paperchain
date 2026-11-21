"""One command that gets a folder ready for an agent to write in.

`paperchain start` runs the setup steps in order (create or open the project,
sort loose files, import the manuscript, file and convert the references, pair
them with Zotero, lock them, write the context cards, run the diagnostics) and
prints what is left to do. It is safe to run again: every step is skipped when
there is nothing to do.

It only ever adds. It never passes `--accept-changes`, never replaces an
existing draft, and never blesses a reference that changed after it was locked.
That one case, and an ambiguous manuscript, are the only reasons it stops and
asks the human.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .context import write_cards
from .convert import run_convert
from .doctor import run_doctor
from .errors import Finding, PaperchainError
from .extract import SUPPORTED_SUFFIXES
from .import_cmd import run_import
from .init_cmd import run_init
from .locking import run_lock, run_unlock
from .match_cmd import run_match
from .organize import run_organize
from .project import Project
from .reference_log import reference_fingerprint
from .util import sha256_file


def _drift(project: Project) -> list[str]:
    """Locked references (or the Zotero export) that no longer match their hashes."""
    drifted: list[str] = []
    for source in project.manifest.sources:
        path = project.root / source.path
        if not source.sha256:
            continue
        if not path.is_file():
            drifted.append(f"{source.path} is missing")
        elif sha256_file(path) != source.sha256:
            drifted.append(f"{source.path} changed")
    bibliography = project.bibliography_path
    recorded = project.manifest.bibliography_sha256
    if recorded and bibliography is not None and bibliography.is_file():
        if sha256_file(bibliography) != recorded:
            drifted.append(f"{project.relative(bibliography)} changed")
    return drifted


def _new_references(project: Project) -> list[str]:
    known = {source.path for source in project.manifest.sources}
    return [
        project.relative(path)
        for path in project.iter_reference_files()
        if path.suffix.lower() in SUPPORTED_SUFFIXES and project.relative(path) not in known
    ]


def run_start(
    directory: str | None = None,
    title: str | None = None,
    agent: str = "opencode",
    manuscript: str | None = None,
) -> dict[str, Any]:
    steps: list[dict[str, str]] = []
    errors: list[Finding] = []
    warnings: list[Finding] = []
    needs_human: list[str] = []

    def step(name: str, status: str, detail: str = "") -> None:
        steps.append({"step": name, "status": status, "detail": detail})

    def failed(name: str, exc: PaperchainError, human: bool = False) -> None:
        finding = exc.as_finding()
        errors.append(finding)
        step(name, "needs_human" if human else "failed", f"{exc.code}: {exc.message}")
        if human:
            needs_human.append(f"{name}: {exc.message}" + (f" ({exc.hint})" if exc.hint else ""))

    # 1. the project -------------------------------------------------------------
    target = Path(directory).expanduser().resolve() if directory else None
    try:
        try:
            project = Project.open(target)
            step("project", "skipped", f"using {project.root}")
        except PaperchainError as exc:
            if exc.code != "project_not_found":
                raise
            root = target or Path.cwd().resolve()
            adopt = any(not entry.name.startswith(".") for entry in root.iterdir()) if root.is_dir() else False
            run_init(str(root), title=title or root.name, agent=agent, adopt=adopt)
            project = Project.open(root)
            step("project", "done", f"created {project.root}" + (" (adopted the existing files)" if adopt else ""))
    except PaperchainError as exc:
        failed("project", exc)
        return _result(None, steps, errors, warnings, needs_human, [], [])

    def refresh() -> Project:
        return Project.open(project.root)

    # 2. sort loose files --------------------------------------------------------
    ambiguous = False
    try:
        organized = run_organize(project, apply=True, manuscript=manuscript)
        warnings.extend(organized["warnings"])
        moves = organized["data"]["moves"]
        step("organize", "done" if moves else "skipped", f"{len(moves)} file(s) moved" if moves else "nothing to sort")
    except PaperchainError as exc:
        if exc.code != "manuscript_ambiguous":
            failed("organize", exc)
        else:
            ambiguous = True
            try:
                project.find_manuscript(manuscript)
                names = ""
            except PaperchainError as inner:
                names = inner.message.split(": ", 1)[-1]
            question = (
                "more than one file could be the manuscript"
                + (f" ({names})" if names else "")
                + '; ask the human which one it is, then run `paperchain start --manuscript "<that file>"`'
            )
            errors.append(Finding("start_manuscript_ambiguous", question,
                                  hint='rerun with `paperchain start --manuscript "<file>"`; nothing was moved'))
            needs_human.append("manuscript: " + question)
            step("organize", "needs_human", "waiting for the manuscript choice; nothing was moved")
    project = refresh()
    if ambiguous:
        # Stop before the references step: converting or locking would move
        # files after telling the human that nothing was moved.
        return _result(project, steps, errors, warnings, needs_human, [], [])

    # 3. the manuscript ----------------------------------------------------------
    try:
        existing = project.paper_md.read_text(encoding="utf-8") if project.paper_md.is_file() else ""
        if existing and "paperchain:template" not in existing:
            step("import", "skipped", "Paper/paper.md already has a draft; it is never replaced")
        else:
            original = project.find_manuscript(None)
            if original is None:
                step("import", "skipped", "no manuscript found (fine when you are writing from scratch)")
            else:
                imported = run_import(project)
                warnings.extend(imported["warnings"])
                step("import", "done", f"{imported['source']} -> {imported['paper']} ({imported['words']} words)")
                project = refresh()
    except PaperchainError as exc:
        failed("import", exc)
        project = refresh()

    # 4. references: file, convert, match, lock ---------------------------------
    new_refs = _new_references(project)
    was_locked = bool(project.manifest.locked_at)
    bibliography = project.bibliography_path
    # A Zotero export that has never been locked is an addition, like a new reference.
    new_export = bool(bibliography and bibliography.is_file() and not project.manifest.bibliography_sha256)
    drift = _drift(project) if was_locked else []
    if drift:
        message = "; ".join(drift)
        errors.append(Finding("start_reference_changed", f"a locked reference changed: {message}",
                              hint="a human decides: if the change is intended run `paperchain unlock`, "
                                   "`paperchain convert --accept-changes`, `paperchain lock --accept-changes`"))
        needs_human.append(f"references: {message}")
        step("references", "needs_human", f"not touched because {message}")
    elif was_locked and not new_refs and not new_export:
        step("references", "skipped", f"{len(project.manifest.sources)} source(s) locked, nothing new")
    else:
        unlocked_here = False
        try:
            if was_locked:
                run_unlock(project, additive=True)
                unlocked_here = True
                project = refresh()
            converted = run_convert(project)
            warnings.extend(converted["warnings"])
            project = refresh()
            if project.bibliography_path is not None:
                try:
                    matched = run_match(project, apply=True)
                    step("match", "done", "; ".join(f"{k} {v}" for k, v in _tally(matched["sources"]).items()))
                except PaperchainError as exc:
                    failed("match", exc)
                project = refresh()
            if project.manifest.sources:
                run_lock(project)
                unlocked_here = False
                step("references", "done", f"{len(project.manifest.sources)} source(s) converted and locked"
                     + (f"; {len(new_refs)} new" if new_refs else "")
                     + ("; Zotero export locked" if new_export else ""))
            else:
                step("references", "skipped", "no references yet; put PDF or DOCX files in References/ and run again")
        except PaperchainError as exc:
            failed("references", exc, human=exc.code in {"lock_changes", "convert_changes"})
        finally:
            project = refresh()
            if unlocked_here and project.manifest.sources:
                try:
                    run_lock(project)
                except PaperchainError:
                    warnings.append(Finding("start_left_unlocked", "the references could not be locked again",
                                            severity="warning", hint="run `paperchain lock` once the error above is fixed"))
                project = refresh()

    # 5. context cards -----------------------------------------------------------
    pending: list[str] = []
    cards: list[dict] = []
    try:
        card_result = write_cards(project)
        warnings.extend(card_result["warnings"])
        pending, cards = card_result["pending"], card_result["cards"]
        step("context cards", "done" if cards else "skipped",
             f"{len(cards)} card(s); {len(pending)} need a scoped resume" if cards else "no converted references")
    except PaperchainError as exc:
        failed("context cards", exc)

    # 6. diagnostics -------------------------------------------------------------
    try:
        report = run_doctor(project)
        bad = [c for c in report.get("checks", []) if c["status"] == "fail"]
        for check in bad:
            errors.append(Finding(f"doctor_{check['name'].replace(' ', '_')}", f"{check['name']}: {check['detail']}", hint=check.get("hint")))
        step("doctor", "failed" if bad else "done", "; ".join(f"{c['name']}: {c['detail']}" for c in bad) or "all required checks pass")
    except PaperchainError as exc:
        failed("doctor", exc)

    return _result(project, steps, errors, warnings, needs_human, pending, cards)


def _tally(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def _result(project: Project | None, steps, errors, warnings, needs_human, pending, cards) -> dict[str, Any]:
    next_steps: list[str] = []
    if needs_human:
        next_steps.append("Stop and ask the human to resolve `data.needs_human` before anything else.")
    if pending:
        next_steps.append("Write the scoped resume for each key in `data.pending_cards` (see AGENTS.md, Context cards).")
    if project is not None and not needs_human:
        draft = project.paper_md.read_text(encoding="utf-8") if project.paper_md.is_file() else ""
        if not draft or "paperchain:template" in draft:
            next_steps.append("Write the paper in Paper/paper.md, or ask the human for a manuscript to import.")
        next_steps.append("Run `paperchain check --json`, fix every error, then `paperchain build`.")
    return {
        "steps": steps,
        "errors": errors,
        "warnings": warnings,
        "data": {
            "project": str(project.root) if project else "",
            "steps": steps,
            "needs_human": needs_human,
            "pending_cards": pending,
            "cards": [{"key": c["key"], "card": c["card"]} for c in cards],
            "reference_fingerprint": reference_fingerprint(project.manifest) if project else "",
            "next": next_steps,
        },
    }
