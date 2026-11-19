"""Scene builder — converts structured script into Manim Python code."""

import logging
import re
from pathlib import Path

from ..parsers.models import ScriptOutput, Scene
from .templates import (
    get_imports,
    get_scene_header,
    get_intro_scene,
    get_section_header,
    get_file_footer,
)

logger = logging.getLogger(__name__)

I1 = "    "   # 4-space indent (class level)
I2 = "        "  # 8-space indent (inside construct method)


def build_scene_file(script: ScriptOutput, output_dir: Path) -> Path:
    """Build a complete Manim scene file from the script."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "scene.py"

    code = _generate_full_code(script)
    output_path.write_text(code)

    logger.info(f"Wrote Manim scene file: {output_path}")
    return output_path


def _generate_full_code(script: ScriptOutput) -> str:
    """Generate the complete Python source code."""
    parts = []
    parts.append('"""Auto-generated animation scene."""')
    parts.append(get_imports())
    parts.append(get_scene_header(script))
    parts.append(get_intro_scene(script))

    for i, scene in enumerate(script.scenes):
        parts.append(_build_scene_block(scene, i))

    parts.append(get_file_footer())
    return "\n".join(parts)


def _build_scene_block(scene: Scene, index: int) -> str:
    """Build a single scene block with proper Manim code."""
    visual_type = scene.visual_type

    builders = {
        "intro_title": _build_intro_scene,
        "formula_animation": _build_formula_scene,
        "diagram_zoom": _build_diagram_zoom_scene,
        "chart_build": _build_chart_scene,
        "slide_transition": _build_slide_scene,
        "concept_visual": _build_concept_scene,
    }

    builder = builders.get(visual_type, _build_concept_scene)
    return builder(scene)


def _build_intro_scene(scene: Scene) -> str:
    """Build intro/title scene block."""
    trans_from = _transition_call(scene.transition_from)
    trans_to = _transition_call(scene.transition_to)

    formulas = [e for e in scene.manim_elements if e.startswith("MathTex")]
    key_text = scene.title[:50]

    L = []
    L.append(f'{I2}# === Scene {scene.scene_id}: {key_text} ===')
    L.append(f'{I2}self.next_section("scene_{scene.scene_id}")')
    L.append(trans_from)

    if formulas:
        math_obj = _render_manim_element(formulas[0], key="main_formula")
        L.append(math_obj)
        L.append(f"{I2}self.play(Write(main_formula))")
    else:
        safe = key_text.replace('"', '\\"')
        L.append(f'{I2}main_title = Text("{safe}", font_size=36, color=' + 'BLUE_P)')
        L.append(f"{I2}main_title.center()")
        L.append(f"{I2}self.play(Write(main_title))")
        L.append(f'{I2}self.wait({scene.duration_seconds * 0.6:.1f})')

    L.append(trans_to)
    L.append(f"{I2}self.wait(0.3)")
    L.append("")

    return "\n".join(L)


def _build_formula_scene(scene: Scene) -> str:
    """Build a scene that animates mathematical formulas."""
    trans_from = _transition_call(scene.transition_from)
    trans_to = _transition_call(scene.transition_to)

    formulas = [e for e in scene.manim_elements if e.startswith("MathTex")]
    L = []
    L.append(f'{I2}# === Scene {scene.scene_id}: {scene.title} ===')
    L.append(f'{I2}self.next_section("scene_{scene.scene_id}")')
    L.append(trans_from)

    for i, formula_str in enumerate(formulas):
        key = f"formula_{i}"
        obj = _render_manim_element(formula_str, key=key)
        L.append(obj)
        L.append(f"{I2}self.play(Write({key}))")
        L.append(f"{I2}self.wait(1.5)")

    narr_preview = scene.narration[:80]
    L.append(f'{I2}narr_label = Text("{narr_preview}...", font_size=24, color=WHITE)')
    L.append(f'{I2}narr_label.to_edge(UP, buff=0.5)')
    L.append(f'{I2}self.play(Write(narr_label))')
    L.append(f'{I2}self.wait({max(2, scene.duration_seconds - 4):.1f})')
    L.append(trans_to)
    L.append(f"{I2}self.wait(0.3)")
    L.append("")

    return "\n".join(L)


def _build_diagram_zoom_scene(scene: Scene) -> str:
    """Build a scene that shows and zooms into a diagram/figure."""
    trans_from = _transition_call(scene.transition_from)
    trans_to = _transition_call(scene.transition_to)

    L = []
    L.append(f'{I2}# === Scene {scene.scene_id}: {scene.title} ===')
    L.append(f'{I2}self.next_section("scene_{scene.scene_id}")')
    L.append(trans_from)

    if scene.reference_page:
        L.append(f'{I2}page_img = ImageMobject(str(Path("{{page_placeholder}}").absolute()))')
        L.append(f'{I2}page_img.set_width(14)')
        L.append(f'{I2}self.play(FadeIn(page_img))')
        L.append(f'{I2}self.wait({scene.duration_seconds * 0.4:.1f})')
        L.append(f'{I2}self.play(page_img.animate.scale(1.5).move_to(ORIGIN + RIGHT * 2))')
        L.append(f'{I2}self.wait({scene.duration_seconds * 0.4:.1f})')
    else:
        L.append(f"{I2}# Placeholder: draw conceptual diagram")
        L.append(f'{I2}shape = Circle(radius=1.5, color=' + 'BLUE_P)')
        L.append(f"{I2}self.play(Create(shape))")
        L.append(f'{I2}self.wait({max(2, scene.duration_seconds - 2):.1f})')

    L.append(trans_to)
    L.append(f"{I2}self.wait(0.3)")
    L.append("")

    return "\n".join(L)


def _build_chart_scene(scene: Scene) -> str:
    """Build a scene that builds up a chart/plot step by step."""
    trans_from = _transition_call(scene.transition_from)
    trans_to = _transition_call(scene.transition_to)

    L = []
    L.append(f'{I2}# === Scene {scene.scene_id}: {scene.title} ===')
    L.append(f'{I2}self.next_section("scene_{scene.scene_id}")')
    L.append(trans_from)

    L.append(f"{I2}bar_chart = VGroup()")
    L.append(f"{I2}data_values = [1, 2, 3, 2.5, 1.8]")
    L.append(f"{I2}for i, val in enumerate(data_values):")
    L.append(f'{I2}    bar = Rectangle(height=val, width=0.5, fill_opacity=0.7)')
    L.append(f'{I2}    bar.set_color_by_gradient(' + 'GREEN_P, BLUE_P)')
    L.append(f'{I2}    bar.move_to(i * 0.7 * RIGHT + DOWN)')
    L.append(f'{I2}    bar_chart.add(bar)')
    L.append(f'{I2}self.play(Create(bar_chart))')
    L.append(f'{I2}self.wait({max(2, scene.duration_seconds - 3):.1f})')

    L.append(trans_to)
    L.append(f"{I2}self.wait(0.3)")
    L.append("")

    return "\n".join(L)


def _build_slide_scene(scene: Scene) -> str:
    """Build a scene that transitions between PDF slide images."""
    trans_from = _transition_call(scene.transition_from)
    trans_to = _transition_call(scene.transition_to)

    L = []
    L.append(f'{I2}# === Scene {scene.scene_id}: {scene.title} ===')
    L.append(f'{I2}self.next_section("scene_{scene.scene_id}")')
    L.append(trans_from)

    if scene.reference_page:
        L.append(f'{I2}img = ImageMobject(str(Path("{{slide_placeholder}}").absolute()))')
        L.append(f'{I2}img.set_width(16)')
        L.append(f'{I2}self.play(FadeIn(img))')
        L.append(f'{I2}self.wait({scene.duration_seconds - 2:.1f})')
        L.append(trans_to)
    else:
        title = scene.title.replace('"', '\\"')
        L.append(f'{I2}placeholder = Text("{title}", font_size=36)')
        L.append(f"{I2}placeholder.center()")
        L.append(f'{I2}self.play(Write(placeholder))')
        L.append(f'{I2}self.wait({max(2, scene.duration_seconds - 2):.1f})')
        L.append(trans_to)

    L.append(f"{I2}self.wait(0.3)")
    L.append("")

    return "\n".join(L)


def _build_concept_scene(scene: Scene) -> str:
    """Build a generic concept visualization scene."""
    trans_from = _transition_call(scene.transition_from)
    trans_to = _transition_call(scene.transition_to)

    L = []
    L.append(f'{I2}# === Scene {scene.scene_id}: {scene.title} ===')
    L.append(f'{I2}self.next_section("scene_{scene.scene_id}")')
    L.append(trans_from)

    if scene.manim_elements:
        for i, elem in enumerate(scene.manim_elements[:3]):
            if elem.startswith("MathTex"):
                obj = _render_manim_element(elem, key=f"elem_{i}")
                L.append(obj)
                L.append(f"{I2}self.play(Write(elem_{i}))")
            elif elem.startswith("Circle"):
                obj = _render_manim_element(elem, key=f"elem_{i}")
                L.append(obj)
                L.append(f"{I2}self.play(Create(elem_{i}))")
            elif elem.startswith("Line"):
                obj = _render_manim_element(elem, key=f"elem_{i}")
                L.append(obj)
                L.append(f"{I2}self.play(Create(elem_{i}))")
            else:
                L.append(f'{I2}# TODO: implement \'{elem}\'')
    else:
        title = scene.title[:40].replace('"', '\\"')
        L.append(f'{I2}concept_text = Text("{title}", font_size=36, weight=BOLD)')
        L.append(f'{I2}concept_text.center()')
        L.append(f'{I2}self.play(GrowFromCenter(concept_text))')

    L.append(f'{I2}self.wait({max(2, scene.duration_seconds - 2):.1f})')
    L.append(trans_to)
    L.append(f"{I2}self.wait(0.3)")
    L.append("")

    return "\n".join(L)


def _transition_call(transition_name: str) -> str:
    """Convert transition string to full self.play() call with 8-space indent."""
    mapping = {
        "fade_in": f'{I2}self.play(FadeIn(Mobject()))',
        "fade_out": f'{I2}self.play(FadeOut(Mobject()))',
        "slide_up": f'{I2}self.play(FadeIn(Mobject(), shift=DOWN))',
        "slide_down": f'{I2}self.play(FadeIn(Mobject(), shift=UP))',
        "slide_left": f'{I2}self.play(FadeIn(Mobject(), shift=RIGHT))',
        "slide_right": f'{I2}self.play(FadeIn(Mobject(), shift=LEFT))',
        "transform": f'{I2}self.play(Transform(Mobject(), Mobject()))',
        "grow_from_center": f'{I2}self.play(GrowFromCenter(Mobject()))',
        "grow_from_edge": f'{I2}self.play(GrowFromEdge(Mobject()))',
        "write": f'{I2}self.play(Write(Mobject()))',
        "unwrite": f'{I2}self.play(Unwrite(Mobject()))',
    }
    return mapping.get(transition_name, f'{I2}self.play(FadeIn(Mobject()))')


def _render_manim_element(elem_str: str, key: str) -> str:
    """Render a manim element string into code with 8-space indent.

    Examples:
        MathTex(r'E = mc^2') -> I2 + key = MathTex(r'E = mc^2')
        Circle(radius=1) -> I2 + key = Circle(radius=1)
    """
    match = re.match(r"(\w+)\((.*)\)", elem_str.strip())
    if match:
        return f"{I2}{key} = {match.group(1)}({match.group(2)})"
    # Handle cases like MathTex(r'...')
    if elem_str.startswith(("MathTex", "Text", "Circle", "Line", "Rectangle")):
        return f"{I2}{key} = {elem_str}"
    return f"{I2}# TODO: {elem_str}"
