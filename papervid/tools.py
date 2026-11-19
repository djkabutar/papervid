"""Non-interactive papervid tools, driven by Claude Code (see .claude/skills/papervid).

Every subcommand prints a single JSON object to stdout; logs go to stderr.

    python -m papervid.tools doctor
    python -m papervid.tools init paper.pdf
    python -m papervid.tools status   <work_dir>
    python -m papervid.tools validate <work_dir>
    python -m papervid.tools crop     <work_dir>              # crops every figure listed in script.json
    python -m papervid.tools tts      <work_dir> [--voice en-US-AndrewNeural]
    python -m papervid.tools render   <work_dir> --scene 3 [--quality l|m|h]
    python -m papervid.tools frames   <work_dir> --scene 3 [--count 6]
    python -m papervid.tools assemble <work_dir> [--quality h]
"""

import argparse
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .parsers.models import ScriptOutput
from .utils.helpers import (
    ensure_ffmpeg_installed,
    ensure_poppler_installed,
    estimate_video_length,
    find_executable,
    format_file_size,
)

logger = logging.getLogger("papervid.tools")

VISUAL_TYPES = {
    "intro_title", "concept_visual", "formula_animation",
    "diagram_zoom", "chart_build", "slide_transition", "conclusion",
}
QUALITY_DIRS = {"l": "480p15", "m": "720p30", "h": "1080p60"}
DEFAULT_VOICE = "en-US-AndrewNeural"


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _emit(payload: dict, ok: bool = True) -> int:
    payload = {"ok": ok, **payload}
    print(json.dumps(payload, indent=2, default=str))
    return 0 if ok else 1


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return slug[:max_len].rstrip("_") or "paper"


def _work_dir(path: str) -> Path:
    wd = Path(path).expanduser().resolve()
    if not wd.is_dir():
        raise SystemExit(_emit({"error": f"work dir not found: {wd}"}, ok=False))
    return wd


def _load_script(wd: Path) -> ScriptOutput:
    path = wd / "script.json"
    if not path.exists():
        raise SystemExit(_emit({"error": f"missing {path}; write the script first"}, ok=False))
    return ScriptOutput.load(path)


def _scene_file(wd: Path, scene_id: int) -> Path:
    return wd / "scenes" / f"scene_{scene_id:02d}.py"


def _scene_audio(wd: Path, scene_id: int) -> Path:
    return wd / "audio" / f"scene_{scene_id:02d}.mp3"


def _latest_render(wd: Path, scene_id: int, quality: str) -> Path | None:
    media = wd / "renders" / quality / "videos" / f"scene_{scene_id:02d}" / QUALITY_DIRS[quality]
    videos = [p for p in media.glob("*.mp4")] if media.exists() else []
    return max(videos, key=lambda p: p.stat().st_mtime) if videos else None


def _narration_hash(scene, voice: str, rate: str, pitch: str) -> str:
    return hashlib.sha1(f"{voice}|{rate}|{pitch}|{scene.narration.strip()}".encode()).hexdigest()[:16]


def _parse_ids(spec: str, script: ScriptOutput) -> list[int]:
    all_ids = [s.scene_id for s in script.scenes]
    if spec in ("all", ""):
        return all_ids
    ids = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            ids.extend(range(int(a), int(b) + 1))
        else:
            ids.append(int(part))
    return [i for i in ids if i in all_ids]


# --------------------------------------------------------------------------- #
#  Subcommands                                                                 #
# --------------------------------------------------------------------------- #

def cmd_doctor(args) -> int:
    checks = {
        "python": sys.executable,
        "ffmpeg": ensure_ffmpeg_installed(),
        "ffprobe": shutil.which("ffprobe") is not None,
        "poppler": ensure_poppler_installed(),
        "latex": shutil.which("latex") is not None,
        "dvisvgm": shutil.which("dvisvgm") is not None,
    }
    manim = find_executable("manim")
    try:
        out = subprocess.run([manim, "--version"], capture_output=True, text=True, timeout=60)
        checks["manim"] = out.stdout.strip() or out.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        checks["manim"] = False
        checks["manim_error"] = str(e)
    for mod in ("edge_tts", "pdf2image", "pypdf", "pydub", "PIL"):
        try:
            __import__(mod)
            checks[mod] = True
        except ImportError:
            checks[mod] = False

    checks["mathtex"] = _mathtex_works() if checks["latex"] and checks["dvisvgm"] else False

    required = ["ffmpeg", "ffprobe", "poppler", "manim", "edge_tts", "pdf2image", "pypdf", "pydub", "PIL"]
    missing = [k for k in required if not checks.get(k)]
    if not checks["mathtex"]:
        checks["warning"] = (
            "MathTex cannot compile (manim needs latex, dvisvgm and the standalone/preview "
            "packages; on Arch: pacman -S texlive-latexextra). safe_math() will fall back to plain text."
        )
    return _emit({"checks": checks, "missing": missing}, ok=not missing)


def _mathtex_works() -> bool:
    """Compile a tiny MathTex in a throwaway dir to prove the LaTeX toolchain works."""
    import tempfile

    code = (
        "from manim import MathTex, config\n"
        "import sys\n"
        "config.media_dir = sys.argv[1]\n"
        "MathTex(r'\\frac{a}{b}')\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r = subprocess.run([sys.executable, "-c", code, tmp], capture_output=True, text=True, timeout=120, cwd=tmp)
        except subprocess.TimeoutExpired:
            return False
    return r.returncode == 0


def cmd_init(args) -> int:
    from .parsers.pdf_parser import parse_pdf
    from pypdf import PdfReader

    pdf = Path(args.pdf).expanduser().resolve()
    if not pdf.exists():
        return _emit({"error": f"PDF not found: {pdf}"}, ok=False)

    reader = PdfReader(str(pdf))
    meta_title = ((reader.metadata or {}).get("/Title") or "").strip()
    slug = args.slug or _slugify(pdf.stem if len(meta_title) < 4 else meta_title)
    wd = Path(args.out).expanduser().resolve() / slug
    for sub in ("pages", "figures", "scenes", "audio", "renders", "frames"):
        (wd / sub).mkdir(parents=True, exist_ok=True)

    pages = sorted((wd / "pages").glob("page_*.png"))
    if not pages or args.force:
        paper = parse_pdf(pdf, dpi=args.dpi, max_pages=args.max_pages, out_dir=wd / "pages")
        pages = [p.image_path for p in paper.pages]
        title, authors = paper.metadata.title, paper.metadata.authors
    else:
        title = meta_title
        authors = [a.strip() for a in ((reader.metadata or {}).get("/Author") or "").split(";") if a.strip()]

    meta = {
        "pdf": str(pdf),
        "title": title,
        "authors": authors,
        "total_pdf_pages": len(reader.pages),
        "rendered_pages": len(pages),
        "dpi": args.dpi,
    }
    (wd / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return _emit({"work_dir": str(wd), **meta, "pages_dir": str(wd / "pages")})


def cmd_status(args) -> int:
    wd = _work_dir(args.work_dir)
    result = {
        "work_dir": str(wd),
        "pages": len(list((wd / "pages").glob("page_*.png"))),
        "script": (wd / "script.json").exists(),
        "final": str(wd / "final.mp4") if (wd / "final.mp4").exists() else None,
        "scenes": [],
    }
    if result["script"]:
        script = ScriptOutput.load(wd / "script.json")
        for s in script.scenes:
            low, high = _latest_render(wd, s.scene_id, "l"), _latest_render(wd, s.scene_id, "h")
            scene_file = _scene_file(wd, s.scene_id)
            result["scenes"].append({
                "scene_id": s.scene_id,
                "title": s.title,
                "audio": _scene_audio(wd, s.scene_id).exists() and s.audio_duration > 0,
                "audio_duration": s.audio_duration,
                "code": scene_file.exists(),
                "render_l": bool(low and low.stat().st_mtime >= scene_file.stat().st_mtime) if scene_file.exists() else False,
                "render_h": bool(high and high.stat().st_mtime >= scene_file.stat().st_mtime) if scene_file.exists() else False,
                "review": json.loads(p.read_text()) if (p := wd / "frames" / f"scene_{s.scene_id:02d}" / "review.json").exists() else None,
            })
    return _emit(result)


def cmd_validate(args) -> int:
    wd = _work_dir(args.work_dir)
    try:
        raw = json.loads((wd / "script.json").read_text())
    except (OSError, json.JSONDecodeError) as e:
        return _emit({"error": f"script.json unreadable: {e}"}, ok=False)

    script = ScriptOutput.from_dict(raw)
    errors, warnings, outline = [], [], []
    n_pages = len(list((wd / "pages").glob("page_*.png")))

    if not script.scenes:
        errors.append("no scenes")
    ids = [s.scene_id for s in script.scenes]
    if ids != list(range(1, len(ids) + 1)):
        errors.append(f"scene_id must be 1..N in order, got {ids}")

    for s in script.scenes:
        words = len(s.narration.split())
        est = words / 2.5
        if not s.narration.strip():
            errors.append(f"scene {s.scene_id}: empty narration")
        if not s.visual_plan.strip():
            errors.append(f"scene {s.scene_id}: empty visual_plan")
        if s.visual_type not in VISUAL_TYPES:
            warnings.append(f"scene {s.scene_id}: unusual visual_type '{s.visual_type}'")
        if est > 75:
            warnings.append(f"scene {s.scene_id}: ~{est:.0f}s of narration; consider splitting")
        for fig in s.figures:
            if not {"page", "box", "name"} <= fig.keys():
                errors.append(f"scene {s.scene_id}: figure needs page, box, name: {fig}")
            elif not (1 <= int(fig["page"]) <= n_pages):
                errors.append(f"scene {s.scene_id}: figure page {fig['page']} not rendered (have {n_pages})")
            elif len(fig["box"]) != 4:
                errors.append(f"scene {s.scene_id}: figure box must be [x0, y0, x1, y1]")
        outline.append({
            "scene_id": s.scene_id, "title": s.title, "visual_type": s.visual_type,
            "words": words, "est_seconds": round(est, 1), "figures": [f.get("name") for f in s.figures],
        })

    return _emit({
        "title": script.title,
        "scenes": len(script.scenes),
        "total_words": script.total_words,
        "est_duration": estimate_video_length(script.total_words),
        "errors": errors,
        "warnings": warnings,
        "outline": outline,
    }, ok=not errors)


def cmd_crop(args) -> int:
    from PIL import Image

    wd = _work_dir(args.work_dir)
    script = _load_script(wd)
    out_dir = wd / "figures"
    out_dir.mkdir(exist_ok=True)
    written, errors = [], []

    for s in script.scenes:
        for fig in s.figures:
            try:
                page = wd / "pages" / f"page_{int(fig['page']):03d}.png"
                img = Image.open(page)
                x0, y0, x1, y1 = [float(v) for v in fig["box"]]
                # Boxes are fractions of the page (0-1); pixel boxes are also accepted
                if max(x0, y0, x1, y1) <= 1.0:
                    x0, x1 = x0 * img.width, x1 * img.width
                    y0, y1 = y0 * img.height, y1 * img.height
                box = tuple(int(round(v)) for v in (x0, y0, x1, y1))
                if box[2] <= box[0] or box[3] <= box[1]:
                    raise ValueError(f"empty box {box}")
                out = out_dir / f"{fig['name']}.png"
                img.crop(box).save(out)
                written.append({"scene_id": s.scene_id, "name": fig["name"], "path": str(out), "size": img.crop(box).size})
            except (KeyError, ValueError, OSError) as e:
                errors.append(f"scene {s.scene_id} figure {fig}: {e}")

    return _emit({"figures": written, "errors": errors}, ok=not errors)


def cmd_voices(args) -> int:
    from .voice.tts import list_voices

    voices = [v for v in list_voices() if v["locale"].startswith(args.locale)]
    return _emit({"voices": [f"{v['name']} ({v['gender']})" for v in voices]})


def cmd_tts(args) -> int:
    from .renderer.ffmpeg_ops import combine_audio_chunks, probe_duration
    from .voice.tts import generate_voice

    wd = _work_dir(args.work_dir)
    script = _load_script(wd)
    ids = _parse_ids(args.scene, script)
    chunk_dir = wd / "audio" / "_chunks"
    results = []

    for s in script.scenes:
        if s.scene_id not in ids:
            continue
        out = _scene_audio(wd, s.scene_id)
        stamp = out.with_suffix(".hash")
        digest = _narration_hash(s, args.voice, args.rate, args.pitch)
        if not args.force and out.exists() and stamp.exists() and stamp.read_text() == digest:
            s.audio_duration = round(probe_duration(out), 3)
            results.append({"scene_id": s.scene_id, "cached": True, "duration": s.audio_duration})
            continue

        # edge-tts occasionally returns an empty file; retry rather than poison the scene
        single = ScriptOutput(title=script.title, author_line=script.author_line, scenes=[s])
        good, attempts = [], 0
        while attempts < 3:
            attempts += 1
            shutil.rmtree(chunk_dir, ignore_errors=True)
            try:
                segments = generate_voice(single, chunk_dir, voice=args.voice, rate=args.rate, pitch=args.pitch)
            except Exception as e:  # network/service errors surface here
                logger.warning(f"scene {s.scene_id}: TTS attempt {attempts} raised {e}")
                segments = []
            good = [
                seg for seg in segments
                if Path(seg.audio_path).exists() and Path(seg.audio_path).stat().st_size > 0
            ]
            if len(good) == len(segments) and good:
                break
            logger.warning(f"scene {s.scene_id}: TTS attempt {attempts} produced empty audio, retrying")
            time.sleep(2 * attempts)

        if not good:
            results.append({"scene_id": s.scene_id, "error": f"TTS produced no audio after {attempts} attempts"})
            continue
        combine_audio_chunks(good, out)
        stamp.write_text(digest)
        s.audio_duration = round(probe_duration(out), 3)
        results.append({"scene_id": s.scene_id, "cached": False, "duration": s.audio_duration, "path": str(out)})

    shutil.rmtree(chunk_dir, ignore_errors=True)
    script.total_duration = round(sum(s.audio_duration for s in script.scenes), 3)
    script.save(wd / "script.json")
    failed = [r for r in results if "error" in r]
    return _emit({
        "voice": args.voice,
        "scenes": results,
        "total_audio_seconds": script.total_duration,
    }, ok=not failed)


def cmd_render(args) -> int:
    from .renderer.ffmpeg_ops import probe_duration, run_manim

    wd = _work_dir(args.work_dir)
    script = _load_script(wd)
    ids = _parse_ids(args.scene, script)
    by_id = {s.scene_id: s for s in script.scenes}
    results = []

    for sid in ids:
        scene_file = _scene_file(wd, sid)
        if not scene_file.exists():
            results.append({"scene_id": sid, "ok": False, "error": f"missing {scene_file}"})
            continue
        r = run_manim(scene_file, wd / "renders" / args.quality, quality=args.quality, timeout=args.timeout)
        entry = {"scene_id": sid, **r}
        if r["ok"]:
            dur = probe_duration(Path(r["video"]))
            target = by_id[sid].audio_duration
            entry["duration"] = round(dur, 2)
            entry["audio_duration"] = target
            if target and dur + 0.05 < target:
                entry["warning"] = f"video {dur:.1f}s shorter than narration {target:.1f}s (assemble will freeze last frame)"
        results.append(entry)

    return _emit({"quality": args.quality, "results": results}, ok=all(r["ok"] for r in results))


def cmd_frames(args) -> int:
    from .renderer.ffmpeg_ops import extract_frames_evenly

    wd = _work_dir(args.work_dir)
    video = Path(args.video) if args.video else _latest_render(wd, args.scene, args.quality)
    if not video or not video.exists():
        return _emit({"error": f"no {args.quality} render for scene {args.scene}; run render first"}, ok=False)
    out_dir = wd / "frames" / f"scene_{args.scene:02d}"
    frames = extract_frames_evenly(video, out_dir, count=args.count)
    return _emit({"video": str(video), "frames": [str(f) for f in frames]}, ok=bool(frames))


def cmd_assemble(args) -> int:
    from .renderer.ffmpeg_ops import merge_scenes, overlay_audio, probe_duration

    wd = _work_dir(args.work_dir)
    script = _load_script(wd)
    clips_dir = wd / "renders" / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clips, missing = [], []

    for s in script.scenes:
        video = _latest_render(wd, s.scene_id, args.quality)
        if video is None and args.allow_lower:
            video = next((v for q in ("m", "l") if (v := _latest_render(wd, s.scene_id, q))), None)
        if video is None:
            missing.append(s.scene_id)
            continue
        audio = _scene_audio(wd, s.scene_id)
        clip = clips_dir / f"scene_{s.scene_id:02d}.mp4"
        overlay_audio(video, audio if audio.exists() else None, clip)
        clips.append(clip)

    if missing:
        return _emit({"error": f"scenes without a '{args.quality}' render: {missing}"}, ok=False)

    final = wd / args.output
    merge_scenes(clips, final)
    return _emit({
        "final": str(final),
        "duration": round(probe_duration(final), 2),
        "size": format_file_size(final),
        "scenes": len(clips),
    })


# --------------------------------------------------------------------------- #
#  Entry                                                                       #
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m papervid.tools", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check environment").set_defaults(func=cmd_doctor)

    sp = sub.add_parser("init", help="create work dir and render PDF pages")
    sp.add_argument("pdf")
    sp.add_argument("--out", default="papervid_output")
    sp.add_argument("--slug")
    sp.add_argument("--dpi", type=int, default=150)
    sp.add_argument("--max-pages", type=int, default=40)
    sp.add_argument("--force", action="store_true", help="re-render pages")
    sp.set_defaults(func=cmd_init)

    for name, func, help_ in (
        ("status", cmd_status, "per-scene progress (for resuming)"),
        ("validate", cmd_validate, "check script.json and print outline"),
        ("crop", cmd_crop, "crop all figures listed in script.json"),
    ):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("work_dir")
        sp.set_defaults(func=func)

    sp = sub.add_parser("voices", help="list edge-tts voices")
    sp.add_argument("--locale", default="en-")
    sp.set_defaults(func=cmd_voices)

    sp = sub.add_parser("tts", help="synthesize narration per scene")
    sp.add_argument("work_dir")
    sp.add_argument("--scene", default="all", help="all | 3 | 1,4 | 2-5")
    sp.add_argument("--voice", default=DEFAULT_VOICE)
    sp.add_argument("--rate", default="+0%")
    sp.add_argument("--pitch", default="+0Hz")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_tts)

    sp = sub.add_parser("render", help="render scene file(s) with manim")
    sp.add_argument("work_dir")
    sp.add_argument("--scene", default="all", help="all | 3 | 1,4 | 2-5")
    sp.add_argument("--quality", choices=list(QUALITY_DIRS), default="l")
    sp.add_argument("--timeout", type=int, default=900)
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("frames", help="extract evenly spaced frames for review")
    sp.add_argument("work_dir")
    sp.add_argument("--scene", type=int, required=True)
    sp.add_argument("--count", type=int, default=6)
    sp.add_argument("--quality", choices=list(QUALITY_DIRS), default="l")
    sp.add_argument("--video", help="explicit video path instead of latest render")
    sp.set_defaults(func=cmd_frames)

    sp = sub.add_parser("assemble", help="mux audio per scene and concatenate")
    sp.add_argument("work_dir")
    sp.add_argument("--quality", choices=list(QUALITY_DIRS), default="h")
    sp.add_argument("--allow-lower", action="store_true", help="fall back to lower-quality renders")
    sp.add_argument("--output", default="final.mp4")
    sp.set_defaults(func=cmd_assemble)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
