"""Project configuration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    """Global configuration for papervid."""

    # PDF settings
    pdf_dpi: int = 200
    max_pages: int = 50

    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("./papervid_output"))
    video_resolution: tuple[int, int] = (1920, 1080)
    frame_rate: int = 60
    quality: str = "high"  # low, medium, high

    # LLM / llama.cpp settings
    llama_cpp_url: str = "http://localhost:8080"
    llama_cpp_model: str = "llama3.2"

    # Voice / TTS settings
    tts_voice: str = "en-US-AriaNeural"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"

    # Manim settings
    manim_background_color: str = "#000000"
    manim_font: str = "Georgia"
    manim_math_font: str = "FreeMono"

    # Pipeline settings
    generate_tts: bool = True
    generate_manim: bool = True
    preview_video: bool = False
    keep_intermediates: bool = False

    # Scene timing defaults (seconds per ~15 words)
    words_per_second: float = 2.5

    # Runtime state (set during pipeline execution)
    pdf_path: Optional[Path] = None
    paper_data: Optional[object] = None
    script: Optional[object] = None
    scene_file: Optional[Path] = None
    voice_segments: list = field(default_factory=list)
    output_video: Optional[Path] = None


def create_default_config() -> "Config":
    """Create a new Config with default values."""
    return Config()
