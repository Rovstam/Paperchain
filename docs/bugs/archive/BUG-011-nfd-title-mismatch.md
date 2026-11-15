# BUG-011: A decomposed accent is treated as a different title

- **Status:** fixed
- **Severity:** medium
- **Area:** check | match | library
- **Found:** 2026-11-14
- **Audit:** A5-3
- **Related:** `tests/test_audit6.py`

## Observed

A title written in NFD (`preparacion` plus a combining acute) did not equal the composed form. With `citation_key` set, `check` raised `source_metadata_mismatch` for the same work, and `match` failed to pair the title. macOS metadata commonly uses NFD.

## Expected

Composed and decomposed forms compare equal.

## Reproduction

```python
unicodedata.normalize("NFD", "Preparación") == "Preparación"  # False
```

## Evidence

`library.py`: `_title_key()` only case-folded and removed punctuation; it did not normalize Unicode.

## Fix

`library.py`: `title_key()` applies NFKC, case folding, NFKD and strips combining marks. `match_cmd.py` uses the same function.

## Verification

`tests/test_audit6.py::test_nfd_and_nfc_titles_are_equal`, `::test_an_nfd_bibliography_title_is_not_a_metadata_mismatch`, `::test_match_pairs_an_nfd_title` (2026-11-14).
