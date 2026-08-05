# Installing pyenv on Linux

`weave-cv` needs Python 3.12+. Check yours with `python3 --version` —
if it's older, install one with [pyenv](https://github.com/pyenv/pyenv)
without touching your system Python.

## 1. Build dependencies

pyenv builds Python from source, so install a compiler and headers
first.

**Debian / Ubuntu:**

```
$ sudo apt update
$ sudo apt install -y build-essential libssl-dev zlib1g-dev libbz2-dev \
    libreadline-dev libsqlite3-dev curl git libncursesw5-dev xz-utils \
    tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

**Fedora / RHEL / CentOS:**

```
$ sudo dnf install -y make gcc zlib-devel bzip2 bzip2-devel readline-devel \
    sqlite sqlite-devel openssl-devel tk-devel libffi-devel xz-devel
```

**Arch:**

```
$ sudo pacman -S --needed base-devel openssl zlib xz tk
```

## 2. Install pyenv

```
$ curl https://pyenv.run | bash
```

## 3. Hook it into your shell

Add this to `~/.bashrc` (or `~/.zshrc` for zsh), then restart your
terminal:

```
export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
```

Confirm it's picked up:

```
$ exec "$SHELL"
$ pyenv --version
pyenv 2.4.x
```

## 4. Install Python 3.12+

From your project folder:

```
$ pyenv install 3.12.8
$ pyenv local 3.12.8
$ python3 --version
Python 3.12.8
```

`pyenv local` scopes 3.12.8 to this folder only (writes a
`.python-version` file here) — it won't change your system-wide
Python. Avoid `pyenv global` unless you actually want 3.12.8
everywhere.

Next: back to the [README](../README.md#installation) to create a
virtual environment and install `weave-cv`.
