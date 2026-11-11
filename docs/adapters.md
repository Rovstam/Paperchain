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

## Status

| Tool | Status | Notes |
| --- | --- | --- |
| OpenCode V2 | config verified, checklist pending | `permissions` array with `shell`, `edit`, `subagent`; `default_agent: writer`; two agents |
| Claude Code | not shipped | Needs `CLAUDE.md` containing `@AGENTS.md`, plus `.claude/settings.json` |
| Codex | not shipped | Reads `AGENTS.md`; needs its own sandbox and approval configuration |

"Config verified" means the tool loaded the file and registered both agents with the expected merged permissions. It does not mean the enforcement checklist below has been run. Only mark `tested = true` after running it.

## OpenCode adapter

Files: `opencode.json`, `.opencode/agents/writer.md`, `.opencode/agents/scout.md`.

The project config does four things:

1. Loads `AGENTS.md` as instructions and selects `writer` by default.
2. Denies edits to `References/`, `Output/`, `paper.toml` and `AGENTS.md`.
3. Denies all shell commands, then allows `paperchain *`, `git status *` and `git diff *`, and re-denies `paperchain unlock*` and `paperchain init*`.
4. Denies launching subagents except `scout`, and asks before touching directories outside the project.

Two rules matter more than the rest:

```jsonc
{ "action": "shell", "resource": "*", "effect": "deny" },
{ "action": "shell", "resource": "paperchain *", "effect": "allow" },
{ "action": "shell", "resource": "paperchain unlock*", "effect": "deny" },
```

Rules are evaluated in order and the last match wins. Without the final deny, `paperchain *` would also allow `paperchain unlock`, which defeats the lock. If you edit the list, keep the specific `deny` rules after the broad `allow`.

The `writer` agent also denies `webfetch` and `websearch`, so it cannot quietly pull facts from outside the reference set. The `scout` subagent is the opposite: it may search, and it can only write to `Candidates/`.

The agent definitions live in Markdown with YAML frontmatter, which OpenCode merges with the project config. Agent rules are appended after global rules.

## Adding Claude Code

Claude Code does not read `AGENTS.md` directly. The usual bridge is a `CLAUDE.md` at the project root containing:

```markdown
@AGENTS.md
```

Then add a settings file for the same deny/allow shape. The settings schema changes between releases, so write it against the version you run, test it, and only then set `tested = true` in `adapter.toml`.

## Adding Codex

Codex reads `AGENTS.md` without a bridge. The work is in its sandbox and approval configuration: block writes outside `Paper/` and `Candidates/`, and block `paperchain unlock`. Test the exact version.

## Testing an adapter

1. `paperchain init /tmp/adapter-test --agent <name>`
2. Open that folder in the tool.
3. Ask the agent to edit `References/originals/` and confirm it is refused.
4. Ask it to run `paperchain unlock` and confirm it is refused.
5. Ask it to run `paperchain check` and confirm it is allowed.
6. Ask it to write in `Paper/paper.md` and confirm it is allowed.

For a quick check that the config was parsed at all, OpenCode has `opencode debug config` and `opencode debug agents` run from the project folder. They show the merged rules and the registered agents without calling a model.

Record the tool version in the pull request. If a tool cannot enforce a rule, say so in the README rather than pretending.
