# Paperchain repository rules

The repository that contains this file is the Paperchain source repository, not a paper project. This file lives in `docs/`; paths below are relative to the repository root. The paper project is the folder that contains `paper.toml`.

## Paperchain usage questions

- When the user asks how to start, install, initialize, or use Paperchain, run `paperchain help --json` if the command is available and relay `data.steps`. Otherwise answer from `README.md` and `docs/`. Do not search `Documents`, `Monograph`, `AppData` or unrelated project folders.
- Treat the current working directory as the project unless the user names a path.
- Empty folder: `paperchain init . --title "Project Name"`, put the manuscript in `Manuscript/`, put references under `References/`, then run `paperchain import`, `paperchain convert`, `paperchain lock`, `paperchain check`, `paperchain build`.
- Folder with an existing manuscript and references: `paperchain init . --adopt --title "Project Name"`, then the same import/convert/lock/check/build sequence.
- Only inspect files or run commands when the user asks about their actual project, gives a path, or reports an error. "How do I start?" is a documentation question, not a filesystem investigation.

## Repository work

- `src/paperchain/` is the product source; `tests/` and `docs/` support it.
- `monograph/` is a separate working project and is not imported by Paperchain.
- Run `python -m pytest -q` for tests. Pandoc-dependent tests skip when pandoc is not on `PATH`.

## Bug reports

- File every product bug as `docs/bugs/open/BUG-<number>-<short-slug>.md`, copied from `docs/bugs/TEMPLATE.md`. Use the next number that has never appeared in `open/` or `archive/`.
- When the fix is verified, update the report and move it to `docs/bugs/archive/`. Never delete a report; close it as `fixed`, `duplicate` or `won't fix`.
- Audit-wide findings stay in `docs/audits/AUDIT-LOG.md`; put the audit id in the individual bug file instead of duplicating the whole entry.

## Audit packaging

When the user says **"Generate an audit"**, produce a zip of the current working tree, not only a written brief.

- Name it `paperchain-audit-<YYYY-MM-DD>.zip` at the repository root.
- Include the product source, tests, docs, templates, adapters, packaging files, `vendor/wheels/`, `.github/`, and the audit files in `docs/audits/` (`AUDIT.md`, `AUDIT-NECESSITY.md`, `AUDIT-INSTRUCTIONS.md`, `AUDIT-LOG.md`).
- Exclude `.git`, `.venv`, `.tools`, `dist`, `build`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `*.pyc`, root-level `*.zip` and OS cache files.
- Put the archive contents under a single `paperchain/` folder.
- Update `docs/audits/AUDIT-INSTRUCTIONS.md` first so it describes the current state and the specific items that need revision. Do not ship a stale instruction file.
- Update `docs/audits/AUDIT-LOG.md` with each new finding, its status and its evidence, including bugs found while testing a round's own fixes. Findings are never removed from the log; they are closed, not erased.
- Verify the archive with `ZipFile.testzip()` or `python -m zipfile -l`, and report its path, size, file count and SHA-256.
- Do not include the user's paper projects, `Documents`, `Downloads`, `AppData` or their references in the archive.
