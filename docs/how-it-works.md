# How it works

This document is for the human maintaining a paper and for the agent writing it. It describes what the tool guarantees and where the guarantee stops.

## The shape of a paper project

```
paper.toml            manifest: the source list, hashes and build settings
References/originals/  the files you supplied
References/_text/      derived text, one .txt and one .json per source
Paper/paper.md         the draft
Candidates/            proposed sources, awaiting a human
Output/                generated .docx
AGENTS.md              the rules
```

Only `Paper/paper.md`, `Candidates/` and `Output/` are ever written by an agent, and `Output/` only through `paperchain build`.

## Why the draft is Markdown

Word files are bad diff targets. A `.docx` is a zip of XML; a small edit changes compressed bytes, so git cannot show what changed, review is impossible, and a corrupted file silently loses formatting. Pandoc reading and writing `.docx` loses comments, tracked changes and some fields.

So the draft is `Paper/paper.md`, and `paperchain build` renders it with pandoc. The Word file is an artefact, like a compiled binary: never edited, always regenerated. If you need a specific Word style, point `[build] reference_doc` at a `.docx` you have styled and pandoc will use it as the style source.

## Conversion and page maps

Each source becomes two files:

- `References/_text/<key>.txt` — what the agent reads. A line `===== PAGE 12 =====` marks each page.
- `References/_text/<key>.json` — what `check` reads. It holds the pages as structured text, plus the source hash and the converter version.

PDFs are extracted with pypdf. DOCX is read directly from `word/document.xml` with the standard library, so there is no dependency and no round-trip. TXT and MD are read as-is.

Word has no fixed pages, so a DOCX becomes a single page and the citation page is always `p. 1`. That is honest but weak; export to PDF when page-level evidence matters.

## The manifest and the lock

`paper.toml` is written by the tool. `title`, `authors` and `year` are safe for a human to edit; changing `sha256` by hand defeats the point.

`paperchain lock`:

1. hashes every file in `References/originals/` and its converted JSON;
2. writes the hashes, page counts and a lock timestamp into `paper.toml`;
3. makes the originals, the `.txt` and the `.json` read-only (`chmod` on macOS and Linux; `os.chmod` sets the read-only attribute on Windows, so there is one code path).

`paperchain check` re-hashes and reports `source_hash_mismatch` or `text_hash_mismatch` if anything moved. `paperchain unlock` makes the files writable again and clears the lock timestamp, but it keeps the hashes so a later check still detects edits.

Read-only files protect against accidents. They do not stop a determined process running as the same user. The hash check is the part that actually detects tampering.

## What `check` does

For each source: file exists, hash matches, converted JSON exists, JSON hash matches, `.txt` and `.json` agree.

For each citation in `Paper/paper.md`:

1. the key resolves to a source;
2. the page exists in that source;
3. if a quote is present, it appears on the cited page after normalisation.

Normalisation folds case, Unicode NFKC (so `ﬁ` becomes `fi`), curly quotes, dashes, non-breaking spaces, and hyphenated line breaks (`exam-\nple`). It does not remove or add words, so a quote still has to be present.

If the quote exists on a different page, the error names that page. If it exists nowhere, the error quotes the first sixty characters and points at the source file. That is usually a copy error, or a two-column PDF whose extraction interleaved the columns.

Findings are errors and warnings. Errors block `build`. Warnings are judgement calls: a citation without a quote, a source that is never cited, a quote shorter than four words, a pending candidate, references that were never locked.

`--strict` turns `citation_without_quote` into an error, and `[check] require_quotes = true` in `paper.toml` makes it permanent for the project.

## Structured output

Every command has a stable envelope:

```json
{
  "schema_version": 1,
  "program": "paperchain",
  "version": "0.1.0",
  "command": "check",
  "ok": false,
  "exit_code": 1,
  "summary": "1 error(s), 0 warning(s) - ...",
  "errors": [
    {"code": "quote_wrong_page", "severity": "error", "message": "...", "file": "Paper/paper.md", "line": 14, "hint": "..."}
  ],
  "warnings": [],
  "data": {"stats": {}, "citations": []}
}
```

Agents route on `ok`, `errors[].code` and `data.stats`. They should not parse the prose summary, which is for humans and may change.

Error codes are stable and documented in [troubleshooting](troubleshooting.md).

## Build

`build` runs `check` first and refuses to write a document while errors remain, unless `--force`. It renders citations to author-year text, appends a reference list for cited sources (skipped if `paper.md` already has a `## References` heading), and calls pandoc with `Paper/` as the working directory so relative image paths behave. The intermediate markdown is deleted afterwards.

Pandoc is a documented requirement: `doctor` reports it, and `build` stops with `pandoc_missing` rather than producing a half-rendered file.

## What this design cannot do

- Prove a claim is true. It proves a quote exists on a page.
- Read a scanned PDF. There is no text to quote; OCR is a separate step.
- Recover a clean table or a two-column layout. Extraction quality is the weakest link. If the text is wrong, the check fails loudly rather than silently passing.
- Enforce permissions in every agent tool. Each adapter is only as strong as the tool's permission model.
- Stop a careless human. `unlock` exists and always will.

## Why the templates live inside the Python package

An installed wheel cannot reach a sibling `template/` directory. The template and the adapters ship as package data under `src/paperchain/templates/` and `src/paperchain/adapters/`, and `paperchain init` copies them out. That keeps one source of truth: fixing the rules in a release fixes them for everyone who upgrades.
