#!/usr/bin/env python3
"""One-stop CLI that runs (or resumes) the full video-compose pipeline.

This script is intended to be called by an agent (or a human) at any stage —
it detects which artifacts already exist and runs only the missing stages.

Stages:
    1. analyze     analyze_assets.py        → assets.json
    2. treatment   treatment.py draft       → treatment.yaml
    3. music       pick_music.py generate   → bgm.mp3 + bgm_meta.json
    4. edl         generate_edl.py          → timeline.json
    5. preview     preview.py               → preview.mp4
    6. titles      render_titles.py         → titles/*.mov
    7. final       render_final.py          → final.mp4

Each stage is idempotent: it skips work that's already done unless --force is passed.

Usage:
    # Full pipeline up to preview (the agent then asks the user to approve)
    python3 compose.py up-to-preview \\
        --assets-dir ./media --output-dir ./reel-out \\
        --brief "Adoption journey reel" --format reel --target-duration 30 \\
        --language en --tone "warm, uplifting" --mood pet-heartfelt

    # Run only specific stages
    python3 compose.py stage analyze --assets-dir ./media --output-dir ./reel-out
    python3 compose.py stage treatment --output-dir ./reel-out --brief "..." --format reel
    python3 compose.py stage music --output-dir ./reel-out --mood pet-heartfelt
    python3 compose.py stage edl --output-dir ./reel-out
    python3 compose.py stage preview --output-dir ./reel-out
    python3 compose.py stage titles --output-dir ./reel-out
    python3 compose.py stage final --output-dir ./reel-out

    # After approval: run the rest (titles + final)
    python3 compose.py finalize --output-dir ./reel-out

Conventions for --output-dir:
    {output-dir}/
        assets.json
        treatment.yaml
        bgm.mp3
        bgm_meta.json
        timeline.json
        preview.mp4
        titles/
            t1.mov
            t2.mov
        final.mp4
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


def _stage_paths(output_dir):
    p = Path(output_dir).resolve()
    return {
        "root": p,
        "assets": p / "assets.json",
        "treatment": p / "treatment.yaml",
        "music": p / "bgm.mp3",
        "music_meta": p / "bgm_meta.json",
        "timeline": p / "timeline.json",
        "preview": p / "preview.mp4",
        "titles_dir": p / "titles",
        "final": p / "final.mp4",
    }


def _run(cmd, *, description=""):
    if description:
        print(f"\n=== {description} ===", file=sys.stderr)
    print(f"  $ {' '.join(str(c) for c in cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print(f"  Stage failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def stage_analyze(args):
    paths = _stage_paths(args.output_dir)
    paths["root"].mkdir(parents=True, exist_ok=True)
    if paths["assets"].exists() and not args.force:
        print(f"[skip] assets.json exists at {paths['assets']}", file=sys.stderr)
        return
    cmd = [sys.executable, str(SCRIPT_DIR / "analyze_assets.py"),
           "--assets", str(args.assets_dir),
           "-o", str(paths["assets"])]
    if args.force:
        cmd.append("--force")
    if args.no_vision:
        cmd.append("--no-vision")
    _run(cmd, description="Stage 1: analyze assets")


def stage_treatment(args):
    paths = _stage_paths(args.output_dir)
    paths["root"].mkdir(parents=True, exist_ok=True)
    if paths["treatment"].exists() and not args.force:
        print(f"[skip] treatment.yaml exists at {paths['treatment']}", file=sys.stderr)
        return
    if not paths["assets"].exists():
        print(f"Error: assets.json missing — run stage 'analyze' first", file=sys.stderr)
        sys.exit(1)
    cmd = [sys.executable, str(SCRIPT_DIR / "treatment.py"), "draft",
           "--brief", args.brief or "",
           "--assets", str(paths["assets"]),
           "--format", args.format,
           "--target-duration", str(args.target_duration),
           "--language", args.language,
           "--tone", args.tone,
           "-o", str(paths["treatment"])]
    if args.max_shots:
        cmd += ["--max-shots", str(args.max_shots)]
    _run(cmd, description="Stage 2: draft treatment")


def stage_music(args):
    paths = _stage_paths(args.output_dir)
    if paths["music"].exists() and paths["music_meta"].exists() and not args.force:
        print(f"[skip] bgm exists at {paths['music']}", file=sys.stderr)
        return
    if not paths["treatment"].exists():
        print(f"Error: treatment.yaml missing — run stage 'treatment' first", file=sys.stderr)
        sys.exit(1)

    if args.user_music:
        user_music_path = Path(args.user_music).resolve()
        if not user_music_path.exists():
            print(f"Error: --user-music not found: {user_music_path}", file=sys.stderr)
            sys.exit(1)
        if user_music_path != paths["music"]:
            paths["music"].parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(user_music_path, paths["music"])
        cmd = [sys.executable, str(SCRIPT_DIR / "pick_music.py"), "analyze",
               "--input", str(paths["music"]),
               "-o", str(paths["music_meta"]),
               "--mood", args.mood or "user-provided"]
        _run(cmd, description="Stage 3: analyze user-provided music")
        return

    if not args.mood:
        print("Error: --mood required (or use --user-music)", file=sys.stderr)
        print("  Run: python3 pick_music.py suggest --treatment treatment.yaml", file=sys.stderr)
        sys.exit(1)

    cmd = [sys.executable, str(SCRIPT_DIR / "pick_music.py"), "generate",
           "--treatment", str(paths["treatment"]),
           "--mood", args.mood,
           "-o", str(paths["music"]),
           "--meta-output", str(paths["music_meta"])]
    if args.force:
        cmd.append("--force")
    _run(cmd, description="Stage 3: generate music")


def stage_edl(args):
    paths = _stage_paths(args.output_dir)
    if paths["timeline"].exists() and not args.force:
        print(f"[skip] timeline.json exists at {paths['timeline']}", file=sys.stderr)
        return
    for k in ("treatment", "assets", "music", "music_meta"):
        if not paths[k].exists():
            print(f"Error: {paths[k]} missing — run prior stages first", file=sys.stderr)
            sys.exit(1)

    cmd = [sys.executable, str(SCRIPT_DIR / "generate_edl.py"),
           "--treatment", str(paths["treatment"]),
           "--assets", str(paths["assets"]),
           "--music", str(paths["music"]),
           "--music-meta", str(paths["music_meta"]),
           "--format", args.format,
           "-o", str(paths["timeline"])]
    if args.no_beat_snap:
        cmd.append("--no-beat-snap")
    _run(cmd, description="Stage 4: generate EDL")


def stage_preview(args):
    paths = _stage_paths(args.output_dir)
    if paths["preview"].exists() and not args.force:
        print(f"[skip] preview.mp4 exists at {paths['preview']}", file=sys.stderr)
        return
    if not paths["timeline"].exists():
        print(f"Error: timeline.json missing — run stage 'edl' first", file=sys.stderr)
        sys.exit(1)
    cmd = [sys.executable, str(SCRIPT_DIR / "preview.py"),
           "--timeline", str(paths["timeline"]),
           "--assets-root", str(args.assets_dir) if args.assets_dir else str(paths["root"]),
           "-o", str(paths["preview"])]
    _run(cmd, description="Stage 5: render preview (approval gate)")


def stage_titles(args):
    paths = _stage_paths(args.output_dir)
    if not paths["timeline"].exists():
        print(f"Error: timeline.json missing — run stage 'edl' first", file=sys.stderr)
        sys.exit(1)
    cmd = [sys.executable, str(SCRIPT_DIR / "render_titles.py"),
           "--timeline", str(paths["timeline"]),
           "--titles-dir", str(paths["titles_dir"])]
    if args.force:
        cmd.append("--force")
    _run(cmd, description="Stage 6: render titles (Remotion)")


def stage_final(args):
    paths = _stage_paths(args.output_dir)
    if paths["final"].exists() and not args.force:
        print(f"[skip] final.mp4 exists at {paths['final']}", file=sys.stderr)
        return
    if not paths["timeline"].exists():
        print(f"Error: timeline.json missing — run stage 'edl' first", file=sys.stderr)
        sys.exit(1)
    cmd = [sys.executable, str(SCRIPT_DIR / "render_final.py"),
           "--timeline", str(paths["timeline"]),
           "--assets-root", str(args.assets_dir) if args.assets_dir else str(paths["root"]),
           "-o", str(paths["final"])]
    if paths["titles_dir"].exists():
        cmd += ["--titles-dir", str(paths["titles_dir"])]
    if args.motion_intensity:
        cmd += ["--motion-intensity", args.motion_intensity]
    _run(cmd, description="Stage 7: render final composite")


def cmd_up_to_preview(args):
    stage_analyze(args)
    stage_treatment(args)
    stage_music(args)
    stage_edl(args)
    stage_preview(args)

    paths = _stage_paths(args.output_dir)
    print("\n" + "=" * 60, file=sys.stderr)
    print("Approval gate — please review before final render:", file=sys.stderr)
    print(f"  Preview:    {paths['preview']}", file=sys.stderr)
    print(f"  Timeline:   {paths['timeline']}", file=sys.stderr)
    print(f"  Treatment:  {paths['treatment']}", file=sys.stderr)
    print(f"  BGM:        {paths['music']}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("\nWhen ready, finalize with:", file=sys.stderr)
    print(f"  python3 {Path(__file__).name} finalize --output-dir {args.output_dir}",
          file=sys.stderr)
    print(json.dumps({
        "stage": "approval-gate",
        "preview": str(paths["preview"]),
        "timeline": str(paths["timeline"]),
        "treatment": str(paths["treatment"]),
        "music": str(paths["music"]),
    }, indent=2))


def cmd_finalize(args):
    stage_titles(args)
    stage_final(args)

    paths = _stage_paths(args.output_dir)
    print(json.dumps({
        "stage": "complete",
        "final": str(paths["final"]),
    }, indent=2))


def cmd_full(args):
    stage_analyze(args)
    stage_treatment(args)
    stage_music(args)
    stage_edl(args)
    stage_preview(args)
    stage_titles(args)
    stage_final(args)
    paths = _stage_paths(args.output_dir)
    print(json.dumps({
        "stage": "complete",
        "final": str(paths["final"]),
        "preview": str(paths["preview"]),
    }, indent=2))


def cmd_stage(args):
    stage_map = {
        "analyze": stage_analyze,
        "treatment": stage_treatment,
        "music": stage_music,
        "edl": stage_edl,
        "preview": stage_preview,
        "titles": stage_titles,
        "final": stage_final,
    }
    fn = stage_map[args.name]
    fn(args)


def add_common_args(p):
    p.add_argument("--output-dir", required=True)
    p.add_argument("--assets-dir", default=None,
                   help="Source media folder (required for analyze/preview/final stages)")
    p.add_argument("--brief", default=None)
    p.add_argument("--format", default="reel", choices=["reel", "post", "landscape"])
    p.add_argument("--target-duration", type=float, default=30)
    p.add_argument("--language", default="en")
    p.add_argument("--tone", default="warm, uplifting")
    p.add_argument("--max-shots", type=int, default=None)
    p.add_argument("--mood", default=None,
                   help="Mood id for music generation (e.g. pet-heartfelt). "
                        "Run pick_music.py suggest to see options.")
    p.add_argument("--user-music", default=None,
                   help="Skip music generation — use this audio file instead")
    p.add_argument("--no-beat-snap", action="store_true")
    p.add_argument("--no-vision", action="store_true",
                   help="Skip Gemini Vision in asset analysis")
    p.add_argument("--motion-intensity", default="subtle",
                   choices=["subtle", "medium", "strong"])
    p.add_argument("--force", action="store_true",
                   help="Re-run stages even if outputs exist")


def main():
    parser = argparse.ArgumentParser(description="Video-compose one-stop pipeline driver")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("up-to-preview", help="Run stages 1-5 (analyze..preview)")
    add_common_args(p_up)
    p_up.set_defaults(func=cmd_up_to_preview)

    p_fin = sub.add_parser("finalize", help="Run stages 6-7 (titles..final)")
    add_common_args(p_fin)
    p_fin.set_defaults(func=cmd_finalize)

    p_full = sub.add_parser("full", help="Run all 7 stages without an approval gate")
    add_common_args(p_full)
    p_full.set_defaults(func=cmd_full)

    p_st = sub.add_parser("stage", help="Run a single stage")
    p_st.add_argument("name", choices=["analyze", "treatment", "music", "edl",
                                       "preview", "titles", "final"])
    add_common_args(p_st)
    p_st.set_defaults(func=cmd_stage)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
