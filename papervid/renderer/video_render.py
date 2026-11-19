"""Video renderer — renders Manim scenes, syncs audio, merges final video."""

import base64
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..parsers.models import ScriptOutput, VoiceSegment
from ..generators.llm_client import LlamaCppClient
from .ffmpeg_ops import (
    combine_audio_chunks as _combine_audio_chunks,
    extract_scene_class as _extract_scene_class,
    merge_scenes as _merge_scenes,
    overlay_audio as _overlay_audio,
)

logger = logging.getLogger(__name__)


def render_video(
    scene_file: Path,
    voice_segments: list[VoiceSegment],
    script: ScriptOutput,
    output_dir: Path,
    resolution: tuple[int, int] = (1920, 1080),
    frame_rate: int = 60,
    preview: bool = False,
    llm_client: LlamaCppClient = None,
) -> Path:
    """Render the complete video pipeline.

    Steps:
        1. Render Manim scenes
        2. Verify rendered frames with vision LLM
        3. Generate scene-level video files
        4. Sync audio to each scene
        5. Merge all scenes into final video

    Args:
        scene_file: Path to the generated Manim .py file.
        voice_segments: Generated TTS voice segments.
        script: The animation script.
        output_dir: Directory for output files.
        resolution: Video resolution (width, height).
        frame_rate: Frames per second.
        preview: If True, render at low quality for preview.
        llm_client: LLM client for frame verification.

    Returns:
        Path to the final MP4 video.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine quality flags
    if preview:
        quality_flags = ["-ql", "-p"]
        resolution_str = "1280x720"
        frame_rate_int = 30
    else:
        quality_flags = ["-qh"]
        resolution_str = f"{resolution[0]}x{resolution[1]}"
        frame_rate_int = frame_rate

    # Step 1: Get scene class name from the file
    class_name = _extract_scene_class(scene_file)
    logger.info(f"Rendering class '{class_name}' with Manim...")

    # Step 2: Render with manim
    manim_output = output_dir / "_manim_temp"
    media_dir = manim_output / "media"

    manim_cmd = [
        "manim",
        *quality_flags,
        "--media_dir", str(media_dir),
        str(scene_file),
        class_name,
    ]

    logger.info(f"Running: {' '.join(manim_cmd)}")
    try:
        result = subprocess.run(
            manim_cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            logger.warning(f"Manim returned non-zero exit code: {result.returncode}")
            logger.warning(result.stderr[-500:] if result.stderr else "No stderr")
    except subprocess.TimeoutExpired:
        logger.error("Manim render timed out after 600s")
        raise

    # Step 3: Find rendered scene video
    scene_videos = _find_rendered_videos(media_dir, class_name)

    if not scene_videos:
        logger.error("No rendered videos found. Checking manim output...")
        logger.error(result.stderr if 'result' in dir() else "No stderr available")
        # Try to find any mp4 in media directory
        all_videos = list(media_dir.rglob("*.mp4"))
        logger.info(f"Found {len(all_videos)} MP4 files in media dir")
        for v in all_videos:
            logger.info(f"  {v}")
        raise RuntimeError("No rendered scene videos found. Check manim output for errors.")

    # Step 4: Verify rendered frames with vision LLM (optional)
    if llm_client and script.scenes:
        logger.info("Verifying rendered frames with vision LLM...")
        verify_dir = output_dir / "_verify_frames"
        scene_videos = _verify_with_llm(
            scene_videos, script.scenes, llm_client, verify_dir,
            scene_file, media_dir, class_name, resolution_str, frame_rate_int,
        )
        logger.info("Verification complete")

    # Step 5: Sync audio and create scene videos with audio
    logger.info(f"Syncing audio for {len(scene_videos)} scenes...")
    scene_video_files = []

    for i, scene_video_path in enumerate(scene_videos):
        scene_id = i + 1
        # Find voice segments for this scene
        scene_audio = [
            vs for vs in voice_segments if vs.scene_id == scene_id
        ]

        out_video = output_dir / f"scene_{scene_id:03d}_final.mp4"

        if scene_audio:
            # Combine all audio chunks for this scene into one
            combined_audio = output_dir / f"scene_{scene_id:03d}_combined.mp3"
            _combine_audio_chunks(scene_audio, combined_audio)

            # Overlay audio on video
            _overlay_audio(scene_video_path, combined_audio, out_video)
        else:
            # No audio, just copy the video
            shutil.copy2(scene_video_path, out_video)

        scene_video_files.append(out_video)
        logger.info(f"  Scene {scene_id}: {out_video.name}")

    # Step 5: Merge all scenes
    logger.info("Merging all scenes into final video...")
    final_video = output_dir / f"{script.title.replace(' ', '_')[:50]}_final.mp4"

    _merge_scenes(scene_video_files, final_video)

    # Clean up manim temp if not keeping intermediates
    logger.info(f"Final video: {final_video}")
    return final_video


def _find_rendered_videos(media_dir: Path, class_name: str) -> list[Path]:
    """Find the rendered MP4 files for the given scene class."""
    # Manim stores videos in media/Video/x/y/ directory structure
    mp4_files = list(media_dir.rglob("*.mp4"))

    # Filter for files matching our scene class name
    matched = []
    for f in mp4_files:
        # Check if the file name matches the class
        if class_name.lower().replace("_", "") in f.stem.lower().replace("_", ""):
            matched.append(f)
        elif "scene" in f.stem.lower():
            matched.append(f)

    # If no matches, use all mp4 files found
    if not matched and mp4_files:
        matched = sorted(mp4_files)

    return matched


def _verify_with_llm(
    scene_videos: list[Path],
    scenes: list,
    client: LlamaCppClient,
    verify_dir: Path,
    scene_file: Path,
    media_dir: Path,
    class_name: str,
    resolution_str: str,
    frame_rate_int: int,
) -> list[Path]:
    """Verify rendered scene videos with vision LLM.

    Extracts frames from each scene video and samples every 30th frame
    (~1 per second for 30fps) for quality verification. If any sampled
    frame fails, rewrites the
    Manim scene file with LLM-generated corrections and re-renders,
    repeating up to MAX_RETRIES times.

    Args:
        scene_videos: List of rendered scene video paths.
        scenes: List of Scene objects.
        client: LLM client with vision support.
        verify_dir: Directory for verification artifacts.
        scene_file: Path to the generated Manim .py file.
        media_dir: Manim output media directory.
        class_name: Manim scene class name.
        resolution_str: Video resolution string.
        frame_rate_int: Video frame rate.

    Returns:
        List of verified scene video paths.
    """
    from ..renderer.frame_verify import extract_frames, verify_scene_frame, MAX_RETRIES

    verified_videos = []
    scene_id = 0

    for video_path in scene_videos:
        scene_id += 1
        scene = scenes[scene_id - 1] if scene_id - 1 < len(scenes) else None

        if not scene:
            verified_videos.append(video_path)
            continue

        frame_dir = verify_dir / f"scene_{scene_id:03d}"
        frames = extract_frames(video_path, frame_dir)

        if not frames:
            verified_videos.append(video_path)
            continue

        # Sample every 30th frame (~1 frame per second for 30fps video)
        sampled_frames = frames[::30]

        # Verify each sampled frame individually
        failures = []
        for frame in sampled_frames:
            passed, feedback = verify_scene_frame(frame, scene, client)
            if not passed:
                failures.append((frame, feedback))

        if failures:
            logger.info(
                f"Scene {scene_id}: {len(failures)} sampled frame(s) failed verification"
            )

            # Attempt regeneration
            video_path = _retry_regenerate_scene(
                scene_file, scene, scene_id, failures, client,
                media_dir, verify_dir, class_name,
                resolution_str, frame_rate_int, scene_videos,
            )

        verified_videos.append(video_path)

    return verified_videos


def _retry_regenerate_scene(
    scene_file: Path,
    scene,
    scene_id: int,
    failures: list,
    client: LlamaCppClient,
    media_dir: Path,
    verify_dir: Path,
    class_name: str,
    resolution_str: str,
    frame_rate_int: int,
    scene_videos: list,
) -> Path:
    """Regenerate a scene file with LLM corrections and re-render.

    Sends all failed frames and their feedback to the LLM, which returns
    a modified scene.py. The modified file is written, Manim re-renders,
    and frames are re-extracted. This repeats up to MAX_RETRIES times.

    Args:
        scene_file: Path to the generated Manim .py file.
        scene: The Scene object being corrected.
        scene_id: Scene index for logging.
        failures: List of (frame_path, feedback) tuples from failed frames.
        client: LLM client with vision support.
        media_dir: Manim output media directory.
        verify_dir: Directory for verification artifacts.
        class_name: Manim scene class name.
        resolution_str: Video resolution string.
        frame_rate_int: Video frame rate.
        scene_videos: List of all scene video paths (for fallback).

    Returns:
        Path to the verified scene video (may be re-rendered).
    """
    from ..renderer.frame_verify import extract_frames, verify_scene_frame, MAX_RETRIES

    current_scene_file = scene_file
    video_path = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"Regenerating scene {scene_id} (attempt {attempt}/{MAX_RETRIES})")

        # Get modified scene code from LLM
        modified_code = _regenerate_manim_scene(
            current_scene_file, scene, failures, client
        )

        if not modified_code:
            logger.warning(
                f"Failed to generate corrected code for scene {scene_id}"
            )
            break

        # Write modified scene code
        current_scene_file.write_text(modified_code)
        logger.info(f"Wrote corrected scene code to {current_scene_file}")

        # Re-render with Manim
        video_path = _rerender_scene(
            current_scene_file, media_dir, class_name,
            resolution_str, frame_rate_int,
        )

        if not video_path:
            logger.warning(f"Re-render produced no video output for scene {scene_id}")
            break

        # Re-extract and re-verify sampled frames
        frame_dir = verify_dir / f"scene_{scene_id:03d}_retry_{attempt}"
        frame_dir.mkdir(parents=True, exist_ok=True)
        new_frames = extract_frames(video_path, frame_dir)

        if not new_frames:
            logger.warning(f"No frames extracted after re-render for scene {scene_id}")
            break

        sampled_frames = new_frames[::30]
        new_failures = []
        for frame in sampled_frames:
            passed, feedback = verify_scene_frame(frame, scene, client)
            if not passed:
                new_failures.append((frame, feedback))

        if not new_failures:
            logger.info(f"Scene {scene_id} passed verification after {attempt} retry attempt(s)")
            return video_path

        # Still failing — update failures for next retry
        failures = new_failures
        logger.info(
            f"Scene {scene_id}: {len(new_failures)} frame(s) still failing after attempt {attempt}"
        )

    # All retries exhausted — return whatever we have
    logger.warning(
        f"Scene {scene_id} failed verification after {MAX_RETRIES} retries, using last render"
    )
    if video_path:
        return video_path
    fallback_idx = scene_id - 2 if scene_id > 1 else 0
    return scene_videos[fallback_idx] if fallback_idx < len(scene_videos) else scene_videos[0]


def _regenerate_manim_scene(
    scene_file: Path,
    scene,
    failures: list,
    client: LlamaCppClient,
) -> Optional[str]:
    """Generate corrected Manim scene code based on LLM vision feedback.

    Sends the original scene code, failed frame images, and verification
    feedback to the LLM. Requests full modified Python code for the scene
    class that fixes all identified issues.

    Args:
        scene_file: Path to the current Manim scene file.
        scene: The Scene object being corrected.
        failures: List of (frame_path, feedback) tuples.
        client: LLM client with vision support.

    Returns:
        Modified scene code as a string, or None on failure.
    """
    original_code = scene_file.read_text()

    # Encode failed frames as base64 — limit to first 2 to avoid oversized payloads
    frame_images = []
    for frame_path, feedback in failures[:2]:
        frame_data = frame_path.read_bytes()
        b64 = base64.b64encode(frame_data).decode("utf-8")
        frame_images.append((b64, feedback))

    # Build failure descriptions
    failure_descriptions = ""
    for i, (b64, fb) in enumerate(frame_images):
        failure_descriptions += f"\n  Frame {i+1} issue: {fb}"

    # If there were more failures, mention them in text
    for _, fb in failures[2:]:
        failure_descriptions += f"\n  Additional issue: {fb}"

    manim_elements_str = ", ".join(scene.manim_elements) if scene.manim_elements else "none"

    prompt = (
        f"I generated a Manim animation but the vision LLM found issues "
        f"in the rendered frames.\n\n"
        f"Original Scene Title: {scene.title}\n"
        f"Scene ID: {scene.scene_id}\n"
        f"Narration: {scene.narration[:300]}\n"
        f"Visual type: {scene.visual_type}\n"
        f"Manim elements: {manim_elements_str}\n"
        f"Duration: {scene.duration_seconds}s\n\n"
        f"=== FAILURE DETAILS ===\n"
        f"{failure_descriptions}\n\n"
        f"Here is the ORIGINAL scene.py code:\n"
        f"```python\n{original_code}\n```\n\n"
        f"Return the FULL modified scene.py code that fixes all the issues "
        f"identified above. The fix should be minimal — only change what's "
        f"necessary to correct the reported problems.\n\n"
        f"Requirements:\n"
        f"1. Return the COMPLETE file, not just the changed portion\n"
        f"2. Keep all imports and the class header intact\n"
        f"3. Fix the visual elements that the vision LLM flagged\n"
        f"4. Use proper Manim animations (Write, Create, FadeIn, Transform, etc.)\n"
        f"5. Do NOT use placeholder Mobjects if the issue is blank/missing content\n"
        f"6. Preserve the 3Blue1Brown color palette definitions\n\n"
        f"Return ONLY the Python code. Do NOT include explanations or markdown "
        f"code fences — just raw Python code starting with '""" + '"""' + "\n"
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a Manim animation expert. You receive rendered frames "
                "with LLM verification feedback and the original scene code. "
                "Your job is to fix the scene code so the animation correctly "
                "displays the intended visual content. Return the COMPLETE "
                "modified Python file."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
            ]
            + [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                }
                for b64, _ in frame_images
            ],
        },
    ]

    try:
        response = client.chat(messages, stream=False)
        if not response:
            return None

        # Clean up the response: strip markdown code fences if present
        cleaned = response.strip()

        # Remove ```python ... ``` wrapping
        if cleaned.startswith("```python"):
            cleaned = cleaned[len("```python"):].strip()
        if cleaned.startswith("```"):
            cleaned = cleaned[len("```"):].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

        # Validate that the cleaned code contains a scene class
        if "class" not in cleaned or "Scene" not in cleaned:
            logger.warning("LLM response does not appear to contain valid Python code")
            return None

        return cleaned

    except Exception as e:
        logger.warning(f"Regeneration request failed: {e}")
        return None


def _rerender_scene(
    scene_file: Path,
    media_dir: Path,
    class_name: str,
    resolution_str: str,
    frame_rate_int: int,
) -> Optional[Path]:
    """Re-render a Manim scene with updated code.

    Args:
        scene_file: Path to the Manim .py file.
        media_dir: Manim output media directory.
        class_name: Scene class name.
        resolution_str: Resolution string (e.g. '1920x1080').
        frame_rate_int: Frame rate integer.

    Returns:
        Path to the re-rendered video, or None on failure.
    """
    manim_cmd = [
        "manim",
        "-qh",
        "--media_dir", str(media_dir),
        str(scene_file),
        class_name,
    ]

    logger.info(f"Re-rendering: {' '.join(manim_cmd)}")
    try:
        result = subprocess.run(
            manim_cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            logger.warning(f"Re-render failed with code {result.returncode}")
            logger.warning(result.stderr[-500:] if result.stderr else "No stderr")
            return None
    except subprocess.TimeoutExpired:
        logger.error("Re-render timed out after 600s")
        return None

    # Find the re-rendered video
    mp4_files = list(media_dir.rglob("*.mp4"))
    if mp4_files:
        # Find the one matching our class name
        for f in mp4_files:
            if class_name.lower().replace("_", "") in f.stem.lower().replace("_", ""):
                return f
        return mp4_files[-1]

    logger.warning("Re-render produced no MP4 files")
    return None


def render_preview(scene_file: Path, output_dir: Path) -> Path:
    """Render a quick low-quality preview of the scene.

    Args:
        scene_file: Path to Manim .py file.
        output_dir: Output directory.

    Returns:
        Path to preview video.
    """
    class_name = _extract_scene_class(scene_file)
    media_dir = output_dir / "_preview_manim" / "media"

    cmd = [
        "manim",
        "-ql",   # low quality
        "-p",    # preview (open after render)
        "-r", "1280x720",
        "--media_dir", str(media_dir),
        str(scene_file),
        class_name,
    ]

    logger.info(f"Rendering preview: {' '.join(cmd)}")
    subprocess.run(cmd)

    # Find the preview video
    mp4_files = list(media_dir.rglob("*.mp4"))
    if mp4_files:
        return mp4_files[-1]

    raise RuntimeError("Preview render produced no output.")
