"""Command line entry point for soulclip."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from soulclip import __version__
from soulclip.ffmpeg import FFmpegError, ffmpeg_path
from soulclip.pipeline import Pipeline
from soulclip.providers import AuthError, PROVIDERS, ProviderError, get_provider
from soulclip.script_parser import ScriptError, load_script, parse_script, summarize

BANNER = r"""
  soulclip — script in, film out
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="soulclip",
        description="Turn a scene-by-scene script into one long video.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # See how a script will be cut up, without generating anything
  soulclip render script.txt --dry-run

  # Offline demo: renders placeholder clips and stitches them
  soulclip render script.txt --provider mock -o demo.mp4

  # Real render on Replicate, padded out to 5 minutes
  export REPLICATE_API_TOKEN=r8_...
  soulclip render script.txt --provider replicate --target 300 -o film.mp4

  # Three clips in flight at once, with crossfades
  soulclip render script.txt --provider fal --concurrency 3 --crossfade 0.5
""",
    )
    p.add_argument("--version", action="version", version=f"soulclip {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("render", help="generate clips and stitch the final video")
    r.add_argument("script", help="path to the script or story file, or - "
                                  "for stdin")
    r.add_argument("--story", action="store_true",
                   help="treat the input as plain prose and build the scene "
                        "breakdown automatically, carrying character "
                        "descriptions into every shot")
    r.add_argument("--storyboard", choices=["rules", "llm"], default="rules",
                   help="how to break a --story into shots: rules (offline, "
                        "instant) or llm (local Ollama, better pacing)")
    r.add_argument("--storyboard-model", default="llama3.2",
                   help="Ollama model for --storyboard llm")
    r.add_argument("-o", "--output", default="output/final.mp4",
                   help="final video path (default: output/final.mp4)")
    r.add_argument("--provider", default="mock",
                   choices=sorted(list(PROVIDERS) + ["wan", "ltx"]),
                   help="video generation backend (default: mock)")
    r.add_argument("--model", help="model id to use with the provider")

    r.add_argument("--clip-seconds", type=int, default=10,
                   help="length of each generated clip (default: 10)")
    r.add_argument("--target", type=int, metavar="SECONDS",
                   help="pad/split scenes until the film is at least this long, "
                        "e.g. 300 for 5 minutes")
    r.add_argument("--max-scenes", type=int,
                   help="hard cap on clip count, to limit spend")
    r.add_argument("--scenes", metavar="A-B",
                   help="only generate scenes A to B, e.g. 1-30. Lets two "
                        "machines split one film into the same workdir; the "
                        "last one to finish stitches everything.")

    r.add_argument("--workdir", help="where clips and job.json live "
                                     "(default: alongside the output)")
    r.add_argument("--concurrency", type=int, default=1,
                   help="clips to generate in parallel (default: 1)")
    r.add_argument("--retries", type=int, default=2,
                   help="retries per clip before giving up (default: 2)")

    r.add_argument("--width", type=int, default=1280)
    r.add_argument("--height", type=int, default=720)
    r.add_argument("--fps", type=int, default=24)
    r.add_argument("--crossfade", type=float, default=0.0, metavar="SECONDS",
                   help="cross-dissolve between clips, e.g. 0.5")
    r.add_argument("--music", help="audio track to lay over the finished cut")
    r.add_argument("--narrate", action="store_true",
                   help="speak each scene with Kokoro TTS, timed to its clip")
    r.add_argument("--voice", default="af_heart",
                   help="Kokoro voice for --narrate (default af_heart)")
    r.add_argument("--ambience", metavar="FILE",
                   help="looping background bed (rain, sea, room tone)")
    r.add_argument("--music-level", type=float, default=0.18,
                   help="music gain, 0-1 (default 0.18)")
    r.add_argument("--duck", type=float, default=0.35,
                   help="how far music drops under narration (default 0.35)")
    # Look controls for the free still-motion providers
    r.add_argument("--motion", type=float, default=0.12, metavar="AMOUNT",
                   help="camera travel per shot for image-based providers, "
                        "e.g. 0.18 for a stronger push (default: 0.12)")
    r.add_argument("--grain", type=float, default=8.0,
                   help="film grain strength, 0 to disable (default: 8)")
    r.add_argument("--letterbox", type=float, default=0.0, metavar="FRAC",
                   help="cinematic black bars, e.g. 0.12 for a scope look")
    r.add_argument("--grade", choices=["neutral", "warm", "cool"],
                   default="neutral", help="colour grade")
    r.add_argument("--style", help="style text appended to every image prompt "
                                   "(anime, noir, watercolour, ...)")
    # Wan (local GPU video model, e.g. on Colab)
    r.add_argument("--fast", action="store_true",
                   help="load the CausVid step-distilled LoRA: 4 steps and no "
                        "classifier-free guidance, ~10x faster than the "
                        "20-step default. Best speed/quality tradeoff.")
    r.add_argument("--wan-steps", type=int, metavar="N",
                   help="denoising steps for --provider wan "
                        "(default 20, or 4 with --fast)")
    r.add_argument("--wan-frames", type=int, metavar="N",
                   help="frames per clip for wan; snapped to 4k+1 "
                        "(33=2s, 49=3s, 65=4s, 81=5s at 16fps)")
    r.add_argument("--wan-guidance", type=float, metavar="N",
                   help="guidance scale for wan (default 5.0, or 1.0 with "
                        "--fast; >1 doubles the cost per step)")
    r.add_argument("--lora-strength", type=float, metavar="N",
                   help="strength of the --fast LoRA (default 0.8)")

    r.add_argument("--ltx-frames", type=int, metavar="N",
                   help="frames per clip for --provider ltx; snapped to 8k+1 "
                        "(121 = 5s at 24fps)")
    r.add_argument("--ltx-steps", type=int, metavar="N",
                   help="denoising steps for ltx (default 8 for distilled)")

    r.add_argument("--images-per-clip", type=int, default=1, metavar="N",
                   help="stills per clip; 2-3 dissolves between them for "
                        "more movement inside a shot")

    r.add_argument("--fast-concat", action="store_true",
                   help="stream-copy instead of re-encoding (only safe when "
                        "every clip already matches)")

    r.add_argument("--dry-run", action="store_true",
                   help="show the scene breakdown and exit")
    r.add_argument("--no-stitch", action="store_true",
                   help="generate the clips but skip the final join")
    r.add_argument("--allow-partial", action="store_true",
                   help="stitch whatever succeeded even if some clips failed")
    r.add_argument("-q", "--quiet", action="store_true")

    s = sub.add_parser("scenes", help="preview how a script splits into clips")
    s.add_argument("script")
    s.add_argument("--clip-seconds", type=int, default=10)
    s.add_argument("--target", type=int)
    s.add_argument("--max-scenes", type=int)

    sub.add_parser("doctor", help="check ffmpeg and provider credentials")
    return p


def _read_script(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    if not Path(path).exists():
        raise SystemExit(f"Script not found: {path}")
    return load_script(path)


def cmd_scenes(args) -> int:
    scenes = parse_script(
        _read_script(args.script),
        clip_seconds=args.clip_seconds,
        target_seconds=args.target,
        max_scenes=args.max_scenes,
    )
    print(f"\n{summarize(scenes)}\n")
    for scene in scenes:
        text = scene.text if len(scene.text) <= 88 else scene.text[:85] + "..."
        print(f"  {scene.index:>3}. [{scene.duration:>2}s] {scene.label:<24} {text}")
    print()
    return 0


def cmd_doctor(args) -> int:
    import os

    print(BANNER)
    try:
        print(f"  ffmpeg   : {ffmpeg_path()}")
    except FFmpegError as exc:
        print(f"  ffmpeg   : NOT FOUND\n             {exc}")

    from soulclip.ffmpeg import ffprobe_path
    print(f"  ffprobe  : {ffprobe_path() or 'not found (durations estimated)'}")

    print("\n  credentials:")
    checks = {
        "replicate": ("REPLICATE_API_TOKEN", "REPLICATE_API_KEY"),
        "fal": ("FAL_KEY", "FAL_API_KEY"),
        "xai": ("XAI_API_KEY",),
        "command": ("SOULCLIP_COMMAND",),
    }
    for provider, names in checks.items():
        found = next((n for n in names if os.environ.get(n)), None)
        mark = "ok " if found else "-  "
        detail = f"{found} is set" if found else f"set {' or '.join(names)}"
        print(f"    [{mark}] {provider:<10} {detail}")
    print("    [ok ] mock       always available (no key needed)")
    print()
    return 0


def cmd_render(args) -> int:
    output = Path(args.output).expanduser()
    workdir = Path(args.workdir).expanduser() if args.workdir else \
        output.parent / f".{output.stem}_work"

    raw_text = _read_script(args.script)

    if args.story:
        from soulclip.storyboard import StoryboardError, build as build_board

        try:
            board = build_board(
                raw_text,
                backend=args.storyboard,
                clip_seconds=args.clip_seconds,
                target_seconds=args.target,
                scenes=args.max_scenes,
                style=args.style or "",
                model=args.storyboard_model,
            )
        except StoryboardError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        raw_text = board.to_script()
        if not args.quiet:
            names = ", ".join(
                f"{c.name} ({c.description})" if c.description else c.name
                for c in board.characters.values()
            )
            print(f"  story    : {len(board.scenes)} scenes from prose")
            if names:
                print(f"  cast     : {names}")

    try:
        scenes = parse_script(
            raw_text,
            clip_seconds=args.clip_seconds,
            target_seconds=args.target,
            max_scenes=args.max_scenes,
        )
    except ScriptError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(BANNER)
        print(f"  script   : {args.script}")
        print(f"  provider : {args.provider}"
              + (f" ({args.model})" if args.model else ""))
        print(f"  plan     : {summarize(scenes)}")
        print(f"  output   : {output}")
        print(f"  workdir  : {workdir}\n")

    if args.scenes:
        try:
            lo_s, _, hi_s = args.scenes.partition("-")
            lo, hi = int(lo_s), int(hi_s or lo_s)
        except ValueError:
            print(f"error: --scenes wants a range like 1-30, got {args.scenes!r}",
                  file=sys.stderr)
            return 2
        subset = [s for s in scenes if lo <= s.index <= hi]
        if not subset:
            print(f"error: no scenes in range {lo}-{hi} (have 1-{len(scenes)})",
                  file=sys.stderr)
            return 2
        if not args.quiet:
            print(f"  range    : scenes {lo}-{hi} ({len(subset)} of "
                  f"{len(scenes)} clips)\n")
        scenes = subset
        # Other workers still owe the remaining clips, so do not stitch a
        # partial film unless the user explicitly asks for one.
        if not args.allow_partial:
            args.no_stitch = True

    if args.dry_run:
        for scene in scenes:
            text = scene.text if len(scene.text) <= 88 else scene.text[:85] + "..."
            print(f"  {scene.index:>3}. [{scene.duration:>2}s] "
                  f"{scene.label:<24} {text}")
        print("\n  dry run — nothing generated.\n")
        return 0

    look = {
        "motion": args.motion,
        "grain": args.grain,
        "letterbox": args.letterbox,
        "grade": args.grade,
        "images_per_clip": args.images_per_clip,
        "size": f"{args.width}x{args.height}",
        "image_size": f"{args.width}x{args.height}",
    }
    if args.style:
        look["style"] = args.style

    if args.provider == "ltx":
        look.update({"height": args.height, "width": args.width})
        if args.ltx_steps is not None:
            look["steps"] = args.ltx_steps
        if args.ltx_frames:
            look["frames"] = args.ltx_frames

    if args.provider == "wan":
        look.update({"height": args.height, "width": args.width})
        if args.fast:
            look["speed_lora"] = "causvid"
        if args.lora_strength is not None:
            look["lora_strength"] = args.lora_strength
        # Only set these when given, so a distilled LoRA can supply its own
        # trained defaults instead of being overridden by argparse defaults.
        if args.wan_steps is not None:
            look["steps"] = args.wan_steps
        elif not args.fast:
            look["steps"] = 20
        if args.wan_guidance is not None:
            look["guidance"] = args.wan_guidance
        elif not args.fast:
            look["guidance"] = 5.0
        if args.wan_frames:
            look["frames"] = args.wan_frames

    try:
        provider = get_provider(args.provider, args.model, **look)
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    reporter = (lambda m: None) if args.quiet else print
    pipeline = Pipeline(
        provider, workdir,
        reporter=reporter,
        max_retries=args.retries,
        concurrency=args.concurrency,
    )

    try:
        result = pipeline.render(
            scenes, output,
            width=args.width, height=args.height, fps=args.fps,
            crossfade=args.crossfade,
            music=Path(args.music) if args.music else None,
            narrate=args.narrate,
            voice=args.voice,
            ambience=Path(args.ambience) if args.ambience else None,
            music_level=args.music_level,
            duck=args.duck,
            fast_concat=args.fast_concat,
            allow_partial=args.allow_partial,
            stitch=not args.no_stitch,
        )
    except AuthError as exc:
        print(f"\nauth error: {exc}", file=sys.stderr)
        print("Run `soulclip doctor` to see which variables are set.",
              file=sys.stderr)
        return 3
    except (ProviderError, FFmpegError) as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Progress is saved — re-run to pick up where "
              "you left off.", file=sys.stderr)
        return 130

    if not args.quiet:
        print(f"\n  generated {result.generated}, reused {result.reused}, "
              f"failed {len(result.failed)} in {result.elapsed:.0f}s")

    if args.no_stitch:
        return 0
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {
        "render": cmd_render,
        "scenes": cmd_scenes,
        "doctor": cmd_doctor,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
