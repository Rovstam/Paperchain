# BUG-009: Inline `references:` metadata forges the bibliography

- **Status:** fixed
- **Severity:** high
- **Area:** check
- **Found:** 2026-11-14
- **Audit:** A5-1
- **Related:** `tests/test_audit6.py`

## Observed

A YAML metadata block with `references:` defined an inline CSL entry. `check` was ok and `build` printed the invented author, title and year instead of the Zotero export. The writer agent can edit `paper.md`, so this breaks R3.

## Expected

Citation settings and bibliographies are not document metadata. A YAML block may set title, author, date, abstract or keywords, but any other key is an error.

## Reproduction

```markdown
---
references:
- id: Haron2023
  title: FORGED INLINE TITLE
  author: [{family: Invented, given: Ivan}]
  issued: {date-parts: [[1999]]}
---
```

## Evidence

`check.py`: `FRONT_MATTER_DENY` listed `bibliography` but not `references`, so an inline CSL list passed.

## Fix

`check.py` uses `FRONT_MATTER_ALLOW`. Any key outside the document-metadata allow-list is `front_matter_overrides_citations`, including `references:`.

## Verification

`tests/test_audit6.py::test_inline_references_metadata_is_an_error`, `::test_an_unknown_metadata_key_is_an_error`, `::test_allowed_document_metadata_is_allowed` (2026-11-14).
