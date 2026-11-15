# BUG-005: The style validator accepted unknown ids and styles without a bibliography

- **Status:** fixed
- **Severity:** medium
- **Area:** check | docs
- **Found:** 2026-11-14
- **Audit:** A4-5
- **Related:** `tests/test_audit5.py`, `tests/test_style.py`

## Observed

A numeric IEEE copy with its own id and a title starting "Vancouver" passed `style_problem`. A CSL file with no `<bibliography>` element also passed. The docs claimed non-Vancouver numeric styles were rejected.

## Expected

The id decides. Only a known Vancouver id (or one a human explicitly accepts) passes, the style must be independent, and it must contain a `<bibliography>` element.

## Reproduction

```python
style_problem(path_with_id("http://example.org/my-numeric"), "vancouver")  # None
```

## Evidence

`library.py`: `named` accepted any title starting with an alias; there was no `<bibliography>` check.

## Fix

`library.py`: `KNOWN_STYLE_IDS` plus an optional `styles/accepted-csl-ids.txt` sidecar; an unknown id is rejected even when the title says Vancouver; a missing `<bibliography>` is rejected. The docs and tests describe the sidecar.

## Verification

`tests/test_audit5.py::test_a_custom_numeric_style_named_vancouver_is_rejected`, `::test_a_style_without_a_bibliography_element_is_rejected`, `::test_a_named_variant_can_be_accepted_explicitly` (2026-11-14).
