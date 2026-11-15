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
| `manifest_invalid` | TOML is malformed, a source key is not a lowercase slug, a key is duplicated, a `path` is absolute or resolves outside `References/`, or `[build] reference_doc`, `bibliography` or `csl` is absolute or outside the project. |
| `manifest_version` | The project was written by a newer paperchain. Upgrade the tool. |
| `already_initialized` | `init` found a `paper.toml`. Use `--force` only if you mean to overwrite template files. |
| `destination_not_empty` | Choose an empty folder, pass `--adopt` to keep existing files, or pass `--force` to overwrite template files. |
| `unknown_adapter` | `init --agent X` where X does not exist. `paperchain init --help` lists the default; the adapters live inside the package. |

## Cache

Generated text, page maps, `INDEX.md`, manuscript media and build temp files live outside the project. `paperchain doctor --json` prints the path under `data.cache`. It is safe to delete the cache folder; run `paperchain convert` afterwards to regenerate it. Set `PAPERCHAIN_CACHE_DIR` before running the command to use a different location. If `Paper/media` is a junction/symlink, do not copy the project without also copying the cache; re-run `paperchain import` if the link is broken.

## Manuscript import

| Code | Meaning |
| --- | --- |
| `manuscript_missing` | No DOCX/PDF found in the project root or `Manuscript/`. Put one there, or pass its path. |
| `manuscript_ambiguous` | More than one possible manuscript was found. Keep one, or pass the exact path (`paperchain import PATH`, or `paperchain organize --manuscript PATH`). |
| `organize_failed` | `organize --apply` could not move a file. Close it if it is open, then run the command again; already-moved files are not moved twice. |
| `organize_missing` (warning) | A planned file disappeared between the plan and `--apply`. Re-run `paperchain organize` to refresh the plan. |
| `manuscript_outside_project` | The original must stay inside the project so its hash can be checked later. |
| `paper_exists` | `Paper/paper.md` already has your edits. Edit it directly, or pass `--force` to replace it from the original (the current draft is saved as `paper.md.bak`). |
| `manuscript_hash_mismatch` | The original changed after import. Re-run `paperchain import --force` (the current draft is saved as `paper.md.bak`), then review the Markdown before building. |
| `manuscript_unhashed` | `[manuscript]` has a path but no `sha256`, so a replacement cannot be detected. Run `paperchain import --force` to record the hash. |
| `pandoc_missing` | DOCX import needs Pandoc. Install it, or export the manuscript as PDF/TXT for a plain-text import. |
| `unsupported_manuscript` | Only DOCX, PDF, MD and TXT manuscripts are imported. |
| `manuscript_empty` | The imported file has no text. A scanned PDF needs OCR first. |
| `import_failed` | Pandoc could not read the DOCX. Re-export it and try again. |
| `pdf_import_plain_text` (warning) | A PDF manuscript is imported as plain paragraphs; headings and images are not reconstructed. |
| `bibliography_missing` / `bibliography_invalid` | `References/library.json` is absent or not CSL JSON. Export it again from Zotero. |
| `bibliography_bibtex_unsupported` | The only bibliography is `References/library.bib` (BibTeX), or `[build] bibliography` points at one. Paperchain reads CSL JSON: `pandoc -f bibtex -t csljson References/library.bib -o References/library.json`, then set `bibliography = "References/library.json"`. If Pandoc stops at `@misc{,` or another empty key, give those Zotero items a key first, then export again. |
| `bibliography_duplicate_id` | Two CSL entries share an id. It is an error when a source or citation uses the id, because Paperchain and citeproc may choose different entries; an unused duplicate is a warning. Give each item a unique Better BibTeX key and re-export. |
| `bibliography_entry_unmatched` (warning) | One or more CSL entries have no source. Run `paperchain match`, or add and convert the PDF. |
| `citation_not_in_bibliography` | The source's `citation_key` (or its key) is not in the CSL JSON, or Pandoc reported that citeproc could not resolve it during `build`. Keys must start and end with a letter or digit; Pandoc treats a trailing `. : / + -` as punctuation outside the key. Run `paperchain match --apply`, fix the key, or add the item in Zotero and re-export. |
| `front_matter_overrides_citations` | A YAML metadata block in `Paper/paper.md` sets a key outside the document-metadata allow-list (`title`, `author`, `date`, `abstract`, `keywords`, `lang`, ...). Pandoc accepts such a block anywhere in the document, including a blockquote or list item. `references:`, `suppress-bibliography`, `bibliography`, `csl`, `nocite` and unknown keys are rejected. Remove the key; citations and the bibliography belong in `paper.toml` or the Zotero export. |
| `bibliography_missing_from_output` | The built document cites sources but has no reference list. Delete citation-changing YAML from anywhere in `paper.md` and rebuild. Detection uses citeproc's `Bibliography` paragraph style; ordinary prose containing the word "references" does not count. |

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
| `docx_hidden_text_skipped` (warning) | Runs marked hidden were skipped, whether the formatting was direct or came from a character or paragraph style. A reader cannot see them, so they are not citable. |
| `docx_styles_ignored` (warning) | `word/styles.xml` could not be parsed, so style-based hidden text was not skipped. Re-export the file. |
| `docx_textbox_skipped` (warning) | Text inside text boxes was skipped. Move it into the body to cite it. |
| `docx_too_large` | The compressed document expands past the 32 MB XML limit. Export a text-only copy. |
| `source_outside_project` | A file under `References/` is a link to a target outside the folder. Copy the file in instead. |
| `source_unreadable` | A path could not be resolved, usually a broken link. |
| `key_collision` | Two files still map to the same key after the folder path is added. Rename one, for example `study-2024.pdf` and `study-2024-supplement.pdf`. |
| `invalid_category` | `--into` needs one folder name, without slashes or a drive letter. |
| `conflicting_options` | `--into` was used with `--no-organize` or `--only`, so no loose file could be moved. |
| `unknown_source` | `convert --only KEY` and no file has that key. |
| `project_locked` | The reference set is locked. Run `paperchain unlock`, convert, then `paperchain lock`. |
| `convert_changes` | A reference changed since it was last converted. Inspect it, then re-run `convert --accept-changes` to bless the new bytes. |
| `lock_failed` | A source is missing, was never converted, or a configured style's export/CSL file is missing. For a style project the hint names the style files; otherwise run `convert` first. |
| `file_read_only` | Writing to a locked file. Unlock first, and only if you mean to. |
| `permission_failed` | The OS refused a permission change. Close the file in Word or Explorer, or check ownership. |

## Hashing and the lock

| Code | Meaning |
| --- | --- |
| `source_hash_mismatch` | An original changed after locking. Restore the file from backup; do not simply relock, because the old quotes were verified against the old bytes. |
| `text_hash_mismatch` | A cached `*.json` page map was edited after conversion. Regenerate: unlock, `convert --force`, lock. |
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
| `unknown_citation_key` | The key is neither a source key nor a `citation_key`. Add the file and convert, run `paperchain match`, or fix the key. |
| `citation_key_unmatched` (warning) | `paperchain match` could not find any CSL entry whose title agrees with a source. Check that the PDF is the work the Zotero item names, or set `citation_key` by hand. |
| `citation_key_ambiguous` (warning) | More than one CSL entry matches a source title, an exact title is duplicated, or the candidate id is not a valid citation key (for example it ends in `.`). `match` does not guess or write an invalid key; set `citation_key` by hand or fix the Zotero id. |
| `citation_key_no_title` (warning) | A source has no title, so it cannot be matched. Set `title` in `paper.toml` or set `citation_key` by hand. |
| `bibliography_duplicate_title` (warning) | Several CSL entries share a title, so title matching cannot choose. Set `citation_key` by hand. |
| `page_out_of_range` | The source has fewer pages than the citation claims. |
| `quote_not_found` | The quoted words are not anywhere in the source. Usually a copy error, or an extraction problem. |
| `quote_wrong_page` | The quote exists, on a different page. The error names the page. |
| `quote_too_short` (warning) | Fewer than four words. Quote a full clause. This becomes an error under `--strict` or `[check] require_quotes = true`. |
| `citation_without_quote` (warning) | The citation has a page but no evidence. `--strict` makes this an error. |
| `citation_without_page` (warning) | The citation has no page. Add one for factual claims. |
| `citation_malformed` | The bracket does not match the syntax. See `AGENTS.md`. |
| `citation_unrecognized` | Something looks like a citation but is not the supported form: `[see @key]`, `[-@key]`, a bare `@key`, a bracketed `@@key`, an HTML entity such as `[&#64;key]`, an escaped `[\@key]`, or an escaped bracket. Pandoc renders these as citation-shaped text, so they are errors rather than ignored. |
| `multiple_citations` | One citation per bracket: `[@a, p. 1] [@b, p. 2]`. |
| `unterminated_comment` | An HTML comment is never closed, so everything after it is invisible to `check`. Close it. |
| `unterminated_code_block` | A fenced code block is never closed. Close it; a fence indented four or more spaces is not a fence. |
| `placeholder` | `TODO`, `TKTK`, `FIXME`, `[[` or `lorem ipsum` is still in the draft. `XXX` counts only when it stands alone on a line or sits in brackets, so text such as "Super Bowl XXX" is left alone. |
| `unused_source` (warning) | A converted source is never cited. |
| `candidate_pending` (warning) | A proposal in `Candidates/` was never approved or deleted. |
| `source_metadata_unconfirmed` (warning) | A source has no authors or year, or the file metadata named a placeholder such as "Administrator". Set `authors` and `year` in `paper.toml` so the citation and reference list name the work. |
| `source_metadata_mismatch` | The `paper.toml` title and the CSL JSON entry under the same key describe different works. It is an error once `citation_key` is set, because citeproc will print that entry; without a key it is a warning. |

`paperchain match` also reports a `suggestion` status when the titles only contain one another, for example a PDF title of "Cancer" inside "Cancer immunotherapy review 2020". A suggestion is not applied by `--apply`; confirm the entry and set `citation_key` by hand.

## "The quote is right there, but check says it is not"

Extraction quality is the most common cause.

1. Open `<cache>/text/<key>.txt` (the path is in `paperchain doctor --json`, `data.cache.text`) and search for the words. If they are absent, the PDF did not extract them.
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
| `pandoc_resource_blocked` | An image path is absolute, outside `Paper/`, a non-image `data:` URI, remote, or missing. Move it under `Paper/` and use a relative path. An image `data:image/...` URI is accepted because it is self-contained. `build` validates both the Markdown/HTML source and Pandoc's own AST, so reference-style images (`![a][id]`), percent-encoded names, code examples and indented code are covered. |
| `style_requires_bibliography` / `style_requires_csl` | `[build] style` is set but `References/library.json` or the CSL file is missing. Export CSL JSON from Zotero; download the NLM/Vancouver CSL from https://www.zotero.org/styles/vancouver into `styles/vancouver.csl`. `lock` refuses to run in this state instead of recording empty hashes. |
| `csl_not_vancouver` | The CSL file is dependent, is not numeric, has no `<bibliography>` element, or has an id outside the known Vancouver list. A dependent style names its parent in the error; use the independent NLM/Vancouver style from https://www.zotero.org/styles/vancouver. For a confirmed variant with a newer id, add the id to `styles/accepted-csl-ids.txt` beside the CSL file. |
| `bibliography_hash_mismatch` / `csl_hash_mismatch` | The Zotero export, the CSL file, or the `styles/accepted-csl-ids.txt` sidecar changed after `lock`. Review the change, then `paperchain lock --accept-changes`. |
| `bibliography_not_locked` / `csl_not_locked` | `lock` ran before the export or the CSL file existed, so it recorded no hash. Run `paperchain lock --accept-changes`. |
| `pandoc_failed` with `Could not find data file data/data/docx/[Content_Types].xml` | Seen with Debian's packaged pandoc 3.1.3 under the old `--sandbox` build. Current `build` does not use `--sandbox`; if it persists, install a release build from pandoc.org instead of the distro package. |
| `reference_doc_missing` / `manifest_invalid` | `[build] reference_doc` points at a file that does not exist, or at an absolute path or a path outside the project. Keep the reference DOCX inside the project and use a relative path, or remove the line. |
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
