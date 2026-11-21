from __future__ import annotations

from typing import Any


def help_data() -> dict[str, Any]:
    """The quick-start text, in one place for humans and agents."""
    return {
        "title": "Paperchain quick start",
        "intro": "Paperchain is installed once per machine. A project is just a folder with paper.toml.",
        "steps": [
            {
                "title": "0. The short way",
                "text": "`paperchain start` does steps 1 to 3 below in one go and is safe to repeat: it creates the project if needed, sorts the files, imports the manuscript, files and converts the references, locks them and writes the context cards. It only adds. If a locked reference changed or several files could be the manuscript, it stops and says what it needs from you.",
                "commands": [
                    "paperchain start",
                    'paperchain start --manuscript "my manuscript.docx"',
                ],
            },
            {
                "title": "1. Open the project folder",
                "text": "Use the folder that contains your manuscript and references. If it is empty, create the project there. If it already has files, adopt it without overwriting them.",
                "commands": [
                    'paperchain init . --title "Project Name"',
                    'paperchain init . --adopt --title "Project Name"',
                ],
            },
            {
                "title": "2. Sort the files that are already there",
                "text": "If the folder already had a manuscript, reference folders or notes, `organize` sorts them: the original moves to Manuscript/, reference PDFs/DOCX move to References/, and everything else moves to Dump/. The plan is printed first and changes nothing; --apply performs the moves. Nothing is deleted, and name collisions go to Dump/conflicts/.",
                "commands": [
                    "paperchain organize",
                    "paperchain organize --apply",
                ],
            },
            {
                "title": "3. Import the manuscript and prepare references",
                "text": "The original manuscript is read, never edited. import writes Paper/paper.md. If References/library.json exists, `match --apply` records the Better BibTeX key of each source so citations can use either name. convert files loose references into a folder named after the paper's title and writes a context card (<name>.context.md) beside each one; `context` refreshes the cards, and an agent writes the scoped resume under the marker line.",
                "commands": [
                    "paperchain import",
                    "paperchain convert",
                    "paperchain context",
                    "paperchain match --apply",
                    "paperchain lock",
                ],
            },
            {
                "title": "4. Write",
                "text": "Edit Paper/paper.md, or ask an agent to edit it. Do not edit Output/ or the original manuscript.",
                "commands": [],
            },
            {
                "title": "5. Check and build",
                "text": "check verifies hashes, keys, pages and quotes. build refuses to run while errors remain.",
                "commands": [
                    "paperchain check",
                    "paperchain build",
                ],
            },
        ],
        "notes": [
            "The original DOCX/PDF is never modified.",
            "`organize` moves files; it never deletes. Without --apply it is read-only.",
            "Generated text, images and temp files live outside the project; paperchain doctor --json reports the cache paths under data.cache.",
            "References/library.json is an optional CSL JSON export from Zotero. When present, build uses it for citations and the bibliography.",
            "Source keys come from the reference's folder and file name (a title for loose files filed by convert), Zotero ids do not. `paperchain match` pairs them by title and reports unmatched or ambiguous cases; `--apply` writes citation_key into paper.toml, and a citation may then use either the source key or the Zotero id.",
            "Reference categories are folder names under References/. List them in References/.paperchain-categories.json so organize recognizes them, and use `organize --into CATEGORY` or `convert --into CATEGORY` to place loose files there.",
            "Generated citation keys are capped at 60 characters; long titles end with a short digest, and colliding keys add more of the folder path.",
            "Agents: run `paperchain help --json` and relay data.steps. Do not scan unrelated folders to answer a how-to question.",
        ],
        "json_hint": "Run `paperchain help --json` for the same instructions in machine-readable form.",
    }
