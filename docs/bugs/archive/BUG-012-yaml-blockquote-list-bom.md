# BUG-012: YAML in a container, escaped key or BOM escaped `check`

- **Status:** fixed
- **Severity:** low–medium
- **Area:** check
- **Found:** 2026-11-14
- **Audit:** A5-4
- **Related:** `tests/test_audit6.py`, BUG-001

## Observed

Pandoc dropped the reference list for a `suppress-bibliography` block in a blockquote, in a list item, with an escaped key (`"suppress\u002dbibliography"`), as a complex key (`? suppress-bibliography`) and after a UTF-8 BOM. `check` reported ok in all five cases. The strict `Bibliography` detector still failed the build, so nothing shipped silently.

## Expected

`check` and Pandoc agree on which YAML metadata keys exist.

## Evidence

`check.py`: `front_matter_keys()` looked only at plain top-level lines and did not strip a BOM.

## Fix

`check.py` strips a leading BOM, builds container-stripped views for a blockquote or list item, parses quoted, escaped and complex keys, and uses `FRONT_MATTER_ALLOW` so an escaped key cannot hide behind a deny-list mismatch.

## Verification

`tests/test_audit6.py::test_an_escaped_key_is_seen`, `::test_a_complex_key_is_seen`, `::test_a_bom_does_not_hide_the_block`, `::test_a_blockquote_block_is_seen`, `::test_a_list_item_block_is_seen` (2026-11-14).
