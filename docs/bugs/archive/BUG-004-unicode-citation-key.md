# BUG-004: A non-ASCII Zotero id makes the project unusable

- **Status:** fixed
- **Severity:** medium
- **Area:** match | project | check
- **Found:** 2026-11-14
- **Audit:** A4-4
- **Related:** `tests/test_audit5.py`

## Observed

`match --apply` wrote `citation_key = "Peña2022"` into `paper.toml`. Every later command failed with `manifest_invalid`, and `[@Peña2022]` was read as a malformed citation.

## Expected

Pandoc and Zotero allow such keys, so `paper.toml` and the citation parser accept Unicode letters.

## Reproduction

```powershell
paperchain match --apply   # writes Peña2022
paperchain check           # manifest_invalid
```

## Evidence

`project.py`: `CITATION_KEY_RE` was `^[A-Za-z0-9]...`. `citations.py`: `CITATION_RE` used the same ASCII first character.

## Fix

Both regexes use `[^\W_]` for the first character and `\w` for the rest, which accepts Unicode letters and digits while rejecting a leading underscore or punctuation.

## Verification

`tests/test_audit5.py::test_a_non_ascii_citation_key_works_end_to_end`, `::test_match_writes_a_non_ascii_id_that_project_accepts` (2026-11-14).
