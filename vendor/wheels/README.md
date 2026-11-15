# Offline test wheels

Universal (`py3-none-any`) wheels for running the test suite without network access. They match the versions the suite was verified with on 2026-11-13:

- pytest 9.2.0, pluggy 1.7.0, iniconfig 2.3.1, packaging 26.3, Pygments 2.21.0, colorama 0.4.6
- pypdf 7.0.1 (Paperchain's runtime dependency, needed by the tests)
- tomli 2.0.1 (only imported on Python 3.10)

Install into the active environment:

```bash
python -m pip install --no-index --find-links vendor/wheels pytest pypdf tomli
```

Then, from the repository root, run the suite without installing Paperchain itself:

```bash
PYTHONPATH=src python -m pytest -q          # Windows PowerShell: $env:PYTHONPATH = "src"
```

Pytest 9 requires Python 3.10 or newer, the same floor as Paperchain.

These wheels cover the test runner and the Python dependencies. Pandoc is a separate executable and is not shipped; when it is absent, 11 tests skip and `build`/DOCX import cannot be exercised. See `docs/audits/AUDIT-INSTRUCTIONS.md` for what an offline audit can and cannot claim.
