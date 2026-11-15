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

Requires Python 3.10+ and [pandoc](https://pandoc.org/installing.html) 2.15 or newer (pandoc is needed for DOCX import, `build`, and citeproc; `build` validates image paths itself before invoking Pandoc; PDF/TXT import and `check` do not need it).

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

Do **not** copy the repository, `.venv`, `src/` or `tests/` into each paper project. Install the command once; `pipx` keeps it in its own environment. The source checkout itself can live anywhere outside your documents, for example `C:\Tools\paperchain`. A paper project only needs the command and `pandoc` on `PATH`.

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

`import`, `convert`, `match` and `lock` are yours to run. The agent is not allowed to import, convert, match, lock or unlock. If the original manuscript changes, `check` reports `manuscript_hash_mismatch`; re-run `paperchain import --force` (the current draft is saved as `Paper/paper.md.bak`), review the Markdown, and continue.

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
├── styles/                CSL files, for example vancouver.csl
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

`check` verifies the quote against the extracted text for that page. Without a Zotero bibliography, `build` replaces the bracket with `(Smith, 2024, p. 12)` and appends a reference list for cited sources, unless `paper.md` already has a `## References` heading. With a CSL style, Pandoc citeproc formats the citations and the reference list; standard Vancouver is numeric and normally does not print page locators, so the page in `[@key, p. 12]` is evidence for `check`, not necessarily text in the final document.

YAML metadata blocks may set document metadata such as `title`, `author`, `date`, `abstract`, `keywords` and `lang`, but `check` uses an allow-list: citation settings and an inline `references:` bibliography are errors. A citation key must start and end with a letter or digit, because Pandoc treats a trailing `. : / + -` as punctuation outside the key; `build` also fails if citeproc reports that it could not resolve a citation.

### Zotero and Vancouver

Zotero is not read live. Paperchain uses an export you make by hand, and the style is only enforced if you ask for it. To get Vancouver as a property of the project:

1. Start the project with `paperchain init . --title "..." --style vancouver`. This writes `style = "vancouver"`, `bibliography = "References/library.json"` and `csl = "styles/vancouver.csl"` under `[build]` in `paper.toml`.
2. In Zotero, give each item a Better BibTeX key and export the collection as **CSL JSON** to `References/library.json`.
3. Download the NLM/Vancouver CSL from [Zotero's style page](https://www.zotero.org/styles/vancouver) and save it as `styles/vancouver.csl`. The page currently serves the NLM/Vancouver style (id `nlm-citation-sequence`), which is the current official style. `paperchain init --style vancouver` creates the `styles/` folder but does not bundle the CSL file.
4. Run `paperchain match --apply`. Source keys come from filenames; this pairs each source with a Zotero entry by title and records `citation_key = "Amaeze2021"` in `paper.toml`. Only an exact normalized title is applied; a title that merely contains the other is shown as a suggestion for you to confirm. Unmatched, ambiguous and duplicate-title cases are reported instead of guessed, and can be set by hand.
5. Run `paperchain lock`. This hashes the Zotero export and the CSL file next to the references.

After that a citation may use either name: `[@Amaeze2021]` and `[@smith2024]` resolve to the same source, and citeproc always receives the Better BibTeX key.

What is then enforced:

- `check` fails with `style_requires_bibliography` / `style_requires_csl` if either file is missing, and with `csl_not_vancouver` if the style is not an independent, numeric style with a `<bibliography>` element and a known Vancouver id. A dependent style is rejected with the name of its parent. If a legitimate variant has a newer id, list that id in `styles/accepted-csl-ids.txt` beside the CSL file; `lock` hashes that sidecar together with the CSL, so a later edit is a `csl_hash_mismatch`. The writer adapter denies edits to `styles/**`.
- `check` fails with `bibliography_hash_mismatch` (or `csl_hash_mismatch`) if the export or the style changed after `lock`. A Zotero re-export is therefore never silent; review it and run `paperchain lock --accept-changes`.
- A locked style project must have hashed both files: an unhashed export is `bibliography_not_locked`, an unhashed style is `csl_not_locked`, and `lock` refuses to run while either file is missing.
- `build` never falls back to the built-in author-year renderer or to Pandoc's default style while `style` is set, and `--force` does not override that.
- `check` fails with `source_metadata_mismatch` once a `citation_key` is set and the CSL entry's title is not the same work as the PDF title. Without a `citation_key`, the same mismatch is a warning.
- Two CSL entries with one id are an error as soon as a source or citation uses that id, because Paperchain and citeproc may choose different entries. An unused duplicate stays a warning.

What is not enforced: whether the chosen CSL prints a locator such as `p. 12`. The official NLM/Vancouver style is numeric and does not print page locators; the page remains available to `check`. Without `style`, the previous behaviour is unchanged: `library.json` plus no `csl` gives Pandoc's default author-date style.

Citeproc output is static formatted text, not live Zotero fields; use the Zotero Word plugin if you need click-to-refresh fields. Only DOCX output is supported.

## Commands

| Command | Who runs it | What it does |
| --- | --- | --- |
| `paperchain help` | anyone | print the quick-start instructions; `--json` returns them as steps for agents |
| `paperchain init` | human | create a project folder from the template |
| `paperchain organize` | human | sort existing files into `Manuscript/`, `References/` and `Dump/`; plan first, `--apply` to move |
| `paperchain import` | human | copy the original manuscript to `Paper/paper.md` without editing the original |
| `paperchain convert` | human | extract page-marked text from references (recursively); the agent adapter denies it |
| `paperchain lock` | human | record hashes, refuse to bless changes without `--accept-changes`, make references read-only |
| `paperchain match` | human | pair sources with Zotero/Better BibTeX entries by title; `--apply` writes `citation_key` |
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
- [Changelog](docs/CHANGELOG.md) — what changed in each release.
- [Contributing](docs/contributing.md) — tests, fixtures, releasing.

## License

MIT. See [LICENSE](LICENSE).
