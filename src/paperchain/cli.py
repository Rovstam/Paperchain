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
from .init_cmd import run_init
from .locking import run_lock, run_unlock
from .project import Project

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CANNOT_RUN = 2


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

    if command == "init":
        result = run_init(
            directory=args.directory,
            title=args.title,
            agent=args.agent,
            force=args.force,
            git=args.git,
        )
        summary = f'created "{result["title"]}" in {result["root"]} (adapter: {result["adapter"]})'
        if not result["git"] and args.git:
            summary += " [git init failed]"
        return _envelope(command, True, summary, data=result["data"])

    if command == "convert":
        project = _project(args)
        result = run_convert(project, force=args.force, only=args.only, prune=args.prune)
        parts = [f"converted {len(result['converted'])}"]
        parts.append(f"skipped {len(result['skipped'])}")
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
        result = run_lock(project)
        summary = f"locked {result['sources']} source(s); references are now read-only"
        return _envelope(command, True, summary, data=result["data"])

    if command == "unlock":
        project = _project(args)
        result = run_unlock(project)
        summary = f"unlocked {result['data']['files']} file(s)"
        return _envelope(command, True, summary, data=result["data"])

    if command == "check":
        project = _project(args)
        report = run_check(project, strict=args.strict)
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
    parser = argparse.ArgumentParser(
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

    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

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
    p_init.add_argument("--git", action="store_true", help="run git init in the new project")

    p_convert = sub.add_parser(
        "convert",
        parents=[common],
        help="extract page-marked text from every reference",
    )
    p_convert.add_argument("--force", action="store_true", help="re-extract even if unchanged")
    p_convert.add_argument("--only", metavar="KEY", help="convert one source by key")
    p_convert.add_argument("--prune", action="store_true", help="drop sources whose files are gone")

    sub.add_parser(
        "lock",
        parents=[common],
        help="freeze hashes and make references read-only",
    )
    sub.add_parser(
        "unlock",
        parents=[common],
        help="make references writable again (human only)",
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


def print_human(payload: dict[str, Any]) -> None:
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
