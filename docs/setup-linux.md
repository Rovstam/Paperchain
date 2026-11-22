# Linux setup

Tested on Ubuntu 24.04. The same steps work on Debian and, with `dnf`, on Fedora.

## 1. Packages

Debian or Ubuntu:

```bash
sudo apt update
sudo apt install python3 python3-venv pipx pandoc
pipx ensurepath
```

Fedora:

```bash
sudo dnf install python3 pipx pandoc
pipx ensurepath
```

Open a new terminal, then check:

```bash
python3 --version
pandoc --version
pipx --version
```

## 2. paperchain

From a clone, until the first PyPI release:

```bash
git clone https://github.com/Rovstam/Paperchain.git paperchain
pipx install ./paperchain
paperchain doctor
```

For a fork, replace `Rovstam/Paperchain` in the clone URL with your GitHub username and repository name.

From PyPI later:

```bash
pipx install paperchain
pipx upgrade paperchain
```

## 3. First paper

```bash
paperchain init ~/papers/my-paper --title "My Paper" --agent opencode
cd ~/papers/my-paper
# put the original manuscript in Manuscript/, and reference PDFs/DOCX in References/ (subfolders allowed)
paperchain import
paperchain convert
paperchain lock
paperchain check
```

Open the folder in OpenCode. The `writer` agent is the default.

## Linux-specific notes

- **`python` versus `python3`.** On most distributions `python` does not exist. `pipx install` handles this for you; your agent only calls `paperchain`.
- **Read-only files** use `chmod 444`. If your editor refuses to save a reference, that is the lock doing its job.
- **Containers.** In a devcontainer, install pandoc in the image and run `paperchain doctor` after the container starts. Files bind-mounted from Windows inherit the host's permission model; `lock` may report a permission error there. Run the tool inside the same filesystem.
- **Line endings.** `.gitattributes` forces LF. Do not delete it if Windows users share the repository.
- **Headless servers.** `build` needs no display. `convert` needs no OCR unless the PDFs are scans, in which case install `tesseract-ocr` and `ocrmypdf`.

## Uninstall

```bash
pipx uninstall paperchain
```
