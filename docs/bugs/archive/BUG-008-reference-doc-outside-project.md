# BUG-008: `reference_doc` is not contained in the project

- **Status:** fixed
- **Severity:** low
- **Area:** build | project
- **Found:** 2026-11-14
- **Audit:** A4-8
- **Related:** `tests/test_audit5.py`

## Observed

An absolute `[build] reference_doc` outside the project built silently, while `bibliography` and `csl` were rejected with `manifest_invalid`.

## Expected

All three build input paths follow the same rule: relative to the project and inside it.

## Reproduction

```toml
[build]
reference_doc = "C:/outside/style.docx"
```

## Evidence

`project.py`: `validate()` looped over `bibliography` and `csl`, not `reference_doc`.

## Fix

`project.py`: `reference_doc` joined the same path check. `build.py` still reports `reference_doc_missing` when a valid relative path does not exist.

## Verification

`tests/test_audit5.py::test_reference_doc_outside_the_project_is_rejected` (2026-11-14).
