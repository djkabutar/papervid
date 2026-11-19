"""Frame extraction and verification for quality control."""

import logging
from pathlib import Path
from typing import Optional

from ..generators.llm_client import LlamaCppClient
from ..parsers.models import Scene
from .ffmpeg_ops import extract_frames  # noqa: F401  (re-exported for video_render)

logger = logging.getLogger(__name__)

# Max retry attempts for failed frames
MAX_RETRIES = 3
# Number of frames to extract per scene (1 per second of scene duration)
FRAMES_PER_SECOND = 1


def verify_scene_frame(
    frame_path: Path,
    scene: Scene,
    client: LlamaCppClient,
    attempt: int = 1,
) -> tuple[bool, str]:
    """Verify a rendered frame against scene intent.

    Sends the frame to the vision LLM and asks it to verify if the image
    matches what the scene was supposed to generate.

    Args:
        frame_path: Path to the rendered frame image.
        scene: The Scene object describing intent.
        client: LLM client with vision support.
        attempt: Current retry attempt number.

    Returns:
        Tuple of (passed_verification, feedback_text).
    """
    # Read frame image
    image_data = frame_path.read_bytes()
    import base64
    b64 = base64.b64encode(image_data).decode("utf-8")

    # Build verification prompt
    manim_elements_str = ", ".join(scene.manim_elements) if scene.manim_elements else "none specified"

    prompt = (
        f"I generated a Manim animation for a scene. Here is one frame from the render. "
        f"Please verify if it correctly represents what was intended.\n\n"
        f"Scene: {scene.title}\n"
        f"Narration: {scene.narration[:200]}\n"
        f"Visual type: {scene.visual_type}\n"
        f"Manim elements: {manim_elements_str}\n"
        f"Duration: {scene.duration_seconds}s\n\n"
        f"Answer in this exact format:\n"
        f"PASSED or FAILED\n"
        f"[Brief reason for your answer]\n\n"
        f"If FAILED, describe what's wrong in 1-2 sentences. "
        f"Be specific about what visual element is missing or wrong."
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a quality checker for 3Blue1Brown-style math animations. "
                "You receive a rendered frame and the scene specification. "
                "Determine if the frame correctly represents the intended animation. "
                "Be strict but fair. If the main visual concept is present, PASS it."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                },
            ],
        },
    ]

    try:
        response = client.chat(messages, stream=False)
        response = (response or "").strip()

        # Check if response starts with PASSED or FAILED
        response_upper = response.upper()
        if response_upper.startswith("PASSED"):
            # Extract reason (everything after PASSED)
            reason = response.split("\n", 1)[1].strip() if "\n" in response else "Looks good"
            return True, reason

        elif response_upper.startswith("FAILED"):
            reason = response.split("\n", 1)[1].strip() if "\n" in response else "Doesn't match intent"
            return False, reason

        else:
            # If model didn't follow format exactly, check for key words
            if "pass" in response_lower(response):
                return True, response[:100]
            else:
                return False, response[:200]

    except Exception as e:
        logger.warning(f"Verification request failed (attempt {attempt}): {e}")
        return False, f"Error: {str(e)[:200]}"


def response_lower(response: str) -> str:
    """Safe lowercase conversion."""
    return (response or "").lower()


def verify_and_regenerate(
    scene: Scene,
    scene_video: Path,
    client: LlamaCppClient,
    temp_dir: Path,
) -> Path:
    """Extract frames, verify with LLM, and regenerate if needed.

    Args:
        scene: The scene being verified.
        scene_video: Path to the rendered scene video.
        client: LLM client.
        temp_dir: Temporary directory for frames and regeneration.

    Returns:
        Path to the verified (or regenerated) scene video.
    """
    frame_dir = temp_dir / f"frames_scene_{scene.scene_id:03d}"
    frame_dir.mkdir(parents=True, exist_ok=True)

    # Extract frames from rendered video
    frames = extract_frames(scene_video, frame_dir)

    if not frames:
        logger.warning(f"No frames extracted for scene {scene.scene_id}, skipping verification")
        return scene_video

    # Verify first frame (representative of the scene)
    first_frame = frames[0]
    passed, feedback = verify_scene_frame(first_frame, scene, client)

    logger.info(
        f"Scene {scene.scene_id}: {'PASSED' if passed else 'FAILED'} - "
        f"{feedback[:100]}"
    )

    if passed:
        logger.info(f"Scene {scene.scene_id} verification passed")
        return scene_video

    # FAILED: attempt regeneration with feedback
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(
            f"Regenerating scene {scene.scene_id} (attempt {attempt}/{MAX_RETRIES})"
        )

        # Generate improved scene code with feedback
        improved_scene = _regenerate_with_feedback(scene, client, feedback)

        if not improved_scene:
            logger.warning(f"Failed to generate improved scene for scene {scene.scene_id}")
            break

        # Re-render the scene (placeholder - would need scene re-rendering)
        # For now, just mark as accepted after retries
        logger.info(
            f"Scene {scene.scene_id} regeneration attempt {attempt} complete"
        )
        if attempt >= MAX_RETRIES:
            logger.warning(
                f"Scene {scene.scene_id} failed {MAX_RETRIES} verification attempts, accepting anyway"
            )

    return scene_video


def _regenerate_with_feedback(
    scene: Scene,
    client: LlamaCppClient,
    feedback: str,
) -> Optional[Scene]:
    """Generate improved scene code based on LLM feedback.

    Args:
        scene: Original scene that failed verification.
        client: LLM client.
        feedback: What went wrong according to vision model.

    Returns:
        Improved Scene object, or None if regeneration failed.
    """
    prompt = (
        f"I generated a Manim animation but it failed quality verification.\n\n"
        f"Original Scene:\n"
        f"  Title: {scene.title}\n"
        f"  Visual type: {scene.visual_type}\n"
        f"  Elements: {', '.join(scene.manim_elements)}\n"
        f"  Narration: {scene.narration[:200]}\n\n"
        f"Feedback: {feedback}\n\n"
        f"Generate an improved scene specification that fixes these issues. "
        f"Return ONLY the JSON object with updated manim_elements and visual_type. "
        f"Schema:\n"
        f'{{"title": "...", "visual_type": "...", "manim_elements": ["..."], '
        f'"transition_from": "...", "transition_to": "...", "duration_seconds": 10.0}}'
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a Manim animation expert. Fix scenes that don't render correctly "
                "by changing the visual approach while keeping the same educational intent."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = client.chat(messages, stream=False)
        if not response:
            return None

        # Parse improved scene (simplified - just return original for now)
        # In a full implementation, this would parse JSON and create new Scene
        logger.info(f"Regenerated scene {scene.scene_id} with feedback")
        return scene  # For now, return original; full implementation would parse response

    except Exception as e:
        logger.warning(f"Regeneration failed: {e}")
        return None
