from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .errors import Finding, PaperchainError
from .project import Project
from .util import sha256_file

# A folder is treated as a reference collection when its name is one of these.
REFERENCE_DIR_RE = re.compile(
    r"^(references?|referencias?|bibliograf\w*|bibliography|sources?|fuentes|articulos?|literatura)$",
    re.IGNORECASE,
)

# Loose documents whose names look like instructions or examples are working
# material, not citable sources. The obvious case is a formatting guide such
# as "MONOGRAFIA, Depart. de Publicaciones 2016.pdf".
GUIDE_NAME_RE = re.compile(
    r"(monograf[ií]a|gu[ií]a|manual|norma|acuerdo|resoluci[oó]n|formato|plantilla|ejemplo|instructivo|reglamento)",
    re.IGNORECASE,
)

REFERENCE_SUFFIXES = {".pdf", ".docx"}
PROJECT_DIRS = {"Paper", "Output", "Candidates", "References", "Manuscript", "Dump"}
PROJECT_FILES = {
    "paper.toml",
    "AGENTS.md",
    "opencode.json",
    ".gitignore",
    ".gitattributes",
    "README.md",
    "LICENSE",
    "CLAUDE.md",
    "GEMINI.md",
}
SYSTEM_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}


@dataclass(frozen=True)
class Move:
    source: str
    target: str
    kind: str


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    manuscript: str = ""
    manuscript_target: str = ""
    _sources: set[str] = field(default_factory=set, repr=False)
    _targets: set[str] = field(default_factory=set, repr=False)

    def add(self, root: Path, source: Path, target: Path, kind: str) -> Move | None:
        source_rel = source.relative_to(root).as_posix()
        if source_rel in self._sources:
            return None
        self._sources.add(source_rel)
        target, kind = self._available(root, target, source, kind)
        target_rel = target.relative_to(root).as_posix()
        move = Move(source_rel, target_rel, kind)
        self.moves.append(move)
        return move

    def _available(
        self, root: Path, target: Path, source: Path, kind: str
    ) -> tuple[Path, str]:
        target_rel = target.relative_to(root).as_posix()
        if target_rel not in self._targets and not target.exists():
            self._targets.add(target_rel)
            return target, kind

        if (
            target_rel not in self._targets
            and target.is_file()
            and source.is_file()
            and sha256_file(target) == sha256_file(source)
        ):
            # The same bytes are already in place. Keep the copy that is not in
            # the canonical folder, but move it out of the way instead of
            # deleting it.
            archived = root / "Dump" / source.relative_to(root)
            return self._numbered(root, archived), "duplicate"

        # A different file already has this name. Never overwrite it.
        return (
            self._numbered(root, root / "Dump" / "conflicts" / source.relative_to(root)),
            "conflict",
        )

    def _numbered(self, root: Path, target: Path) -> Path:
        candidate = target
        counter = 2
        while candidate.relative_to(root).as_posix() in self._targets or candidate.exists():
            candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
            counter += 1
        self._targets.add(candidate.relative_to(root).as_posix())
        return candidate


def _is_hidden(path: Path) -> bool:
    return path.name.startswith((".", "~$"))


def _is_system(path: Path) -> bool:
    return path.name.casefold() in SYSTEM_NAMES or path.suffix.casefold() == ".ini"


def _looks_like_guide(name: str) -> bool:
    return bool(GUIDE_NAME_RE.search(name))


def _resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _under(path: Path, roots: list[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _reference_index(root: Path) -> dict[str, str]:
    """Hashes already present in References/, keyed by digest."""
    index: dict[str, str] = {}
    references = root / "References"
    if not references.is_dir():
        return index
    for path in sorted(references.rglob("*")):
        if not path.is_file() or _is_hidden(path):
            continue
        try:
            index.setdefault(sha256_file(path), path.relative_to(root).as_posix())
        except OSError:
            continue
    return index


def _add_reference(
    plan: Plan,
    root: Path,
    source: Path,
    target: Path,
    index: dict[str, str],
) -> None:
    """Plan a reference move, but archive a copy whose bytes already exist."""
    try:
        digest = sha256_file(source)
    except OSError:
        digest = ""
    if digest and digest in index:
        plan.add(root, source, root / "Dump" / source.relative_to(root), "duplicate")
        return
    move = plan.add(root, source, target, "reference")
    if move is not None and move.kind == "reference" and digest:
        index[digest] = move.target


def _plan_dump(plan: Plan, root: Path, entry: Path, manuscript: Path | None) -> None:
    if entry.is_file():
        plan.add(root, entry, root / "Dump" / entry.relative_to(root), "dump")
        return
    for path in sorted(entry.rglob("*")):
        if not path.is_file():
            continue
        # Keep real hidden files (a nested .git, .gitkeep) where they are, but
        # Word lock files are transient and must not leave the old folder alive.
        if _is_hidden(path) and not path.name.startswith("~$"):
            continue
        if manuscript is not None and path.resolve() == manuscript:
            continue
        plan.add(root, path, root / "Dump" / path.relative_to(root), "dump")


def _plan_reference_dir(
    plan: Plan,
    root: Path,
    entry: Path,
    manuscript: Path | None,
    index: dict[str, str],
) -> None:
    for path in sorted(entry.rglob("*")):
        if not path.is_file():
            continue
        if _is_hidden(path) and not path.name.startswith("~$"):
            continue
        if manuscript is not None and path.resolve() == manuscript:
            continue
        if _is_system(path) or path.name.startswith("~$"):
            # desktop.ini, Word lock files and friends belong to the old
            # folder, not to the reference set.
            plan.add(root, path, root / "Dump" / path.relative_to(root), "dump")
            continue
        _add_reference(
            plan,
            root,
            path,
            root / "References" / path.relative_to(entry),
            index,
        )


def _free_name(target: Path) -> Path:
    candidate = target
    counter = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
        counter += 1
    return candidate


def _manuscript_candidates(project: Project) -> list[Path]:
    found: list[Path] = []
    for folder in (project.root, project.manuscript_dir):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file() or _is_hidden(path):
                continue
            if path.suffix.lower() in {".docx", ".pdf"}:
                found.append(path.resolve())
    return sorted(set(found))


def build_plan(
    project: Project,
    manuscript: str | None = None,
    references: list[str] | None = None,
    dumps: list[str] | None = None,
) -> Plan:
    root = project.root.resolve()
    plan = Plan()
    reference_index = _reference_index(root)
    forced_references = [_resolve(root, value) for value in (references or [])]
    forced_dumps = [_resolve(root, value) for value in (dumps or [])]

    manuscript_path: Path | None = None
    candidate_paths: set[Path] = set()
    if manuscript:
        manuscript_path = _resolve(root, manuscript)
        if not manuscript_path.is_file():
            raise PaperchainError(
                "manuscript_missing",
                f"{manuscript} does not exist",
                hint="pass the original DOCX or PDF to --manuscript",
            )
    elif project.manifest.manuscript_path:
        manuscript_path = _resolve(root, project.manifest.manuscript_path)
        if not manuscript_path.is_file():
            plan.warnings.append(
                Finding(
                    "manuscript_missing",
                    f"the recorded manuscript {project.manifest.manuscript_path} is missing",
                    file=project.manifest.manuscript_path,
                    hint="restore it, or pass --manuscript with the current original",
                )
            )
            manuscript_path = None
    else:
        try:
            manuscript_path = project.find_manuscript()
        except PaperchainError as exc:
            if exc.code != "manuscript_ambiguous":
                raise
            candidates = _manuscript_candidates(project)
            plan.candidates = [project.relative(path) for path in candidates]
            candidate_paths = set(candidates)
            plan.warnings.append(
                Finding(
                    "manuscript_ambiguous",
                    exc.message,
                    hint="pick the original with `paperchain organize --manuscript PATH`",
                )
            )

    if manuscript_path is not None:
        plan.manuscript = project.relative(manuscript_path)
        if manuscript_path.is_relative_to(project.manuscript_dir.resolve()):
            plan.manuscript_target = plan.manuscript
        else:
            target = root / "Manuscript" / manuscript_path.name
            if (
                target.is_file()
                and sha256_file(target) == sha256_file(manuscript_path)
            ):
                # The canonical copy already exists. Keep it and archive the
                # extra one instead of moving the original over itself.
                plan.add(
                    root,
                    manuscript_path,
                    root / "Dump" / manuscript_path.relative_to(root),
                    "duplicate",
                )
                plan.manuscript_target = target.relative_to(root).as_posix()
            else:
                target = _free_name(target)
                move = plan.add(root, manuscript_path, target, "manuscript")
                plan.manuscript_target = (
                    move.target if move is not None else target.relative_to(root).as_posix()
                )

    for entry in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        if entry.name.casefold() in {name.casefold() for name in PROJECT_DIRS}:
            continue
        if entry.name.casefold() in {name.casefold() for name in PROJECT_FILES}:
            continue
        if _is_hidden(entry) or _is_system(entry):
            continue
        if manuscript_path is not None and entry.resolve() == manuscript_path:
            continue
        if manuscript_path is None and entry.resolve() in candidate_paths:
            continue

        if _under(entry.resolve(), forced_dumps):
            _plan_dump(plan, root, entry, manuscript_path)
            continue
        if _under(entry.resolve(), forced_references):
            if entry.is_dir():
                _plan_reference_dir(
                    plan, root, entry, manuscript_path, reference_index
                )
            else:
                _add_reference(
                    plan,
                    root,
                    entry,
                    root / "References" / entry.name,
                    reference_index,
                )
            continue

        if entry.is_file():
            if (
                entry.suffix.casefold() in REFERENCE_SUFFIXES
                and not _looks_like_guide(entry.name)
            ):
                _add_reference(
                    plan,
                    root,
                    entry,
                    root / "References" / entry.name,
                    reference_index,
                )
            else:
                _plan_dump(plan, root, entry, manuscript_path)
            continue

        if REFERENCE_DIR_RE.match(entry.name):
            _plan_reference_dir(
                plan, root, entry, manuscript_path, reference_index
            )
        else:
            _plan_dump(plan, root, entry, manuscript_path)

    return plan


def _apply_moves(project: Project, plan: Plan) -> tuple[list[Move], list[Finding]]:
    root = project.root.resolve()
    performed: list[Move] = []
    problems: list[Finding] = []

    for move in plan.moves:
        source = root / move.source
        target = root / move.target
        if not source.exists():
            problems.append(
                Finding(
                    "organize_missing",
                    f"{move.source} disappeared before it could be moved",
                    severity="warning",
                    file=move.source,
                )
            )
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = root / "Dump" / "conflicts" / move.source
                target = _unique_destination(root, target)
                target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except OSError as exc:
            problems.append(
                Finding(
                    "organize_failed",
                    f"cannot move {move.source}: {exc}",
                    file=move.source,
                    hint="close the file if it is open, then re-run `paperchain organize --apply`",
                )
            )
            continue
        performed.append(
            Move(move.source, target.relative_to(root).as_posix(), move.kind)
        )

    return performed, problems


def _unique_destination(root: Path, target: Path) -> Path:
    candidate = target
    counter = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
        counter += 1
    return candidate


def _update_manifest(project: Project, performed: list[Move], plan: Plan) -> bool:
    manifest = project.manifest
    changed = False
    if (
        plan.manuscript
        and plan.manuscript_target
        and (project.root / plan.manuscript_target).is_file()
        and manifest.manuscript_path in {"", plan.manuscript}
    ):
        manifest.manuscript_path = plan.manuscript_target
        changed = True
    mapping = {
        move.source: move.target
        for move in performed
        if move.kind in {"reference", "manuscript", "duplicate", "conflict"}
    }
    for source in manifest.sources:
        if source.path in mapping:
            source.path = mapping[source.path]
            changed = True
    if changed:
        project.save()
    return changed


def _remove_empty_dirs(project: Project, performed: list[Move]) -> None:
    root = project.root.resolve()
    protected = {name.casefold() for name in PROJECT_DIRS}
    parents = {(root / move.source).parent for move in performed}
    for start in sorted(parents, key=lambda path: len(path.parts), reverse=True):
        current = start
        while (
            current != root
            and current.is_dir()
            and current.name.casefold() not in protected
            and not any(current.iterdir())
        ):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def run_organize(
    project: Project,
    apply: bool = False,
    manuscript: str | None = None,
    references: list[str] | None = None,
    dumps: list[str] | None = None,
) -> dict:
    plan = build_plan(
        project,
        manuscript=manuscript,
        references=references,
        dumps=dumps,
    )

    if apply and plan.candidates and not plan.manuscript:
        raise PaperchainError(
            "manuscript_ambiguous",
            "more than one possible manuscript; refusing to move files",
            hint="choose the original with `paperchain organize --manuscript PATH --apply`",
        )

    performed: list[Move] = []
    warnings = list(plan.warnings)
    if apply:
        performed, problems = _apply_moves(project, plan)
        warnings.extend(problems)
        _update_manifest(project, performed, plan)
        _remove_empty_dirs(project, performed)

    moves = performed if apply else plan.moves
    counts: dict[str, int] = {}
    for move in moves:
        counts[move.kind] = counts.get(move.kind, 0) + 1

    return {
        "applied": apply,
        "candidates": plan.candidates,
        "warnings": warnings,
        "data": {
            "applied": apply,
            "manuscript": plan.manuscript_target or plan.manuscript,
            "counts": counts,
            "moves": [
                {"source": move.source, "target": move.target, "kind": move.kind}
                for move in moves
            ],
            "candidates": plan.candidates,
        },
    }
