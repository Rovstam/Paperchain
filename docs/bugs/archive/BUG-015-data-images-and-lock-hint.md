# BUG-015: Image data URIs are rejected and the missing-CSL hint is wrong

- **Status:** fixed
- **Severity:** low
- **Area:** build | lock | docs
- **Found:** 2026-11-14
- **Audit:** A5-7
- **Related:** `tests/test_audit6.py`, `tests/test_style.py`, A4-9

## Observed

`build` rejected a legitimate `data:image/...` URI with `pandoc_resource_blocked`. When a style project had no CSL, `lock` said to run `paperchain convert` first, which does not fix a missing style file.

## Expected

A self-contained image data URI is accepted. A style error points at the bibliography or CSL.

## Evidence

`build.py`: `_SCHEME_RE` rejected every `data:` target. `locking.py`: one generic hint covered source and style problems.

## Fix

`build.py` accepts `data:image/...` URIs and still rejects other `data:` payloads. `locking.py` names the style files when the problem is a missing export or CSL.

## Verification

`tests/test_audit6.py::test_a_data_image_is_accepted`, `::test_a_non_image_data_uri_is_rejected`; `tests/test_style.py::test_lock_refuses_a_style_project_without_the_csl` (2026-11-14).
