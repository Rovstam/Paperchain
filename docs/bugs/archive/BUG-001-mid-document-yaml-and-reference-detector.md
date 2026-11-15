# BUG-001: Mid-document YAML and a prose reference detector

- **Status:** fixed
- **Severity:** high
- **Area:** check | build
- **Found:** 2026-11-14
- **Audit:** A4-1
- **Related:** `tests/test_audit5.py`

## Observed

A YAML metadata block in the middle of `Paper/paper.md` set `suppress-bibliography: true`. `check` reported no error because it only read a leading block. `build` then produced numeric citations without a reference list, because `_docx_has_reference_list` accepted any prose containing "references" or "bibliography". A quoted key and a flow mapping also passed `check`.

## Expected

Every YAML metadata block that changes citations is an error. A citeproc document with citations but no `Bibliography` paragraphs fails the build, whatever the prose says.

## Reproduction

```markdown
# T

## Related work with references

---
suppress-bibliography: true
---

A claim [@study2024].
```

## Evidence

`check.py`: `front_matter_keys()` read only a leading block. `build.py`: `_docx_has_reference_list()` fell back to a text search.

## Fix

`front_matter_keys()` scans every metadata block after masking code, and recognises quoted keys and one-line flow mappings. `_docx_has_reference_list()` accepts only the `Bibliography` paragraph style.

## Verification

`tests/test_audit5.py::test_a_mid_document_suppress_bibliography_is_an_error`, `::test_a_mid_document_block_cannot_remove_the_reference_list`, `::test_prose_with_the_word_references_is_not_a_reference_list`, `::test_quoted_and_flow_mapping_keys_are_seen` (2026-11-14).
