"""Shared building blocks for Claude-authored Manim scenes.

Every scene file in a work dir looks like:

    from papervid.manim_kit import *

    class Scene03(PaperScene):
        def build(self):
            ...

`PaperScene` loads this scene's entry from ../script.json (matched by the
`scene_NN.py` filename) and, after `build()`, holds the last frame until the
narration audio has finished, so animation length always covers the voice.
"""

import json
import os
import re
import sys
from pathlib import Path

from manim import *  # noqa: F401,F403  (re-exported for scene files)
from manim import (
    BOLD, DOWN, LEFT, UP, UR,
    Dot, ImageMobject, MathTex, Mobject, Scene, Text, VGroup, config,
)

config.background_color = "#0F0F14"

# 3Blue1Brown-ish palette
GOLD = "#FFB347"
BLUE_P = "#77A1D3"
GREEN_P = "#77D37A"
PINK_P = "#DD7ADB"
RED_P = "#E07A7A"
WHITE_P = "#F8F8F8"
DIM_WHITE = "#AAAAAA"

# Safe content area (frame is ~14.22 x 8 units); keep a margin on every edge
SAFE_WIDTH = config.frame_width - 1.0
SAFE_HEIGHT = config.frame_height - 1.0

FONT = "sans-serif"


# --------------------------------------------------------------------------- #
#  Layout helpers                                                              #
# --------------------------------------------------------------------------- #

def fit_to_frame(mobj: Mobject, max_width: float = SAFE_WIDTH, max_height: float = SAFE_HEIGHT) -> Mobject:
    """Scale a mobject down (never up) so it fits inside the safe area."""
    if mobj.width > max_width:
        mobj.scale_to_fit_width(max_width)
    if mobj.height > max_height:
        mobj.scale_to_fit_height(max_height)
    return mobj


def wrap_text(text: str, max_chars: int = 48) -> str:
    """Greedy word-wrap so Text() doesn't run off screen."""
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > max_chars:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return "\n".join(lines)


def heading(text: str, color: str = GOLD, font_size: int = 44) -> Text:
    """Scene heading pinned to the top edge."""
    t = Text(text, font=FONT, font_size=font_size, color=color, weight=BOLD)
    fit_to_frame(t)
    return t.to_edge(UP, buff=0.4)


def title_card(title: str, subtitle: str | None = None) -> VGroup:
    """Centered title with optional subtitle."""
    t = Text(wrap_text(title, 36), font=FONT, font_size=52, color=WHITE_P, weight=BOLD, line_spacing=0.9)
    group = VGroup(t)
    if subtitle:
        s = Text(wrap_text(subtitle, 60), font=FONT, font_size=28, color=BLUE_P)
        s.next_to(t, DOWN, buff=0.45)
        group.add(s)
    fit_to_frame(group)
    return group.center()


def caption(text: str, font_size: int = 28, color: str = DIM_WHITE, max_chars: int = 60) -> Text:
    """Wrapped caption pinned to the bottom edge."""
    c = Text(wrap_text(text, max_chars), font=FONT, font_size=font_size, color=color, line_spacing=0.8)
    fit_to_frame(c, max_height=2.0)
    return c.to_edge(DOWN, buff=0.4)


def body_text(text: str, font_size: int = 32, color: str = WHITE_P, max_chars: int = 44) -> Text:
    """Wrapped paragraph text."""
    t = Text(wrap_text(text, max_chars), font=FONT, font_size=font_size, color=color, line_spacing=0.9)
    return fit_to_frame(t)


def bullet_list(items: list[str], font_size: int = 32, color: str = WHITE_P, max_chars: int = 44) -> VGroup:
    """Left-aligned bullets with gold dots."""
    rows = VGroup()
    for item in items:
        dot = Dot(color=GOLD, radius=0.07)
        label = Text(wrap_text(item, max_chars), font=FONT, font_size=font_size, color=color, line_spacing=0.85)
        dot.next_to(label, LEFT, buff=0.3).align_to(label, UP).shift(DOWN * 0.15)
        rows.add(VGroup(dot, label))
    rows.arrange(DOWN, aligned_edge=LEFT, buff=0.35)
    return fit_to_frame(rows)


def safe_math(tex: str, fallback: str | None = None, font_size: int = 48, color: str = WHITE_P, **kwargs) -> Mobject:
    """MathTex that falls back to Text if LaTeX fails to compile.

    Always pass `fallback` as a readable Unicode rendering, e.g.
    safe_math(r"\frac{QK^T}{\sqrt{d}}", fallback="QKᵀ / √d").
    """
    try:
        m = MathTex(tex, font_size=font_size, color=color, **kwargs)
    except Exception as e:  # LaTeX errors surface as ValueError / OSError
        print(f"[manim_kit] MathTex failed ({str(e)[:120]}); falling back to Text", file=sys.stderr)
        m = Text(fallback or tex, font="serif", slant="ITALIC", font_size=int(font_size * 0.8), color=color)
    return fit_to_frame(m)


def paper_figure(path: str | Path, width: float | None = None, height: float | None = None) -> ImageMobject:
    """Load a cropped paper figure, sized to fit (defaults to 60% of the safe area)."""
    img = ImageMobject(str(path))
    if width:
        img.scale_to_fit_width(width)
    if height:
        img.scale_to_fit_height(height)
    if not width and not height:
        img.scale_to_fit_width(SAFE_WIDTH * 0.6)
        if img.height > SAFE_HEIGHT * 0.75:
            img.scale_to_fit_height(SAFE_HEIGHT * 0.75)
    return img


def corner_label(text: str) -> Text:
    """Small label in the upper-right corner (e.g. 'Fig. 3')."""
    return Text(text, font=FONT, font_size=20, color=DIM_WHITE).to_corner(UR, buff=0.3)


# --------------------------------------------------------------------------- #
#  PaperScene                                                                  #
# --------------------------------------------------------------------------- #

class PaperScene(Scene):
    """Base class: loads the scene spec and pads to the narration length."""

    tail_seconds = 0.5

    def setup(self):
        self.scene_file = self._scene_file()
        self.work_dir = self.scene_file.parent.parent
        self.spec = self._load_spec()

    def construct(self):
        self.build()
        self.hold_until(self.target_duration)

    def build(self):
        raise NotImplementedError("Implement build() in your scene")

    # -- timing ---------------------------------------------------------- #

    @property
    def target_duration(self) -> float:
        audio = float(self.spec.get("audio_duration") or 0.0)
        planned = float(self.spec.get("duration_seconds") or 0.0)
        return (audio + self.tail_seconds) if audio > 0 else planned

    @property
    def elapsed(self) -> float:
        return self.renderer.time

    @property
    def remaining(self) -> float:
        return max(0.0, self.target_duration - self.elapsed)

    def hold_until(self, t: float) -> None:
        """Wait until the scene clock reaches t seconds (no-op if already past)."""
        gap = t - self.elapsed
        if gap > 0.05:
            self.wait(gap)

    # -- assets ---------------------------------------------------------- #

    def figure(self, name: str) -> Path:
        """Path to a cropped figure in <work_dir>/figures/."""
        for ext in (".png", ".jpg"):
            p = self.work_dir / "figures" / f"{name}{ext}"
            if p.exists():
                return p
        raise FileNotFoundError(f"figure '{name}' not found in {self.work_dir / 'figures'}")

    def page(self, number: int) -> Path:
        """Path to a full rendered PDF page."""
        return self.work_dir / "pages" / f"page_{number:03d}.png"

    # -- internals ------------------------------------------------------- #

    def _scene_file(self) -> Path:
        env = os.environ.get("PAPERVID_SCENE_FILE")
        if env:
            return Path(env).resolve()
        module = sys.modules.get(type(self).__module__)
        return Path(getattr(module, "__file__", "scene_00.py")).resolve()

    def _load_spec(self) -> dict:
        match = re.search(r"scene_(\d+)", self.scene_file.stem)
        script_path = self.work_dir / "script.json"
        if not match or not script_path.exists():
            return {}
        scene_id = int(match.group(1))
        data = json.loads(script_path.read_text())
        for s in data.get("scenes", []):
            if int(s.get("scene_id", -1)) == scene_id:
                return s
        return {}
