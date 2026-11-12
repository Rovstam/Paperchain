# How it works

This document is for the human maintaining a paper and for the agent writing it. It describes what the tool guarantees and where the guarantee stops.

## The shape of a paper project

```
paper.toml            manifest: the source list, hashes and build settings
Manuscript/           the original DOCX/PDF; never edited
References/<topic>/   the PDF/DOCX/TXT/MD files you supplied; subfolders allowed
References/library.json  optional CSL JSON export from Zotero
cache (outside project)  generated text, page maps, INDEX.md, media and build temp
Paper/paper.md        the draft
Candidates/           proposed sources, awaiting a human
Output/               generated .docx
Dump/                 working material, old folders and name conflicts
AGENTS.md             the rules
```

Only `Paper/paper.md`, `Candidates/` and `Output/` are ever written by an agent, and `Output/` only through `paperchain build`.

`paperchain import` reads the original manuscript and writes `Paper/paper.md`. The original is never edited, moved or made read-only. Its hash is stored in `paper.toml`; `check` reports `manuscript_hash_mismatch` if it is replaced, and `manuscript_unhashed` if the path has no hash at all, so stale Markdown cannot be built silently. `import --force` saves the draft it replaces as `Paper/paper.md.bak`. DOCX import uses Pandoc (headings, tables and images are kept where Pandoc can represent them). PDF import extracts plain paragraphs and says so in a warning.

## Adopting a folder that already has files

`paperchain init . --adopt` adds only the missing project files; it never moves existing material. `paperchain organize` then builds a plan:

- the original DOCX/PDF goes to `Manuscript/`;
- documents in reference folders (`Referencias/`, `References/`, `Articulos/`, `Bibliografia/`, `Sources/`, `Fuentes/`, ...) go to `References/`, keeping their subfolders;
- loose PDF/DOCX files in the project root go to `References/`, unless the name looks like a guide, example, norm or template; those go to `Dump/`;
- every other file or folder (old notes, rules, examples, reviews) goes to `Dump/`.

Before planning a move, `organize` hashes the file. If the same bytes are already present anywhere under `References/`, the extra copy is archived under `Dump/` instead of being added again, so a reference tree copied by hand does not become a duplicate. Different files that would land on the same name go to `Dump/conflicts/`; nothing is overwritten and nothing is deleted. The plan is read-only by default; `--apply` performs the moves and updates `paper.toml` when the manuscript moved. Use `--manuscript PATH` when more than one candidate exists, and `--reference PATH` / `--dump PATH` to override the classification of a file or folder.

Reference paths are relative to `References/` and may be nested. A file directly in `References/` or `References/originals/` keeps its filename as the key; `References/diabetes/study.pdf` becomes `diabetes-study`.

## Why the draft is Markdown

Word files are bad diff targets. A `.docx` is a zip of XML; a small edit changes compressed bytes, so git cannot show what changed, review is impossible, and a corrupted file silently loses formatting. Pandoc reading and writing `.docx` loses comments, tracked changes and some fields.

So the draft is `Paper/paper.md`, and `paperchain build` renders it with pandoc. The Word file is an artefact, like a compiled binary: never edited, always regenerated. If you need a specific Word style, point `[build] reference_doc` at a `.docx` you have styled and pandoc will use it as the style source.

## Conversion and page maps

Each source becomes two files in the OS cache, not in the project:

- `<cache>/text/<key>.txt` — what the agent reads. A line `===== PAGE 12 =====` marks each page.
- `<cache>/text/<key>.json` — what `check` reads. It holds the pages as structured text, plus the source hash and the converter version.
- `<cache>/text/INDEX.md` — the index reported by `paperchain doctor --json` as `data.cache.index`.

The cache is `%LOCALAPPDATA%\paperchain\projects\<project-id>` on Windows, `~/Library/Caches/paperchain/...` on macOS, and `$XDG_CACHE_HOME/paperchain/...` on Linux. Set `PAPERCHAIN_CACHE_DIR` to override it. `Paper/media/` is a junction/symlink to the cache media folder when the OS allows it, so links in `paper.md` remain `media/...`; otherwise it is a normal folder. Loose PDF/DOCX files directly in `References/` are moved into `References/<key>/` before conversion; nested files are left alone.

PDFs are extracted with pypdf. DOCX is read directly from `word/document.xml` with the standard library, so there is no dependency and no round-trip. Runs marked hidden, deleted text and text-box contents are skipped, because a reader does not see them; hidden formatting is read from both direct run properties and `word/styles.xml` (character and paragraph styles, including `basedOn` inheritance). `noBreakHyphen` becomes a hyphen. A zip with two document parts, or an XML part larger than 32 MB, is rejected. TXT and MD are read as-is.

Word has no fixed pages, so a DOCX becomes a single page and the citation page is always `p. 1`. That is honest but weak; export to PDF when page-level evidence matters.

## The manifest and the lock

`paper.toml` is written by the tool. `title`, `authors` and `year` are safe for a human to edit; changing `sha256` by hand defeats the point.

`paperchain lock`:

1. hashes every converted reference under `References/` and its converted JSON;
2. re-extracts every original and compares the result with the JSON page map, so a hand-edited page map cannot be blessed;
3. compares the hashes with the ones already recorded, and refuses to continue if a file changed unless you pass `--accept-changes`;
4. writes the hashes, page counts and a lock timestamp into `paper.toml`;
5. makes the originals, the `.txt` and the `.json` read-only (`chmod` on macOS and Linux; `os.chmod` sets the read-only attribute on Windows, so there is one code path).

Step 2 is why `--accept-changes` cannot launder fabricated text: the original is the reference, not the JSON. Step 5 only removes write permission; it never grants a permission the file did not already have.

The comparison in step 3 is what stops `lock` from silently blessing an edit made after `unlock`. `--accept-changes` is the explicit opt-in; the old hashes are then replaced. `convert` applies the same rule: when a source's bytes changed since the last conversion it stops with `convert_changes` unless `--accept-changes` is passed, so the unlock/convert/relock sequence is deliberate rather than silent.

`paperchain check` re-hashes and reports `source_hash_mismatch` or `text_hash_mismatch` if anything moved. `paperchain unlock` makes the files writable again and clears the lock timestamp, but it keeps the hashes so a later check still detects edits. A missing hash is always an error: a reference the tool cannot hash is a reference it cannot verify.

Read-only files protect against accidents. They do not stop a determined process running as the same user. The hash check is the part that actually detects tampering.

`paper.toml` is the trust root. It is writable by the human and denied to the agent. Anyone who can rewrite both the manifest and the reference files can defeat a local checker; no self-contained tool can prevent that. If that matters, commit the project to a private repository and compare the manifest across commits. The tool's job is to make an accidental or agent-driven change visible, not to defend against the person who owns the machine.

## What `check` does

The original manuscript, if one was imported, is hashed and must still match `paper.toml`. For each source: file exists, hash matches, converted JSON exists, JSON hash matches, and the `.txt` is regenerated from the JSON and compared exactly. The `.txt` is the file the writer reads, so a hand-edited copy is an error, not a warning.

For each citation in `Paper/paper.md`:

1. the key resolves to a source;
2. the page exists in that source;
3. if a quote is present, it appears on the cited page after normalisation, anchored on word boundaries.

Citation parsing masks fenced code, inline code and HTML comments in one left-to-right pass, so a `<!--` inside a code span cannot swallow the rest of the draft. An unterminated comment or fence is an error. Any `@key` that no strict citation covers (`[see @key]`, `[-@key]`, a bare `@key`) is reported as `citation_unrecognized` rather than ignored.

`check --reextract` also re-extracts every original and compares it with the JSON page map. It is slower, so it is opt-in for `check`, but `build` always uses it: the document you ship is built from text verified against the source bytes, not against a manifest that could have been edited.

Normalisation folds case, Unicode NFKC (so `ﬁ` becomes `fi`), curly quotes, dashes, non-breaking spaces, and hyphenated line breaks (`exam-\nple`). A quote must also start and end on a word boundary, so `"not be ruled out"` does not match inside `"cannot be ruled out"`. If the text breaks a real compound as `well-\nknown`, both `wellknown` and `well-known` are tried.

If the quote exists on a different page, the error names that page. If it exists nowhere, the error quotes the first sixty characters and points at the source file. That is usually a copy error, or a two-column PDF whose extraction interleaved the columns.

Findings are errors and warnings. Errors block `build`. Warnings are judgement calls: a citation without a quote, a source that is never cited, a quote shorter than four words (an error under `--strict`), a pending candidate, references that were never locked.

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

`build` runs `check` first and refuses to write a document while errors remain, unless `--force`. If `References/library.json` exists (or `[build] bibliography` is set), it removes the verification quotes, keeps the page locators, and lets Pandoc citeproc format the citations and bibliography from the CSL JSON. Otherwise it renders citations to author-year text and appends a reference list for cited sources (skipped if `paper.md` already has a `## References` heading). It calls pandoc with `Paper/` as the working directory and `--sandbox`, so relative image paths work but files outside the project and remote URLs cannot be embedded; a blocked resource fails the build with `pandoc_resource_blocked`. The intermediate markdown is deleted afterwards.

Citeproc output is static formatted text, not live Zotero fields. Use the Zotero Word plugin when fields must refresh inside Word. The project currently emits DOCX only.

Pandoc is a documented requirement: `doctor` reports it, and `build` stops with `pandoc_missing` rather than producing a half-rendered file.

## What this design cannot do

- Prove a claim is true. It proves a quote exists on a page.
- Read a scanned PDF. There is no text to quote; OCR is a separate step.
- Recover a clean table or a two-column layout. Extraction quality is the weakest link. If the text is wrong, the check fails loudly rather than silently passing.
- Enforce permissions in every agent tool. Each adapter is only as strong as the tool's permission model.
- Stop a careless human. `unlock` exists and always will.

## Why the templates live inside the Python package

An installed wheel cannot reach a sibling `template/` directory. The template and the adapters ship as package data under `src/paperchain/templates/` and `src/paperchain/adapters/`, and `paperchain init` copies them out. That keeps one source of truth: fixing the rules in a release fixes them for everyone who upgrades.
