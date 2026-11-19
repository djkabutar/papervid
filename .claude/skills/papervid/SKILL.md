---
name: papervid
description: Turn a research paper PDF into a narrated 3Blue1Brown-style Manim explainer video, using Claude Code itself (no external LLM). Use when the user runs /papervid or asks to make a video/animation from a paper.
argument-hint: <paper.pdf> [--voice en-US-AndrewNeural] [--scenes N] [--auto] [--quality h|m]
---

# papervid: paper → animated video

Arguments: `$ARGUMENTS`

You are the director. You read the paper, write the script, send each scene to the
`manim-scene` subagent, and assemble the result. Deterministic work (page rendering, TTS,
manim, ffmpeg) goes through the tool CLI. Every tool prints JSON with an `"ok"` field.

```
PY=bin/py        # wrapper that finds the right Python (see docs/setup.md); run from the project root
$PY -m papervid.tools <cmd> ...
```

Parse the arguments. The PDF path is required; ask for it if missing. Defaults:
- `--voice en-US-AndrewNeural` (`$PY -m papervid.tools voices` lists the options)
- `--scenes` chosen by you, 6–12
- `--quality h` (final render; use `m` for a faster draft)
- `--auto` off

## 0. Preflight and resume

1. `$PY -m papervid.tools doctor`
   - Stop and report anything in `missing`.
   - If `checks.mathtex` is false, remember it: equations will render as plain Text, so every `safe_math` call needs a good Unicode `fallback=`. Mention once to the user that `texlive-latexextra` fixes this.
2. `$PY -m papervid.tools init <pdf>` → returns `work_dir` (referred to as `$W` below).
   - It is idempotent and reuses pages that are already rendered.
3. If `$W/script.json` already exists, run `$PY -m papervid.tools status $W` and resume from the first incomplete step. Don't redo finished work unless the user asks.
   - If `status` shows an unchanged script, `tts` is cached.
   - Scenes with `render_l` true and a `review` status of `pass` are done.

## 1. Understand the paper

- Read the PDF itself with the Read tool, 20 pages per call using `pages: "1-20"`, `"21-40"`, and so on. Skip references and appendices unless they hold key results.
- Identify:
  - the problem and why it matters
  - the core idea and its intuition
  - the key equations, at most 3–4, written in LaTeX
  - the method pipeline
  - the headline results with real numbers
  - limitations and takeaways
- Note which figures and tables are worth showing, and the page each is on.
- For each one, Read `$W/pages/page_NNN.png` to estimate its bounding box as page fractions `[x0, y0, x1, y1]` (0–1, origin top-left).

## 2. Write `$W/script.json`

```json
{
  "title": "Short video title",
  "author_line": "First Author et al. · Venue Year",
  "scenes": [
    {
      "scene_id": 1,
      "title": "Hook: why quantization breaks",
      "visual_type": "intro_title",
      "narration": "Spoken words only, no stage directions…",
      "visual_plan": "Concrete, animatable description: what appears, in what order, how it moves, what's highlighted, which equation/figure. Tie beats to narration phrases.",
      "figures": [{"page": 4, "box": [0.08, 0.10, 0.92, 0.42], "name": "fig3_pipeline"}],
      "duration_seconds": 20
    }
  ]
}
```

Script rules:
- Scene 1 is a hook plus the title. The last scene is the takeaway or conclusion. `scene_id` runs 1..N in order.
- One idea per scene, with 30–130 words of narration (about 12–50s at 150 wpm). The whole video is about 3–7 minutes unless the user asks otherwise.
- Narration is conversational and intuition-first, with no citations or "Figure 3 shows…". Build every concept before using it. Write numbers the way they are spoken.
- `visual_type` is one of: `intro_title`, `concept_visual`, `formula_animation`, `diagram_zoom`, `chart_build`, `slide_transition`, `conclusion`.
- Favour real animation over slides. That means building diagrams from shapes, transforming equations term by term, and growing bar charts from the paper's actual numbers. Use cropped paper figures when redrawing them would lose information.
- Figure `name` values are unique `snake_case`.

Then:
1. `$PY -m papervid.tools validate $W`. Fix any `errors` and consider the `warnings`.
2. If any scene has figures, run `$PY -m papervid.tools crop $W`, then Read every cropped PNG in `$W/figures/`.
   - Adjust the boxes and re-crop until each image is tight: nothing cut off, and no surrounding body text.

## 3. Outline approval (skip if `--auto`)

Show the `validate` outline as a compact table: #, title, type, seconds, figures. Include a one-line gist of each narration and the estimated total length.

Then use AskUserQuestion with these options:
- **Approve**
- **Revise**, with notes collected through "Other"
- **Shorter**
- **More depth**

Apply the requested changes, re-validate, and ask again. Only continue once the user approves.

## 4. Narration audio

`$PY -m papervid.tools tts $W --voice <voice>`

This writes `audio_duration` into script.json. Every scene is timed to it, so TTS must run **before** any scene is coded. If you later edit a narration, re-run `tts`; unchanged scenes stay cached.

## 5. Build scenes with subagents

Spawn one `manim-scene` subagent per scene. Batches of **3 in parallel** keep CPU contention reasonable, since manim is heavy. Prompt each with:

```
Work dir: <$W>
Scene: <id>
MathTex available: <true|false>
Python: bin/py
Neighbouring scenes (for visual continuity): <prev title>, <next title>
```

Each subagent writes `$W/scenes/scene_NN.py`, renders it at low quality, reviews the frames, and saves `$W/frames/scene_NN/review.json`. It returns a status of `pass` or `fail` with notes.

- If a scene comes back `fail`, look at its notes and frames. Either re-dispatch it once with specific guidance, or simplify its `visual_plan` in script.json and re-dispatch.
- Don't hand-edit scenes yourself unless the fix is trivial.
- After all batches, run `$PY -m papervid.tools status $W` and confirm every scene has `code`, `render_l`, and a review.

## 6. Final render and assembly

1. `$PY -m papervid.tools render $W --quality <h|m>`, using a Bash timeout of 600000 ms. For many scenes, render in chunks such as `--scene 1-4`.
   - If a scene fails only at high quality (rare), read `stderr_tail`, fix it, and re-render that scene.
2. `$PY -m papervid.tools assemble $W --quality <h|m>`
   - This adds the audio to each scene, holds the last frame if the narration runs long, and concatenates everything into `$W/final.mp4`.
3. Spot-check: `$PY -m papervid.tools frames $W --scene <k> --quality <q> --count 2` for two or three scenes, and Read the frames.

## 7. Report

Tell the user:
- the path to `final.mp4`, its duration, and its size
- the scene count and voice used
- any scene that shipped with known issues
- how to iterate: edit `script.json` or a `scenes/scene_NN.py` file, then run `/papervid <pdf>` again. It resumes, so only the changed scenes need rework.

## Rules

- Never call external LLM APIs. The llama.cpp pipeline in `papervid/cli.py` is a separate, alternate backend; don't use it here.
- Keep everything inside `$W`. Don't write into `papervid/` unless you're improving `manim_kit.py` itself.
- If a tool returns `"ok": false`, read its `error` or `stderr_tail` before retrying. Don't loop on the same failure more than twice; report it instead.
