# Audit instructions: current Paperchain working tree

This archive is the current Paperchain working tree, not a release. Audit the code in this archive. Do not modify the repository; work in a temporary copy. The deliverable is a review with reproducible findings and a revision plan, not a rewrite.

`docs/audits/AUDIT-LOG.md` records earlier findings, their status and their evidence. Check there before reporting something as new; if it is already closed, say which test would have caught it. Recent rounds changed several behaviours that an older report may call a bug: a mid-document YAML block is now scanned and metadata is an allow-list, a duplicate CSL id is an error when used, `match --apply` requires an exact title, Unicode citation keys are allowed, keys must start and end with a letter or digit, NFD titles fold to the same key, and `style_problem` decides by id. Re-test those claims before assuming the old behaviour.

## Test environment: pytest and network

Auditors have repeatedly reported "pytest is not installed and the sandbox has no network". Treat that as an environment fact to work around, not as a finding about Paperchain, and do not stop the audit because of it.

1. Check what is actually available: `python --version`, `python -m pytest --version` and `python -m pip --version`.
2. If pytest or `pypdf` is missing, the archive ships universal wheels in `vendor/wheels/`. With pip, install them offline: `python -m pip install --no-index --find-links vendor/wheels pytest pypdf tomli`. No network is needed. `pypdf` is Paperchain's runtime dependency: without it many tests fail with `missing_dependency`, which is an environment gap, not a product defect.
3. Run from the repository root with the source on the path, so Paperchain itself does not need to be installed: `PYTHONPATH=src python -m pytest -q` (PowerShell: `$env:PYTHONPATH = "src"`).
4. Without network, Pandoc cannot be installed. Twelve tests skip and `build`, DOCX import and citeproc stay unverified. Report that explicitly, do not describe the suite as fully passing, and do not treat the missing executable as a defect.
5. If neither pytest nor pip is usable, say plainly that the suite could not run, then audit by reading the code and exercising the CLI paths that do not need Pandoc. Missing tooling lowers confidence; it does not excuse a report without reproductions.

Both `pyproject.toml` and the wheels require Python 3.10 or newer.

## The user's goal

The user wants to write papers with an AI agent under these constraints:

- **R1:** The AI helps draft and edit their papers.
- **R2:** It reads only the references they supplied.
- **R3:** It does not invent facts, quotes, page numbers, authors, dates or numbers. If the references do not support a claim, the claim is not written.
- **R4:** Zotero is the reference manager.
- **R5:** Citations and the bibliography are Vancouver, enforced by the project rather than by the agent's memory.
- **R6:** Complexity must justify itself.

Do not re-litigate whether the project is necessary unless new evidence changes the answer. The existing `docs/audits/AUDIT-NECESSITY.md` covers that question. This audit is about the remaining revision.

## Current state & Rewrite Blueprint

The working tree represents the state after Round 5 plus the Round 7 changes (visible re-blessing, the Zotero export locked in every project, title-based reference folders, context cards, `paperchain start`; see `docs/CHANGELOG.md` and `docs/audits/AUDIT-LOG.md`). The earlier rewrite blueprint was superseded and moved to `Dump/AUDIT-REWRITE-BLUEPRINT.md`; it is not the plan. Of its Zotero guardrail (D4), `check` already blocks citing a source with no entry in the export; only an ingestion-time alert is missing. Existing fixes in this tree include:

- `[build] style = "vancouver"` and `paperchain init --style vancouver`.
- `lock` hashes `References/library.json` and the CSL file only when a style is configured, and refuses to run while either is missing.
- `check` accepts both the older `vancouver` CSL identity and the current NLM/Vancouver identity (`nlm-citation-sequence`), requires a `<bibliography>` element, and rejects dependent styles, known other styles and unknown ids. A confirmed variant can be added to `styles/accepted-csl-ids.txt` beside the CSL file.
- Style configuration errors are reported before `pandoc_missing`.
- DOCX import writes relative image paths (`media/image1.png`) instead of absolute Windows paths, and only rewrites link targets.
- Build copies cache media into a temporary folder inside `Paper/`, validates image targets from Pandoc's AST as well as the Markdown source, rewrites media links only outside code, and no longer uses Pandoc's `--sandbox`.
- `citation_key` on each source plus `paperchain match`. `match --apply` writes only an exact normalized title; containment is a `suggestion`.
- Citation keys may contain Unicode letters, so ids such as `Peña2022` work in `paper.toml` and in `[@Peña2022]`.
- YAML metadata is an allow-list. A block that changes citations is rejected anywhere in the document, including a quoted key, an escaped key, a complex key, a one-line flow mapping, a block after a leading blank line, a blockquote, a list item and after a UTF-8 BOM. A block inside a code fence is ignored. An inline `references:` bibliography is rejected.
- `build`'s reference-list detector uses citeproc's `Bibliography` paragraph style, not a search for the word "references" in prose. A `Citeproc: citation ... not found` warning is promoted to `citation_not_in_bibliography`.
- Citation keys must start and end with a letter or digit. Duplicate CSL ids are an error when a source or citation uses the id, and a warning when the id is unused.
- Title comparison folds NFKC and NFKD and strips combining marks, so composed and decomposed accents compare equal.
- `source_metadata_mismatch` is an error once `citation_key` is set and the titles are not equal; without a key it remains a warning.
- `[build] reference_doc` is validated like `bibliography` and `csl`. `styles/accepted-csl-ids.txt` is hashed with the CSL in `csl_sha256`, and the writer adapter denies `styles/**`.
- `build` rewrites media links and checks resources only outside fenced, inline and four-space indented code. Image `data:image/...` URIs are accepted; other `data:` payloads are blocked.
- BibTeX exports are reported with a conversion command instead of a JSON parse error. A lone `References/library.bib` (no JSON, no `[build] bibliography`) is detected too.
- `paperchain start` stops at an ambiguous manuscript before converting or locking anything, and archives a second DOCX manuscript in `Dump/` instead of ingesting it as a citable source.
- Tests: with Pandoc 3.13 on `PATH` (Windows), 346 passed and 2 skipped (POSIX mode bits and symlink privileges). Without Pandoc, 335 passed and 13 skipped.

Treat these as claims to verify, not as proof. Some documentation or tests may still be stale, and the round-5 fixes have not been exercised against a real Zotero export or a fresh live monograph.

## Live test evidence

A copy of a real monograph was used for a round-3 end-to-end test with Pandoc 3.13:

- `init --adopt` added the project files without changing existing ones; the manuscript DOCX imported as 3,501 words.
- Two reference PDFs were converted; `match --apply` paired them with `Haron2023` and `Amaeze2021` from a real 28-entry Better BibTeX export.
- A temporary `[@Haron2023, p. 4: "..."]` citation verified its quote, and `build` produced a DOCX with `(Haron et al. 2023, 4)` and a reference list. With the current official Vancouver CSL it produced `(1)` and an NLM-formatted entry.
- The export contained seven entries with empty keys (`@misc{,`); Pandoc rejects the file until they are keyed. `check` reports `bibliography_bibtex_unsupported` for the lone `.bib` with the conversion command.
- `check` aggregated 25 unused CSL entries into one warning instead of 25 separate lines.
- Round 4 was verified with the test suite and by fetching https://www.zotero.org/styles/vancouver on 2026-11-14; the live file is `NLM/Vancouver: Citing Medicine 2nd edition (citation-sequence)`, id `nlm-citation-sequence`, and `style_problem` accepts it. Round 5 was verified on Windows with Pandoc 3.13 (259 passed, 2 skipped) and without Pandoc (249 passed, 12 skipped). No fresh live monograph or real Zotero export was run in round 5.

Do not use the user's real paper project for the audit; create open-access or synthetic fixtures instead.

## What needs revision, in priority order

### 1. Verify the newest fixes adversarially

These are the newest changes and the most likely place for a regression:

- **Metadata allow-list:** try an inline `references:` entry, an unknown key, a nested `author:` list, a block with only comments, and a document with a BOM. Confirm an allowed key such as `title` or `keywords` is not reported and an unknown key is. Try keys that Pandoc decodes but a plain string comparison does not, such as `"suppress\u002dbibliography"` and `? suppress-bibliography`.
- **Key punctuation:** try keys ending in `.`, `:`, `/`, `+`, `-` and `_`, both in `paper.toml` and in a citation. Confirm `check` errors and that a forced build cannot leave an unresolved citation. Also try a key that contains `:` or `.` in the middle and must still parse.
- **NFD titles:** compare composed and decomposed accents in `paper.toml`, CSL JSON and a PDF metadata title. Confirm `match`, `check` and the metadata warning agree. Try characters that NFKD strips differently, such as ligatures, `ß`, Greek tonos and Cyrillic accents.
- **YAML containers and BOM:** repeat the round-4 cases inside a blockquote and a list item, with a BOM, with an escaped key and with a complex key. Confirm a legitimate nested `author:` list is not mistaken for a top-level key.
- **Style sidecar:** add a BOM and a trailing `# comment`; lock; edit the sidecar and the CSL separately and confirm both are `csl_hash_mismatch`. Confirm the adapter denies `styles/**` and that the sidecar cannot be used to accept a differently named style by accident.
- **Indented code and data images:** try a four-space code block, an indented code block inside a list, a tab-indented block and a code block with blank lines. Confirm `build` leaves all of them alone and still rewrites the real image beside them. Confirm an image `data:` URI builds and a non-image `data:` URI is blocked.

The round-4 cases are still worth re-testing:

- **YAML metadata blocks:** try a block inside a blockquote or list item, an indented opening delimiter, `...` as the closing delimiter, a block with duplicate keys, a quoted key with escaped quotes, a flow mapping with nested braces or commas in strings, CRLF and a UTF-8 BOM, a block immediately after a heading, a block after an HTML comment, and a `---` line inside a tilde fence. Confirm `check` sees what Pandoc sees, and that a legal horizontal rule is not reported as metadata.
- **Reference-list detector:** test a custom `reference_doc`, a CSL style with `reference-section-title`, a hand-written list with a `Bibliography` style, a suppressed list in a document whose prose says "references", and Pandoc versions older than 3.13. Confirm the detector does not require a heading and does not accept prose.
- **Duplicate ids:** test a duplicate id that is matched but not cited, one cited through the internal key, one cited through `citation_key`, one in `match --apply`, and one in an export that also has a duplicate title. Run the same export through Pandoc citeproc and compare which entry it prints. Confirm `check` errors whenever the built reference could depend on the choice.
- **Exact matching:** test titles that differ only by punctuation, Unicode normalization (composed vs decomposed accents), a subtitle, a filename prefix, a year, a leading article, and two entries with the same normalized title. Confirm a containment suggestion is never applied and is visible in both human and JSON output.
- **Unicode keys:** test composed and decomposed `Peña`, a combining mark, a Greek or Cyrillic key, a key with an emoji, a key that is only digits, and a key starting with `_` or punctuation. Confirm the manifest parser, citation parser, `match`, `check` and citeproc agree on what is valid, and that `Paper/paper.md` encoding cannot make a key that parses in one place fail in another.
- **Style validation:** test a dependent style, a style with no `<bibliography>`, a style with `<bibliography>` but no citation-number, a numeric style with an unknown id and a Vancouver title, a real renamed NLM variant, and the sidecar file with a full URL, a bare id, a comment and a blank line. Decide whether the sidecar is an acceptable human opt-in or a bypass that an agent could write.
- **Code rewriting:** test backtick and tilde fences, indented fences, nested-looking fences, inline code with a media path, an HTML comment containing a media path, and a fence that is never closed. Confirm the rewrite never changes code and still rewrites the real image beside it.
- **`reference_doc`:** test absolute, `..`, a symlink or junction inside the project, a case-insensitive Windows path, a missing file and a directory. Confirm `manifest_invalid` and `reference_doc_missing` are used for the right cases.

### 2. Remaining known issues

Decide whether these are worth fixing now or should stay documented limitations:

- A project without `style` does not notice a Zotero re-export. This is documented, but the bibliography can drift silently in the author-year path.
- The style sidecar is still a trust input, even though it is now hashed and the writer adapter denies `styles/**`. Confirm that a human understands what it accepts and that no other path lets an agent write it.
- `check` still runs without Pandoc, so its YAML scan is a separate parser. Compare it with Pandoc's own metadata parse for any remaining disagreement, especially unusual flow mappings, anchors and aliases.
- `csl_sha256` now covers the CSL plus its sidecar. Check that an old project with a sidecar and a pre-round-5 lock fails loudly once and then accepts `lock --accept-changes`.

### 3. Zotero and BibTeX

The architecture is CSL JSON plus a `citation_key` mapping. Verify with a real Zotero/Better BibTeX export, not a hand-written stub:

- Duplicate ids through citeproc, including the exact entry that Pandoc prints.
- Empty keys, duplicate keys and non-ASCII titles in the `.bib` conversion path.
- Better BibTeX ids with Unicode, `_`, `:`, `.`, `+`, `/`, `-` and unusual capitalization.
- The current NLM/Vancouver CSL and any renamed variant the CSL project now serves. Confirm the documented URL and id are still current.
- Entries without authors or years, and how they reach the built reference list.
- What happens when `match` sees a short or junk PDF title, and whether the suggestion output is clear enough for a human.

### 4. Build resources after removing `--sandbox`

Build validates the Markdown/HTML source and then Pandoc's AST. Re-test whether that is sufficient:

- Reference-style Markdown images (`![alt][id]` with `[id]: path`).
- Image paths with spaces, angle brackets, URL encoding, `..`, symlinks and Windows junctions.
- Remote URLs, `file:` URLs and data URIs.
- HTML `<picture>`, `<source>`, CSS `url(...)` and raw HTML that Pandoc might process.
- Whether removing `--sandbox` lets any other resource outside `Paper/` or the cache be read.
- Whether a failed build leaves `.paperchain-build-media` behind.
- Whether the build works when `Paper/media` is a normal folder, a Windows junction and a POSIX symlink, and with `PAPERCHAIN_NO_LINKS=1`.
- Whether media links inside code fences and inline code now survive the build byte-for-byte.

### 5. Import media paths

- DOCX with one image, several images, an existing `Paper/media` folder and a repeated import with `--force`.
- Images whose names collide or contain spaces and non-ASCII characters.
- An existing draft with absolute media links from an older version.
- Windows junction, POSIX symlink and the no-link fallback.
- Whether the old `Paper/media/media/` layout from earlier imports still builds.

### 6. Tests and platform coverage

- Run the suite with and without Pandoc; run it on Windows, Linux and macOS if possible.
- Check that the new style tests do not depend on Pandoc when they do not need it.
- Look for tests that assert a behaviour only because the fixture does not exercise the real path. The "official" CSL in `tests/test_style.py` and `tests/test_audit4.py` is a hand-written stub; `tests/test_audit5.py` also uses stubs. No test uses a real Zotero export, no test runs duplicate ids through citeproc, and the reference-list prose test uses a generated DOCX.
- Check the build-resource tests cover the `--sandbox` removal.
- Report exact counts and the Pandoc version.

### 7. Documentation

Search the docs and README for stale claims after round 5:

- The metadata allow-list and the rejection of inline `references:`.
- Keys that must start and end with a letter or digit.
- Exact matching, accents and the `suggestion` status.
- Duplicate ids as errors when used.
- Unicode and NFD citation keys.
- The style sidecar, its hash and the `<bibliography>` requirement.
- `reference_doc` being contained in the project.
- Indented code and image `data:` URIs.
- The NLM/Vancouver name and URL.
- Test counts and the claim that `--sandbox` is gone.
- The difference between a style project and a styleless project for Zotero drift.

Documentation mismatch is a finding when it would make a user follow a broken workflow.

### 8. Packaging and install

- Does the wheel contain `templates/`, `adapters/` and dotfiles such as `.github/copilot-instructions.md`?
- Does `paperchain init` work from a non-editable install?
- Does `init --adopt` leave existing manuscript, reference and draft files untouched?
- Does the archive accidentally include the user's paper projects, cache, `.venv`, `.tools`, `dist` or root-level zips?

## Commands and fixtures

Use a temporary project, not the user's real monograph or Downloads folder.

Online, with the package installed:

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; source .venv/bin/activate elsewhere
python -m pip install -e ".[dev]"
python -m pytest -q
```

Offline, without installing Paperchain (see `vendor/wheels/README.md`):

```bash
python -m pip install --no-index --find-links vendor/wheels pytest pypdf tomli
PYTHONPATH=src python -m pytest -q     # PowerShell: $env:PYTHONPATH = "src"
```

Pandoc is required for DOCX import, `build` and citeproc. The archive excludes `.venv`, `.tools`, `dist`, `.git`, caches and root `*.zip` files, so install Pandoc yourself when a network is available. Without it, say which paths you could not exercise instead of guessing.

Useful end-to-end check:

```bash
paperchain init /tmp/audit --title "Audit" --style vancouver
cd /tmp/audit
# put an open-access PDF or a generated fixture under References/
# export a small CSL JSON to References/library.json
# put the official NLM/Vancouver CSL at styles/vancouver.csl
paperchain import
paperchain convert
paperchain match
paperchain match --apply
paperchain lock
paperchain check --json
paperchain build
```

Set `PAPERCHAIN_CACHE_DIR` to keep generated text out of the real OS cache. Do not use the user's copyrighted monograph or the `Preparación para colonoscopia.pdf` file; both are outside the archive and must not be read or copied.

## What counts as a finding

Report in this order:

1. A citation, quote, page or bibliography that is wrong but `check` reports `ok`, or a build that succeeds with an error.
2. A correct workflow that is blocked, especially Zotero keys, official Vancouver CSL, or images.
3. A warning where an error is needed, or an error that is easy to suppress without fixing the cause.
4. Portability, packaging or platform failure.
5. Documentation mismatch.

For each finding provide:

- severity;
- `file:line`;
- exact reproduction, including commands and input text;
- why it matters for R1–R6;
- a suggested fix;
- whether the fix changes `paper.toml`, the JSON contract or an error code.

## Do not

- Do not modify the repository; use a temporary copy.
- Do not edit `docs/audits/AUDIT.md`, `docs/audits/AUDIT-NECESSITY.md` or this file.
- Do not read the user's `Documents`, `Downloads`, `AppData` or other paper projects.
- Do not use the user's real references or manuscript as fixtures.
- Do not report the intentional limits from `docs/audits/AUDIT.md` as bugs.
- Do not recommend deleting `check` or extraction while R3 is a hard requirement.
- Do not claim a prompt-only workflow is equivalent without testing it.
- Do not call a feature overkill only because it is large; tie the judgment to R1–R6.
