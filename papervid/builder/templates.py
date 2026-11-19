"""3Blue1Brown-style Manim scene templates."""

IND = "    "  # base indent


def get_imports() -> str:
    """Get the standard imports for 3B1B-style scenes."""
    lines = [
        "from manim import *",
        "",
        'config.background_color = BLACK',
        "config.frame_rate = 60",
        "",
        "# 3Blue1Brown color palette",
        'GOLD = "#FFB347"',
        'BLUE_P = "#77A1D3"',
        'GREEN_P = "#77D37A"',
        'PINK_P = "#DD7ADB"',
        'WHITE_P = "#F8F8F8"',
        'DIM_WHITE = "#CCCCCC"',
    ]
    return "\n".join(lines)


def get_scene_header(script) -> str:
    """Get the scene class header with proper indentation."""
    safe_title = "".join(c if c.isalnum() else "_" for c in script.title[:30])
    lines = [
        "",
        f"class {safe_title}_Scene(Scene):",
        f'    """Auto-generated animation for: {script.title}"""',
        "",
        "    def construct(self):",
        "        pass  # placeholder",
    ]
    return "\n".join(lines)


def get_intro_scene(script) -> str:
    """Generate intro/title scene. All lines indented 8 spaces for inside construct()."""
    title = script.title.replace('"', '\\"')[:60]
    author = script.author_line[:40]

    lines = [
        "",
        "        # === INTRO TITLE SCENE ===",
        "        title_text = Text(",
        f'            "{title}",',
        "            font_size=48,",
        "            weight=BOLD,",
        "            color=WHITE_P,",
        "        )",
        "        subtitle = Text(",
        f'            "{author}",',
        "            font_size=28,",
        "            color=BLUE_P,",
        "        )",
        "        subtitle.next_to(title_text, DOWN, buff=0.3)",
        "",
        "        intro_group = VGroup(title_text, subtitle).center()",
        "",
        "        self.play(Write(title_text))",
        "        self.play(Write(subtitle))",
        "        self.wait(2)",
        "        self.play(FadeOut(intro_group))",
        "        self.wait(0.5)",
    ]
    return "\n".join(lines)


def _transition_to_manim(transition_name: str) -> str:
    """Convert transition name to full self.play() call with 8-space indent."""
    mapping = {
        "fade_in": "        self.play(FadeIn(Mobject()))",
        "fade_out": "        self.play(FadeOut(Mobject()))",
        "slide_up": "        self.play(FadeInFromDown(Mobject()))",
        "slide_down": "        self.play(FadeInFromUp(Mobject()))",
        "slide_left": "        self.play(FadeInFromLeft(Mobject()))",
        "slide_right": "        self.play(FadeInFromRight(Mobject()))",
        "transform": "        self.play(Transform(Mobject(), Mobject()))",
        "grow_from_center": "        self.play(GrowFromCenter(Mobject()))",
        "grow_from_edge": "        self.play(GrowFromEdge(Mobject()))",
        "write": "        self.play(Write(Mobject()))",
        "unwrite": "        self.play(Unwrite(Mobject()))",
    }
    return mapping.get(transition_name, "        self.play(FadeIn(Mobject()))")


def get_section_header(index: int) -> str:
    """Generate self.next_section() call for Manim section grouping."""
    return f"    self.next_section(\"Section {index}\")"


def get_file_footer() -> str:
    """File footer — nothing needed for Manim."""
    return ""
