# Changelog

## Unreleased - fourth audit fixes

### Fixed

- YAML metadata is now an allow-list of document keys such as `title`, `author`, `date`, `abstract`, `keywords` and `lang`. An inline `references:` bibliography, `suppress-bibliography`, `bibliography`, `csl`, `nocite` and unknown keys are `front_matter_overrides_citations` anywhere in the document, including a blockquote, a list item, an escaped key, a complex key and after a UTF-8 BOM. No new code.
- Citation keys must start and end with a letter or digit. Pandoc treats a trailing `. : / + -` as punctuation outside the key, so `Haron2023.` used to pass `check` and render as an unresolved citation. `match` refuses to write such an id, and `build` promotes `Citeproc: citation ... not found` to `citation_not_in_bibliography`.
- Title comparison uses NFKC, case folding, NFKD and stripped combining marks, so a decomposed accent from macOS metadata matches the composed form instead of raising `source_metadata_mismatch` or blocking `match`.
- `styles/accepted-csl-ids.txt` accepts a UTF-8 BOM and a ` # comment` after an id. `lock` hashes the sidecar together with the CSL in `csl_sha256`, so editing either is `csl_hash_mismatch`. The writer adapter denies edits to `styles/**`.
- Media-link rewriting and resource checks skip four-space indented code as well as fences, inline code and HTML comments. Image `data:image/...` URIs are accepted; other `data:` payloads remain blocked.
- The `lock` hint for a missing style file no longer says to run `convert` first; it names the missing CSL/export instead.

### Not changed

- No `paper.toml` schema change and no new JSON fields. Error codes are reused: `front_matter_overrides_citations` and `citation_not_in_bibliography` fire in more cases. `csl_sha256` now covers the CSL plus its optional sidecar, but the field and format are unchanged.

## Unreleased - third audit fixes

### Fixed

- `check` scans every YAML metadata block, not only one at the top, and recognises quoted keys and one-line flow mappings. `build`'s reference-list detector now looks only for citeproc's `Bibliography` paragraph style, so prose containing the word "references" can no longer hide a suppressed list. No new error code.
- A CSL id that appears more than once is an error when a source or citation uses it, because Paperchain and citeproc may choose different entries; an unused duplicate remains a warning. `match` will not apply a duplicated id. This is a severity change to `bibliography_duplicate_id`.
- `paperchain match --apply` writes only an exact normalized title. Containment is reported as a new `suggestion` status for a human to confirm. `source_metadata_mismatch` becomes an error once `citation_key` is set and the titles are not equal; without a key it stays a warning.
- Citation keys may contain Unicode letters (`Peña2022`), in the manifest and in `[…]` citations, so `match` cannot write a key that every later command rejects.
- `style_problem` decides by CSL id: an unknown numeric style is rejected even when its title starts with "Vancouver", and the style must contain a `<bibliography>` element. A confirmed variant can be accepted by listing its id in `styles/accepted-csl-ids.txt` beside the CSL file.
- `build` rewrites media links only outside code fences and code spans, so an example inside a fence is left as written. `[build] reference_doc` is now validated like `bibliography` and `csl`: an absolute path or a path outside the project is `manifest_invalid`.
- Documentation names the style currently served at https://www.zotero.org/styles/vancouver as NLM/Vancouver and describes the stricter matching and style checks.

### Not changed

- No `paper.toml` schema change and no new JSON fields. Error codes: severity changes only (`bibliography_duplicate_id`, `source_metadata_mismatch`). `paperchain match` gains the status value `suggestion`.

## Unreleased - Zotero keys, build resources and locks

### Added

- `citation_key` on each `[[sources]]` entry and the `paperchain match` command. Source keys come from filenames; Better BibTeX ids do not, so a citation could never satisfy both `check` and citeproc. `match` pairs them by title, reports unmatched, ambiguous, no-title and duplicate-title cases, and `--apply` writes `citation_key` into `paper.toml`. A citation may use either the source key or the `citation_key`; citeproc always receives the Zotero id. `citation_key` must be unique and may contain Unicode letters, digits and `_ . : / + -`.
- New error codes: `front_matter_overrides_citations`, `bibliography_missing_from_output`, `bibliography_bibtex_unsupported`, `bibliography_not_locked`, `csl_not_locked`. New warnings: `bibliography_entry_unmatched`, `bibliography_duplicate_id` (now an error when the id is used), `bibliography_duplicate_title`, `citation_key_unmatched`, `citation_key_ambiguous`, `citation_key_no_title`.
- `tests/test_audit4.py`.

### Fixed

- `build` validates image targets from Pandoc's own AST, so reference-style images (`![a][id]`), bracketed alt text and percent-encoded names are checked. Previously only inline `![alt](path)` was seen and Pandoc read the others.
- Images with `%20`, balanced parentheses, a raw space or a `./media/` prefix are accepted; a dangling `Paper/media` link explains that the cache was cleared. `import` only rewrites link targets, not prose that mentions a path, and no longer removes a junction.
- A YAML metadata block that changes citations (`suppress-bibliography`, `bibliography`, `csl`, `nocite`, ...) is an error anywhere in the document, and `build` fails with `bibliography_missing_from_output` if a citing document has no reference list. Detection uses citeproc's `Bibliography` paragraph style; a heading-alone check rejected every normal citing build, and a prose search hid a suppressed list.
- A BibTeX export is reported as `bibliography_bibtex_unsupported` with the `pandoc -f bibtex -t csljson` conversion command, instead of a JSON parse error or a silent `bibliography_missing`. A lone `References/library.bib` with no JSON is detected too, so the project no longer builds with silently unformatted citations. Duplicate CSL ids are an error when a source or citation uses the id.
- `check` reports unused CSL entries in one aggregated warning; a real 28-entry Zotero export previously produced 25 separate lines on every run.
- `style_problem` accepts `<number variable="citation-number">`, requires a `<bibliography>` element, and decides by id: it rejects dependent styles (naming the parent), known other styles such as IEEE, and unknown numeric styles that merely title themselves Vancouver.
- `lock` refuses to run while a configured style's bibliography or CSL file is missing; `check` reports an unhashed export or style as an error instead of a warning.
- The default test fixture no longer sets `PAPERCHAIN_NO_LINKS=1`, so the junction/symlink media layout is exercised; `test_audit4.py` covers the real-folder fallback explicitly.

### Not changed

- No `vancouver.csl` is bundled; the user downloads it. The official NLM/Vancouver style does not print page locators; the page remains evidence for `check`. Contract changes: `paper.toml` gains `citation_key`; `check --json` citations gain `citation_key`; new error and warning codes.

## Unreleased - Zotero drift and enforced style

### Added

- `[build] style = "vancouver"` and `paperchain init --style vancouver`. With a style set, `check` requires `References/library.json` and a CSL file, and rejects a CSL that is not a numeric style named Vancouver or NLM/Vancouver (`style_requires_bibliography`, `style_requires_csl`, `csl_not_vancouver`, `style_unknown`). `build` raises these errors even with `--force`, so it cannot silently produce author-year output.
- `lock` records `bibliography_sha256` and `csl_sha256` under `[build]` when a style is configured; `check` reports `bibliography_hash_mismatch`, `csl_hash_mismatch` and `bibliography_missing` when the Zotero export or the style changes after `lock`, and warns `bibliography_not_locked` when a style project's library exists but was never hashed. `lock --accept-changes` blesses a re-export.
- `tests/test_style.py`.

### Fixed

- The current official Zotero Vancouver style identifies itself as NLM/Vancouver (`nlm-citation-sequence`); `style_problem` now accepts that style instead of rejecting it for not being named `vancouver`.
- `test_symlink_outside_originals_is_rejected` created a symlink in `References/originals/`, which `init` does not create; the test now creates it.
- A style configuration error is now reported before `pandoc_missing`, so `build --force` refuses a broken style even on a machine without Pandoc.
- Projects without `style` keep the previous behaviour: `lock` does not hash `library.json` or a CSL file, and `check` does not enforce those hashes.
- Documentation points at https://www.zotero.org/styles/vancouver, the current source of the NLM/Vancouver CSL, instead of a removed `vancouver.csl` path.
- `import` now extracts media with `--extract-media=Paper`, so image links are relative to `Paper/` instead of absolute Windows paths.
- `build` no longer uses Pandoc's `--sandbox`, which rejects legitimate local images on current Pandoc releases. It validates image paths itself and rejects absolute, remote or outside-project paths with `pandoc_resource_blocked`. Cache media is copied into a temporary folder under `Paper/` for the build and deleted afterwards.

### Not changed

- No `vancouver.csl` is bundled; the user downloads it. The built document is not inspected, only the configuration. The official NLM/Vancouver style does not print page locators; the page remains evidence for `check`. JSON contract: new error codes only.

## Unreleased - reference categories

### Added

- `paperchain organize --into CATEGORY` and `paperchain convert --into CATEGORY` place loose PDF/DOCX files in an existing subject folder instead of `References/<key>/` (or flat in `References/`). `--into` also lets `organize` accept a loose file whose name looks like a norm, guide or template.
- `References/.paperchain-categories.json` lists extra subject folders. `organize` treats those names like `Articulos/` and `Referencias/`, so an agent can add a category without changing Paperchain. The file is tiny, human-readable and does not hold generated data.
- Generated citation keys are capped at 60 characters. A long title is cut at a word boundary and ends with an 8-character digest, so two articles with the same opening words still get different keys.
- When two files still collide, `convert` adds more of the folder path to the key (`Articulos/2024/review.pdf` becomes `articulos-2024-review`), and a path already in `paper.toml` keeps the key it already has.

### Known issues

- A per-article folder whose name is a truncated copy of a long filename (for example `References/Articulos/Some long title/Some long title.pdf`) is not recognised as the organized form, so the key repeats the title. It is left for the next audit; it does not break uniqueness.

## Unreleased - third audit fixes

An external audit of 0.3.0 found places where the verifier, the extractor and the recovery commands could still fail silently. This entry records the fixes; the error-code table in `docs/troubleshooting.md` lists the new codes.

### Fixed

- `check` now honours a backslash-escaped `<!--`, and reports citation-shaped text that Pandoc would render literally: HTML entities such as `[&#64;key]` and `[&commat;key]`, an escaped `[\@key]`, and an escaped bracket. They reuse `citation_unrecognized` rather than a new code.
- DOCX extraction reads `word/styles.xml`, so text hidden by a character style or a paragraph style (including `basedOn` inheritance) is skipped instead of verifying a quote. A style part that cannot be parsed warns with `docx_styles_ignored`.
- Quote matching rejects a leading `-` or `.` inside a number: `"-5 degrees"` no longer matches `1-5 degrees`, and `".5 mg"` no longer matches `1.5 mg`.
- Line-break hyphen joining is restricted to letters, so `10-\n20` stays a range instead of becoming `1020`.
- A manuscript path without a `sha256` is now `manuscript_unhashed`, an error, matching `source_unhashed`.
- `project_id` must be a 32-character lowercase uuid hex; absolute paths, separators and traversal are rejected before they reach the cache path.
- The OpenCode adapter no longer allows `git diff *`, which could write through `--output`; `--output`, shell metacharacters and quoted `unlock`/`init`/`convert`/`import`/`lock` are denied after the allow rules.
- `build` runs Pandoc with `--sandbox`, and a resource Pandoc refuses to read (outside the project or a remote URL) fails the build with `pandoc_resource_blocked` instead of being dropped silently.
- `init --force` and `import --force` save the draft (and `init --force` the manifest) as `*.bak` before overwriting; `doctor` and `check` hints say so.
- `convert` requires `--accept-changes` when a reference changed since the last conversion, so the unlock/convert/relock sequence no longer re-blesses a changed source silently.
- New `paperchain organize` command: plan-first sorting of an adopted folder into `Manuscript/`, `References/` and `Dump/`. It deduplicates by content, never deletes, and puts name collisions in `Dump/conflicts/`; `--apply` performs the moves and updates `paper.toml`.
- Non-Latin filenames get a stable hashed key instead of all collapsing to `doc`.
- `XXX` is a placeholder only when it stands alone on a line or sits in brackets, so "Super Bowl XXX" no longer blocks a build.
- Generic file metadata (`Administrator`, `Untitled`, and so on) is not used as an attribution; `convert` and `check` warn with `source_metadata_unconfirmed` when authors or year are missing, and `source_metadata_mismatch` when the CSL entry appears to describe a different work.
- `Manifest.save` writes through the atomic temp-file path.
- `init` expands template placeholders in one pass, so a title containing `{{date}}` is not expanded again.
- `pypdf` is bounded below 8.0 to reduce cross-version extraction drift.

### Documentation

- `README.md` no longer calls `convert` an agent command or hardcodes a local install path.
- `docs/how-it-works.md` and `docs/troubleshooting.md` describe the sandbox, the style-based hidden-text handling and the new error codes.
- `vendor/wheels/` ships universal pytest, pypdf and tomli wheels, and `docs/audits/AUDIT-INSTRUCTIONS.md` explains the offline install, so an audit without network can still run the suite instead of reporting "pytest is not installed".

## 0.3.0 - external cache and per-reference folders

### Added

- `paperchain help` prints the quick-start instructions, and `paperchain help --json` returns them as structured steps so an agent can relay them without scanning folders.
- Derived text, page maps, `INDEX.md` and build temp files now live in the OS cache (`%LOCALAPPDATA%\paperchain` on Windows) instead of inside each project. `paperchain doctor --json` reports the paths under `data.cache`, and `PAPERCHAIN_CACHE_DIR` overrides the location.
- `paperchain convert` moves loose PDF/DOCX files directly under `References/` into `References/<key>/<file>`. Nested files are left alone. `--no-organize` disables the move.
- A project gets a stable `project_id` in `paper.toml`, so its cache survives moving the project folder.

### Changed

- `paperchain init --adopt` initializes a folder that already contains a manuscript and references, adding only missing template files and never overwriting existing ones.
- `paperchain init` no longer creates `References/_text/`.
- The generated `AGENTS.md` tells the writer to read the cache paths from `paperchain doctor --json`.
- Project folders now contain only inputs, `paper.toml`, `Paper/paper.md`, `Paper/media/`, agent files and `Output/`.

## 0.2.0 — project folders, manuscript import, Zotero bibliography

### Added

- A project folder can hold the original manuscript in `Manuscript/` (or the project root). `paperchain import` converts it to `Paper/paper.md` and records its hash; the original is never edited, moved or locked. `check` reports `manuscript_hash_mismatch` if it changes later.
- Reference discovery is recursive under `References/`. Subfolders are allowed, and `References/topic/name.pdf` gets the stable key `topic-name`.
- Optional CSL JSON bibliography at `References/library.json` (or `[build] bibliography`). When present, `build` uses Pandoc citeproc, and `check` reports `citation_not_in_bibliography` for keys that Zotero does not contain.
- `[build] csl` selects a CSL style for citeproc.
- `paperchain init` creates `Manuscript/`, and generated projects now ignore manuscript and nested reference files in git.

### Changed

- `paperchain convert` and `check` scan `References/` recursively instead of only `References/originals/`.
- `paperchain import` is human-only in the OpenCode adapter.
- Reference types remain PDF, DOCX, TXT and MD; other files are ignored with a warning. PDF and DOCX are the intended formats.

## 0.1.2 — second audit fixes

An external re-audit found that the 0.1.1 tests passed but the guarantee still had holes.

### Fixed

- Scanner: an escaped backtick no longer opens a code span, and a backtick fence whose info string contains a backtick is treated as inline code. Both previously hid later citations.
- `@` followed by any non-space character is now inspected. `[@Ünknown2020]`, `[@_nobody]` and `@{nobody}` are `citation_unrecognized` instead of `ok`.
- A missing hash is always an error. Deleting `locked_at`, `sha256` and `text_sha256` together no longer downgrades the checks to warnings.
- `lock` re-extracts every original and compares it with the JSON page map, so `--accept-changes` cannot bless fabricated text. The JSON's self-declared source hash was not enough.
- Manifest paths must resolve inside `References/originals/`, keys must match `^[a-z0-9][a-z0-9-]*$`, and duplicates are rejected. Opening a hostile project no longer lets `lock` or `unlock` chmod an arbitrary file.
- chmod removes and restores write bits instead of assigning `0644`/`0444`, so `unlock` never grants a permission the file did not have.
- `[build] output` must resolve inside `Output/`.
- argparse abbreviations are disabled (`--fo` is no longer `--force`).
- The OpenCode adapter uses an allowlist of `check`, `doctor` and `build`, so quoting (`"unlock"`, `un\lock`) and a leading `--project` cannot reach a denied subcommand.
- DOCX: hidden runs, deleted text and text boxes are skipped with warnings; `noBreakHyphen` is preserved; strict OOXML namespaces work; duplicate `word/document.xml` parts and XML larger than 32 MB are rejected; a corrupt `docProps/core.xml` no longer aborts conversion.
- Symlinked references resolving outside `originals/` are rejected.
- An `@` inside a quoted span is no longer mistaken for multiple citations.
- A non-numeric `size` or `pages` is `manifest_invalid`, not an internal error.
- `lock` writes the manifest after the chmod pass, so a permission failure cannot leave `locked_at` set.
- `lock_drift` also checks the `.txt` copy.
- `check --reextract` re-extracts every original; `build` always does, so a page map forged together with the manifest cannot produce a document.

### Added

- Error codes: `docx_hidden_text_skipped`, `docx_textbox_skipped`, `docx_too_large`, `invalid_output`, `source_outside_project`, `source_unreadable`.

## 0.1.1 — first audit fixes

Fixes from an external audit. Three of them let `check` return `ok` on a citation that was wrong or never inspected.

### Fixed

- Masking: `<!--` inside a code span no longer starts a comment, and an unterminated comment or code fence is an error instead of silently hiding the rest of the draft.
- Fences: only an indent of three spaces or less opens one, and a closer must use the same character and at least the opening length.
- Pandoc-style citations that are not the supported form (`[see @key]`, `[-@key]`, a bare `@key`) are reported as `citation_unrecognized` instead of being ignored. Backslash escaping now counts runs, so `\\[@key]` is still checked.
- A missing hash while `locked_at` is set is an error, not a warning.
- `lock` refuses to bless a changed reference or converted text without `--accept-changes`.
- The `.txt` is regenerated from the anchored JSON and compared exactly; a hand edit is `text_file_mismatch`.
- Quote matching is anchored on word boundaries, and a compound broken as `well-\nknown` matches both `wellknown` and `well-known`.
- A `]` inside a quoted span no longer ends the citation early.
- Adapter: deny `unlock`, `convert`, `lock`, `init` and `--force` anywhere in the command line, so a leading `--project` cannot slip past. Deny edits to `opencode.json`, `.opencode/**`, `.gitignore` and `.gitattributes`.

### Added

- `paperchain lock --accept-changes`.
- Error codes: `citation_unrecognized`, `unterminated_comment`, `unterminated_code_block`, `text_file_mismatch`, `lock_changes`, `text_stale`.
- `check` and `lock` compare the source hash recorded inside the JSON page map with the file on disk, so a relock cannot bless text extracted from a different version.

## 0.1.0

Initial working scaffold: `init`, `convert`, `lock`, `unlock`, `check`, `build`, `doctor`; OpenCode adapter; 38 tests.
