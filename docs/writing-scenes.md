# Writing scenes

Each scene is one Python file: `scenes/scene_NN.py`. Claude's `manim-scene` helper writes these for you. This page is for when you want to read one, fix one, or write one yourself.

## The basic shape

```python
from papervid.manim_kit import *

class Scene03(PaperScene):
    def build(self):
        title = heading("Where the energy goes")
        self.play(Write(title))

        bar = Rectangle(width=6, height=0.6, color=RED_P)
        self.play(GrowFromEdge(bar, LEFT))
        self.hold_until(8.0)   # wait until 8 seconds into the narration

        self.play(FadeOut(title, bar))
```

A few rules:

- The class name must be `SceneNN` with two digits, and it must extend `PaperScene`.
- Put your animation in `build()`, not `construct()`. `PaperScene` has its own `construct()`. It calls your `build()` and then waits until the scene is as long as the audio.

## What PaperScene gives you

`PaperScene` reads this scene's entry from `script.json` for you.

- `self.spec`: this scene's data from `script.json`.
- `self.target_duration`: how long the scene should be. It's the narration length plus half a second.
- `self.elapsed`: how many seconds have played so far.
- `self.remaining`: how many seconds are left.
- `self.hold_until(t)`: wait until `t` seconds. Use it to line up a visual with a word in the narration.
- `self.figure("name")`: the path to `figures/name.png`.
- `self.page(n)`: the path to the full image of page `n`.

If your animation ends early, `PaperScene` pads the end so the scene still matches the audio. If the audio runs longer than the video, `assemble` holds the last frame until the voice is done.

## Helpers in manim_kit

`papervid.manim_kit` brings in everything from `manim`, plus these.

**Colours:** `GOLD`, `BLUE_P`, `GREEN_P`, `PINK_P`, `RED_P`, `WHITE_P`, `DIM_WHITE`. The background is near black.

**Text and layout:**

- `heading(text)`: a title at the top of the frame.
- `title_card(title, subtitle)`: a big centred title.
- `caption(text)`: small wrapped text at the bottom.
- `body_text(text)`: normal wrapped text.
- `bullet_list(items)`: a list with bullets.
- `corner_label(text)`: a small label in the corner.
- `fit_to_frame(mobj)`: shrinks something so it fits on screen.
- `wrap_text(s, n)`: breaks a string into lines of about `n` characters.
- `SAFE_WIDTH`, `SAFE_HEIGHT`: the safe area. Keep things inside x from -6.6 to 6.6 and y from -3.5 to 3.5.

**Maths:** `safe_math(tex, fallback="...")`. It draws the LaTeX if TeX works, and shows the `fallback` text if it doesn't. Always give a fallback.

**Figures:** `paper_figure(path, width=None, height=None)` loads a PNG as an image. Patent drawings and other white-background images look better on a white rounded card.

## Render and look at it

```sh
bin/py -m papervid.tools render papervid_output/<name> --scene 3 --quality l
bin/py -m papervid.tools frames papervid_output/<name> --scene 3 --count 6
```

`frames` saves six evenly spaced JPGs in `frames/scene_03/`. Open them and check:

- Nothing overlaps or runs off the edge.
- Text is big enough to read (24pt or more).
- The screen isn't empty for long.
- What's on screen matches what the voice is saying at that moment.

The helper writes what it found to `frames/scene_NN/review.json` with a `pass` or `fail` status.
