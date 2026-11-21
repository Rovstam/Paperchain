from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import PROGRAM, SCHEMA_VERSION, __version__
from .build import describe_output, run_build
from .check import run_check
from .convert import run_convert
from .doctor import run_doctor
from .errors import Finding, PaperchainError
from .help_cmd import help_data
from .import_cmd import run_import
from .init_cmd import run_init
from .locking import run_lock, run_unlock
from .context import write_cards
from .start import run_start
from .match_cmd import run_match
from .organize import run_organize
from .project import Project

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CANNOT_RUN = 2


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that never accepts abbreviated long options."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)


def _project(args: argparse.Namespace) -> Project:
    path = getattr(args, "project", None)
    return Project.open(Path(path) if path else None)


def _envelope(
    command: str,
    ok: bool,
    summary: str,
    errors: list[Finding] | None = None,
    warnings: list[Finding] | None = None,
    data: dict[str, Any] | None = None,
    exit_code: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "program": PROGRAM,
        "version": __version__,
        "command": command,
        "ok": ok,
        "exit_code": exit_code if exit_code is not None else (EXIT_OK if ok else EXIT_FINDINGS),
        "summary": summary,
        "errors": [finding.as_dict() for finding in (errors or [])],
        "warnings": [finding.as_dict() for finding in (warnings or [])],
        "data": data or {},
    }


def _findings(code: str, checks: list[dict], severity: str) -> list[Finding]:
    return [
        Finding(
            code=f"{code}_{check['name'].replace(' ', '_')}",
            message=f"{check['name']}: {check['detail']}",
            severity=severity,
            hint=check.get("hint"),
        )
        for check in checks
        if check["status"] == ("fail" if severity == "error" else "warn")
    ]


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    command = args.command

    if command == "help":
        data = help_data()
        return _envelope(command, True, data["title"], data=data)

    if command == "init":
        result = run_init(
            directory=args.directory,
            title=args.title,
            agent=args.agent,
            force=args.force,
            git=args.git,
            adopt=args.adopt,
            style=args.style or "",
        )
        verb = "adopted" if result["data"].get("adopted") else "created"
        summary = f'{verb} "{result["title"]}" in {result["root"]} (adapter: {result["adapter"]})'
        if result["data"].get("skipped"):
            summary += f"; kept {result['data']['skipped']} existing file(s)"
        if result["data"].get("backups"):
            summary += "; saved " + ", ".join(result["data"]["backups"])
        if not result["git"] and args.git:
            summary += " [git init failed]"
        return _envelope(command, True, summary, data=result["data"])

    if command == "organize":
        project = _project(args)
        result = run_organize(
            project,
            apply=args.apply,
            manuscript=args.manuscript,
            references=args.reference,
            dumps=args.dump,
            into=args.into,
        )
        moves = result["data"]["moves"]
        counts = result["data"]["counts"]
        if result["applied"]:
            summary = f"moved {len(moves)} file(s) into the project folders"
        else:
            summary = (
                f"plan: {len(moves)} file(s) would move; nothing changed "
                "(re-run with --apply)"
            )
        if counts:
            summary += " (" + ", ".join(
                f"{count} {kind}" for kind, count in sorted(counts.items())
            ) + ")"
        if result["candidates"]:
            summary += "; more than one possible manuscript"
        return _envelope(
            command,
            True,
            summary,
            warnings=result["warnings"],
            data=result["data"],
        )

    if command == "import":
        project = _project(args)
        result = run_import(project, source=args.source, force=args.force)
        summary = (
            f"imported {result['source']} into {result['paper']} "
            f"({result['words']} words); the original was not modified"
        )
        if result.get("backups"):
            summary += f"; previous draft saved as {', '.join(result['backups'])}"
        return _envelope(
            command,
            True,
            summary,
            warnings=result["warnings"],
            data={key: value for key, value in result.items() if key != "warnings"},
        )

    if command == "convert":
        project = _project(args)
        result = run_convert(
            project,
            force=args.force,
            only=args.only,
            prune=args.prune,
            organize=not args.no_organize,
            accept_changes=args.accept_changes,
            into=args.into,
        )
        parts = [f"converted {len(result['converted'])}"]
        parts.append(f"skipped {len(result['skipped'])}")
        if result["moved"]:
            parts.append(f"organized {len(result['moved'])}")
        if result["pruned"]:
            parts.append(f"pruned {len(result['pruned'])}")
        summary = ", ".join(parts) + f" ({result['data']['sources']} source(s) total)"
        return _envelope(
            command,
            True,
            summary,
            warnings=result["warnings"],
            data=result["data"],
        )

    if command == "lock":
        project = _project(args)
        result = run_lock(project, accept_changes=args.accept_changes)
        summary = f"locked {result['sources']} source(s); references are now read-only"
        if result["changes"]:
            summary += f" (accepted {len(result['changes'])} change(s))"
        return _envelope(command, True, summary, data=result["data"])

    if command == "start":
        result = run_start(
            args.directory or getattr(args, "project", None),
            title=args.title,
            agent=args.agent,
            manuscript=args.manuscript,
        )
        needs = result["data"]["needs_human"]
        done = sum(1 for item in result["steps"] if item["status"] == "done")
        if needs:
            summary = f"setup paused: {len(needs)} thing(s) need a human"
        elif result["errors"]:
            summary = f"setup finished with {len(result['errors'])} error(s)"
        else:
            summary = f"ready: {done} step(s) done, {len(result['data']['pending_cards'])} context card(s) need a resume"
        return _envelope(
            command,
            not result["errors"],
            summary,
            errors=result["errors"],
            warnings=result["warnings"],
            data=result["data"],
        )

    if command == "context":
        project = _project(args)
        result = write_cards(project, only=args.only)
        counts = {name: sum(1 for c in result["cards"] if c["status"] == name) for name in ("created", "updated", "unchanged", "kept")}
        summary = (
            f"{len(result['cards'])} card(s): {counts['created']} new, {counts['updated']} updated, "
            f"{counts['unchanged']} unchanged; {len(result['pending'])} need a scoped resume"
        )
        return _envelope(
            command, True, summary, warnings=result["warnings"],
            data={"cards": result["cards"], "pending": result["pending"]},
        )

    if command == "match":
        project = _project(args)
        result = run_match(project, apply=args.apply, overwrite=args.overwrite)
        suggestions = [row for row in result["sources"] if row["status"] == "suggestion"]
        summary = (
            f"matched {len(result['matched'])} source(s), kept {len(result['kept'])}, "
            f"{len(result['unmatched'])} unmatched, {len(result['ambiguous'])} ambiguous, "
            f"{len(suggestions)} suggestion(s)"
        )
        if suggestions:
            summary += "; suggestions are not applied, confirm a citation_key by hand"
        if not args.apply and result["matched"]:
            summary += "; re-run with --apply to write citation_key into paper.toml"
        elif result["applied"]:
            summary += "; paper.toml updated"
        return _envelope(
            command,
            True,
            summary,
            warnings=result["warnings"],
            data={
                "sources": result["sources"],
                "matched": len(result["matched"]),
                "kept": len(result["kept"]),
                "unmatched": [row["key"] for row in result["unmatched"]],
                "ambiguous": [row["key"] for row in result["ambiguous"]],
                "applied": result["applied"],
            },
        )

    if command == "unlock":
        project = _project(args)
        result = run_unlock(project)
        summary = f"unlocked {result['data']['files']} file(s)"
        return _envelope(command, True, summary, data=result["data"])

    if command == "check":
        project = _project(args)
        report = run_check(project, strict=args.strict, reextract=args.reextract)
        stats = report.stats
        summary = (
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s) - "
            f"{stats.get('quotes_verified', 0)}/{stats.get('citations_with_quote', 0)} quote(s) verified, "
            f"{stats.get('citations', 0)} citation(s), {stats.get('sources', 0)} source(s)"
        )
        data = dict(report.data)
        data["stats"] = stats
        data["citations"] = report.citations
        return _envelope(
            command,
            report.ok,
            summary,
            errors=report.errors,
            warnings=report.warnings,
            data=data,
        )

    if command == "build":
        project = _project(args)
        result = run_build(project, force=args.force)
        if not result.ok:
            summary = (
                f"build blocked: {len(result.report.errors)} check error(s); "
                f"run `{PROGRAM} check` and fix them, or pass --force"
            )
            return _envelope(
                command,
                False,
                summary,
                errors=result.report.errors,
                warnings=result.report.warnings,
            )
        data = describe_output(result, project)
        summary = f"built {data['output']} ({data['size']}) with {data['pandoc']}"
        if result.report.errors:
            data["check_errors"] = [finding.as_dict() for finding in result.report.errors]
            summary += f" (forced past {len(result.report.errors)} check error(s))"
        return _envelope(
            command,
            True,
            summary,
            warnings=result.report.warnings,
            data=data,
        )

    if command == "doctor":
        project = _project(args)
        result = run_doctor(project)
        failed = [check for check in result["checks"] if check["status"] == "fail"]
        warned = [check for check in result["checks"] if check["status"] == "warn"]
        summary = (
            f"all {len(result['checks'])} checks passed"
            if result["ok"] and not warned
            else f"{len(failed)} failed, {len(warned)} warning(s), {len(result['checks'])} checks"
        )
        return _envelope(
            command,
            result["ok"],
            summary,
            errors=_findings("doctor", result["checks"], "error"),
            warnings=_findings("doctor", result["checks"], "warning"),
            data={"checks": result["checks"], **result["data"]},
        )

    raise PaperchainError("usage", f"unknown command {command!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog=PROGRAM,
        description="Source-grounded paper writing for AI agents.",
        epilog="Every command accepts --json for machine-readable output.",
    )
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print one JSON object on stdout and nothing else",
    )
    parser.add_argument(
        "--project",
        metavar="DIR",
        help="paper project folder (default: nearest parent with paper.toml)",
    )

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    common.add_argument(
        "--project",
        metavar="DIR",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )

    sub = parser.add_subparsers(
        dest="command", required=True, metavar="command", parser_class=_Parser
    )

    sub.add_parser(
        "help",
        parents=[common],
        help="show the quick-start instructions",
        description="Print the Paperchain quick-start instructions. Use --json for an agent-readable payload.",
    )

    p_init = sub.add_parser(
        "init",
        parents=[common],
        help="create a paper project from the template",
        description="Create a paper project: AGENTS.md, the folder layout, paper.toml and an agent adapter.",
    )
    p_init.add_argument("directory", nargs="?", default=".", help="where to create it (default: .)")
    p_init.add_argument("--title", help="paper title (default: the folder name)")
    p_init.add_argument(
        "--agent",
        default="opencode",
        help="agent adapter to install (default: opencode)",
    )
    p_init.add_argument("--force", action="store_true", help="write over an existing folder")
    p_init.add_argument(
        "--adopt",
        action="store_true",
        help="keep existing files and add only the missing project files",
    )
    p_init.add_argument(
        "--style",
        choices=["vancouver"],
        help="pin the citation style in paper.toml; check and build then refuse to fall back to another style",
    )
    p_init.add_argument("--git", action="store_true", help="run git init in the new project")

    p_organize = sub.add_parser(
        "organize",
        parents=[common],
        help="sort existing files into Manuscript/, References/ and Dump/",
        description="Move files that already exist in the project into the folders paperchain expects. Without --apply it only prints the plan.",
    )
    p_organize.add_argument(
        "--apply",
        action="store_true",
        help="move the files; without it, print the plan and change nothing",
    )
    p_organize.add_argument(
        "--manuscript",
        metavar="PATH",
        help="the original DOCX/PDF when more than one candidate exists",
    )
    p_organize.add_argument(
        "--reference",
        action="append",
        default=[],
        metavar="PATH",
        help="an extra file or folder to treat as references (repeatable)",
    )
    p_organize.add_argument(
        "--dump",
        action="append",
        default=[],
        metavar="PATH",
        help="an extra file or folder to treat as working material (repeatable)",
    )
    p_organize.add_argument(
        "--into",
        metavar="CATEGORY",
        help="put loose references in this References/ subfolder (created if missing)",
    )

    p_import = sub.add_parser(
        "import",
        parents=[common],
        help="copy the original manuscript into Paper/paper.md without editing it",
        description="Convert the project's original DOCX/PDF manuscript to editable Markdown. The original is only read.",
    )
    p_import.add_argument(
        "source",
        nargs="?",
        help="manuscript file (default: the one in the project root or Manuscript/)",
    )
    p_import.add_argument(
        "--force",
        action="store_true",
        help="replace an existing Paper/paper.md",
    )

    p_convert = sub.add_parser(
        "convert",
        parents=[common],
        help="extract page-marked text from every reference",
    )
    p_convert.add_argument("--force", action="store_true", help="re-extract even if unchanged")
    p_convert.add_argument("--only", metavar="KEY", help="convert one source by key")
    p_convert.add_argument("--prune", action="store_true", help="drop sources whose files are gone")
    p_convert.add_argument(
        "--no-organize",
        action="store_true",
        help="leave loose PDF/DOCX files directly in References/ instead of moving them",
    )
    p_convert.add_argument(
        "--into",
        metavar="CATEGORY",
        help="move loose PDF/DOCX files into this References/ subfolder instead of References/<key>/",
    )
    p_convert.add_argument(
        "--accept-changes",
        action="store_true",
        help="accept references that changed since the last conversion",
    )

    p_lock = sub.add_parser(
        "lock",
        parents=[common],
        help="freeze hashes and make references read-only",
    )
    p_lock.add_argument(
        "--accept-changes",
        action="store_true",
        help="accept references that changed since the last lock",
    )
    p_start = sub.add_parser(
        "start",
        parents=[common],
        help="set up this folder for writing: sort, import, convert, lock, context cards",
        description="Run the setup steps in order and print what is left. Safe to run again. It only adds: it never accepts changed references and never replaces a draft.",
    )
    p_start.add_argument("directory", nargs="?", help="the project or the folder to turn into one (default: here)")
    p_start.add_argument("--title", help="title for a new project (default: the folder name)")
    p_start.add_argument("--agent", default="opencode", help="agent adapter for a new project (default: opencode)")
    p_start.add_argument("--manuscript", metavar="FILE", help="the original manuscript, when more than one file could be it")
    p_context = sub.add_parser(
        "context",
        parents=[common],
        help="write a context card next to each converted reference",
        description="Write or refresh <name>.context.md beside every converted reference. The generated top is rebuilt from the cached text; the scoped resume below the marker is kept.",
    )
    p_context.add_argument("--only", nargs="+", metavar="KEY", help="only these source keys")
    sub.add_parser(
        "unlock",
        parents=[common],
        help="make references writable again (human only)",
    )

    p_match = sub.add_parser(
        "match",
        parents=[common],
        help="map Zotero/Better BibTeX ids onto sources by title",
        description="Pair each source with a CSL JSON entry and record its citation_key. Reports unmatched, ambiguous and duplicate-title cases; --apply writes paper.toml.",
    )
    p_match.add_argument(
        "--apply",
        action="store_true",
        help="write citation_key into paper.toml; without it, print the plan",
    )
    p_match.add_argument(
        "--overwrite",
        action="store_true",
        help="re-match sources that already have a citation_key",
    )

    p_check = sub.add_parser(
        "check",
        parents=[common],
        help="verify hashes, citations, pages and quotes",
    )
    p_check.add_argument(
        "--strict",
        action="store_true",
        help="require quoted evidence for every citation",
    )
    p_check.add_argument(
        "--reextract",
        action="store_true",
        help="re-extract every original and compare it with the converted page map",
    )

    p_build = sub.add_parser(
        "build",
        parents=[common],
        help="check, then build Output/*.docx with pandoc",
    )
    p_build.add_argument("--force", action="store_true", help="build even if check reports errors")

    sub.add_parser(
        "doctor",
        parents=[common],
        help="diagnose the toolchain and the project",
    )

    return parser


def _location(finding: dict[str, Any]) -> str:
    file = finding.get("file")
    line = finding.get("line")
    if file and line:
        return f"{file}:{line}"
    return file or "-"


def _print_help(data: dict[str, Any]) -> None:
    print(data["title"])
    print()
    print(data["intro"])
    for step in data.get("steps", []):
        print()
        print(step["title"])
        if step.get("text"):
            print(f"  {step['text']}")
        for command in step.get("commands", []):
            print(f"  $ {command}")
    notes = data.get("notes", [])
    if notes:
        print()
        print("Notes")
        for note in notes:
            print(f"  - {note}")
    if data.get("json_hint"):
        print()
        print(data["json_hint"])


def print_human(payload: dict[str, Any]) -> None:
    if payload["command"] == "help":
        _print_help(payload["data"])
        return

    print(payload["summary"])
    # Doctor prints its own check list; the findings would duplicate it.
    if payload["command"] != "doctor":
        for finding in payload["errors"]:
            print(f"  error {_location(finding)} [{finding['code']}] {finding['message']}")
            if finding.get("hint"):
                print(f"        {finding['hint']}")
        for finding in payload["warnings"]:
            print(f"  warn  {_location(finding)} [{finding['code']}] {finding['message']}")
            if finding.get("hint"):
                print(f"        {finding['hint']}")

    data = payload.get("data") or {}
    if payload["command"] == "init" and data.get("next"):
        print("  next steps:")
        for step in data["next"]:
            print(f"    - {step}")
    if payload["command"] == "doctor":
        for check in data.get("checks", []):
            mark = {"ok": "ok  ", "warn": "warn", "fail": "fail"}[check["status"]]
            print(f"  {mark} {check['name']}: {check['detail']}")
            if check["status"] != "ok" and check.get("hint"):
                print(f"        {check['hint']}")
    if payload["command"] == "organize":
        moves = data.get("moves") or []
        for move in moves[:60]:
            print(f"  {move['kind']:<10} {move['source']} -> {move['target']}")
        if len(moves) > 60:
            print(f"  ... and {len(moves) - 60} more")
        for candidate in data.get("candidates") or []:
            print(f"  candidate manuscript: {candidate}")
    if payload["command"] == "start":
        for item in data.get("steps", []):
            mark = {"done": "ok  ", "skipped": "skip", "needs_human": "ASK ", "failed": "FAIL"}.get(item["status"], item["status"])
            print(f"  {mark} {item['step']}: {item['detail']}")
        for item in data.get("needs_human", []):
            print(f"  needs a human: {item}")
        if data.get("next"):
            print("  next:")
            for item in data["next"]:
                print(f"    - {item}")
    if payload["command"] == "context":
        for card in data.get("cards", []):
            state = "stale" if card.get("stale") else ("resume" if card.get("has_resume") else "pending")
            print(f"  {card['status']:<9} {state:<8} {card['key']} -> {card['card']}")
    if payload["command"] == "match":
        for row in data.get("sources", []):
            candidates = row.get("candidates") or []
            target = row.get("citation_key") or (candidates[0] if candidates else "-")
            print(f"  {row['status']:<10} {row['key']} -> {target}")
            if row["status"] in {"ambiguous", "suggestion"} and candidates:
                print(f"        candidates: {', '.join(candidates)}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_mode = bool(getattr(args, "json", False))

    try:
        payload = dispatch(args)
    except PaperchainError as exc:
        finding = exc.as_finding()
        exit_code = (
            EXIT_CANNOT_RUN
            if exc.code in {"project_not_found", "usage"}
            else EXIT_FINDINGS
        )
        payload = _envelope(
            getattr(args, "command", "unknown"),
            False,
            exc.message,
            errors=[finding],
            exit_code=exit_code,
        )
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - defensive
        if os.environ.get("PAPERCHAIN_DEBUG"):
            raise
        payload = _envelope(
            getattr(args, "command", "unknown"),
            False,
            f"unexpected error: {type(exc).__name__}: {exc}",
            errors=[
                Finding(
                    "internal_error",
                    f"{type(exc).__name__}: {exc}",
                    hint="rerun with PAPERCHAIN_DEBUG=1 to see the traceback, and report it",
                )
            ],
            exit_code=EXIT_CANNOT_RUN,
        )

    if json_mode:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print_human(payload)
    return int(payload["exit_code"])
