# papervid

Turns a research paper PDF into a narrated, 3Blue1Brown-style Manim video.

## Two pipelines
- **Claude Code (primary)**: run `/papervid <paper.pdf>`.
  - `.claude/skills/papervid/SKILL.md` directs the run: Claude reads the PDF, writes `script.json`, and gets the outline approved.
  - `.claude/agents/manim-scene.md` writes, renders, and visually checks each scene.
  - No external LLM is used.
- **llama.cpp (alternate)**: `python main.py [pdf]` is an interactive CLI.
  - Code: `papervid/cli.py`, `generators/`, `builder/` (template scene code), and `renderer/video_render.py` (LLM frame verification).

## Environment
- Always run Python through `bin/py`, never a hard-coded interpreter path. It picks `$PAPERVID_PYTHON`, then `.venv/bin/python`, then an active venv, then `python3`, and it puts the project root on `PYTHONPATH`. The system python has no manim.
- Each machine sets its own interpreter in `.claude/settings.local.json` (git-ignored, see `.claude/settings.local.json.example`) as `env.PAPERVID_PYTHON`. Don't put absolute paths in `.claude/settings.json`.
- Run tools from the project root: `bin/py -m papervid.tools <cmd>`. Every command prints JSON with an `ok` field.
- User docs live in `README.md` and `docs/`. Keep them in plain, simple English with no em-dashes, and update them when commands or setup change.
- Check the environment with `... -m papervid.tools doctor`. If `mathtex` is false, the TeX install lacks `standalone`/`preview` (`texlive-latexextra`), and `safe_math` falls back to Unicode text.

## Layout
- `papervid/tools.py`: non-interactive CLI with `init`, `status`, `validate`, `crop`, `voices`, `tts`, `render`, `frames`, `assemble`.
- `papervid/manim_kit.py`: the `PaperScene` base class (loads its spec from script.json and pads to narration length), palette, and layout helpers. Every Claude-written scene imports it.
- `papervid/renderer/ffmpeg_ops.py`: manim/ffmpeg helpers shared by both pipelines.
- `papervid/parsers/models.py`: `Scene` / `ScriptOutput` dataclasses, including the script.json (de)serialization.

## Work dir: `papervid_output/<slug>/`
```
meta.json  script.json  final.mp4
pages/page_NNN.png     figures/<name>.png
audio/scene_NN.mp3     scenes/scene_NN.py  (class SceneNN(PaperScene))
renders/{l,m,h}/...    renders/clips/      frames/scene_NN/{frame_*.jpg,review.json}
```
Order of steps: init → script.json → validate/crop → **tts (before coding scenes)** → per-scene render/review → render -q h → assemble.
