# Audit brief: is Paperchain necessary, or is it overkill?

This file is a brief for the next AI, not a review and not a product document. Do not modify the repository, this file, `docs/audits/AUDIT.md`, the source, the tests or the docs while auditing. Work in a temporary copy. The deliverable is a written decision with evidence, not a rewrite.

## The three questions to answer

1. Are these scripts and libraries necessary at all?
2. Can the same result be achieved with simple prompts and Markdown files?
3. Is all of this project really necessary?

A defensible answer must take a position on each question. "It depends" is only acceptable if you state the conditions, the evidence for each branch, and which branch applies to this user.

## The user's actual goal

The user wants to write papers with an AI agent under these constraints:

- **R1 — Assisted writing.** The AI helps draft and edit the user's papers.
- **R2 — Supplied sources only.** The AI reads the references the user supplied and must not introduce outside facts.
- **R3 — No invented evidence.** The AI may only write claims supported by those references. In particular, it must not invent quotes, page numbers, authors, dates or numbers. If a claim cannot be supported, it must not be written.
- **R4 — Zotero is the reference manager.** The bibliography metadata is expected to come from Zotero, not from hand-maintained BibTeX or from the AI.
- **R5 — Vancouver, enforced by the project.** Citations and the reference list must be Vancouver. The style must be a property of the project, not something the agent is merely asked to remember.
- **R6 — Simplicity has value.** The user is asking whether the machinery is proportionate. Complexity is a cost even when it works, and a feature is not necessary merely because it is defensible.

Two readings of R5 need to be kept apart, because they lead to different verdicts:

- **R5a — Project-configured style.** `paper.toml` (or an equivalent project file) pins the Vancouver CSL style and the build always uses it.
- **R5b — Correct rendered output.** The built document actually contains Vancouver-style in-text citations and a Vancouver reference list, including how page locators are handled.

The phrase "at the project itself" most likely means R5a, but the user will judge the result by R5b. Answer both. If the repository only supports one, say so.

## What the existing `docs/audits/AUDIT.md` is for

`docs/audits/AUDIT.md` is an adversarial security and correctness brief: can the guarantee be broken silently? It is not a fitness-for-purpose brief. Do not reuse its findings as the answer to this audit. In particular, do not spend the audit hunting parser edge cases or permission bypasses. Use it only to understand what the project claims, then ask whether those claims are worth their cost for R1–R6.

Treat the repository's stated limits as scope, not as defects: no OCR, DOCX is always page 1, quote checking proves existence rather than fair paraphrasing, two-column PDFs extract badly, and `unlock`/`--force` exist. The question is whether those limits leave enough of R1–R6 satisfied.

## Current state of the repository

Audit the current working tree, not the 0.3.0 release. The tree has uncommitted changes, including changes to `docs/audits/AUDIT.md`, `docs/CHANGELOG.md`, several modules and tests.

Measured in this environment on 2026-11-14, after the round-5 fixes:

- 21 Python files under `src/paperchain/` including `__init__.py` and `__main__.py`; 6,048 lines of Python.
- 17 test files; 2,833 lines; 247 test functions; 259 passed and 2 skipped with Pandoc 3.13, or 249 passed and 12 skipped without Pandoc on Windows.
- Runtime dependencies: `pypdf` (and `tomli` only on Python 3.10). Pandoc is an external dependency for DOCX import, `build` and citeproc.
- 11 CLI commands: `help`, `init`, `organize`, `import`, `convert`, `match`, `lock`, `unlock`, `check`, `build`, `doctor`.
- One agent adapter, OpenCode, marked `tested = false` in `src/paperchain/adapters/opencode/adapter.toml`.
- No LLM API, no vector database, no server and no database. The AI is external. Paperchain is a text extractor, a deterministic checker, a manifest and a build wrapper.

Largest modules, for orientation only:

| File | Lines | Role |
| --- | ---: | --- |
| `src/paperchain/check.py` | 1082 | hash, key, page, quote, YAML and bibliography verification |
| `src/paperchain/cli.py` | 574 | command parsing and JSON envelopes |
| `src/paperchain/build.py` | 509 | citeproc/fallback rendering, resources and pandoc |
| `src/paperchain/organize.py` | 486 | adoption and file sorting |
| `src/paperchain/extract.py` | 444 | PDF/DOCX text and page maps |
| `src/paperchain/project.py` | 440 | paths, validation and cache layout |
| `src/paperchain/citations.py` | 350 | citation syntax, masking and rendering |
| `src/paperchain/convert.py` | 342 | reference discovery, keys and conversion |
| `src/paperchain/manifest.py` | 290 | `paper.toml` model and hashes |
| `src/paperchain/library.py` | 252 | CSL JSON, title keys and style validation |
| `src/paperchain/init_cmd.py` | 230 | template and adapter installation |
| `src/paperchain/match_cmd.py` | 219 | source-to-Zotero title matching |
| `src/paperchain/doctor.py` | 193 | toolchain diagnostics |
| `src/paperchain/import_cmd.py` | 186 | manuscript to Markdown |
| `src/paperchain/locking.py` | 178 | lock, unlock and read-only bits |
| `src/paperchain/util.py` | 138 | hashing, normalisation and file helpers |
| `src/paperchain/help_cmd.py` | 60 | quick-start text |
| `src/paperchain/errors.py` | 43 | error and finding types |
| `src/paperchain/locations.py` | 23 | OS cache paths |

The user-facing workflow is `init` (or `init --adopt` + `organize`) → put the manuscript in `Manuscript/` and references under `References/` → `import` → `convert` → `lock` → agent edits `Paper/paper.md` → `check` → `build`.

## What each part is actually doing

Do not accept this table as complete; verify it in the code. It is a starting map.

| Part | What it does | Directly supports | Preliminary necessity question |
| --- | --- | --- | --- |
| `extract.py`, `convert.py` | PDF/DOCX/TXT/MD to page-marked cache text plus a JSON page map | R2, R3 | Without page text and page labels, neither an AI nor a checker can tie a claim to a page. |
| `citations.py` | Parses `[@key]`, `[@key, p. 12]`, ranges and quoted evidence | R3, R5 | The quote part is the only machine-readable evidence the checker can test. |
| `check.py` | Re-hashes sources, checks keys and pages, and verifies quotes after normalisation | R3 | This is the only part that can refuse a fabricated citation deterministically. |
| `library.py` | Loads Zotero/Better BibTeX CSL JSON and indexes entries by `id` | R4 | Zotero metadata can be used only through an export like this. |
| `build.py` | Runs `check`, then Pandoc with citeproc or a built-in author-year fallback | R5, output | Build is where Vancouver is applied, if a Vancouver CSL is supplied. |
| `manifest.py` | Stores source paths, hashes, page counts, manuscript hash and build settings | R3, R6 | A small project state file is hard to avoid; the TOML schema may be larger than needed. |
| `locking.py` | Hashes, `chmod`s and unlocks references | source integrity | Useful against accidental or agent edits, but not against hallucination. |
| `project.py`, `locations.py` | Resolves paths and puts generated text in the OS cache | infrastructure | The external cache is a design choice, not a requirement of R1–R5. |
| `import_cmd.py` | Converts an existing manuscript to Markdown | adoption | Irrelevant if the user starts from a blank draft. |
| `init_cmd.py` | Installs the project template and adapter | setup | Convenience; the same layout can be created by hand. |
| `organize.py` | Sorts an existing folder into `Manuscript/`, `References/` and `Dump/` | adoption | Pure convenience; not part of the guarantee. |
| `doctor.py`, `help_cmd.py` | Diagnostics and onboarding | setup | Convenience; can be replaced by docs. |
| `adapters/opencode/*` | Agent instructions and path/shell permissions | guardrail | A prompt-level rule, not proof. The adapter itself says it is untested. |
| `cli.py` | Command surface and stable JSON | UX | Necessary only if the rest is kept. |
| `tests/` | Regression and adversarial tests | confidence | Valuable, but test volume is not evidence that every feature is necessary. |

## What the Zotero and Vancouver requirements currently get

These are factual starting points, not conclusions. Verify each with a real build.

- Zotero is not integrated live. `References/library.json` is an optional CSL JSON export. The user must export it manually from Zotero or Better BibTeX. There is no Zotero API, no SQLite reader and no automatic refresh (`README.md:161-171`, `docs/how-it-works.md:129-131`).
- Citation keys must match the Better BibTeX keys. `check` requires each cited key to exist in the CSL JSON when the file is present (`src/paperchain/check.py:538-551`).
- `library.json` is deliberately excluded from the source set (`src/paperchain/project.py:18-28`). `lock` and `check` hash the PDFs/DOCX and the generated page maps, but not the CSL JSON itself. Re-exporting or editing Zotero metadata can therefore change titles, authors and the bibliography without a `source_hash_mismatch`. `check` only warns when a manifest title and a CSL title look different (`src/paperchain/check.py:457-471`).
- There is no bundled `vancouver.csl` anywhere in the repository. A search for `*.csl` and `vancouver` found no style file. The README shows `csl = "styles/vancouver.csl"` as an example, but the user must obtain and place that file.
- If `References/library.json` is absent, `build` uses the built-in author-year renderer, not Vancouver (`src/paperchain/build.py:79-98`, `src/paperchain/citations.py:340-362`). If `library.json` exists but `[build] csl` is not set, Pandoc citeproc uses its own default CSL, which is not Vancouver. Vancouver is therefore opt-in twice: export the library, then configure the style.
- Nothing verifies that the configured CSL file is actually Vancouver. Nothing validates the style's class (numeric vs author-date), its locator format, or whether the built DOCX contains a Vancouver reference list.
- Page locators are preserved for citeproc as `p. 12` / `pp. 12-14` (`src/paperchain/build.py:189-202`). Whether a Vancouver numeric style renders those locators acceptably in Word must be tested, not assumed.
- The built-in fallback citation is `(Authors, Year, p. 12)` (`src/paperchain/citations.py:340-350`). That is not Vancouver under either reading of R5.

If R4 and R5 are hard requirements, the project is currently a kit rather than a solution: Zotero export, Better BibTeX keys, a Vancouver CSL file and a `paper.toml` setting are all manual steps. Count those steps in the cost comparison.

## What "necessary" should mean in this audit

Classify each part, not the project as a whole. Use these levels and say which level a feature is at.

- **N0 — Required for the guarantee.** Removing it lets a false citation, invented quote or wrong page pass without a deterministic error. It is necessary if R3 is a hard requirement.
- **N1 — Required for the workflow.** Removing it makes the workflow impractical for this user even if the guarantee survives. Example: a way to map citation keys to files.
- **N2 — Convenience.** Setup, diagnostics, templates, adoption and formatting help. Nice, not load-bearing.
- **N3 — Insurance.** Locks, read-only bits, manuscript hashing, source-drift detection, tamper evidence. Valuable only if the user cares about detecting later changes.
- **N4 — Productization.** Multi-OS behaviour, packaging, adapters for several agents, cache management, polished JSON, a broad test suite. Necessary to ship to strangers, not necessarily to write one paper.
- **N5 — Speculative or unused.** Features with no identified user or no test. Say so directly if you find them.

A feature is overkill for this user when it is N2–N5, has nonzero operational or maintenance cost, and its removal does not weaken R1–R6.

## Answering question 1: are the scripts and libraries necessary?

The audit must separate the **guarantee-bearing core** from the **product scaffolding**. Do not argue from line count alone. For each item, identify the smallest concrete failure that would occur if it were removed.

Specifically test or reason about these claims:

- **PDF/DOCX extraction and page maps.** Can the AI read a 40-page PDF and reliably know page numbers without extraction? What happens with a scanned PDF, a two-column paper, a DOCX, or a PDF whose text layer is wrong? If extraction is unavoidable, is `pypdf` the right dependency, or would `pdftotext`/`mutool`/PyMuPDF be simpler and more accurate?
- **The checker.** Can a prompt alone guarantee that a quote appears on the cited page? Can a second LLM? What is the false-negative rate of each, and what does a single undetected fabricated quote cost the user? This is the central question.
- **The citation parser.** Is a custom syntax necessary, or could the project use Pandoc's native `[@key, p. 12]` and a small verifier? What does the custom syntax buy: quoted evidence inside the citation, strict rejection of unparseable forms, stable line numbers?
- **The manifest and hashes.** Is `paper.toml` necessary for key→file mapping, or would a simple `sources.json`/front matter do? Are hashes necessary if the user trusts their own files? What breaks if the manifest is removed?
- **The build wrapper.** Could the user run `pandoc` directly with `--citeproc --csl vancouver.csl`? What does `build` add: running `check` first, validating image resources without `--sandbox`, deterministic output naming, quote removal? Is that worth a wrapper?
- **The lock and read-only layer.** Does it prevent hallucination? No. Does it prevent source drift? Yes, if the source changes after locking. Is that a requirement, or insurance the user did not ask for?
- **The adapter.** Is it enforcement or advice? The file itself says `tested = false`. If a prompt in `AGENTS.md` already says "do not edit references", what does the adapter add, and what does it cost in portability and maintenance?
- **The cache.** Does generated text need to live outside the project? What breaks if it lives in `.paperchain/` inside the project? Is the external cache worth the permission prompt, cleanup and path complexity?
- **`init`, `organize`, `import`, `doctor`, `help`.** Which of these would a user miss after the first day? Which can be replaced by a README and three commands?
- **Tests and packaging.** Are 2,833 lines of tests and a wheel necessary for one user, or are they the cost of shipping? Do not call them overkill merely because the user is one person; they are what keeps the guarantee from regressing.

The answer to question 1 should end with a keep/optional/remove table and a **minimum viable code path**: the smallest set of files, dependencies and commands that still satisfies R1–R5. Estimate its size and name every guarantee it loses.

## Answering question 2: can prompts and Markdown do the same thing?

Build the baseline. Do not answer from intuition.

A fair baseline is:

- Zotero with Better BibTeX keys and a CSL JSON export.
- Markdown files for the draft and the reference notes.
- A strong system prompt or `AGENTS.md` that says: use only these sources, quote exact text, always give a page, never invent a citation, ask when evidence is missing.
- Pandoc with `--citeproc --csl vancouver.csl` for output.
- Optionally, a second LLM or a human reviewer as the checker.

Then compare it with Paperchain on the same fixture, same model, same references, same draft. Measure behavior, not vibes.

Suggested fixture:

- Three to five open-access PDFs with known page contents, including one two-column paper and one scanned/image-only paper.
- One DOCX reference, to test the page-1 limit.
- One Zotero CSL JSON export with a deliberate missing entry and a deliberate title mismatch.
- A 10–20 page draft with 20 citations: some correct, some with an invented quote, some with a correct quote on the wrong page, some with a nonexistent key, some without a page, some with a quote that exists in a different source.
- A fixed answer key, so a blind scorer can mark false negatives and false positives.

Scenarios that must be run for both approaches:

| Scenario | What to observe |
| --- | --- |
| Correct quote on the correct page | accepted, rendered correctly |
| Invented quote that sounds plausible | is it detected? by what mechanism? |
| Real quote, wrong page | is it detected? |
| Real quote, wrong source | is it detected? |
| Nonexistent citation key | is it detected before or during build? |
| Page beyond the source length | is it detected? |
| Citation without a page | warning, error, or silence? |
| Reference file edited after the draft was written | is the change detected? |
| Zotero metadata re-exported with a changed title/author | is the change detected, and does the bibliography change? |
| Vancouver style applied | are in-text citations numeric and the reference list Vancouver? do page locators survive? |
| DOCX reference | can the page be verified at all? |
| Scanned PDF | does the workflow fail loudly or silently? |
| Long draft with 30+ sources | does the model drift, truncate or start inventing? |
| Prompt injection inside a PDF | does the agent follow it? does any check catch it? |
| Agent told to "just finish the paper" | does it fabricate to satisfy the instruction? |

The prompt-only baseline will probably produce a usable draft. The question is not whether it can produce a paper; it is whether it can **guarantee** the specific property the user asked for. Separate these outcomes in the report:

- **Writing quality**: fluency, structure, coverage. A prompt can be excellent here.
- **Citation formatting**: Zotero + Pandoc + Vancouver CSL can be excellent here.
- **Evidence integrity**: whether a wrong quote or page is caught deterministically. This is where a prompt is weakest.

Also test the "second AI as checker" option explicitly. It is the most plausible prompt-only substitute for `check`. Record its cost, latency, nondeterminism, and whether it can be fooled by the same model that wrote the text. A second model that catches 19 of 20 errors is not equivalent to a deterministic check; say what the residual risk is.

## Answering question 3: is the whole project necessary?

This is a portfolio decision, not a code decision. Weigh:

- **Frequency and stakes.** One paper a year with human review of every citation is different from a thesis, a grant, or a lab with a publication record at stake.
- **Cost of a false negative.** If one fabricated quote in a submitted paper is unacceptable, the deterministic check has high value. If the user reads and verifies every citation anyway, the check is insurance against fatigue, not a hard requirement.
- **Setup and per-session friction.** Count the commands, the manual Zotero export, the CSL file, the cache permission, the `paper.toml` edits and the recovery steps. Compare with opening Zotero, Word and a chat window.
- **Maintenance.** Python, `pypdf`, Pandoc, OpenCode, a Vancouver CSL, Windows read-only bits, cache cleanup. Who fixes it when extraction changes or a new Pandoc version alters output?
- **Lock-in and transparency.** Is the project understandable to the user, or does it require an AI to maintain? Can the user inspect and repair it?
- **Opportunity cost.** Every hour spent on `organize`, adapters or packaging is an hour not spent on the paper.
- **What the user actually asked for.** R1–R5 do not mention multi-agent support, adoption of messy folders, a cache outside the project, tamper-evident locks, DOCX-only output, or a polished CLI. Those may still be good ideas, but they need their own justification.

Take a position on one of these outcomes, with reasons:

- **Keep as is.** The guarantee is worth the cost; the gaps in Zotero/Vancouver are fixable without simplification.
- **Keep the core, cut the product.** Retain extraction, citation parsing, quote checking, Zotero CSL loading and Vancouver build; remove or make optional the adoption, adapter, cache, lock and packaging layers.
- **Replace with a thin tool.** A prompt, Markdown, Zotero export, Pandoc and a small checker (roughly a few hundred lines) meet R1–R5; Paperchain is over-engineered for this user.
- **Replace with prompts only.** The user accepts manual review and the residual risk; the project is unnecessary. State exactly what is lost.
- **Use an existing product.** Zotero + Word + a writing assistant, or a reference-grounded research tool, meets the need with less maintenance but without the same page-level guarantee.

If you recommend a thin tool, specify its behavior precisely enough that another agent could implement it: input layout, citation syntax, what is checked, what is not, how Zotero metadata is read, how Vancouver is selected, how the DOCX is produced, and what the user sees on failure. Do not write the implementation in this audit.

## Decision criteria to apply explicitly

Use these as a scorecard, not as a substitute for judgment:

| Criterion | Question |
| --- | --- |
| Guarantee | Does the part prevent a wrong citation/quote from passing silently, or only make it less likely? |
| User requirement | Which of R1–R6 does it serve? If none, why is it there? |
| Failure visibility | When it fails, does the user know, or does it degrade quietly? |
| Operational cost | Install, commands, manual steps, permissions, recovery, maintenance. |
| Cognitive cost | How many concepts must the user hold? Sources, keys, pages, hashes, cache, adapter, CSL, Pandoc, manifest. |
| Reversibility | Can the user stop using it and still have a readable paper and references? |
| Portability | Does it work on the user's OS without a support session? |
| Evidence | Was the claim tested, or is it inferred from the README? |

A part is justified only if its criterion score is better than the simplest alternative that meets the same requirement.

## Required output from the auditor

Produce a single review with this structure:

1. **Verdict in one paragraph.** Answer all three questions directly. State the recommended shape: keep, trim, replace, or prompts only.
2. **Assumptions.** Resolve R5a vs R5b, live Zotero vs exported Zotero, DOCX vs Markdown output, single user vs collaborators, and hard guarantee vs best effort. If the user has not specified, state the assumption you used and how the verdict changes under the other reading.
3. **Evidence table.** For each of the three questions, list the test or code fact, the result, and what it implies. Include exact commands and versions.
4. **Necessity matrix.** Every module, dependency and command gets `keep`, `optional`, or `remove`, with a reason tied to R1–R6 and an N0–N5 label. Include the tests and packaging.
5. **Baseline comparison.** Prompt + Markdown + Zotero + Pandoc + Vancouver vs Paperchain, on the fixture. Report detection results, false positives/negatives, time and friction. Distinguish writing quality, formatting and evidence integrity.
6. **Zotero/Vancouver gap analysis.** What works today, what is manual, what is not enforced, and whether the gap is a blocker for R4/R5 or a documentation issue.
7. **Minimum viable alternative.** If the project is overkill, the smallest design that still satisfies the user's hard requirements, with estimated size and dependencies. If it is not overkill, the smallest defensible subset and what should be deferred.
8. **Cost of simplification.** What guarantee, convenience or safety is lost under the recommendation. Be specific; do not say "some robustness".
9. **Revision plan.** Ordered, concrete changes another AI should make, with file references. Separate "must fix to meet R4/R5" from "optional simplification" and "do not touch".
10. **Open questions.** Only questions that genuinely change the verdict. State a default answer for each so the user can reply briefly.

## Rules for the auditor

- Do not modify the repository. Use a temporary copy and `PAPERCHAIN_CACHE_DIR`.
- Do not rewrite `docs/audits/AUDIT.md`; this is a separate question.
- Do not treat the README's claims as evidence. Run the workflow.
- Do not equate "the model usually follows the prompt" with a guarantee.
- Do not recommend deleting `check` or extraction while R3 is a hard requirement, unless you have tested a substitute that catches the same failures.
- Do not recommend a full rewrite without first building and testing the prompt-only baseline.
- Do not call a feature overkill just because it is large. Call it overkill when its cost exceeds its contribution to R1–R6.
- Do not call a feature necessary just because it is well tested. Tests show that it works, not that the user needs it.
- Do not report the intentional limits in `docs/audits/AUDIT.md` as bugs. Report them as scope only if they make R1–R6 unattainable.
- Do not use copyrighted PDFs. Use open-access fixtures.
- If a test cannot be run because Pandoc or a PDF is missing, say so and mark the conclusion as inferred.

## Suggested prompt for the revising AI

> Read `docs/audits/AUDIT-NECESSITY.md` and the repository. Answer the three questions in it: are the scripts and libraries necessary, can simple prompts plus Markdown achieve the same result, and is the whole project necessary for a single user who wants AI-assisted papers grounded in Zotero references with Vancouver citations enforced by the project. Do not modify the repository. Build a fair prompt-only baseline in a temporary folder and compare it with Paperchain on the same fixture, including invented quotes, wrong pages, missing keys, changed references and Vancouver output. Separate writing quality from evidence integrity. Give a verdict, a keep/optional/remove matrix tied to the user's requirements, the smallest viable alternative, and a concrete revision plan. Report exact commands and evidence.
