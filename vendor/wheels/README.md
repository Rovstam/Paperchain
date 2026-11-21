# Offline wheels

Universal (`py3-none-any`) wheels so the package and its tests can be installed without network access. Verified on 2026-11-16 with:

- build backend: hatchling 1.33.0 with pathspec 1.1.1, trove-classifiers 2026.9.21.13, tomlkit 0.15.2, packaging 26.3, pluggy 1.7.0
- runtime: pypdf 7.0.1; tomli 2.0.1 only on Python 3.10
- tests: pytest 9.2.0, iniconfig 2.3.1, Pygments 2.21.0, colorama 0.4.6

## Install Paperchain

From the repository root, point pip at the wheels for both the package and its build isolation:

```bash
PIP_NO_INDEX=1 PIP_FIND_LINKS="$PWD/vendor/wheels" python -m pip install .
```

PowerShell:

```powershell
$env:PIP_NO_INDEX = "1"
$env:PIP_FIND_LINKS = "$PWD\vendor\wheels"
python -m pip install .
```

`--no-index --find-links` alone is not enough: pip builds in an isolated environment that ignores those flags for the build requirements. The environment variables apply to that subprocess too.

## Run the tests

```bash
python -m pip install --no-index --find-links vendor/wheels pytest pypdf tomli
python -m pytest -q
```

`pypdf` is a runtime dependency; without it the PDF tests fail with `missing_dependency`. `tomli` is imported only on Python 3.10.

Without installing anything, the suite can also be run from the source tree:

```bash
PYTHONPATH=src python -m pytest -q          # PowerShell: $env:PYTHONPATH = "src"
```

Pytest 9 requires Python 3.10 or newer, the same floor as Paperchain.

Pandoc is a separate executable and is not shipped. When it is absent, 13 tests skip and `build`/DOCX import cannot be exercised. See `docs/audits/AUDIT-INSTRUCTIONS.md` for what an offline run can and cannot claim.
