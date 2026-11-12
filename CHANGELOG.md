# Changelog

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
