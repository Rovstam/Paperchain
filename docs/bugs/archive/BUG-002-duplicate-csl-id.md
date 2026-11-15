# BUG-002: A duplicated CSL id is a warning, not an error

- **Status:** fixed
- **Severity:** high
- **Area:** check | match
- **Found:** 2026-11-14
- **Audit:** A4-2
- **Related:** `tests/test_audit5.py`, audit observation L3-2

## Observed

Two CSL entries shared the id `Haron2023`, the second a different work. `check` reported `ok` and warned that the first entry was used. Pandoc 3.1.3 citeproc used the last entry, so the DOCX printed the wrong reference.

## Expected

A duplicated id used by a source or citation is an error, because Paperchain and citeproc may disagree. An unused duplicate remains a warning.

## Reproduction

Put two entries with id `study2024` in `References/library.json`, the second with a different title, and run `paperchain check`.

## Evidence

`check.py`: `bibliography_duplicate_id` was always appended to `report.warnings`. `library.py`: `load_csl_entries()` keeps the first entry.

## Fix

`check` promotes `bibliography_duplicate_id` to an error when a source's `citation_key` or a parsed citation uses the id. `match` refuses to apply a duplicated id (status `ambiguous`). No new code.

## Verification

`tests/test_audit5.py::test_a_duplicate_id_used_by_a_source_is_an_error`, `::test_an_unused_duplicate_id_stays_a_warning`, `::test_match_does_not_apply_a_duplicate_id` (2026-11-14).
