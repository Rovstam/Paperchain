# paperchain

**Write papers with an AI agent that can only use the sources you gave it.**

`paperchain` is a small Python CLI plus a set of agent rules. You drop PDFs and Word files into `References/originals/`. The tool converts them to page-marked text, hashes them, and makes them read-only. The agent drafts `Paper/paper.md` with citations that name a source and a page. `paperchain check` then proves that every citation resolves and every quoted span actually occurs on the cited page. `paperchain build` turns the Markdown into a `.docx`.

The point is not to make the agent smarter. It is to make its output cheap to audit.

```
References/originals/*.pdf ──convert──> References/_text/*.txt (+ page map)
                                              │
                                     agent writes Paper/paper.md
                                              │
                                    check: keys, pages, quotes
                                              │
                                     build: Output/*.docx
```

## What `check` can and cannot prove

It can prove that:

- the reference files are byte-for-byte the ones you locked;
- every citation key exists;
- the cited page exists;
- a quoted span appears on that page, after normalising whitespace, ligatures and line-break hyphenation.

It cannot prove that a claim is true or fairly paraphrased. A quote can exist and still be misused. Read the paper, or at least the sentences that carry the most weight.

The real safeguard is `paperchain check`, not the permission files. Permissions are a guardrail; the checker is the evidence.

## Install

Requires Python 3.10+ and [pandoc](https://pandoc.org/installing.html) (pandoc is only needed for `build`).

<details>
<summary><strong>Windows</strong></summary>

```powershell
winget install --id Python.Python.3.12 -e
winget install --id JohnMacFarlane.Pandoc -e
py -m pip install --user pipx
py -m pipx ensurepath
# open a new terminal
git clone <this-repo> paperchain
pipx install ./paperchain
paperchain doctor
```

`py` is the Windows launcher; `python` may not exist. `pipx` keeps the tool in its own environment so it cannot break other projects.
</details>

<details>
<summary><strong>macOS</strong></summary>

```bash
brew install python@3.12 pandoc pipx
pipx ensurepath
# open a new terminal
git clone <this-repo> paperchain
pipx install ./paperchain
paperchain doctor
```
</details>

<details>
<summary><strong>Linux</strong></summary>

```bash
sudo apt install python3 python3-pip pipx pandoc    # Debian/Ubuntu
pipx ensurepath
# open a new terminal
git clone <this-repo> paperchain
pipx install ./paperchain
paperchain doctor
```
</details>

Until the first PyPI release, install from a clone. After that, `pipx install paperchain` (or `pip install -U paperchain`) is enough, and every paper gets fixes without copying scripts.

## Five-minute demo

```bash
paperchain init my-paper --title "My Paper" --agent opencode
cd my-paper
# put real PDFs, DOCX, TXT or MD files in References/originals/
paperchain convert
paperchain lock
paperchain check
paperchain build
```

`init` creates the folder layout, `AGENTS.md`, `paper.toml` and the OpenCode agent files. Open the folder in OpenCode and the `writer` agent is selected by default.

`convert` and `lock` are yours to run. The agent is not allowed to lock or unlock.

## Layout of a paper project

```
my-paper/
├── AGENTS.md              the rules, read by every agent
├── paper.toml             sources, hashes, build settings
├── References/
│   ├── originals/         the PDFs and Word files you supplied (gitignored)
│   └── _text/             page-marked text + page map (gitignored)
├── Candidates/            sources an agent proposes; not citable
├── Paper/paper.md         the only file the writer edits
├── Output/                generated .docx (gitignored)
├── opencode.json          permissions and default agent
└── .opencode/agents/      writer and scout
```

`References/originals/` and `References/_text/` are ignored by git on purpose: they are copies of other people's work. Keep paper projects in **private** repositories.

## Citation syntax

| Syntax | Meaning |
| --- | --- |
| `[@smith2024]` | source only |
| `[@smith2024, p. 12]` | source and page |
| `[@smith2024, pp. 12-14]` | page range |
| `[@smith2024, p. 12: "exact words"]` | page plus quoted evidence |

`check` verifies the quote against the extracted text for that page. `build` replaces the bracket with `(Smith, 2024, p. 12)` and appends a reference list for cited sources, unless `paper.md` already has a `## References` heading.

## Commands

| Command | Who runs it | What it does |
| --- | --- | --- |
| `paperchain init` | human | create a project from the template |
| `paperchain convert` | human or agent | extract page-marked text from references |
| `paperchain lock` | human | record hashes, refuse to bless changes without `--accept-changes`, make references read-only |
| `paperchain unlock` | human | make references writable again |
| `paperchain check` | agent | verify hashes, keys, pages, quotes |
| `paperchain build` | agent | check, then build `Output/*.docx` |
| `paperchain doctor` | anyone | diagnose Python, pandoc, OCR, hashes, adapter |

Every command prints human text by default and one JSON object with `--json`. Exit codes: `0` clean, `1` findings or a failed check, `2` the command could not run. Agents should read the JSON.

## Agent support

| Tool | Status | Files |
| --- | --- | --- |
| OpenCode V2 | config verified on 2.2.6; permission checklist not run | `opencode.json`, `.opencode/agents/writer.md`, `.opencode/agents/scout.md` |
| Claude Code | not shipped | needs `CLAUDE.md` with `@AGENTS.md` and a settings file |
| Codex | not shipped | reads `AGENTS.md`; needs its own sandbox settings |

The rules live in `AGENTS.md` for every tool. Permission files are adapters, because each tool invents its own format. The adapter is a guardrail, not the guarantee.

## Documentation

- [How it works](docs/how-it-works.md) — manifest, hashes, page maps, check semantics, limits.
- [Agent adapters](docs/adapters.md) — the adapter contract and how to verify one.
- [Windows setup](docs/setup-windows.md) · [macOS setup](docs/setup-macos.md) · [Linux setup](docs/setup-linux.md)
- [Troubleshooting](docs/troubleshooting.md) — error codes and fixes.
- [Contributing](docs/contributing.md) — tests, fixtures, releasing.

## License

MIT. See [LICENSE](LICENSE).
