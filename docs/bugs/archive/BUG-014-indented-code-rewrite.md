# BUG-014: Indented code is rewritten as a media link

- **Status:** fixed
- **Severity:** low
- **Area:** build
- **Found:** 2026-11-14
- **Audit:** A5-6
- **Related:** `tests/test_audit6.py`, BUG-007

## Observed

A four-space indented code block containing `![x](media/image1.png)` was rewritten to `.paperchain-build-media/image1.png`. Fenced code, tildes, inline code and comments were already fixed.

## Expected

Indented code shows text, so `build` leaves it unchanged.

## Reproduction

```markdown
    ![x](media/image1.png)
```

## Evidence

`build.py`: `_rewrite_media_links()` collected fenced and inline ranges but not indented code.

## Fix

`citations.py`: `indented_code_ranges()` finds four-space or tab-indented blocks and continues through blank lines. `build.py`: `_rewrite_media_links()` merges those ranges with the existing masks, and `_mask_code_blocks()` keeps resource checks from reading code examples.

## Verification

`tests/test_audit6.py::test_media_rewrite_skips_indented_code`, `::test_resource_checks_skip_indented_code` (2026-11-14).
