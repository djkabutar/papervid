"""Script generation — sends PDF page images to vision LLM."""

import base64
import json
import logging
import re
from pathlib import Path

from ..parsers.models import PaperData, ScriptOutput, Scene
from .llm_client import LlamaCppClient

logger = logging.getLogger(__name__)


def generate_script(paper: PaperData, client: LlamaCppClient) -> ScriptOutput:
    """Generate animation script by sending PDF page images to vision LLM.

    The vision model analyzes PDF page images directly — no text extraction.

    Args:
        paper: Parsed paper data (images only).
        client: Active llama.cpp client with vision support.

    Returns:
        Complete ScriptOutput with all scenes.
    """
    logger.info(f"Generating script for '{paper.metadata.title}'")

    if not paper.pages:
        logger.warning("No pages found in PDF")
        return ScriptOutput(title=paper.metadata.title or "Research Paper", author_line="Unknown")

    # Send page images in batches to the vision LLM
    all_scenes: list[Scene] = []
    scene_counter = 0
    max_images_per_request = 5

    # Group pages into batches
    for batch_start in range(0, len(paper.pages), max_images_per_request):
        batch_images = paper.pages[batch_start:batch_start + max_images_per_request]
        start_page = batch_images[0].page_number
        end_page = batch_images[-1].page_number
        image_paths = [p.image_path for p in batch_images]

        logger.info(f"Processing pages {start_page}-{end_page} ({len(image_paths)} images)")

        try:
            raw_output = _send_images_to_vision(image_paths, paper, start_page, client)

            if not raw_output:
                logger.warning(f"Empty response for pages {start_page}-{end_page}")
                continue

            scenes = _parse_llm_output(raw_output, all_scenes, scene_counter)
            all_scenes.extend(scenes)
            scene_counter += len(scenes)
            logger.info(f"Pages {start_page}-{end_page}: {len(scenes)} scenes generated")

        except Exception as e:
            logger.warning(f"Failed to process pages {start_page}-{end_page}: {e}")

    author_line = ", ".join(paper.metadata.authors) if paper.metadata.authors else "Unknown Authors"

    return ScriptOutput(
        title=paper.metadata.title or "Research Paper",
        author_line=author_line,
        scenes=all_scenes,
        total_duration=sum(s.duration_seconds for s in all_scenes),
    )


def _send_images_to_vision(
    image_paths: list[Path],
    paper: PaperData,
    start_page: int,
    client: LlamaCppClient,
) -> str:
    """Convert page images to base64 and send to LLM."""
    # Encode images
    image_data_list = []
    for img_path in image_paths:
        img_bytes = img_path.read_bytes()
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        mime = "image/png"
        image_data_list.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    # Build multi-turn conversation: show images, then request scenes
    prompt_text = (
        f"I'll show you pages {start_page}-{start_page + len(image_paths) - 1} "
        f"from a research paper titled '{paper.metadata.title or 'Untitled'}'. "
        f"Analyze these pages and create animation scenes for a 3Blue1Brown-style video."
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert science communicator. You analyze research paper "
                "pages (as images) and create animated video scripts in the style of "
                "3Blue1Brown — clear, visual, intuitive explanations."
            ),
        },
        # Step 1: Show the images
        {"role": "user", "content": [
            {"type": "text", "text": prompt_text},
            *image_data_list,
        ]},
        # Step 2: Ask for scene definitions
        {"role": "assistant", "content": "I've analyzed the paper pages. Now I'll create animation scenes."},
        {"role": "user", "content": [
            {
                "type": "text",
                "text": (
                    f"Based on these pages, create animation scenes. Include:\n"
                    f"- Introduction/title scene\n"
                    f"- Key concepts and equations\n"
                    f"- Diagrams and figures\n"
                    f"- Results and conclusions\n\n"
                    f"For each scene, provide: title, narration (spoken words), visual_type, "
                    f"manim_elements, transitions, and duration.\n\n"
                    f"Return ONLY a valid JSON array. Each object must have these fields:\n"
                    f"  scene_id (int), title (str), narration (str), "
                    f"visual_type (formula_animation|diagram_zoom|chart_build|slide_transition|concept_visual|intro_title),\n"
                    f"  manim_elements (array of strings), transition_from (fade_in|slide_up|transform|grow_from_center),\n"
                    f"  transition_to (fade_out|slide_down|transform|shrink_to_center),\n"
                    f"  duration_seconds (float)\n\n"
                    f"Make narration concise and engaging (~150 words/min speaking pace).\n"
                    f"Include at least 3-6 scenes total."
                ),
            }
        ]},
    ]

    return client.chat(messages, stream=True)


def _parse_llm_output(raw: str, existing_scenes: list[Scene], start_id: int) -> list[Scene]:
    """Parse LLM JSON output with recovery for truncated responses."""
    # Extract JSON from markdown code blocks
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_str = raw.strip()

    # Try direct parse first
    try:
        parsed = json.loads(json_str)
        scenes_raw = parsed.get("scenes", []) if isinstance(parsed, dict) else parsed
        return _extract_scenes(scenes_raw, start_id)
    except json.JSONDecodeError as e:
        logger.warning(f"Direct parse failed: {e}. Attempting recovery...")

    # Recovery attempts
    return _recover_json(json_str, start_id)


def _recover_json(json_str: str, start_id: int) -> list[Scene]:
    """Attempt to repair and parse truncated/corrupt JSON."""
    # Recovery 1: Close unclosed brackets
    repaired = _close_brackets(json_str)
    if repaired != json_str:
        try:
            parsed = json.loads(repaired)
            return _extract_scenes(parsed, start_id)
        except json.JSONDecodeError:
            pass

    # Recovery 2: Fix unterminated strings
    repaired = _fix_unterminated_strings(json_str)
    if repaired != json_str:
        try:
            parsed = json.loads(repaired)
            return _extract_scenes(parsed, start_id)
        except json.JSONDecodeError:
            pass

    # Recovery 3: Extract individual scene objects via regex
    return _extract_fragments(json_str, start_id)


def _extract_scenes(scenes_raw, start_id: int) -> list[Scene]:
    """Extract Scene objects from parsed JSON."""
    if isinstance(scenes_raw, dict) and "scenes" in scenes_raw:
        scenes_raw = scenes_raw["scenes"]

    scenes = []
    for i, s in enumerate(scenes_raw):
        if not isinstance(s, dict):
            continue
        scene = Scene(
            scene_id=s.get("scene_id", start_id + i + 1),
            title=s.get("title", f"Scene {start_id + i + 1}"),
            narration=s.get("narration", ""),
            visual_type=s.get("visual_type", "concept_visual"),
            manim_elements=s.get("manim_elements", []),
            transition_from=s.get("transition_from", "fade_in"),
            transition_to=s.get("transition_to", "fade_out"),
            duration_seconds=float(s.get("duration_seconds", 10.0)),
            reference_page=s.get("reference_page"),
        )
        scenes.append(scene)
    return scenes


def _extract_fragments(json_str: str, start_id: int) -> list[Scene]:
    """Extract individual scene objects from corrupted JSON text."""
    scenes = []
    pattern = r'\{\s*"scene_id"\s*:\s*(\d+).*?\}'
    for match in re.finditer(pattern, json_str, re.DOTALL):
        try:
            obj_str = match.group(0)
            obj_str = _close_brackets(obj_str)
            obj_str = _fix_unterminated_strings(obj_str)
            obj = json.loads(obj_str)
            scene = Scene(
                scene_id=obj.get("scene_id", start_id + len(scenes) + 1),
                title=obj.get("title", f"Scene {start_id + len(scenes) + 1}"),
                narration=obj.get("narration", ""),
                visual_type=obj.get("visual_type", "concept_visual"),
                manim_elements=obj.get("manim_elements", []),
                transition_from=obj.get("transition_from", "fade_in"),
                transition_to=obj.get("transition_to", "fade_out"),
                duration_seconds=float(obj.get("duration_seconds", 10.0)),
            )
            scenes.append(scene)
        except (json.JSONDecodeError, ValueError):
            continue
    return scenes


def _close_brackets(s: str) -> str:
    """Close any unclosed brackets/arrays/objects in JSON."""
    stack = []
    in_string = False
    escape_next = False

    for c in s:
        if escape_next:
            escape_next = False
            continue
        if c == '\\' and in_string:
            escape_next = True
        elif c == '"':
            in_string = not in_string
        elif not in_string:
            if c in ('{', '['):
                stack.append(c)
            elif c == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
                else:
                    s += '}'
            elif c == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
                else:
                    s += ']'

    closing = {'{': '}', '[': ']'}
    while stack:
        s += closing[stack.pop()]

    if in_string:
        last_quote = s.rfind('"')
        if last_quote > 0:
            s = s[:last_quote] + '"' + s[last_quote + 1:]

    return s


def _fix_unterminated_strings(s: str) -> str:
    """Fix unterminated string values in JSON."""
    result = []
    in_string = False
    escape_next = False

    for c in s:
        if escape_next:
            escape_next = False
            result.append(c)
            continue
        if c == '\\' and in_string:
            escape_next = True
            result.append(c)
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
        elif c == ',' and not in_string:
            result.append(c)
        else:
            result.append(c)

    final = ''.join(result)
    if in_string:
        final += '"'
    return final
