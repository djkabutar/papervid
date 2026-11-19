"""Interactive CLI for papervid — Research Paper to Animated Video."""

import json
import logging
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from papervid.config import Config, create_default_config
from papervid.parsers.pdf_parser import parse_pdf
from papervid.parsers.models import PaperData, ScriptOutput
from papervid.generators.llm_client import LlamaCppClient
from papervid.generators.script_gen import generate_script
from papervid.builder.scene_builder import build_scene_file
from papervid.voice.tts import generate_voice, list_voices
from papervid.renderer.video_render import render_video
from papervid.utils.helpers import (
    setup_logging,
    ensure_poppler_installed,
    ensure_ffmpeg_installed,
    estimate_video_length,
    format_file_size,
)

logger = logging.getLogger(__name__)
console = Console()


def main():
    """Main entry point for the papervid CLI."""
    setup_logging("INFO")
    config = create_default_config()

    console.print(Panel.fit(
        "[bold gold1]papervid[/bold gold1] — Research Paper → Animated Video\n"
        "[dim]Powered by Manim, Ollama, and edge-tts[/dim]",
        border_style="gold1",
    ))
    console.print("")

    # --- Step 0: Check dependencies ---
    if not ensure_ffmpeg_installed():
        console.print("[bold red]Error:[/bold red] ffmpeg is not installed.")
        console.print("Install it with: [cyan]sudo apt install ffmpeg[/cyan]")
        sys.exit(1)

    if not ensure_poppler_installed():
        console.print("[bold yellow]Warning:[/bold yellow] poppler-utils not found.")
        console.print("PDF-to-image conversion may fail. Install with: [cyan]sudo apt install poppler-utils[/cyan]")

    # --- Step 1: Get PDF file ---
    console.print("\n[dim]─[/dim]" * 60)
    pdf_path = _ask_for_pdf()
    config.pdf_path = pdf_path

    if not pdf_path.exists():
        console.print(f"[bold red]File not found:[/bold red] {pdf_path}")
        sys.exit(1)

    # --- Step 2: Parse PDF (render pages as images) ---
    console.print("\n[dim]─[/dim]" * 60)
    paper_data = _parse_pdf_step(pdf_path, config)
    config.paper_data = paper_data

    # --- Step 3: Check llama.cpp ---
    console.print("\n[dim]─[/dim]" * 60)
    client = _setup_llama_cpp(config)
    if client is None:
        console.print("\n[dim]llama.cpp check skipped. Script generation will be simulated.[/dim]")

    # --- Step 4: Generate script (vision LLM analyzes PDF images) ---
    console.print("\n[dim]─[/dim]" * 60)
    script = _generate_script_step(paper_data, client)
    config.script = script

    # --- Step 5: Preview script ---
    _preview_script(script)

    # --- Step 6: Voice selection ---
    voice_config = _select_voice()
    config.tts_voice = voice_config["voice"]
    config.tts_rate = voice_config["rate"]
    config.tts_pitch = voice_config["pitch"]
    config.generate_tts = voice_config["generate_tts"]

    # --- Step 8: Build Manim scene ---
    console.print("\n[dim]─[/dim]" * 60)
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scene_file = build_scene_file(script, output_dir / "scenes")
    config.scene_file = scene_file

    # --- Step 9: Preview or render ---
    console.print("\n[dim]─[/dim]" * 60)

    action = Prompt.ask(
        "  [bold]What would you like to do?[/bold]",
        choices=["preview", "render", "both"],
        default="both",
    )

    if action in ("preview", "both"):
        console.print("\n[i]Previewing scene code...[/i]")
        _show_scene_code(scene_file)

    if action in ("render", "both"):
        # --- Step 10: Generate voice ---
        voice_segments = []
        if config.generate_tts:
            voice_segments = _generate_voice_step(script, output_dir, config)
            config.voice_segments = voice_segments

        # --- Step 11: Render video ---
        final_video = _render_video_step(scene_file, voice_segments, script, output_dir, config, client)
        config.output_video = final_video

        # --- Done! ---
        console.print("\n")
        console.print(Panel.fit(
            f"[bold green]✓[/bold green] Video ready!\n\n"
            f"  [dim]Location:[/dim] [cyan]{final_video}[/cyan]\n"
            f"  [dim]Size:[/dim] {format_file_size(final_video)}\n"
            f"  [dim]Duration:[/dim] {estimate_video_length(script.total_words)}\n"
            f"  [dim]Scenes:[/dim] {len(script.scenes)}",
            border_style="green",
        ))

        open_video = Prompt.ask("  Open video?", choices=["y", "n"], default="y")
        if open_video == "y":
            _open_video(final_video)

    console.print("\n[dim]Done![/dim]\n")


def _ask_for_pdf() -> Path:
    """Prompt user to select a PDF file."""
    console.print("\n[bold gold1]Step 1/7: Select PDF[/bold gold1]")

    # Check for command line argument
    if len(sys.argv) > 1:
        pdf = Path(sys.argv[1])
        if pdf.exists():
            console.print(f"  Using PDF from command line: [cyan]{pdf}[/cyan]")
            return pdf

    console.print("  Drag & drop your PDF file here, or paste the path:")
    console.print("  [dim]Example: ~/Downloads/research_paper.pdf[/dim]")

    pdf_input = Prompt.ask("  [bold]PDF path[/bold]")
    return Path(pdf_input).expanduser().resolve()


def _parse_pdf_step(pdf_path: Path, config: Config) -> PaperData:
    """Parse the PDF and render pages as images for vision LLM."""
    console.print("\n[bold gold1]Step 2/7: Rendering PDF Pages[/bold gold1]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Rendering PDF pages as images...", total=None)

        try:
            paper_data = parse_pdf(
                pdf_path,
                dpi=config.pdf_dpi,
                max_pages=config.max_pages,
            )
        except Exception as e:
            console.print(f"[bold red]Error rendering PDF:[/bold red] {e}")
            raise

        progress.update(task, description="[green]PDF rendered successfully![/green]")

    # Show summary (images only, no text extraction)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("Title", paper_data.metadata.title or "N/A")
    table.add_row("Authors", ", ".join(paper_data.metadata.authors) or "N/A")
    table.add_row("Pages Rendered", str(len(paper_data.pages)))
    console.print(Panel(table, title="Paper Summary", border_style="cyan"))

    return paper_data


def _setup_llama_cpp(config: Config) -> LlamaCppClient | None:
    """Set up and verify llama.cpp connection."""
    console.print("\n[bold gold1]Step 3/7: llama.cpp Connection[/bold gold1]")

    # Allow custom base URL
    base_url = Prompt.ask(
        "  [dim]llama.cpp server URL[/dim]",
        default=config.llama_cpp_url,
    )

    model_name = Prompt.ask(
        "  [dim]Model name (must support vision/images)[/dim]",
        default=config.llama_cpp_model,
    )

    client = LlamaCppClient(base_url=base_url, model=model_name)

    if client.check_available():
        console.print(f"\n  [green]✓[/green] Connected to llama.cpp at [cyan]{base_url}[/cyan]")
        console.print(f"  [green]✓[/green] Using model: [cyan]{model_name}[/cyan]")
        console.print(f"\n  [dim]Server running with: llama.cpp -m {model_name} -c 8192 --port 8080[/dim]")
        return client
    else:
        console.print(f"\n  [yellow]Cannot reach llama.cpp server at[/yellow] [cyan]{base_url}[/cyan]")
        console.print("  Options:")
        console.print("    1. Start llama.cpp server: [cyan]llama.cpp/server -m MODEL -c 8192 --port 8080[/cyan]")
        console.print("    2. Continue without LLM (will use mock data)")
        choice = Prompt.ask("  Choose", choices=["1", "2"], default="1")
        if choice == "2":
            return None
        return client


def _generate_script_step(
    paper_data: PaperData,
    client: LlamaCppClient | None,
) -> ScriptOutput:
    """Generate the animation script from PDF page images."""
    console.print("\n[bold gold1]Step 4/7: Generating Animation Script[/bold gold1]")

    if client is None:
        console.print("\n  [yellow]⚠ Generating MOCK script (llama.cpp not available)[/yellow]")
        return _generate_mock_script(paper_data)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Vision LLM analyzing PDF images...",
            total=None,
        )

        try:
            script = generate_script(
                paper_data,
                client,
            )
        except Exception as e:
            console.print(f"\n[bold red]Error generating script:[/bold red] {e}")
            console.print("[dim]Falling back to mock script.[/dim]")
            script = _generate_mock_script(paper_data)

        progress.update(task, description="[green]Script generated![/green]")

    # Show stats
    console.print(f"\n  [dim]Scenes:[/dim] {len(script.scenes)}")
    console.print(f"  [dim]Total narration:[/dim] {script.total_words} words")
    console.print(f"  [dim]Estimated duration:[/dim] {estimate_video_length(script.total_words)}")

    return script


def _generate_mock_script(paper_data: PaperData) -> ScriptOutput:
    """Generate a mock script when LLM is unavailable."""
    scenes = []
    scene_id = 0

    # Intro scene
    scene_id += 1
    scenes.append({
        "scene_id": scene_id,
        "title": paper_data.metadata.title or "Research Paper",
        "narration": f"Welcome to our presentation on {paper_data.metadata.title or 'this research paper'} by {paper_data.metadata.authors[0] if paper_data.metadata.authors else 'the authors'}.",
        "visual_type": "intro_title",
        "manim_elements": ["Text(title)"],
        "transition_from": "fade_in",
        "transition_to": "fade_out",
        "duration_seconds": 8.0,
    })

    # Page scenes
    for i, page in enumerate(paper_data.pages[:5]):
        scene_id += 1
        scenes.append({
            "scene_id": scene_id,
            "title": f"Page {page.page_number} Analysis",
            "narration": f"This is a placeholder narration for page {page.page_number}. The vision model would analyze the diagrams and formulas here.",
            "visual_type": "diagram_zoom",
            "manim_elements": [f"ImageMobject('page_{page.page_number}')"],
            "transition_from": "slide_up",
            "transition_to": "fade_out",
            "duration_seconds": 10.0,
            "reference_page": page.page_number,
        })

    from papervid.parsers.models import Scene as SceneModel
    from papervid.parsers.models import ScriptOutput as ScriptOutputModel

    parsed_scenes = [
        SceneModel(
            scene_id=s["scene_id"],
            title=s["title"],
            narration=s["narration"],
            visual_type=s["visual_type"],
            manim_elements=s["manim_elements"],
            transition_from=s["transition_from"],
            transition_to=s["transition_to"],
            duration_seconds=s["duration_seconds"],
            reference_page=s.get("reference_page"),
        )
        for s in scenes
    ]

    return ScriptOutputModel(
        title=paper_data.metadata.title or "Research Paper",
        author_line=", ".join(paper_data.metadata.authors) or "Unknown",
        scenes=parsed_scenes,
        total_duration=sum(s.duration_seconds for s in parsed_scenes),
    )


def _preview_script(script: ScriptOutput) -> None:
    """Show the generated script to the user."""
    console.print("\n[bold gold1]Step 5/7: Review Script[/bold gold1]")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", width=3)
    table.add_column("Title", width=35)
    table.add_column("Type", width=20)
    table.add_column("Duration", width=10)
    table.add_column("Words", width=8)

    for s in script.scenes:
        table.add_row(
            str(s.scene_id),
            s.title[:35],
            s.visual_type.replace("_", " "),
            f"{s.duration_seconds:.0f}s",
            str(len(s.narration.split())),
        )

    console.print(Panel(table, title=f"Script ({len(script.scenes)} scenes, {estimate_video_length(script.total_words)})"))

    action = Prompt.ask(
        "  What would you like to do?",
        choices=["continue", "view_details", "regenerate"],
        default="continue",
    )

    if action == "view_details":
        for s in script.scenes:
            console.print(Panel(
                f"[bold]{s.title}[/bold]\n"
                f"Type: {s.visual_type}\n"
                f"Duration: {s.duration_seconds:.1f}s\n"
                f"[dim]{s.narration[:200]}...[/dim]",
                border_style="cyan",
            ))

    elif action == "regenerate":
        console.print("\n[dim]Regenerating script...[/dim]")
        # This would loop back to step 5 in a full implementation


def _select_voice() -> dict:
    """Let user select TTS voice and options."""
    console.print("\n[bold gold1]Step 6/7: Voice Settings[/bold gold1]")

    use_tts = Prompt.ask("  Enable voice narration?", choices=["y", "n"], default="y")

    if use_tts.lower() != "y":
        return {"voice": "", "rate": "+0%", "pitch": "+0Hz", "generate_tts": False}

    voices = list_voices()
    if not voices:
        console.print("  [yellow]Could not fetch voice list. Using default.[/yellow]")
        return {"voice": "en-US-AriaNeural", "rate": "+0%", "pitch": "+0Hz", "generate_tts": True}

    # Show English voices
    english_voices = [v for v in voices if v["locale"].startswith("en-")]
    if english_voices:
        voice_list = english_voices[:15]  # Limit display
    else:
        voice_list = voices[:15]

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", width=3)
    table.add_column("Voice Name", width=35)
    table.add_column("Gender", width=8)
    table.add_column("Locale", width=12)

    for i, v in enumerate(voice_list):
        table.add_row(str(i + 1), v["name"], v["gender"], v["locale"])

    console.print(Panel(table, title="Available Voices"))

    voice_choice = Prompt.ask(
        "  Select voice number",
        default="1",
    )

    idx = int(voice_choice) - 1
    selected_voice = voice_list[idx] if 0 <= idx < len(voice_list) else voice_list[0]

    rate = Prompt.ask("  Speech rate", default="+0%")
    pitch = Prompt.ask("  Pitch", default="+0Hz")

    return {
        "voice": selected_voice["name"],
        "rate": rate,
        "pitch": pitch,
        "generate_tts": True,
    }


def _generate_voice_step(script: ScriptOutput, output_dir: Path, config: Config) -> list:
    """Run TTS generation with the voice settings chosen in _select_voice."""
    console.print("\n[dim]Synthesizing voice narration...[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Generating audio...", total=None)
        segments = generate_voice(
            script,
            output_dir / "audio",
            voice=config.tts_voice,
            rate=config.tts_rate,
            pitch=config.tts_pitch,
        )
        progress.update(task, description="[green]Voice generated![/green]")

    return segments


def _render_video_step(
    scene_file: Path,
    voice_segments: list,
    script: ScriptOutput,
    output_dir: Path,
    config: Config,
    client: LlamaCppClient | None = None,
) -> Path:
    """Run the video rendering pipeline."""
    console.print("\n[dim]Rendering final video...[/dim]")

    # Ask if user wants frame verification
    do_verify = Prompt.ask(
        "  Enable vision LLM frame verification?",
        choices=["y", "n"],
        default="n",
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Rendering...", total=None)
        video = render_video(
            scene_file=scene_file,
            voice_segments=voice_segments,
            script=script,
            output_dir=output_dir / "video",
            resolution=config.video_resolution,
            frame_rate=config.frame_rate,
            preview=config.preview_video,
            llm_client=client if do_verify.lower() == "y" else None,
        )
        progress.update(task, description="[green]Video complete![/green]")

    return video


def _show_scene_code(scene_file: Path) -> None:
    """Display the generated scene code."""
    code = scene_file.read_text()
    # Show first 60 lines
    lines = code.split("\n")
    preview = "\n".join(lines[:60])
    if len(lines) > 60:
        preview += "\n... (truncated, full code saved to " + str(scene_file) + ")"

    console.print(Panel(
        Text(preview, style="dim"),
        title=f"Scene Code ({len(lines)} lines) — {scene_file}",
        border_style="cyan",
        expand=False,
    ))


def _open_video(video_path: Path) -> None:
    """Open video in default player."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(video_path)])
        elif sys.platform == "win32":
            subprocess.run(["start", str(video_path)], shell=True)
        else:
            subprocess.run(["xdg-open", str(video_path)])
    except Exception as e:
        console.print(f"[yellow]Could not open video: {e}[/yellow]")
        console.print(f"  Manually play: [cyan]mpv {video_path}[/cyan]")


if __name__ == "__main__":
    main()
