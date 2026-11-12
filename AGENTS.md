# Paperchain repository rules

This directory is the Paperchain source repository, not a paper project. The paper project is the folder that contains `paper.toml`.

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
