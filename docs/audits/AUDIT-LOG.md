# Audit log

This file tracks every audit finding and every bug found while verifying, with its status and the evidence that closes it. `docs/CHANGELOG.md` says what changed; this file says which finding a change answers and how to re-check it. `docs/audits/AUDIT.md` and `docs/audits/AUDIT-INSTRUCTIONS.md` describe the next audit and are rewritten each round, so they are not a history; this file is.

Statuses: `fixed` (code and test), `fixed (live)` (code, test and verified on a real project), `open`, `data` (a problem in the user's data, not in Paperchain), `limitation` (known behaviour, documented rather than fixed).

## Round 5 — 2026-11-14

| ID | Finding | Status | Change | Evidence |
|---|---|---|---|---|
| A5-1 | An inline `references:` YAML block defined a whole bibliography and overrode the Zotero export, so the writer could invent authors, titles and dates. | fixed | `check.py`: `FRONT_MATTER_ALLOW` replaces the deny list; an unknown key, including `references:`, is `front_matter_overrides_citations` | `tests/test_audit6.py::test_inline_references_metadata_is_an_error`, `::test_an_unknown_metadata_key_is_an_error`, `::test_allowed_document_metadata_is_allowed` |
| A5-2 | A key ending in `. : / + -` passed `check` and `build` but Pandoc rendered it unresolved, because Pandoc treats the trailing punctuation as outside the key. | fixed | `citations.py` / `project.py`: keys must start and end with a letter or digit; `match_cmd.py` refuses to write an invalid id; `build.py`: `_unresolved_citations()` promotes the citeproc warning to `citation_not_in_bibliography` | `tests/test_audit6.py::test_a_citation_key_ending_in_punctuation_is_rejected`, `::test_a_citation_ending_in_punctuation_is_malformed`, `::test_the_citeproc_not_found_warning_is_detected`, `::test_match_does_not_write_a_key_ending_in_punctuation` |
| A5-3 | A decomposed (NFD) accent did not match the composed title, so `check` raised a false `source_metadata_mismatch` and `match` failed to pair the same work. | fixed | `library.py`: `title_key()` applies NFKC, case folding, NFKD and strips combining marks; `match_cmd.py` uses the same key | `tests/test_audit6.py::test_nfd_and_nfc_titles_are_equal`, `::test_an_nfd_bibliography_title_is_not_a_metadata_mismatch`, `::test_match_pairs_an_nfd_title` |
| A5-4 | `check` still missed `suppress-bibliography` in a blockquote, a list item, an escaped key, a complex key and after a UTF-8 BOM. | fixed | `check.py`: BOM stripping, blockquote/list container views, general key parsing, complex-key handling; allow-list makes escaped and unknown keys visible | `tests/test_audit6.py::test_an_escaped_key_is_seen`, `::test_a_complex_key_is_seen`, `::test_a_bom_does_not_hide_the_block`, `::test_a_blockquote_block_is_seen`, `::test_a_list_item_block_is_seen` |
| A5-5 | The writer adapter did not deny `styles/**`, and the accepted-ids sidecar was not hashed. | fixed | `opencode.json` denies `styles/**`; `library.py`: `style_sha256()` covers the CSL and sidecar; `locking.py` / `check.py` use it | `tests/test_audit6.py::test_the_adapter_denies_writing_the_style_folder`, `::test_the_sidecar_accepts_a_bom_and_a_trailing_comment`; `tests/test_style.py::test_an_edited_style_sidecar_is_detected_after_lock` |
| A5-6 | A four-space indented code block was rewritten as a media link. | fixed | `citations.py`: `indented_code_ranges()`; `build.py`: `_rewrite_media_links()` and `_mask_code_blocks()` skip indented code | `tests/test_audit6.py::test_media_rewrite_skips_indented_code`, `::test_resource_checks_skip_indented_code` |
| A5-7 | `data:` images were still rejected, and the missing-CSL `lock` hint still said to run `convert` first. | fixed | `build.py`: image `data:image/...` URIs are accepted, other data URIs remain blocked; `locking.py`: the hint names the missing style files | `tests/test_audit6.py::test_a_data_image_is_accepted`, `::test_a_non_image_data_uri_is_rejected`; `tests/test_style.py::test_lock_refuses_a_style_project_without_the_csl` |

## Round 4 — 2026-11-14

| ID | Finding | Status | Change | Evidence |
|---|---|---|---|---|
| A4-1 | A mid-document YAML block with `suppress-bibliography` passed `check`, and `build` accepted any DOCX text containing "references" as a reference list. Quoted keys, flow mappings and a leading blank line passed too. | fixed | `check.py`: `front_matter_keys()` scans every metadata block and masked code; `build.py`: `_docx_has_reference_list()` accepts only the `Bibliography` style | `tests/test_audit5.py::test_a_mid_document_suppress_bibliography_is_an_error`, `::test_a_mid_document_block_cannot_remove_the_reference_list`, `::test_prose_with_the_word_references_is_not_a_reference_list`, `::test_quoted_and_flow_mapping_keys_are_seen` |
| A4-2 | A duplicated CSL id was only a warning, while citeproc could print the second entry and `check` read the first. | fixed | `check.py`: `bibliography_duplicate_id` is an error when a source or citation uses the id; `match_cmd.py` will not apply a duplicated id | `tests/test_audit5.py::test_a_duplicate_id_used_by_a_source_is_an_error`, `::test_an_unused_duplicate_id_stays_a_warning`, `::test_match_does_not_apply_a_duplicate_id` |
| A4-3 | `match --apply` could pair a source with a different work by title containment, and `source_metadata_mismatch` used the same loose test as a warning. | fixed | `library.py`: `titles_equal()`; `match_cmd.py`: exact title only, containment is `suggestion`; `check.py`: mismatch is an error when `citation_key` is set | `tests/test_audit5.py::test_containment_is_only_a_suggestion`, `::test_a_mismatched_title_is_an_error_once_a_citation_key_is_set` |
| A4-4 | A Zotero id with a non-ASCII letter (`Peña2022`) written by `match` made every later command fail with `manifest_invalid`. | fixed | `project.py` / `citations.py`: `CITATION_KEY_RE` and `CITATION_RE` accept Unicode letters | `tests/test_audit5.py::test_a_non_ascii_citation_key_works_end_to_end`, `::test_match_writes_a_non_ascii_id_that_project_accepts` |
| A4-5 | `style_problem` accepted an unknown numeric style whose title started with "Vancouver", and accepted a style with no `<bibliography>` element. | fixed | `library.py`: id allow-list plus `styles/accepted-csl-ids.txt`; require `<bibliography>` | `tests/test_audit5.py::test_a_custom_numeric_style_named_vancouver_is_rejected`, `::test_a_style_without_a_bibliography_element_is_rejected`, `::test_a_named_variant_can_be_accepted_explicitly` |
| A4-6 | Documentation called the Zotero style "Vancouver" without saying the page now serves NLM/Vancouver. | fixed | README, `docs/how-it-works.md`, `docs/troubleshooting.md`; URL fetched 2026-11-14 and still served `nlm-citation-sequence` | `README.md` "Zotero and Vancouver"; `docs/troubleshooting.md` style rows |
| A4-7 | `build` rewrote media paths inside fenced and inline code. | fixed | `build.py`: `_rewrite_media_links()` rewrites only outside `scan_markdown()` ranges | `tests/test_audit5.py::test_media_rewrite_skips_code_fences_and_spans` |
| A4-8 | `[build] reference_doc` could be absolute or outside the project, unlike `bibliography` and `csl`. | fixed | `project.py`: `reference_doc` is validated with the other build paths | `tests/test_audit5.py::test_reference_doc_outside_the_project_is_rejected` |
| A4-9 | Smaller points: `data:` images are rejected, a missing CSL on `lock` says "run convert first", and a styleless project does not notice a Zotero re-export. | fixed | A5-7 accepts image `data:` URIs and fixes the `lock` hint. A styleless project still does not hash a Zotero export; that remains documented behaviour rather than a lock guarantee. | `tests/test_audit6.py::test_a_data_image_is_accepted`, `tests/test_style.py::test_lock_refuses_a_style_project_without_the_csl` |

## Round 3 — 2026-11-13

| ID | Finding | Status | Change | Evidence |
|---|---|---|---|---|
| A3-1 | `build` only checked inline `![alt](path)` images, so reference-style images (`![a][id]`), bracketed alt text and percent-encoded names could reach Pandoc unvalidated. | fixed (live) | `build.py`: `_ast_image_targets()`, `_check_resources()` | `tests/test_audit4.py::test_a_reference_style_image_outside_the_project_is_seen`, `::test_a_bracketed_alt_image_outside_the_project_is_seen` |
| A3-2 | Source keys came from filenames, Zotero keys do not, so one citation could not satisfy both `check` and citeproc. | fixed (live) | `citation_key` in `manifest.py`/`project.py`, `match_cmd.py`, `paperchain match` | `tests/test_audit4.py::test_a_zotero_key_cites_the_source_it_is_mapped_to`, `::test_match_apply_writes_the_citation_key` |
| A3-3 | Citation-changing YAML front matter (`suppress-bibliography`, `bibliography`, ...) could remove references without a diagnostic. | fixed (live) | `check.py`: `front_matter_keys()`; `build.py`: `bibliography_missing_from_output` | `tests/test_audit4.py::test_suppress_bibliography_front_matter_is_an_error` |
| A3-4 | Valid media paths (`%20`, `(1)`, raw spaces, `./media/`) were rejected; `import` rewrote prose and could remove a junction. | fixed | `build.py`, `import_cmd.py`, `util.is_link` | `tests/test_audit4.py::test_a_percent_encoded_image_name_is_accepted`, `::test_a_parenthesis_in_an_image_name_is_accepted` |
| A3-5 | A BibTeX export produced a JSON parse error or a silent `bibliography_missing` instead of the conversion command. | fixed (live) | `library.py`: `bibliography_bibtex_unsupported`, `bibtex_conversion_hint()` | `tests/test_audit4.py::test_a_bibtex_export_is_reported_with_a_conversion_hint`, `::test_a_bibtex_only_project_is_reported_with_the_conversion_hint` |
| A3-6 | A CSL file could name itself Vancouver while being IEEE, APA or a dependent style; `<number variable="citation-number">` was rejected. | fixed (live) | `library.py`: `KNOWN_STYLE_IDS`, `OTHER_STYLE_IDS`, `style_problem()` | `tests/test_audit4.py::test_the_current_zotero_vancouver_download_is_accepted`, `::test_an_ieee_style_that_calls_itself_vancouver_is_rejected` |
| A3-7 | `lock` could record an empty hash when the style's export or CSL was missing; unhashed files were only a warning. | fixed | `locking.py`, `check.py`: `bibliography_not_locked`, `csl_not_locked` | `tests/test_style.py`, `tests/test_audit4.py::test_lock_points_a_bibtex_export_at_the_conversion` |

## Bugs found while verifying round 3

These were found by running the tests with Pandoc 3.13 and by using a copy of the user's real monograph. They are defects in the round-3 changes, not in the original audit.

| ID | Bug | Status | Change | Evidence |
|---|---|---|---|---|
| B3-1 | `bibliography_missing_from_output` searched for the word "References", but citeproc marks references with the `Bibliography` paragraph style and adds no heading. Every normal citing build failed. | fixed (live) | `build.py`: `_docx_has_reference_list()` | `tests/test_audit4.py::test_a_cited_build_keeps_the_reference_list`, `::test_the_reference_list_detector_reads_citeproc_output` |
| B3-2 | A project whose only bibliography was `References/library.bib` passed `check` with 0 errors and built without citeproc, so citations silently lost their formatting. | fixed (live) | `project.py`: `bibliography_path()` returns the `.bib`; `locking.py` reports it | `tests/test_audit4.py::test_a_bibtex_only_project_is_reported_with_the_conversion_hint` |
| B3-3 | `check` printed one warning per unused CSL entry; a 28-entry export produced 25 lines on every run. | fixed (live) | `check.py`: one aggregated `bibliography_entry_unmatched` warning with `data.keys` | `tests/test_audit4.py::test_an_unused_csl_entry_is_a_warning`; live run dropped 30 warnings to 6 |

## Observations from the live project (not product bugs)

| ID | Observation | Status | Note |
|---|---|---|---|
| L3-1 | Seven entries in `Referencias/library.bib` have empty cite keys (`@misc{,`), so `pandoc -f bibtex` rejects the whole file. | data | Give those items a Better BibTeX key in Zotero and export again. `docs/troubleshooting.md` names this case. |
| L3-2 | `Dores2023` appears twice in the export. | fixed | Reclassified by A4-2: `bibliography_duplicate_id` is an error once a source or citation uses the id, because Paperchain and citeproc may choose different entries. An unused duplicate remains a warning. |
| L3-3 | A two-column PDF interleaves right-column text into a quoted sentence, so a correct quote can fail `quote_not_found`. | limitation | Extraction limitation, not a matching bug; the hint points at the `.txt` to fix. Tracked here rather than hidden. |

## Earlier rounds

Round 1 and round 2 predate this log. Their findings and fixes are recorded in `docs/CHANGELOG.md` under **0.1.1 - first audit fixes** and **0.1.2 - second audit fixes**; there is no per-finding table for them, and no archived auditor report.

## Archives

- `paperchain-audit-<YYYY-MM-DD>.zip` at the repository root is the packaged tree for one audit round (see `docs/AGENTS.md`). `paperchain-audit-2026-11-14.zip` is the round-4 tree, packaged before the round-5 fixes; regenerate it before the next audit. `paperchain-audit-2026-11-13.zip` is from before the third-audit fixes.
- The auditor's written report is not stored in the repository; only the resulting changes are. Add it under `docs/audits/<YYYY-MM-DD>/` if it needs to survive.
