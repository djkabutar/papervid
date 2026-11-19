"""Voice generation using edge-tts (Microsoft Edge TTS)."""

import asyncio
import logging
from pathlib import Path

import edge_tts

from ..parsers.models import ScriptOutput, VoiceSegment

logger = logging.getLogger(__name__)

# Maximum duration per TTS chunk (seconds) to keep quality high
MAX_TTS_DURATION = 55


def list_voices() -> list[dict]:
    """List available edge-tts voices.

    Returns:
        List of dicts with 'name', 'gender', 'locale'.
    """
    try:
        result = asyncio.run(edge_tts.list_voices())
        voices = []
        for v in result:
            voices.append({
                "name": v["ShortName"],
                "gender": v.get("Gender", "Unknown"),
                "locale": v["Locale"],
                "friendly": f"{v['ShortName']} ({v.get('Gender', '?')}) [{v['Locale']}]",
            })
        # Sort by locale then name
        voices.sort(key=lambda x: (x["locale"], x["name"]))
        return voices
    except Exception as e:
        logger.error(f"Failed to list voices: {e}")
        return []


def generate_voice(
    script: ScriptOutput,
    output_dir: Path,
    voice: str = "en-US-AriaNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> list[VoiceSegment]:
    """Generate TTS audio and subtitles for all scenes.

    Args:
        script: The full animation script.
        output_dir: Directory to save audio/subtitle files.
        voice: edge-tts voice name.
        rate: Speech rate (+0%, -10%, etc.).
        pitch: Speech pitch (+0Hz, -10Hz, etc.).

    Returns:
        List of VoiceSegment objects.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    segments = []
    current_time = 0.0

    for scene in script.scenes:
        narration = scene.narration.strip()
        if not narration:
            continue

        # Split narration into chunks if too long
        chunks = _split_narration(narration)

        for chunk_idx, chunk in enumerate(chunks):
            audio_path = output_dir / f"scene_{scene.scene_id:03d}_chunk_{chunk_idx:02d}.mp3"
            subtitle_path = output_dir / f"scene_{scene.scene_id:03d}_chunk_{chunk_idx:02d}.srt"

            try:
                _run_tts(
                    text=chunk,
                    audio_path=audio_path,
                    subtitle_path=subtitle_path,
                    voice=voice,
                    rate=rate,
                    pitch=pitch,
                )

                duration = _get_audio_duration(audio_path)
                segments.append(VoiceSegment(
                    scene_id=scene.scene_id,
                    audio_path=audio_path,
                    subtitle_path=subtitle_path,
                    start_time=current_time,
                    duration=duration,
                ))
                current_time += duration + 0.2  # 0.2s gap between chunks

            except Exception as e:
                logger.error(f"TTS failed for scene {scene.scene_id}, chunk {chunk_idx}: {e}")
                # Create a silent segment placeholder
                segments.append(VoiceSegment(
                    scene_id=scene.scene_id,
                    audio_path=audio_path,
                    subtitle_path=subtitle_path,
                    start_time=current_time,
                    duration=max(scene.duration_seconds / len(chunks), 2.0),
                ))
                current_time += max(scene.duration_seconds / len(chunks), 2.0) + 0.2

    logger.info(f"Generated {len(segments)} voice segments, total ~{current_time:.0f}s")
    return segments


def _split_narration(text: str) -> list[str]:
    """Split narration into chunks that fit within MAX_TTS_DURATION.

    Splits on sentence boundaries when possible.
    """
    words = text.split()
    words_per_chunk = int(MAX_TTS_DURATION * 2.5)  # ~2.5 words per second

    if len(words) <= words_per_chunk:
        return [text]

    chunks = []
    for i in range(0, len(words), words_per_chunk):
        chunk = " ".join(words[i:i + words_per_chunk])
        chunks.append(chunk)

    return chunks


def _write_srt(text: str, subtitle_path: Path) -> None:
    """Write a simple SRT subtitle file based on timing estimates.

    Splits text into chunks and assigns time ranges.
    """
    words = text.split()
    words_per_second = 3.0  # conservative estimate
    chunk_duration = len(words) / words_per_second

    start = 0.0
    lines = ["1", "00:00:00,000 --> 00:00:00,000", text, "", ""]

    def fmt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = ["1", f"{fmt_time(0.0)} --> {fmt_time(chunk_duration)}", text, ""]
    subtitle_path.write_text("\n".join(lines))


async def _tts_worker(
    text: str,
    audio_path: Path,
    subtitle_path: Path,
    voice: str,
    rate: str,
    pitch: str,
) -> None:
    """Async worker for edge-tts generation."""
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
    )
    await communicate.save(audio_path)

    # Generate SRT subtitles manually (close_subtitles removed in newer edge-tts)
    _write_srt(text, subtitle_path)


def _run_tts(
    text: str,
    audio_path: Path,
    subtitle_path: Path,
    voice: str,
    rate: str,
    pitch: str,
) -> None:
    """Run the TTS worker synchronously."""
    asyncio.run(_tts_worker(text, audio_path, subtitle_path, voice, rate, pitch))


def _get_audio_duration(path: Path) -> float:
    """Get duration of an audio file in seconds."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(path))
        return len(audio) / 1000.0  # pydub returns milliseconds
    except Exception:
        # Fallback estimate: ~2.5 words per second average
        return 4.0
