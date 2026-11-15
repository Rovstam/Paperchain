# BUG-013: The style sidecar was unhashed and writable by the writer

- **Status:** fixed
- **Severity:** low
- **Area:** adapter | lock | check
- **Found:** 2026-11-14
- **Audit:** A5-5
- **Related:** `tests/test_audit6.py`, `tests/test_style.py`

## Observed

The OpenCode adapter denied edits to `References/`, `paper.toml` and others, but not `styles/**`. The writer agent could edit `styles/accepted-csl-ids.txt` and the CSL file. A CSL edit was caught by `csl_hash_mismatch`; the sidecar was not hashed. The sidecar also rejected a BOM or a trailing `# comment`.

## Expected

The writer cannot modify style trust inputs, and a human edit after `lock` is visible.

## Evidence

`src/paperchain/adapters/opencode/opencode.json`: no `styles/**` deny rule. `locking.py`: only `sha256_file(csl)` was recorded.

## Fix

The adapter denies `styles/**`. `library.py`: `style_sha256()` hashes the CSL and its optional sidecar together; `locking.py` and `check.py` use it in `csl_sha256`. The sidecar reader accepts `utf-8-sig` and a ` # comment` after an id.

## Verification

`tests/test_audit6.py::test_the_adapter_denies_writing_the_style_folder`, `::test_the_sidecar_accepts_a_bom_and_a_trailing_comment`; `tests/test_style.py::test_an_edited_style_sidecar_is_detected_after_lock` (2026-11-14).
