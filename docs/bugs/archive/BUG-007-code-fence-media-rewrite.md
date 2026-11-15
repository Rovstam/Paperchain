# BUG-007: Build rewrites media paths inside code

- **Status:** fixed
- **Severity:** low
- **Area:** build
- **Found:** 2026-11-14
- **Audit:** A4-7
- **Related:** `tests/test_audit5.py`

## Observed

When `Paper/media` was a link, a fenced example containing `![figure](media/image1.png)` came out of the build as `.paperchain-build-media/image1.png`.

## Expected

Code fences and inline code show text, so `build` leaves them byte-for-byte alone.

## Reproduction

````markdown
```markdown
![figure](media/image1.png)
```
````

## Evidence

`build.py`: `_rewrite_media_links()` ran on the whole rendered document.

## Fix

`_rewrite_media_links()` collects code and comment ranges with `scan_markdown()` and applies the rewrites only to the text outside them. `scan_markdown()` gained an optional `ranges` output; existing callers are unchanged.

## Verification

`tests/test_audit5.py::test_media_rewrite_skips_code_fences_and_spans` (2026-11-14).
