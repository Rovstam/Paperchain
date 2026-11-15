# Bug reports

This folder tracks product bugs as one Markdown file each. There is no live issue tracker in this repository, so the files are the history.

```
docs/bugs/
├── TEMPLATE.md   copy this when you file a bug
├── open/         current, unfixed bugs
└── archive/      closed bugs, whether fixed, duplicate or won't fix
```

## Filing a bug

1. Copy `TEMPLATE.md` into `open/`.
2. Name it `BUG-<number>-<short-slug>.md`, for example `BUG-012-lock-empty-hash.md`. Use the next number that has never appeared in `open/` or `archive/`.
3. Fill in the observed behaviour, what you expected, and a reproduction that another person can run.
4. Keep the report small: commands, copied output, file:line, and the test that should have caught it. Do not paste a whole copyrighted paper or a full document dump.

A bug that came from an audit should name its audit id (for example `A3-4`) so the two records can be cross-checked. `docs/audits/AUDIT-LOG.md` keeps the audit-wide summary; this folder keeps the individual reports.

## Closing a bug

When the fix is verified, update the report:

- set `Status` to `fixed`, `duplicate` or `won't fix`;
- add the change and the test or command that proves it;
- move the file from `open/` to `archive/`.

Never delete a report. If a bug turns out not to be a bug, archive it with an explanation instead. If a fixed bug regresses, copy the archived report back to `open/` as a new number and link the old one.

## Status values

| Status | Meaning |
| --- | --- |
| `open` | Reproducible, not fixed. Belongs in `open/`. |
| `fixed` | Fixed and verified. Belongs in `archive/`. |
| `duplicate` | Same cause as another report. Link it. |
| `won't fix` | Intentional limitation or not worth the cost. Explain why. |

Severity is `high` (silent wrong result or data loss), `medium` (wrong result with a visible failure) or `low` (usability or documentation).
