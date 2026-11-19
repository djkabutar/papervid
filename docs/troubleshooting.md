# Troubleshooting

## bin/py: can't find a Python to run

`bin/py` couldn't find any of the Pythons it looks for. Either:

- set `PAPERVID_PYTHON` to the full path of your env's Python (see [setup.md](setup.md#3-tell-papervid-which-python-to-use)), or
- make a `.venv` folder inside the project.

If you set it in `.claude/settings.local.json`, restart Claude Code. It only reads that file when it starts.

## doctor shows the wrong Python, or "No module named manim"

`bin/py` found a Python, but not the one with manim in it. Run `bin/py -m papervid.tools doctor` and look at `checks.python`. If it says `/usr/bin/python3` or similar, `PAPERVID_PYTHON` isn't set where you think it is. Check:

```sh
echo $PAPERVID_PYTHON
```

In Claude Code, the value comes from `.claude/settings.local.json`. In your terminal, it comes from your shell config.

## Claude keeps asking for permission to run commands

The shared settings only allow commands that start with `bin/py -m papervid.tools` or `./bin/py -m papervid.tools`. If Claude runs Python some other way (for example with a full path), you'll get asked. That usually means an old copy of the skill or agent is in use. Check that `.claude/skills/papervid/SKILL.md` and `.claude/agents/manim-scene.md` say `PY=bin/py`.

## TTS fails with 403

You see something like `403, message='Invalid response status'` and every scene ends up with no audio.

Microsoft changes the token that edge-tts sends from time to time, and old versions of edge-tts stop working. Update it:

```sh
bin/py -m pip install --upgrade edge-tts
```

Then run `tts` again.

## Equations show as plain text

`doctor` says `"mathtex": false`. Your TeX install is missing the `standalone` or `preview` package. Install `texlive-latexextra` (Arch) or `texlive-latex-extra` (Debian and Ubuntu). Until then, `safe_math` shows the fallback text instead.

## init only made 40 pages

That's the default limit. Run it again with a bigger number and `--force`:

```sh
bin/py -m papervid.tools init paper.pdf --max-pages 80 --force
```

## A scene renders at low quality but fails at high quality

This is rare. Run the high quality render for just that scene and read `stderr_tail` in the output:

```sh
bin/py -m papervid.tools render papervid_output/<name> --scene 5 --quality h
```

It's often a timeout on a very long scene. Raise it with `--timeout 1800`.

## assemble says a render is missing

One of the scenes doesn't have a render at the quality you asked for. Run `status` to see which one, then render it. Or use `--allow-lower` to fill the gap with a lower quality clip.

## The video and voice don't line up

Every scene is timed to its audio file. If you changed a narration but didn't run `tts` again, the timing is off. Run `tts` (it only redoes changed scenes), then render and assemble again.
