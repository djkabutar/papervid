# Setup

This page shows how to install what papervid needs, and how to tell it which Python to use.

## 1. System tools

papervid calls a few programs that don't come from pip:

- **ffmpeg** and **ffprobe**: cut, join and measure the video and audio.
- **poppler**: turns PDF pages into images (pdf2image uses it).
- **TeX** with `standalone` and `preview`: Manim uses it to draw equations. You can skip it, but equations will show as plain text.
- **espeak-ng**: not needed. edge-tts does the voice.

On Arch Linux:

```sh
sudo pacman -S ffmpeg poppler texlive-basic texlive-latexextra
```

On Debian or Ubuntu:

```sh
sudo apt install ffmpeg poppler-utils texlive texlive-latex-extra
```

Manim also needs Cairo and Pango. Most desktop systems already have them. If `pip install manim` fails, check the Manim install guide for your system.

## 2. Python packages

You need Python 3.11 or newer. Make a virtual env and install the packages into it. You can put the env anywhere you like.

Inside the project (the easiest choice, because `bin/py` finds it with no extra setup):

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Or somewhere else:

```sh
python -m venv ~/pythonenv
~/pythonenv/bin/pip install -r requirements.txt
```

## 3. Tell papervid which Python to use

Every command in this project runs through `bin/py`. It's a short shell script that finds your Python and runs it, so nothing in the repo needs your real path.

It looks in this order and stops at the first hit:

| Order | Where it looks | When to use it |
| --- | --- | --- |
| 1 | `$PAPERVID_PYTHON` | Your env is outside the project |
| 2 | `.venv/bin/python` in the project | You made the env as `.venv` |
| 3 | `$VIRTUAL_ENV/bin/python` | You ran `source .../bin/activate` first |
| 4 | `python3` on your PATH | Everything is installed globally |

If you made `.venv` inside the project, you are done. Skip to step 4.

If your env is somewhere else, set `PAPERVID_PYTHON`.

**For Claude Code**, put it in `.claude/settings.local.json`. Git ignores this file, so your path never ends up in a commit:

```sh
cp .claude/settings.local.json.example .claude/settings.local.json
```

Then edit it:

```json
{
  "env": {
    "PAPERVID_PYTHON": "/home/you/pythonenv/bin/python"
  }
}
```

Claude Code reads this file when it starts, so restart it after you edit.

**For your own terminal**, add this to your shell config (`~/.zshrc` or `~/.bashrc`):

```sh
export PAPERVID_PYTHON=/home/you/pythonenv/bin/python
```

### Why not just write the path in settings.json?

`.claude/settings.json` is shared with everyone who clones the repo. A path like `/home/dj/pythonenv/bin/python` only works on one machine. So the shared file only allows `bin/py ...`, and each person keeps their own path in the local file.

## 4. Check it

```sh
bin/py -m papervid.tools doctor
```

You should see something like:

```json
{
  "ok": true,
  "checks": {
    "python": "/home/you/pythonenv/bin/python",
    "manim": "Manim Community v0.20.1",
    "mathtex": true,
    ...
  },
  "missing": []
}
```

- `python` tells you which Python `bin/py` picked. If it's the wrong one, fix `PAPERVID_PYTHON`.
- If `missing` has anything in it, install that and run `doctor` again.
- If `mathtex` is `false`, TeX is missing `standalone` or `preview`. Install `texlive-latexextra` (Arch) or `texlive-latex-extra` (Debian). Videos still work, but equations show as plain text.

## 5. Voice check (optional)

```sh
bin/py -m papervid.tools voices
```

This lists the English edge-tts voices. If it fails with a `403` error, your edge-tts is too old. See [troubleshooting.md](troubleshooting.md#tts-fails-with-403).
