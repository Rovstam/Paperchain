# Audit brief

You are auditing **paperchain 0.3.0**, a small Python tool and agent-rule template for writing papers strictly from a fixed reference set. Be adversarial. The tool's only real value is its guarantee; if the guarantee can be broken silently, the rest does not matter.

This file is written by the author for the auditor. It is not part of the product.

## What the tool claims

1. After `paperchain lock`, the reference set is frozen: every original and its converted page map is hashed, and `check` recomputes both hashes.
2. Converted text is anchored to the originals: `text_sha256` hashes the JSON page map, `check` regenerates the `.txt` from that JSON and compares it exactly, and `lock`/`build` re-extract each original and compare it with the JSON.
3. The imported original manuscript is unchanged: `paperchain import` records its path and hash in `paper.toml`, and `check` recomputes the hash.
4. Every citation key resolves to a source in `paper.toml`, and to an entry in `References/library.json` when that CSL JSON bibliography is present.
5. Every cited page exists in that source.
6. A quoted span appears on the cited page after normalisation (case, NFKC, smart punctuation, whitespace, hyphenated line breaks).
7. Any error blocks `paperchain build`, unless `--force`.
8. Through the OpenCode adapter, the writer agent cannot edit references, the manuscript, the manifest, the rules or the output, and cannot run `paperchain unlock`, `import`, `convert`, `lock` or `init`.
9. `check` is deterministic, offline, and emits one JSON object with stable error codes.

Generated text, page maps, `INDEX.md`, manuscript media and build temp files live outside the project in the OS cache. `paperchain doctor --json` reports the paths under `data.cache`; `PAPERCHAIN_CACHE_DIR` overrides the location. The cache is derived state, not a second trust root.

## Read in this order

1. `README.md` — the promise and the stated limits.
2. `docs/how-it-works.md` — the design and threat model as the author understands it.
3. `src/paperchain/check.py` — the verifier. This is the product.
4. `src/paperchain/citations.py` — syntax parsing, normalisation, rendering.
5. `src/paperchain/locking.py`, `src/paperchain/manifest.py` — hashes and the manifest.
6. `src/paperchain/extract.py` — PDF/DOCX extraction and page maps.
7. `src/paperchain/convert.py`, `src/paperchain/build.py`, `src/paperchain/import_cmd.py` — the writers.
8. `src/paperchain/project.py`, `src/paperchain/locations.py` — paths, validation and the cache.
9. `src/paperchain/templates/paper/AGENTS.md.tmpl`, `src/paperchain/adapters/opencode/*` — the rules and the guardrail.
10. `tests/` — what is actually exercised.

## Set up

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

Expected: 132 passed with `pandoc` on `PATH` on Windows (Linux/macOS: 134 passed); Windows skips 2 (POSIX mode bits and symlink creation) and Linux/macOS skip 0. Without `pandoc`, 5 more tests skip on any OS (DOCX import, build, and the build-sandbox test), leaving 127 passed and 7 skipped on Windows (129 passed and 5 skipped on Linux/macOS). CI installs pandoc on Ubuntu, macOS and Windows.

The archive excludes `.venv`, `.tools`, `dist`, `.git`, root-level `*.zip` archives and caches, so install pandoc yourself to exercise `build` and DOCX import. The audit workspace must be writable. Set `PAPERCHAIN_CACHE_DIR` to a temporary folder if you want the generated text kept out of your real OS cache.

Three external audits found issues; see `CHANGELOG.md` 0.1.1, 0.1.2 and the Unreleased section (the 0.3.0 fixes). Re-test those before looking for the next class.

Manual end-to-end check:

```bash
paperchain init /tmp/audit --title "Audit"
cd /tmp/audit
# put a PDF, DOCX, TXT or MD file under References/ (loose PDF/DOCX files are moved into References/<key>/)
# optionally put an original DOCX/PDF in Manuscript/ or the project root
paperchain import        # optional, if there is a manuscript
paperchain convert
paperchain lock
paperchain check --json
paperchain build
```

## Attack these specifically

### 1. The hash chain

- Can a reference change after `lock` and still pass `check`? Consider editing `paper.toml` as well as the file, regenerating the cache text, and re-running `convert` or `lock`.
- `text_sha256` covers the JSON, not the `.txt`. Is there a path where the agent quotes text that is in the `.txt` but not the JSON, and check still passes? Which file does the writer read?
- `check` uses the JSON page count for range checks; `source.pages` in the manifest is only informational. Can they disagree harmfully?
- The manuscript is imported, not locked. What does `check` do when `[manuscript]` has a path but no `sha256`? What if the path is absolute, outside the project, or points at a directory?
- Does `unlock` leave enough information to detect a later edit? What happens if `locked_at`, `sha256` and `text_sha256` are removed together?
- TOCTOU: `check` hashes a file in one pass and possibly reads it in another. Does it matter for a local, single-user tool?
- Windows: case-insensitive paths, junctions, replacing or deleting a read-only file.
- The cache is outside the project and keyed by `project_id` from `paper.toml`. Can that string steer `text_dir`, `tmp_dir` or the media directory outside the cache? Try `..`, separators and absolute paths. What would `lock` or `unlock` then chmod?

### 2. The citation parser

- `CITATION_RE` and `BODY_RE` in `citations.py`. Find text that a human reads as a citation but `check` ignores, and text that `check` treats as a citation but a human would not.
- Nested brackets, a `]` inside a quote, escaped brackets, code fences, inline code, multi-line HTML comments, CRLF, a UTF-8 BOM.
- A citation split across two lines. A quote containing a straight quote inside a curly-quoted span.
- Does masking code change offsets or line numbers?
- Pandoc decodes HTML entities and backslash escapes before it writes the `.docx`. Can text that `check` never parses still appear as a citation-shaped string in the built document? Try `&#64;`, `&commat;`, `\@` and `\[`.
- Is `[...]` without `@` ignored safely? Is every bare `@key` reported?

### 3. Quote matching

- `normalize_for_match` folds case, NFKC, dashes and whitespace, removes soft hyphens, and joins line-break hyphenation. Can two materially different strings normalise to the same thing?
- `_find_span` enforces a word boundary only when the first or last character is alphanumeric. Can a quote that starts or ends with punctuation match inside a longer word or number?
- Substring matching means a short generic quote can match anywhere. Is the four-word warning enough, and is the warning easy to ignore by default?
- A quote that spans two pages. A quote duplicated on many pages. A quote inside a page range. A page whose extraction interleaves columns.
- `verify_quote` searches all pages, then reports `quote_wrong_page`. Could that hide a genuinely wrong citation, especially when the citation gives a range?
- Does a quote ever get rendered into the document? Check both the built-in author-year renderer and the citeproc path.

### 4. Windows and POSIX

- `locking.py` uses `os.chmod` with mode bits on both platforms. What happens to a file that was already read-only before `lock`, after `lock`, and after `unlock`? Does `unlock` ever grant a permission the file did not have?
- `util.write_text` writes a temp file and replaces the target, but the product mostly writes directly. What happens when a target is read-only, open in Word, or on a different filesystem?
- Paths are stored POSIX-style in `paper.toml` and resolved with `project.root / path`. Any traversal, case-sensitivity or junction issue? What if `References/` itself is a link to another folder?
- `.gitattributes` forces LF. Does that actually protect any hash, or are all hashed files gitignored binaries and out-of-project cache text?
- Are the cache `.txt`/`.json` files protected the same way as the originals? What does `check` do if they are writable?

### 5. The adapter

- OpenCode V2 evaluates `permissions` in order and the last match wins. The v2.2.6 matcher converts `*` to `.*` and anchors the pattern with `^...$`, case-insensitively. Verify that `paperchain *` does not win over `paperchain unlock*`.
- Given the allow rule `paperchain* check*` and a matcher where `*` matches anything, what does `paperchain check; <any command>` match? What about `paperchain build && <any command>`, a newline, or a subshell? Do the trailing deny rules catch it?
- Does the shell scanner see the command the same way on PowerShell and Bash? Can `paperchain unlock` be reached indirectly (aliases, `cmd /c`, quoting, a script file)?
- Are agent-level rules appended after project rules as documented? Does `default_agent: writer` work if the agent is only defined in `.opencode/agents/`? Use `opencode debug config` and `opencode debug agents` to inspect the merged result without calling a model.
- Are `edit` resources matched as project-relative paths or absolute paths? Which paths under `Paper/` are writable, and does `check` verify what can be written there, for example `Paper/media/`?
- The adapter is marked `tested = false` on purpose. The enforcement checklist in `docs/adapters.md` has not been run.

### 6. Packaging and init

- Does the wheel contain `templates/`, `adapters/` and dotfiles such as `.github/copilot-instructions.md`? Does `paperchain init` work from a non-editable install?
- `init` renames `gitignore`, `gitattributes` and `*.tmpl`, and substitutes `{{program}}`, `{{title}}`, `{{slug}}`, `{{date}}`. Any file where substitution corrupts content, especially when the title itself contains one of those placeholders?
- `init --force` over an existing project overwrites template files. What happens to `paper.toml`, `Paper/paper.md`, the draft and the lock state? Is `doctor`'s recovery hint safe? What about `init --adopt` on an already initialized project?
- Adapter `target` paths come from a packaged `adapter.toml`. Can a third-party adapter write outside the new project with an absolute path or `..`? Can its `source` path escape the adapter folder?

### 7. Tests

- Which part of each claim has no test?
- Are there mutations the tests assert are detected, but only because the test mutates in a way the product would notice for another reason?
- Anything platform-specific that only runs in CI, and therefore may be untested locally? Which tests skip without pandoc?

### 8. Manifest paths and build output

- Can a crafted `paper.toml` make `lock`, `unlock`, `build`, `convert` or `doctor` touch a file outside the project? Try absolute paths, `..`, a key containing separators, `project_id`, a symlink or junction, and a case-insensitive Windows path.
- Does `unlock` ever grant a permission the file did not have?
- Can a failed chmod or a failed manifest save leave `locked_at` set with writable files, or files read-only with no lock?
- `[build] output` must resolve inside `Output/`. What about `[build] reference_doc`, `bibliography` and `csl`? What does `build` pass to pandoc, and can a relative image path or a URL reach outside the project?

### 9. DOCX extraction

- Hidden runs, deleted text, text boxes, duplicate `word/document.xml` entries, strict OOXML namespaces, oversized XML, footnotes, endnotes and headers/footers.
- Hidden formatting can come from direct run properties, a character style, a paragraph style, paragraph-mark properties, `specVanish`, or table-row properties. Which of these are actually skipped, and which still verify a quote?
- Does the extracted text match what a reader sees? A quote from hidden text must never verify.
- Are skipped constructs reported loudly enough? `convert` warnings are not repeated by `check` or `build`.

### 10. Import, bibliography and CSL

- `import` records the manuscript path and hash. Can a manifest with a path but no hash, or a hash but no path, pass `check`? What happens if the manuscript is replaced, moved, or a different file is passed explicitly?
- With `References/library.json` present, `check` requires each citation key in the CSL JSON. Does anything verify that the CSL entry describes the same work as the PDF under that key? What does the built citation say if they disagree?
- Does `build` still use citeproc with `--force` and an unknown key? Does `render_markdown_for_citeproc` keep the page locator and drop the quote correctly?
- Can a CSL JSON `id` with unusual characters collide with a source key or break the citation?

## Intentional limits — do not report these as bugs

- `check` cannot prove a claim is true or fairly paraphrased. It proves a quote exists on a page.
- No OCR. Scanned PDFs raise `pdf_no_text`; the hint says to OCR first.
- Two-column PDFs and tables extract badly. Failures are loud, not silent.
- DOCX has no fixed pages, so a Word source becomes page 1.
- Citation rendering is author-year only, with the key as fallback. No APA/MLA/Chicago.
- Only the OpenCode adapter ships. Claude Code and Codex are documented as not shipped.
- `unlock` exists and always will. A human can defeat any lock.
- `check` makes no network calls, and there is no telemetry. `build` invokes pandoc, which is a documented external dependency.
- Figures and images are not verified by `check`. `Paper/media/` holds extracted manuscript images; `build` embeds whatever the Markdown references.
- The cache is derived state. Deleting it requires a re-convert; it is not a second trust root.
- No git history is included in the archive; it is an uncommitted working tree snapshot.

## What counts as a finding

Report, in this order of severity:

1. **Breaks the guarantee.** A citation, quote or page that is wrong but `check` reports `ok`. A reference or manuscript that changes without an error. A build that succeeds while errors exist.
2. **False alarm.** Correct input rejected, or a legitimate workflow blocked. Include the smallest input.
3. **Weakening.** A warning where an error is needed, or an error that is easy to suppress without fixing the cause.
4. **Portability or packaging.** Works on the author's machine, breaks on another OS or a clean install.
5. **Documentation mismatch.** A claim in `README.md` or `docs/how-it-works.md` that the code does not support.

For each finding give: severity, `file:line`, exact reproduction (commands and input text), why it matters, and a suggested fix. Say explicitly if the fix would change the JSON contract or the error codes.

Do not rewrite the project. The deliverable is a review.

## Suggested prompt

> Audit the attached paperchain 0.3.0 repository against `AUDIT.md`. Work through the list under "Attack these specifically". You may run the tests and the CLI. Report only reproducible findings, worst first, with file:line and a minimal reproduction. Do not report the intentional limits as bugs. There is no git history; treat the working tree as the submission.
