# script.json

`script.json` is the plan for the whole video. Claude writes it, but you can open it and change it yourself. It lives in the video's output folder.

## Example

```json
{
  "title": "Short video title",
  "author_line": "First Author et al. · Venue 2024",
  "scenes": [
    {
      "scene_id": 1,
      "title": "Hook: why this problem matters",
      "visual_type": "intro_title",
      "narration": "The exact words the voice will say.",
      "visual_plan": "What shows up on screen, in what order, and when.",
      "figures": [
        {"page": 4, "box": [0.08, 0.10, 0.92, 0.42], "name": "fig3_pipeline"}
      ],
      "duration_seconds": 20
    }
  ]
}
```

## Top level

| Field | What it is |
| --- | --- |
| `title` | The video's title. Shown at the start. |
| `author_line` | Who wrote the paper and where it was published. |
| `scenes` | The list of scenes, in order. |

## Each scene

| Field | What it is |
| --- | --- |
| `scene_id` | 1, 2, 3 and so on, with no gaps. |
| `title` | A short name for the scene. |
| `visual_type` | What kind of scene it is (see below). |
| `narration` | Only the spoken words. No stage directions, no "Figure 3 shows". |
| `visual_plan` | A clear description of the animation. Say what appears, how it moves, and which words it lines up with. |
| `figures` | Figures to cut out of the paper. Can be empty. |
| `duration_seconds` | A rough guess. The real length comes from the audio. |
| `audio_duration` | Added by `tts`. Don't edit it. |

### visual_type

Pick one of these:

- `intro_title`: the opening hook and title
- `concept_visual`: shapes and diagrams that explain an idea
- `formula_animation`: an equation built up or changed step by step
- `diagram_zoom`: a figure from the paper with zooms and highlights
- `chart_build`: a chart that grows from the paper's real numbers
- `slide_transition`: a short bridge between parts
- `conclusion`: the takeaway at the end

### figures

Each figure has:

- `page`: the page number in the PDF, starting from 1.
- `box`: where the figure is on that page, as `[x0, y0, x1, y1]`. These are fractions of the page from 0 to 1. `0, 0` is the top left corner.
- `name`: a unique name in `snake_case`. The cut image is saved as `figures/<name>.png`.

After you change a box, run `crop` again and look at the image to check it.

## Rules that make a good script

- Scene 1 is a hook plus the title. The last scene is the takeaway.
- One idea per scene.
- 30 to 130 words of narration per scene. At normal speed that's about 12 to 50 seconds.
- Write the way people talk. Explain a word before you use it.
- Write numbers the way they are spoken, like "two point six times", so the voice reads them well.
- Prefer real animation over slides. Draw the diagram, grow the chart, change the equation term by term. Use a cropped figure only when redrawing it would lose detail.

## Check it

```sh
bin/py -m papervid.tools validate papervid_output/<name>
```

This lists errors (you must fix these) and warnings (worth a look). It also prints an outline with the word count and estimated length of each scene.
