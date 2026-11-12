# GitHub Copilot instructions

Read `AGENTS.md` first. It is the source of truth. This file only points Copilot at the same rules.

## What to edit

- Edit `Paper/paper.md`.
- Edit or create `Candidates/<key>.md` when a source is missing.
- Never edit `References/`, `Manuscript/`, `Output/`, `paper.toml` or `AGENTS.md`.

The original manuscript in `Manuscript/` or the project root is read-only. The generated cache is outside the project; `paperchain doctor --json` reports its paths under `data.cache`.

## Workflow

1. Run `paperchain doctor --json`. If it is not `ok`, stop and report the problem.
2. Read `data.cache.index` from the doctor output, then the relevant files in `data.cache.text`.
3. Draft in `Paper/paper.md` using the citation syntax below.
4. Run `paperchain check --json`. Fix every error.
5. Run `paperchain build`. The DOCX appears in `Output/`.
6. Repair the source, not the cache: never hand-edit generated text or `Output/`.

## Citation syntax

- `[@smith2024]`
- `[@smith2024, p. 12]`
- `[@smith2024, pp. 12-14]`
- `[@smith2024, p. 12: "exact words from page 12"]`

Use one citation per bracket. `[see @key]`, `[-@key]` and a bare `@key` are errors. Copy quoted evidence exactly from the cache text. Do not invent sources, pages or quotes.

## Safety

- Never run `paperchain import`, `paperchain convert`, `paperchain lock`, `paperchain unlock`, `paperchain init` or any `--force` command.
- If `check` reports `manuscript_hash_mismatch`, stop and ask the human to re-import the original.
- If a source is missing, write a candidate proposal; do not fill the gap from memory.
- When the human asks how to start, run `paperchain help --json` and relay `data.steps`, or answer directly from `AGENTS.md`; do not scan unrelated folders.
