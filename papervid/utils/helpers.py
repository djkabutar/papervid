"""Utility functions for papervid."""

import logging
import shutil
from pathlib import Path


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def ensure_poppler_installed() -> bool:
    """Check if poppler-utils (pdftoppm/pdftocairo) are installed."""
    return (
        shutil.which("pdftoppm") is not None
        and shutil.which("pdftocairo") is not None
    )


def ensure_ffmpeg_installed() -> bool:
    """Check if ffmpeg is installed."""
    return shutil.which("ffmpeg") is not None


def find_executable(name: str) -> str:
    """Locate a tool on PATH, falling back to the running interpreter's bin dir.

    manim lives in the Python env rather than on the system PATH, so
    `python -m papervid.tools` must still find it when the env isn't activated.
    """
    import sys

    found = shutil.which(name)
    if found:
        return found
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    return name


def estimate_video_length(words: int, wps: float = 2.5) -> str:
    """Estimate video length from word count.

    Args:
        words: Number of words in narration.
        wps: Words per second speaking rate.

    Returns:
        Human-readable duration string like "3m 45s".
    """
    total_seconds = words / wps
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def format_file_size(path: Path) -> str:
    """Format file size as human-readable string."""
    size = path.stat().st_size
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def clean_directory(path: Path, keep_patterns: list[str] | None = None) -> None:
    """Remove files in a directory except those matching keep patterns.

    Args:
        path: Directory to clean.
        keep_patterns: List of glob patterns to keep.
    """
    if not path.exists():
        return

    keep = keep_patterns or []
    for item in path.iterdir():
        if item.is_file():
            should_keep = any(item.match(p) for p in keep)
            if not should_keep:
                item.unlink()
        elif item.is_dir():
            clean_directory(item, keep)
