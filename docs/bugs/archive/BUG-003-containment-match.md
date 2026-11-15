# BUG-003: Containment can pair a source with the wrong work

- **Status:** fixed
- **Severity:** medium
- **Area:** match | check
- **Found:** 2026-11-14
- **Audit:** A4-3
- **Related:** `tests/test_audit5.py`

## Observed

A PDF whose metadata title was "Cancer" was paired by `match --apply` with a CSL entry titled "Cancer immunotherapy review 2020". `check` was clean apart from the missing year, and the built reference named a different author, title and year.

## Expected

`--apply` writes only an exact normalized title. Containment is a suggestion. Once a `citation_key` is set, a title that is not equal is an error.

## Reproduction

```powershell
paperchain match --apply
paperchain check
paperchain build
```

## Evidence

`match_cmd.py` used `titles_agree()` (containment) to decide an apply. `check.py` used the same test for `source_metadata_mismatch`, always as a warning.

## Fix

`library.py`: `titles_equal()`. `match_cmd.py`: exact title only; containment gets the status `suggestion`. `check.py`: `source_metadata_mismatch` is an error when `citation_key` is set, otherwise a warning.

## Verification

`tests/test_audit5.py::test_containment_is_only_a_suggestion`, `::test_a_mismatched_title_is_an_error_once_a_citation_key_is_set`, `::test_a_mismatched_title_is_a_warning_without_a_citation_key` (2026-11-14).
