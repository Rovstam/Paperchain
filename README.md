# paperchain

**Write papers with an AI agent that can only use the sources you gave it.**

`paperchain` is a small Python CLI plus a set of agent rules. You create one folder per project, put the original manuscript in it, and put reference PDFs and Word files under `References/` each on it's respective folder. The tool imports the manuscript to Markdown without touching the original, converts the references to page-marked text, hashes them, and makes them read-only. The agent edits `Paper/paper.md` with citations that name a source and a page. `paperchain check` then proves that every citation resolves and every quoted span actually occurs on the cited page. `paperchain build` turns the Markdown into a `.docx`.

The point is not to make the agent smarter. It is to make its output cheap to audit.

Run `paperchain help` at any time for the short version. Agents should run `paperchain help --json` and relay `data.steps` instead of searching folders.

```
Manuscript/original.docx ──import (read-only)──> Paper/paper.md
References/*/ref.pdf ──────convert────────────> AppData cache (*.txt + page map)
                                                        │
                                               check: keys, pages, quotes
                                                        │
                                               build: Output/*.docx
```

## What `check` can and cannot prove

It can prove that:

- the reference files are byte-for-byte the ones you locked;
- the original manuscript is byte-for-byte the one that was imported;
- every citation key exists;
- the cited page exists;
- a quoted span appears on that page, after normalising whitespace, ligatures and line-break hyphenation.

It cannot prove that a claim is true or fairly paraphrased. A quote can exist and still be misused. Read the paper, or at least the sentences that carry the most weight.

The real safeguard is `paperchain check`, not the permission files. Permissions are a guardrail; the checker is the evidence.

## Install

Requires Python 3.10+ and [pandoc](https://pandoc.org/installing.html) 2.15 or newer (pandoc is needed for DOCX import, `build`, and citeproc; `build` uses `--sandbox`; PDF/TXT import and `check` do not need it).

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

Do **not** copy the repository, `.venv`, `.tools`, `src/` or `tests/` into each paper project. Install the command once; `pipx` keeps it in its own environment. The source checkout itself can live anywhere outside your documents, for example `C:\Tools\paperchain`. A paper project only needs the command on `PATH`.

## Five-minute demo

```bash
paperchain init "My Paper" --title "My Paper" --agent opencode
cd "My Paper"
# put the original manuscript in Manuscript/ (or the project root)
# put reference PDFs/DOCX in References/, in subfolders such as References/diabetes/
paperchain import        # original DOCX/PDF -> Paper/paper.md; original untouched
paperchain convert       # references -> page-marked text
paperchain lock          # hash the references and make them read-only
paperchain check
paperchain build
```

`init` creates the project folder, the layout, `AGENTS.md`, `paper.toml` and the OpenCode agent files. Open the folder in OpenCode and the `writer` agent is selected by default.

`import`, `convert` and `lock` are yours to run. The agent is not allowed to import, convert, lock or unlock. If the original manuscript changes, `check` reports `manuscript_hash_mismatch`; re-run `paperchain import --force` (the current draft is saved as `Paper/paper.md.bak`), review the Markdown, and continue.

If you already prepared the folder with the manuscript and references, adopt it instead of creating a new one:

```bash
cd "My Existing Thesis Folder"
paperchain init . --adopt --title "My Existing Thesis"
paperchain organize          # print the move plan; nothing changes
paperchain organize --apply  # move the files into Manuscript/, References/ and Dump/
```

`--adopt` writes only missing template files. It does not overwrite an existing manuscript, reference file, `AGENTS.md`, `opencode.json` or `Paper/paper.md`. `organize` then sorts what was already there: the original manuscript goes to `Manuscript/`, reference documents to `References/`, and working material (rules, examples, reviews, old notes) to `Dump/`. It deduplicates references by content, never deletes, and sends name conflicts to `Dump/conflicts/`.

## Layout of a paper project

```
my-paper/
├── AGENTS.md              the rules, read by every agent
├── paper.toml             sources, hashes, manuscript and build settings
├── Manuscript/
│   └── original.docx      the original manuscript; never edited or locked
├── References/
│   ├── diabetes/          any subfolders you like
│   │   ├── study.pdf
│   │   └── review.docx
│   └── library.json       optional CSL JSON export from Zotero
├── Candidates/            sources an agent proposes; not citable
├── Paper/paper.md         the only file the writer edits
├── Paper/media/           images extracted from the original, if any
├── Output/                generated .docx (gitignored)
├── Dump/                  working material, old folders, conflicts
├── opencode.json          permissions and default agent
└── .opencode/agents/      writer and scout
```

The original manuscript and the reference files are ignored by git on purpose: they are copies of other people's work. Keep paper projects in **private** repositories.

Generated page text, extracted manuscript images and build temp files are **not** stored in the project. They live in the OS cache folder:

- Windows: `%LOCALAPPDATA%\paperchain\projects\<project-id>\`
- macOS: `~/Library/Caches/paperchain/projects/<project-id>/`
- Linux: `$XDG_CACHE_HOME/paperchain/projects/<project-id>/` (or `~/.cache/paperchain/...`)

`paperchain doctor --json` reports the exact paths under `data.cache`. Set `PAPERCHAIN_CACHE_DIR` to move the cache somewhere else. The `project-id` is stored in `paper.toml`, so the cache survives moving the project folder.

`Paper/media/` is kept as a folder link to the cache (a junction on Windows, a symlink elsewhere) so image paths in `paper.md` stay short. If the OS refuses to create the link, the images fall back to a normal folder inside `Paper/` and everything still works. OpenCode may ask once for permission to read the cache folder because it is outside the project. Allow that folder; it is generated text, not a source of truth.

Reference types: PDF and DOCX are the intended formats. TXT and MD are still accepted because the existing converter supports them. Anything else is ignored with a warning. Loose PDF/DOCX files directly in `References/` are moved by `paperchain convert` into `References/<key>/<file>`; files already in subfolders are left alone. A file in `References/<folder>/name.pdf` gets the key `<folder>-name`, so two subfolders can both contain `review.pdf` without a collision. Projects from older versions that use `References/originals/` keep working.

## Citation syntax

| Syntax | Meaning |
| --- | --- |
| `[@smith2024]` | source only |
| `[@smith2024, p. 12]` | source and page |
| `[@smith2024, pp. 12-14]` | page range |
| `[@smith2024, p. 12: "exact words"]` | page plus quoted evidence |

`check` verifies the quote against the extracted text for that page. By default `build` replaces the bracket with `(Smith, 2024, p. 12)` and appends a reference list for cited sources, unless `paper.md` already has a `## References` heading.

### Zotero / CSL JSON

Export a CSL JSON bibliography from Zotero (or Better BibTeX) to `References/library.json`. When that file exists, `build` uses Pandoc citeproc instead of the built-in author-year renderer: titles, authors, journals, volume and DOI come from Zotero, and the citation keys must match the Better BibTeX keys. To use a specific style, add it to `paper.toml`:

```toml
[build]
bibliography = "References/library.json"
csl = "styles/vancouver.csl"
```

`bibliography` is optional when the file is at the default path. This produces formatted Word citations, not live Zotero fields; use the Zotero Word plugin if you need click-to-refresh fields. Only DOCX output is supported for now.

## Commands

| Command | Who runs it | What it does |
| --- | --- | --- |
| `paperchain help` | anyone | print the quick-start instructions; `--json` returns them as steps for agents |
| `paperchain init` | human | create a project folder from the template |
| `paperchain organize` | human | sort existing files into `Manuscript/`, `References/` and `Dump/`; plan first, `--apply` to move |
| `paperchain import` | human | copy the original manuscript to `Paper/paper.md` without editing the original |
| `paperchain convert` | human | extract page-marked text from references (recursively); the agent adapter denies it |
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
| GitHub Copilot in VS Code | instructions shipped; no permission enforcement | `AGENTS.md`, `.github/copilot-instructions.md` |
| Claude Code | not shipped | needs `CLAUDE.md` with `@AGENTS.md` and a settings file |
| Codex | not shipped | reads `AGENTS.md`; needs its own sandbox settings |

The rules live in `AGENTS.md` for every tool. Permission files are adapters, because each tool invents its own format. The adapter is a guardrail, not the guarantee.

For VS Code, open the project folder itself and select the `Paper/paper.md` file. GitHub Copilot reads `.github/copilot-instructions.md` in recent versions. The integrated terminal must also find `paperchain`: either select Git Bash as the default terminal profile, or add the `Scripts` folder of the Python environment where paperchain is installed (for example `<project>\.venv\Scripts`) to the Windows user `PATH`. Copilot has no permission enforcement, so `paperchain check` remains the evidence.

## Documentation

- [How it works](docs/how-it-works.md) — manifest, hashes, page maps, check semantics, limits.
- [Agent adapters](docs/adapters.md) — the adapter contract and how to verify one.
- [Windows setup](docs/setup-windows.md) · [macOS setup](docs/setup-macos.md) · [Linux setup](docs/setup-linux.md)
- [Troubleshooting](docs/troubleshooting.md) — error codes and fixes.
- [Contributing](docs/contributing.md) — tests, fixtures, releasing.

## License

MIT. See [LICENSE](LICENSE).
