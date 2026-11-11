# macOS setup

Tested on macOS 14 (Apple Silicon) and 15 (Intel).

## 1. Homebrew

If `brew` is missing, install it from <https://brew.sh> and follow the printed instructions.

## 2. The toolchain

```bash
brew install python@3.12 pandoc pipx
pipx ensurepath
```

Open a new terminal, then check:

```bash
python3 --version
pandoc --version
pipx --version
```

## 3. paperchain

From a clone, until the first PyPI release:

```bash
git clone <this-repo> paperchain
pipx install ./paperchain
paperchain doctor
```

From PyPI later:

```bash
pipx install paperchain
pipx upgrade paperchain
```

## 4. First paper

```bash
paperchain init ~/papers/my-paper --title "My Paper" --agent opencode
cd ~/papers/my-paper
# copy PDFs or Word files into References/originals/
paperchain convert
paperchain lock
paperchain check
```

Open the folder in OpenCode. The `writer` agent is the default.

## macOS-specific notes

- **Python from Xcode** is old and may shadow Homebrew. `paperchain doctor` prints the interpreter it is actually using; if it shows `/usr/bin/python3`, reinstall with pipx after `brew install python@3.12`.
- **Line endings.** The project `.gitattributes` forces LF, which is native here. Do not delete it; collaborators on Windows depend on it.
- **Read-only files** are normal Unix permissions (`chmod 444`). Finder shows them as locked.
- **Pandoc is only needed for `build`.** `convert`, `check` and `lock` work without it.
- **No TeX.** The project produces `.docx`, not PDF through LaTeX. Do not install MacTeX unless you want it for something else.

## Uninstall

```bash
pipx uninstall paperchain
```
