# BUG-010: A key ending in punctuation renders unresolved

- **Status:** fixed
- **Severity:** high
- **Area:** check | build | citations | project
- **Found:** 2026-11-14
- **Audit:** A5-2
- **Related:** `tests/test_audit6.py`

## Observed

A Zotero id ending in `.`, such as `Haron2023.`, passed `check` and `build`. The DOCX printed `(Haron2023?, p. 2)` and omitted the reference. Pandoc warned `Citeproc: citation Haron2023 not found` and exited 0.

## Expected

A key must start and end with a letter or digit. If citeproc still cannot resolve a citation, `build` fails instead of writing the document.

## Reproduction

```toml
# paper.toml
citation_key = "Haron2023."
```

```markdown
A claim [@Haron2023., p. 2].
```

## Evidence

`citations.py`: `CITATION_RE` accepted trailing punctuation. `project.py`: `CITATION_KEY_RE` accepted it. `build.py` ignored Pandoc's citeproc warning.

## Fix

Both key regexes require a final letter or digit. `match_cmd.py` refuses to write an invalid id. `build.py`: `_unresolved_citations()` detects the warning and raises `citation_not_in_bibliography`.

## Verification

`tests/test_audit6.py::test_a_citation_key_ending_in_punctuation_is_rejected`, `::test_a_citation_ending_in_punctuation_is_malformed`, `::test_the_citeproc_not_found_warning_is_detected`, `::test_match_does_not_write_a_key_ending_in_punctuation` (2026-11-14).
