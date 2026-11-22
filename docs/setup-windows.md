# Windows setup

Tested on Windows 11 with PowerShell 7.

## 1. Python

```powershell
winget install --id Python.Python.3.12 -e
```

Close and reopen the terminal, then check:

```powershell
py --version
```

Use `py` everywhere. `python` often is not on PATH on Windows, and the Microsoft Store alias can open the store instead.

## 2. pipx

`pipx` installs command-line tools in their own environments, so `paperchain` cannot break another project's dependencies.

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

Open a new terminal so the PATH change applies.

## 3. Pandoc

```powershell
winget install --id JohnMacFarlane.Pandoc -e
```

Check it:

```powershell
pandoc --version
```

Pandoc is only needed for `paperchain build`. `convert`, `check`, `lock` and `doctor` work without it.

## 4. paperchain

From a clone, until the first PyPI release:

```powershell
git clone https://github.com/Rovstam/Paperchain.git paperchain
pipx install ./paperchain
paperchain doctor
```

For a fork, replace `Rovstam/Paperchain` in the clone URL with your GitHub username and repository name.

From PyPI later:

```powershell
pipx install paperchain
pipx upgrade paperchain
```

## 5. First paper

```powershell
paperchain init C:\Users\you\papers\my-paper --title "My Paper" --agent opencode
cd C:\Users\you\papers\my-paper
# put the original manuscript in Manuscript\, and reference PDFs/DOCX in References\ (subfolders allowed)
paperchain import
paperchain convert
paperchain lock
paperchain check
```

Open the folder in OpenCode. The `writer` agent is the default.

## Windows-specific notes

- **Read-only means the file attribute.** `paperchain lock` uses `os.chmod`, so Explorer shows the Read-only checkbox. `paperchain unlock` clears it.
- **Line endings.** The project ships a `.gitattributes` with `* text=auto eol=lf`. Without it, git may rewrite text on checkout, change the hash of a reference, and make `check` fail. Do not delete that file.
- **Long paths.** Deep folders plus long reference file names can hit the 260-character limit. Keep paper folders short, for example `C:\papers\`.
- **Antivirus and OneDrive.** A syncing folder can lock files while pandoc reads them. If `build` fails with a permission error, pause sync or move the project out of OneDrive.
- **WSL.** If you run OpenCode inside WSL, install `paperchain` inside WSL as well. A Windows `paperchain.exe` on PATH is not the same environment, and the permission rules assume one shell.
- **No Word needed.** Pandoc writes the `.docx`; Word or LibreOffice is only for opening the result.

## Uninstall

```powershell
pipx uninstall paperchain
```
