# papervid

papervid turns a research paper (a PDF) into a short narrated video, in the style of 3Blue1Brown. It reads the paper, writes a script, records the voice, animates each scene with Manim, and joins everything into one `final.mp4`.

You can run it in two ways:

- **With Claude Code (the main way).** You type `/papervid paper.pdf` and Claude does the whole job. It reads the PDF, writes the script, builds every scene, checks how each one looks, and puts the video together. No other AI model is needed.
- **With llama.cpp (the other way).** `python main.py` starts a step-by-step menu that uses a local model running on llama.cpp. See [docs/llama-pipeline.md](docs/llama-pipeline.md).

## Quick start

1. Install the system tools (ffmpeg, poppler, a TeX setup) and the Python packages. The full steps are in [docs/setup.md](docs/setup.md).
2. Tell papervid which Python to use (see the next section).
3. Check that everything is in place:

   ```sh
   bin/py -m papervid.tools doctor
   ```

   You want `"ok": true` and an empty `missing` list.
4. Open Claude Code in this folder and run:

   ```
   /papervid papers/my_paper.pdf
   ```

   Add `--auto` if you don't want to approve the outline first.

The video ends up in `papervid_output/<paper-name>/final.mp4`.

## Which Python does it use?

papervid needs a Python that has manim, edge-tts and pdf2image installed. Most people keep these in a virtual env, and that env lives in a different place on every machine. So the project never hard-codes the path. Every command goes through a small script, `bin/py`, and that script finds the right Python by itself.

`bin/py` checks these places, in this order, and uses the first one that exists:

1. The `PAPERVID_PYTHON` environment variable.
2. A `.venv` folder inside the project (`.venv/bin/python`).
3. A virtual env you have already activated (`$VIRTUAL_ENV`).
4. Plain `python3` on your PATH.

It also adds the project folder to `PYTHONPATH`, so `bin/py -m papervid.tools ...` works from any folder.

### Setting it up for Claude Code

The shared file `.claude/settings.json` only uses the relative path `bin/py`, so it works for everyone. Your own path goes in `.claude/settings.local.json`. Git ignores that file, so it stays on your machine.

Copy the example and put in your path:

```sh
cp .claude/settings.local.json.example .claude/settings.local.json
```

```json
{
  "env": {
    "PAPERVID_PYTHON": "/home/you/pythonenv/bin/python"
  }
}
```

Restart Claude Code after you change it, so it picks up the new value.

If you'd rather not set anything, create the env inside the project as `.venv` and `bin/py` will find it on its own:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Docs

| Page | What's in it |
| --- | --- |
| [docs/setup.md](docs/setup.md) | Installing everything and choosing the Python |
| [docs/making-a-video.md](docs/making-a-video.md) | Making a video with `/papervid`, step by step |
| [docs/script-json.md](docs/script-json.md) | The `script.json` file: every field explained |
| [docs/writing-scenes.md](docs/writing-scenes.md) | How a scene file is written, and the `manim_kit` helpers |
| [docs/tools.md](docs/tools.md) | Every `papervid.tools` command and its options |
| [docs/llama-pipeline.md](docs/llama-pipeline.md) | The other way: `main.py` with llama.cpp |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common errors and how to fix them |

## Project layout

```
bin/py                     picks the right Python and runs it
main.py                    starts the llama.cpp menu
papervid/tools.py          the command line tools that Claude uses
papervid/manim_kit.py      PaperScene base class, colours and layout helpers
papervid/renderer/         manim and ffmpeg helpers
papervid/parsers/          PDF reading and the script.json data classes
papervid/voice/tts.py      text to speech with edge-tts
.claude/skills/papervid/   the /papervid command
.claude/agents/            the manim-scene helper that builds one scene
papervid_output/           one folder per video
```
