"""Data models for papervid."""

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional


@dataclass
class PageImage:
    """A rendered PDF page as an image."""
    page_number: int
    image_path: Path
    width: int = 0
    height: int = 0


@dataclass
class PaperMetadata:
    """Metadata from PDF (no text extraction)."""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    date: str = ""
    journal: str = ""


@dataclass
class PaperData:
    """Parsed paper — page images only, no text extraction."""
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    pages: list[PageImage] = field(default_factory=list)

    @property
    def image_paths(self) -> list[Path]:
        return [p.image_path for p in self.pages]

    @property
    def num_pages(self) -> int:
        return len(self.pages)


@dataclass
class Scene:
    """A single animation scene."""
    scene_id: int
    title: str
    narration: str
    visual_type: str
    manim_elements: list[str] = field(default_factory=list)
    transition_from: str = "fade_in"
    transition_to: str = "fade_out"
    duration_seconds: float = 10.0
    reference_page: Optional[int] = None
    # Claude Code workflow fields
    visual_plan: str = ""
    figures: list[dict] = field(default_factory=list)  # [{"page": 3, "box": [x0, y0, x1, y1], "name": "fig2"}]
    audio_duration: float = 0.0


@dataclass
class ScriptOutput:
    """Full generated script."""
    title: str
    author_line: str
    scenes: list[Scene] = field(default_factory=list)
    total_duration: float = 0.0

    @property
    def total_words(self) -> int:
        return sum(len(s.narration.split()) for s in self.scenes)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScriptOutput":
        scene_keys = {f.name for f in fields(Scene)}
        scenes = [
            Scene(**{k: v for k, v in s.items() if k in scene_keys})
            for s in data.get("scenes", [])
        ]
        return cls(
            title=data.get("title", "Research Paper"),
            author_line=data.get("author_line", ""),
            scenes=scenes,
            total_duration=data.get("total_duration", 0.0),
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> "ScriptOutput":
        return cls.from_dict(json.loads(path.read_text()))


@dataclass
class VoiceSegment:
    """A TTS audio segment for a single scene."""
    scene_id: int
    audio_path: Path
    subtitle_path: Path
    start_time: float = 0.0
    duration: float = 0.0


@dataclass
class PipelineState:
    """Tracks progress through the pipeline."""
    pdf_path: Optional[Path] = None
    paper_data: Optional[PaperData] = None
    script: Optional[ScriptOutput] = None
    scene_file: Optional[Path] = None
    voice_segments: list[VoiceSegment] = field(default_factory=list)
    output_video: Optional[Path] = None
    intermediate_dir: Optional[Path] = None
