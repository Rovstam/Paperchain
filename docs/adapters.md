# Agent adapters

The rules live in `AGENTS.md`. Every agent tool reads them, and no adapter should contradict them. What differs per tool is the permission format, so each tool gets an adapter instead of sharing a file that none of them fully understands.

An adapter is a guardrail. `paperchain check` is the guarantee.

## Contract

An adapter is a folder under `src/paperchain/adapters/<name>/` containing:

```
adapter.toml
<files...>
```

`adapter.toml`:

```toml
name = "opencode"
description = "One line shown to maintainers"
tested = true

[[files]]
source = "opencode.json"
target = "opencode.json"

[[files]]
source = "agents/writer.md"
target = ".opencode/agents/writer.md"
```

`paperchain init --agent <name>` copies each `source` to its `target`, creating folders. Text files are rendered with `{{program}}`, `{{title}}`, `{{slug}}` and `{{date}}`, so a rename of the command does not leave stale instructions. Do not put secrets in an adapter.

## Universal files

Every project gets the same markdown files, and each tool picks up the one it knows:

| File | Read by | Content |
| --- | --- | --- |
| `AGENTS.md` | OpenCode, Codex, and other tools that read it | the rules, the workflow and the safety limits; the single source of truth, with no tool-specific wording |
| `CLAUDE.md` | Claude Code | `@AGENTS.md` and a one-line fallback; no rules of its own |
| `GEMINI.md` | Gemini CLI | the same pointer |
| `.github/copilot-instructions.md` | GitHub Copilot | the essential rules, pointing at `AGENTS.md` |

A new rule goes into `AGENTS.md` only. The pointer files are tested to stay short and to import it, and `tests/test_universal_files.py` checks that every command the instruction files name exists in the CLI. Whether a given tool or version loads these files, and follows the `@` import, depends on that tool; none of them has been run against a real session yet. An existing `CLAUDE.md` or `GEMINI.md` is never overwritten by `init --adopt`.

## Status

| Tool | Status | Notes |
| --- | --- | --- |
| OpenCode V2 | config verified, checklist pending | `permissions` array with `shell`, `edit`, `subagent`; `default_agent: writer`; two agents |
| Claude Code | instructions shipped (`CLAUDE.md`); no permission settings | Needs `.claude/settings.json` for the same deny/allow shape |
| Gemini CLI | instructions shipped (`GEMINI.md`); no permission settings | Same pointer as Claude Code |
| Codex | not shipped | Reads `AGENTS.md`; needs its own sandbox and approval configuration |

"Config verified" means the tool loaded the file and registered both agents with the expected merged permissions. It does not mean the enforcement checklist below has been run. Only mark `tested = true` after running it.

## OpenCode adapter

Files: `opencode.json`, `.opencode/agents/writer.md`, `.opencode/agents/scout.md`.

The project config does four things:

1. Loads `AGENTS.md` as instructions and selects `writer` by default.
2. Denies edits to `References/`, `styles/`, `Manuscript/`, `Output/`, any `.docx` or `.pdf`, `paper.toml` and `AGENTS.md`. The `styles/` rule matters because `accepted-csl-ids.txt` widens the style allow-list.
3. Denies all shell commands, then allows `paperchain *`, `git status *` and `git diff *`, and re-denies `paperchain unlock*` and `paperchain init*`.
4. Denies launching subagents except `scout`, and asks before touching directories outside the project.

Two rules matter more than the rest:

```jsonc
{ "action": "shell", "resource": "*", "effect": "deny" },
{ "action": "shell", "resource": "paperchain* check*", "effect": "allow" },
{ "action": "shell", "resource": "paperchain* doctor*", "effect": "allow" },
{ "action": "shell", "resource": "paperchain* build*", "effect": "allow" },
{ "action": "shell", "resource": "* --force*", "effect": "deny" },
{ "action": "shell", "resource": "* unlock*", "effect": "deny" },
{ "action": "shell", "resource": "* convert*", "effect": "deny" },
{ "action": "shell", "resource": "* lock*", "effect": "deny" },
{ "action": "shell", "resource": "* init*", "effect": "deny" },
```

Rules are evaluated in order and the last match wins. This is an allowlist of subcommands, not a denylist of bad ones, because a denylist is easy to sidestep: `paperchain "unlock"`, `paperchain un\lock` and `paperchain --project . unlock` do not look like `paperchain unlock` to a string match. Only commands that contain `check`, `doctor` or `build` are allowed at all.

`--force` is denied after the allow, so `paperchain build --force` stops. The CLI also disables argparse abbreviations (`allow_abbrev=False`), so `--fo` is a usage error rather than a synonym for `--force`.

The writer may therefore run `start`, `context`, `doctor`, `check` and `build`. Converting, matching, locking and unlocking by hand are human steps, and treating them as a boundary is deliberate: `match --apply` writes `paper.toml`. `start` is allowed because it only adds: it runs those steps itself for new references, but it never passes `--accept-changes`, so it cannot bless a changed reference, and it stops and asks when one differs. `References/**/*.context.md` is writable (the allow follows the `References/**` deny) so the writer can fill in the scoped resume, and `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and `.github/copilot-instructions.md` are not.

The `writer` agent also denies `webfetch` and `websearch`, so it cannot quietly pull facts from outside the reference set. The `scout` subagent is the opposite: it may search, and it can only write to `Candidates/`.

The agent definitions live in Markdown with YAML frontmatter, which OpenCode merges with the project config. Agent rules are appended after global rules.

## Adding Claude Code

Claude Code does not read `AGENTS.md` directly. The bridge, a `CLAUDE.md` at the project root whose first line is `@AGENTS.md`, now ships with every project. What is still missing is a settings file for the same deny/allow shape. The settings schema changes between releases, so write it against the version you run, test it, and only then set `tested = true` in `adapter.toml`.

## Adding Codex

Codex reads `AGENTS.md` without a bridge. The work is in its sandbox and approval configuration: block writes outside `Paper/` and `Candidates/`, and block `paperchain unlock`. Test the exact version.

## Testing an adapter

1. `paperchain init /tmp/adapter-test --agent <name>`
2. Open that folder in the tool.
3. Ask the agent to edit `References/` or `Manuscript/` and confirm it is refused.
4. Ask it to run `paperchain import` or `paperchain unlock` and confirm it is refused.
5. Ask it to run `paperchain check` and confirm it is allowed.
6. Ask it to write in `Paper/paper.md` and confirm it is allowed.

For a quick check that the config was parsed at all, OpenCode has `opencode debug config` and `opencode debug agents` run from the project folder. They show the merged rules and the registered agents without calling a model.

Record the tool version in the pull request. If a tool cannot enforce a rule, say so in the README rather than pretending.
