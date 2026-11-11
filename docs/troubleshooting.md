# Troubleshooting

Run `paperchain doctor --json` first. It checks Python, pypdf, pandoc, OCR, the lock state, the adapter and whether `check` passes.

Every error has a stable code in the JSON output. Use the code, not the prose, when searching this page.

## Setup

| Symptom | Fix |
| --- | --- |
| `paperchain: command not found` | `pipx ensurepath`, then open a new terminal. On Windows use `py -m pipx install .`. |
| `paperchain` runs an old version | `pipx install --force .`, or `pipx upgrade paperchain`. |
| `pandoc_missing` | Install pandoc (`winget`, `brew`, or `apt`) and reopen the terminal. Only `build` needs it. |
| `doctor` reports `python 3.9` | pipx used an old interpreter. Reinstall with a 3.10+ interpreter: `pipx install --python python3.12 .`. |
| OpenCode ignores the permissions | Confirm you opened the project folder itself, so `opencode.json` is discovered, and check the adapter status in the README. Permissions are a guardrail; `check` is the guarantee. |

## Project and manifest

| Code | Meaning |
| --- | --- |
| `project_not_found` | No `paper.toml` in this folder or a parent. Pass `--project DIR` or run `paperchain init`. |
| `manifest_missing` | `paper.toml` was deleted. Restore it; the hashes cannot be rebuilt without it. |
| `manifest_invalid` | TOML is malformed, a key is not a lowercase slug, a key is duplicated, or a `path` is absolute or resolves outside `References/`. |
| `manifest_version` | The project was written by a newer paperchain. Upgrade the tool. |
| `already_initialized` | `init` found a `paper.toml`. Use `--force` only if you mean to overwrite template files. |
| `destination_not_empty` | Choose an empty folder, or pass `--force`. |
| `unknown_adapter` | `init --agent X` where X does not exist. `paperchain init --help` lists the default; the adapters live inside the package. |

## Manuscript import

| Code | Meaning |
| --- | --- |
| `manuscript_missing` | No DOCX/PDF found in the project root or `Manuscript/`. Put one there, or pass its path. |
| `manuscript_ambiguous` | More than one possible manuscript was found. Keep one, or pass the exact path. |
| `manuscript_outside_project` | The original must stay inside the project so its hash can be checked later. |
| `paper_exists` | `Paper/paper.md` already has your edits. Edit it directly, or pass `--force` to replace it from the original. |
| `manuscript_hash_mismatch` | The original changed after import. Re-run `paperchain import --force`, then review the Markdown before building. |
| `pandoc_missing` | DOCX import needs Pandoc. Install it, or export the manuscript as PDF/TXT for a plain-text import. |
| `unsupported_manuscript` | Only DOCX, PDF, MD and TXT manuscripts are imported. |
| `manuscript_empty` | The imported file has no text. A scanned PDF needs OCR first. |
| `import_failed` | Pandoc could not read the DOCX. Re-export it and try again. |
| `pdf_import_plain_text` (warning) | A PDF manuscript is imported as plain paragraphs; headings and images are not reconstructed. |
| `bibliography_missing` / `bibliography_invalid` | `References/library.json` is absent or not CSL JSON. Export it again from Zotero. |
| `citation_not_in_bibliography` | A citation key is not in the CSL JSON. Add the item in Zotero, export again, or fix the key. |

## References and conversion

| Code | Meaning |
| --- | --- |
| `no_references` | `References/` is missing. Create it and add files, in subfolders if you like. |
| `unsupported_type` | Only PDF, DOCX, TXT and MD are read. Convert other formats first. |
| `pdf_encrypted` | Export an unlocked copy. |
| `pdf_no_text` | The PDF is a scan. Run OCR first: `ocrmypdf in.pdf out.pdf`, then convert. |
| `pdf_blank_pages` (warning) | Some pages have no text. Quotes from those pages cannot be verified. |
| `docx_unreadable` | Not a real `.docx`, or a corrupt zip. Re-export it. |
| `docx_footnotes_ignored` (warning) | Footnotes are not extracted in this version. Move needed text into the body. |
| `docx_hidden_text_skipped` (warning) | Runs marked hidden were skipped. A reader cannot see them, so they are not citable. |
| `docx_textbox_skipped` (warning) | Text inside text boxes was skipped. Move it into the body to cite it. |
| `docx_too_large` | The compressed document expands past the 32 MB XML limit. Export a text-only copy. |
| `source_outside_project` | A file under `References/` is a link to a target outside the folder. Copy the file in instead. |
| `source_unreadable` | A path could not be resolved, usually a broken link. |
| `key_collision` | Two files map to the same key. Rename one, for example `study-2024.pdf` and `study-2024-supplement.pdf`. Files in different subfolders normally avoid this because the folder becomes a key prefix. |
| `unknown_source` | `convert --only KEY` and no file has that key. |
| `project_locked` | The reference set is locked. Run `paperchain unlock`, convert, then `paperchain lock`. |
| `lock_failed` | A source is missing or was never converted. Run `convert` first. |
| `file_read_only` | Writing to a locked file. Unlock first, and only if you mean to. |
| `permission_failed` | The OS refused a permission change. Close the file in Word or Explorer, or check ownership. |

## Hashing and the lock

| Code | Meaning |
| --- | --- |
| `source_hash_mismatch` | An original changed after locking. Restore the file from backup; do not simply relock, because the old quotes were verified against the old bytes. |
| `text_hash_mismatch` | `References/_text/*.json` was edited after conversion. Regenerate: unlock, `convert --force`, lock. |
| `text_stale` | The converted JSON was built from a different version of the original than the one on disk, or a fresh extraction disagrees with it. Run `convert --force`; a relock must not bless stale text. Use `check --reextract` to catch a page map that was edited along with the manifest. |
| `source_unhashed` / `text_unhashed` | The manifest has no hash for this source. Always an error: an unhashed reference cannot be verified. Run `convert`, or restore `paper.toml`. |
| `text_missing` / `text_invalid` | Conversion output is missing or corrupt. Run `convert --force`. |
| `text_file_missing` | The `.txt` the agent reads is missing. Run `convert --force`. |
| `text_file_mismatch` | The `.txt` no longer matches the hashed page map, so the writer may be reading edited text. Run `convert --force`; do not hand-edit the `.txt`. |
| `unmanaged_source` | A file appeared under `References/` without `convert`. Run `convert`, then `lock`. |
| `references_not_locked` (warning) | Run `paperchain lock` once the sources are final. |
| `lock_drift` (warning) | Files became writable again. Run `lock`. |
| `lock_changes` | `lock` found a reference or its converted text changed since the last lock. Inspect the change, then re-run with `--accept-changes` if it is intended. |

## Citations and quotes

| Code | Meaning |
| --- | --- |
| `unknown_citation_key` | The key is not in `paper.toml`. Add the file and convert, or fix the key. |
| `page_out_of_range` | The source has fewer pages than the citation claims. |
| `quote_not_found` | The quoted words are not anywhere in the source. Usually a copy error, or an extraction problem. |
| `quote_wrong_page` | The quote exists, on a different page. The error names the page. |
| `quote_too_short` (warning) | Fewer than four words. Quote a full clause. This becomes an error under `--strict` or `[check] require_quotes = true`. |
| `citation_without_quote` (warning) | The citation has a page but no evidence. `--strict` makes this an error. |
| `citation_without_page` (warning) | The citation has no page. Add one for factual claims. |
| `citation_malformed` | The bracket does not match the syntax. See `AGENTS.md`. |
| `citation_unrecognized` | Something looks like a citation but is not the supported form: `[see @key]`, `[-@key]`, a bare `@key`, or a bracketed `@@key`. It is an error rather than ignored, because otherwise the citation escapes verification. |
| `multiple_citations` | One citation per bracket: `[@a, p. 1] [@b, p. 2]`. |
| `unterminated_comment` | An HTML comment is never closed, so everything after it is invisible to `check`. Close it. |
| `unterminated_code_block` | A fenced code block is never closed. Close it; a fence indented four or more spaces is not a fence. |
| `placeholder` | `TODO`, `TKTK`, `FIXME`, `XXX`, `[[` or `lorem ipsum` is still in the draft. |
| `unused_source` (warning) | A converted source is never cited. |
| `candidate_pending` (warning) | A proposal in `Candidates/` was never approved or deleted. |

## "The quote is right there, but check says it is not"

Extraction quality is the most common cause.

1. Open `References/_text/<key>.txt` and search for the words. If they are absent, the PDF did not extract them.
2. A two-column paper often interleaves the columns. The text exists but in the wrong order, so a span across a column break will not match.
3. Tables lose their cell structure. Quote a sentence instead of a table cell.
4. Hyphenation at line ends is handled. Missing spaces are not: if the extractor produced `wordone` where the source has `word one`, the quote will not match.
5. A scanned page has no text at all. Run OCR.

If extraction is unusable, quote a shorter span that did extract cleanly, or ask the human to supply a better copy.

## Build

| Code | Meaning |
| --- | --- |
| `pandoc_missing` | Install pandoc. |
| `pandoc_failed` | Pandoc rejected the markdown. The hint contains its stderr. Run the same command by hand in `Paper/` to see the full message. |
| `reference_doc_missing` | `[build] reference_doc` points at a file that does not exist. Fix the path or remove the line. |
| `build_no_output` | Pandoc reported success but wrote nothing. Check disk space and antivirus. |
| `invalid_output` | `[build] output` points outside `Output/`. Use a relative path such as `Output/paper.docx`. |
| `paper_missing` / `paper_empty` | `Paper/paper.md` does not exist or is empty. |

## Still stuck

Run and attach the output of:

```bash
paperchain doctor --json
paperchain check --json
```

That is enough to see versions, lock state and the exact findings without sharing the source documents.
