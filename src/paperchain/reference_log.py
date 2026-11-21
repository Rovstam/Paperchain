"""Make changes to the reference set visible without blocking anyone.

`paperchain unlock`, `lock --accept-changes` and `convert --accept-changes` stay
fully automatic. Each one appends a line to `.paperchain/lock-log.jsonl`, and
`check` and `build` report the fingerprint of the whole reference set and warn
when it was re-blessed since the last successful build. The log is a signal for
the human (or `git diff`), not a lock: anyone who can write the project can edit
it, so it makes a swap visible, not impossible.
"""
from __future__ import annotations

import hashlib
import json

from .manifest import Manifest
from .project import Project
from .util import now_iso

LOG_RELATIVE = ".paperchain/lock-log.jsonl"
REBLESS_EVENTS = {"unlock", "accept_changes"}


def reference_fingerprint(manifest: Manifest) -> str:
    """One hash over every recorded reference, text, bibliography and style hash.

    Empty until something has been locked.
    """
    lines = [
        f"{source.key}\0{source.sha256}\0{source.text_sha256}"
        for source in sorted(manifest.sources, key=lambda item: item.key)
        if source.sha256 or source.text_sha256
    ]
    if not lines and not manifest.bibliography_sha256 and not manifest.csl_sha256:
        return ""
    lines.append(f"bibliography\0{manifest.bibliography_sha256}")
    lines.append(f"csl\0{manifest.csl_sha256}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def short(fingerprint: str) -> str:
    return fingerprint[:12]


def read_events(project: Project) -> list[dict]:
    path = project.root / LOG_RELATIVE
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    events: list[dict] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and isinstance(item.get("event"), str):
            events.append(item)
    return events


def append_event(project: Project, event: str, **fields) -> bool:
    """Append one line. A log that cannot be written never breaks the command."""
    path = project.root / LOG_RELATIVE
    record = {"time": now_iso(), "event": event, **fields}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return False
    return True


def reblessed_since_last_build(events: list[dict]) -> list[dict]:
    """Unlock / accepted-change events after the last successful build."""
    last_build = -1
    for index, item in enumerate(events):
        if item.get("event") == "build":
            last_build = index
    # An unlock that `paperchain start` makes only to add new references cannot bless a change:
    # start refuses to run when a locked reference differs and never accepts changes.
    return [
        item
        for item in events[last_build + 1 :]
        if item.get("event") in REBLESS_EVENTS and not item.get("additive")
    ]


def last_build_fingerprint(events: list[dict]) -> str:
    for item in reversed(events):
        if item.get("event") == "build":
            return str(item.get("fingerprint", "") or "")
    return ""
