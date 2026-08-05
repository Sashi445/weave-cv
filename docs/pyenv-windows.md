# Installing pyenv on Windows

`weave-cv` needs Python 3.12+. Check yours with `python --version` —
if it's older, install one with
[pyenv-win](https://github.com/pyenv-win/pyenv-win) without touching
your system Python. All commands below are run in **PowerShell**.

## 1. Install pyenv-win

```
> choco install pyenv-win
```

No Chocolatey? Scoop works too:

```
> scoop bucket add versions
> scoop install pyenv-win
```

Or skip package managers entirely:

```
> Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/pyenv-win/pyenv-win/master/pyenv-win/install-pyenv-win.ps1" -OutFile "./install-pyenv-win.ps1"; &"./install-pyenv-win.ps1"
```

## 2. Restart your terminal

The installer sets `PYENV`, `PYENV_ROOT`, and `PATH` for you — close
and reopen PowerShell, then confirm:

```
> pyenv --version
pyenv 3.1.x
```

Still not found? Log out and back in, or check that
`%USERPROFILE%\.pyenv\pyenv-win\bin` and
`%USERPROFILE%\.pyenv\pyenv-win\shims` are on your `PATH`.

> **Execution-policy error?** Run PowerShell as Administrator once:
> `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`.

## 3. Install Python 3.12+

From your project folder:

```
> pyenv install 3.12.8
> pyenv local 3.12.8
> python --version
Python 3.12.8
```

`pyenv local` scopes 3.12.8 to this folder only (writes a
`.python-version` file here) — it won't change your system-wide
Python. Avoid `pyenv global` unless you actually want 3.12.8
everywhere.

Next: back to the [README](../README.md#installation) to create a
virtual environment and install `weave-cv`.
