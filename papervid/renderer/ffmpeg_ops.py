"""Deterministic manim/ffmpeg helpers shared by the llama.cpp pipeline and papervid.tools."""

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..parsers.models import VoiceSegment

logger = logging.getLogger(__name__)

# Uniform encoding so per-scene clips can be concatenated safely
VIDEO_CODEC_ARGS = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18"]
AUDIO_CODEC_ARGS = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def extract_scene_class(scene_file: Path) -> str:
    """Extract the scene class name from a Manim Python file."""
    content = scene_file.read_text()
    match = re.search(r"class\s+(\w+_Scene)\s*\(\s*Scene\s*\)", content)
    if match:
        return match.group(1)

    match = re.search(r"class\s+(\w+)\s*\(\s*(?:\w+\.)?\w*Scene\s*\)", content)
    if match:
        return match.group(1)

    raise ValueError(f"Could not find scene class in {scene_file}")


def run_manim(
    scene_file: Path,
    media_dir: Path,
    class_name: str | None = None,
    quality: str = "l",
    timeout: int = 900,
) -> dict:
    """Render one Manim scene class.

    Returns:
        dict with ok, class_name, video (path or None), returncode, stderr_tail.
    """
    from ..utils.helpers import find_executable

    class_name = class_name or extract_scene_class(scene_file)
    media_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        find_executable("manim"),
        f"-q{quality}",
        "--disable_caching",
        "--media_dir", str(media_dir.resolve()),
        str(scene_file.resolve()),
        class_name,
    ]
    # Scene files live in a work dir, so make `import papervid.manim_kit` resolvable
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(project_root), env.get("PYTHONPATH")]))
    env["PAPERVID_SCENE_FILE"] = str(scene_file.resolve())

    logger.info(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=scene_file.parent, env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "class_name": class_name, "video": None,
            "returncode": None, "stderr_tail": f"Timed out after {timeout}s",
        }

    video = _find_class_video(media_dir, scene_file, class_name) if result.returncode == 0 else None
    return {
        "ok": result.returncode == 0 and video is not None,
        "class_name": class_name,
        "video": str(video) if video else None,
        "returncode": result.returncode,
        "stderr_tail": "" if result.returncode == 0 else _error_excerpt(result.stdout, result.stderr),
    }


def _error_excerpt(stdout: str | None, stderr: str | None, limit: int = 3000) -> str:
    """Pull the traceback out of manim's output.

    manim prints its rich traceback to stdout followed by progress/log noise,
    so a plain tail often misses the actual error.
    """
    output = (stdout or "") + "\n" + (stderr or "")
    start = output.rfind("Traceback (most recent call last)")
    if start == -1:
        return output[-limit:]
    tb = output[start:]
    # Rich tracebacks are long; the scene-file frame and the exception line are
    # what matter, so keep frames mentioning scene files plus the traceback's end.
    tail = tb[-(limit // 2):]
    scene_frames = [
        block for block in re.split(r"\n(?=│ /)", tb)
        if re.search(r"scene_\d+\.py", block) and block not in tail
    ]
    excerpt = "\n...\n".join(b[: limit // 4] for b in scene_frames[-2:])
    return (excerpt + "\n...\n" + tail) if excerpt else tail


def _find_class_video(media_dir: Path, scene_file: Path, class_name: str) -> Path | None:
    """Find the newest mp4 manim wrote for a class (ignores partial movie files)."""
    candidates = [
        p for p in media_dir.rglob(f"{class_name}.mp4")
        if "partial_movie_files" not in p.parts and scene_file.stem in p.parts
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def probe_duration(path: Path) -> float:
    """Media duration in seconds via ffprobe (0.0 if unknown)."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 0.0


def extract_frames(video_path: Path, output_dir: Path, fps: int = 1) -> list[Path]:
    """Extract frames from a video at a fixed fps."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"fps={fps}", "-q:v", "2",
        str(output_dir / "frame_%03d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.error(f"Failed to extract frames: {result.stderr[-300:]}")
        return []
    frames = sorted(output_dir.glob("frame_*.jpg"))
    logger.info(f"Extracted {len(frames)} frames from {video_path.name}")
    return frames


def extract_frames_evenly(video_path: Path, output_dir: Path, count: int = 6, width: int = 1280) -> list[Path]:
    """Extract `count` frames evenly spaced through the video (including near the end)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("frame_*.jpg"):
        old.unlink()

    duration = probe_duration(video_path)
    if duration <= 0:
        return []

    frames = []
    for i in range(count):
        # Sample at the centre of each of `count` equal slices
        t = duration * (i + 0.5) / count
        out = output_dir / f"frame_{i + 1:02d}_{t:06.2f}s.jpg"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and out.exists():
            frames.append(out)
    return frames


def combine_audio_chunks(segments: list[VoiceSegment], output_path: Path) -> Path:
    """Combine multiple audio chunks into one file using pydub."""
    from pydub import AudioSegment

    combined = AudioSegment.silent(duration=0)
    for i, seg in enumerate(segments):
        if not Path(seg.audio_path).exists():
            continue
        combined += AudioSegment.from_file(str(seg.audio_path))
        if i < len(segments) - 1:
            combined += AudioSegment.silent(duration=200)  # 200ms gap

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output_path), format="mp3")
    return output_path


def overlay_audio(video_path: Path, audio_path: Path | None, output_path: Path, tail_pad: float = 0.5) -> Path:
    """Mux audio onto video, re-encoding to a uniform format.

    If the narration is longer than the animation, the last frame is held
    so the audio is never cut off. Clips without audio get a silent track
    so the concat step sees identical stream layouts.
    """
    video_dur = probe_duration(video_path)
    audio_dur = probe_duration(audio_path) if audio_path else 0.0
    target = max(video_dur, audio_dur + tail_pad if audio_path else 0.0)
    pad = max(0.0, target - video_dur)

    vf = "fps=60,format=yuv420p"
    if pad > 0.01:
        vf = f"tpad=stop_mode=clone:stop_duration={pad:.3f}," + vf

    if audio_path:
        audio_input = ["-i", str(audio_path)]
        af = ["-af", "apad"]
    else:
        audio_input = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        af = []

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path), *audio_input,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", vf, *af,
        *VIDEO_CODEC_ARGS, *AUDIO_CODEC_ARGS,
        "-t", f"{target:.3f}",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"ffmpeg audio overlay failed: {result.stderr[-500:]}")
        shutil.copy2(video_path, output_path)
    return output_path


def merge_scenes(video_files: list[Path], output_path: Path) -> Path:
    """Concatenate uniformly-encoded clips into one video."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = output_path.parent / "_concat_list.txt"
    concat_list.write_text(
        "\n".join(f"file '{str(Path(vf).resolve())}'" for vf in video_files)
    )

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"ffmpeg concat failed: {result.stderr[-500:]}")
        if video_files:
            shutil.copy2(video_files[0], output_path)
    else:
        logger.info(f"Merged {len(video_files)} scenes into {output_path.name}")

    concat_list.unlink(missing_ok=True)
    return output_path
