# Audit brief

You are auditing **paperchain 0.1.0**, a small Python tool and agent-rule template for writing papers strictly from a fixed reference set. Be adversarial. The tool's only real value is its guarantee; if the guarantee can be broken silently, the rest does not matter.

This file is written by the author for the auditor. It is not part of the product.

## What the tool claims

1. After `paperchain lock`, the reference set is frozen: originals are hashed, and `check` recomputes those hashes.
2. Converted text is anchored to the originals: `text_sha256` hashes the JSON page map, and `check` also compares the `.txt` copy against the JSON.
3. Every citation key resolves to a source in `paper.toml`.
4. Every cited page exists in that source.
5. A quoted span appears on the cited page after normalisation (case, NFKC, smart punctuation, whitespace, hyphenated line breaks).
6. Any error blocks `paperchain build`, unless `--force`.
7. Through the OpenCode adapter, the writer agent cannot edit references, the manifest, the rules, or the output; it cannot run `paperchain unlock`.
8. `check` is deterministic, offline, and emits one JSON object with stable error codes.

Your job is to find the smallest realistic scenario where one of these is false.

## Read in this order

1. `README.md` — the promise and the stated limits.
2. `docs/how-it-works.md` — the design and threat model as the author understands it.
3. `src/paperchain/check.py` — the verifier. This is the product.
4. `src/paperchain/citations.py` — syntax parsing, normalisation, rendering.
5. `src/paperchain/locking.py`, `src/paperchain/manifest.py` — hashes and the manifest.
6. `src/paperchain/extract.py` — PDF/DOCX extraction and page maps.
7. `src/paperchain/convert.py`, `src/paperchain/build.py` — the two writers.
8. `src/paperchain/templates/paper/AGENTS.md.tmpl`, `src/paperchain/adapters/opencode/*` — the rules and the guardrail.
9. `tests/` — what is actually exercised.

## Set up

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

Expected: 85 passed on Linux and macOS; on Windows, 83 passed and 2 skipped (POSIX mode bits and symlink creation). One more test skips if `pandoc` is not installed; install pandoc to exercise `build`.

Two external audits found issues; see `CHANGELOG.md` 0.1.1 and 0.1.2. Re-test those before looking for the next class.

Manual end-to-end check:

```bash
paperchain init /tmp/audit --title "Audit"
cd /tmp/audit
# put a PDF, DOCX, TXT or MD file in References/originals/
paperchain convert
paperchain lock
paperchain check --json
paperchain build
```

## Attack these specifically

### 1. The hash chain

- Can a reference change after `lock` and still pass `check`? Consider editing `paper.toml` as well as the file, regenerating `_text`, or re-running `lock`.
- `text_sha256` covers the JSON, not the `.txt`. Is there a path where the agent quotes text that is in the `.txt` but not the JSON, and check still passes?
- `check` uses `source.pages` from the manifest in some places and the actual JSON page count in others. Can they disagree harmfully?
- Does `unlock` leave enough information to detect a later edit?
- TOCTOU: `check` hashes a file in one pass and possibly reads it in another. Does it matter for a local, single-user tool?
- Windows: case-insensitive paths, junctions, replacing a read-only file, deleting a read-only file.

### 2. The citation parser

- `CITATION_RE` and `BODY_RE` in `citations.py`. Find text that a human reads as a citation but `check` ignores, and text that `check` treats as a citation but a human would not.
- Nested brackets, a `]` inside a quote, escaped brackets, code fences, inline code, multi-line HTML comments, CRLF, a UTF-8 BOM.
- A citation split across two lines. A quote containing a straight quote inside a curly-quoted span.
- Does masking code change offsets or line numbers?
- Is `[...]` without `@` ignored safely?

### 3. Quote matching

- `normalize_for_match` folds case, NFKC, dashes and whitespace, and removes line-break hyphenation. Can two materially different strings normalise to the same thing?
- Substring matching means a short generic quote can match anywhere. Is the four-word warning enough, and is the warning easy to ignore?
- A quote that spans two pages. A quote duplicated on many pages. A page whose extraction interleaves columns.
- `verify_quote` searches all pages, then reports `quote_wrong_page`. Could that hide a genuinely wrong citation?
- Does a quote ever get rendered into the document (it should not)?

### 4. Windows and POSIX

- `locking.py` uses `os.chmod` with `0o444` / `0o644` on both platforms. Is that correct on Windows for files, directories, and already-read-only files?
- `util.write_text` writes a temp file and replaces the target. What happens if the target is read-only?
- Paths are stored POSIX-style in `paper.toml` and resolved with `project.root / path`. Any traversal or case-sensitivity issue?
- `.gitattributes` forces LF. Does that actually protect the hash, or can checkout settings override it?

### 5. The adapter

- OpenCode V2 evaluates `permissions` in order and the last match wins. Verify that `paperchain *` does not win over `paperchain unlock*`.
- Does the shell scanner see the command the same way on PowerShell and Bash? Can `paperchain unlock` be reached indirectly (aliases, `cmd /c`, quoting, a script file)?
- Are agent-level rules appended after global rules as documented? Does `default_agent: writer` work if the agent is only defined in `.opencode/agents/`?
- The adapter is marked `tested = false` on purpose. The enforcement checklist in `docs/adapters.md` has not been run.

### 6. Packaging and init

- Does the wheel contain `templates/` and `adapters/`? Does `paperchain init` work from a non-editable install?
- `init` renames `gitignore`, `gitattributes` and `*.tmpl`, and substitutes `{{program}}`, `{{title}}`, `{{slug}}`, `{{date}}`. Any file where substitution corrupts content?
- `init --force` over an existing project overwrites template files. Is the failure mode acceptable?
- Adapter `target` paths come from a packaged `adapter.toml`. Is a path-traversal adapter possible if a third party ships one?

### 7. Tests

- Which part of the guarantee has no test?
- Are there mutations the tests assert are detected, but only because the test mutates in a way the product would notice for another reason?
- Anything platform-specific that only runs in CI, and therefore may be untested locally?

### 8. Manifest paths and build output

- Can a crafted `paper.toml` make `lock`, `unlock` or `build` touch a file outside the project? Try absolute paths, `..`, a key containing separators, a symlink, and a case-insensitive Windows path.
- Does `unlock` ever grant a permission the file did not have?
- Can a failed chmod leave `locked_at` set with writable files?

### 9. DOCX extraction

- Hidden runs, deleted text, text boxes, duplicate `word/document.xml` entries, strict OOXML namespaces, and oversized XML.
- Does the extracted text match what a reader sees? A quote from hidden text must never verify.

## Intentional limits — do not report these as bugs

- `check` cannot prove a claim is true or fairly paraphrased. It proves a quote exists on a page.
- No OCR. Scanned PDFs raise `pdf_no_text`; the hint says to OCR first.
- Two-column PDFs and tables extract badly. Failures are loud, not silent.
- DOCX has no fixed pages, so a Word source becomes page 1.
- Citation rendering is author-year only, with the key as fallback. No APA/MLA/Chicago.
- Only the OpenCode adapter ships. Claude Code and Codex are documented as not shipped.
- `unlock` exists and always will. A human can defeat any lock.
- There is no network access and no telemetry.
- No git history is included in the archive; it is an uncommitted working tree snapshot.

## What counts as a finding

Report, in this order of severity:

1. **Breaks the guarantee.** A citation, quote or page that is wrong but `check` reports `ok`. A reference that changes without an error. A build that succeeds while errors exist.
2. **False alarm.** Correct input rejected, or a legitimate workflow blocked. Include the smallest input.
3. **Weakening.** A warning where an error is needed, or an error that is easy to suppress without fixing the cause.
4. **Portability or packaging.** Works on the author's machine, breaks on another OS or a clean install.
5. **Documentation mismatch.** A claim in `README.md` or `docs/how-it-works.md` that the code does not support.

For each finding give: severity, `file:line`, exact reproduction (commands and input text), why it matters, and a suggested fix. Say explicitly if the fix would change the JSON contract or the error codes.

Do not rewrite the project. The deliverable is a review.

## Suggested prompt

> Audit the attached paperchain repository against `AUDIT.md`. Work through the list under "Attack these specifically". You may run the tests and the CLI. Report only reproducible findings, worst first, with file:line and a minimal reproduction. Do not report the intentional limits as bugs.
