#!/usr/bin/env python3
"""Export lipsync.json from lines.json - a manifest ready for the seedance-2 skill.

Each clean per-line clip becomes a lipsync reference: speaker, voice, exact
transcript, duration, an `ok` flag for the <=15s seedance limit, and a suggested
storyboard panel index. The skill does NOT build the storyboard; this just maps
clips to panels you provide.

Usage:
    python3 export_lipsync.py --out audio-theater/ep
    python3 export_lipsync.py --lines audio-theater/ep/lines.json --out audio-theater/ep
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    load_config, load_json, save_json, resolve_out_dir,
    get_audio_duration, MAX_CLIP_SECONDS,
)


def main():
    parser = argparse.ArgumentParser(description="Export seedance-2 lipsync manifest")
    parser.add_argument("--out", "-o", required=True, help="Project folder")
    parser.add_argument("--lines", default=None, help="Path to lines.json (default <out>/lines.json)")
    parser.add_argument("--max-clip-seconds", type=float, default=None,
                        help="Max clip duration considered OK for seedance (default 15)")
    parser.add_argument("--panel-start", type=int, default=1,
                        help="Panel index to start mapping from (default 1)")
    args = parser.parse_args()

    config = load_config()
    out_dir = resolve_out_dir(args.out)
    lines_path = Path(args.lines) if args.lines else out_dir / "lines.json"
    if not lines_path.exists():
        print(f"Error: {lines_path} not found. Run generate_voices.py first.", file=sys.stderr)
        sys.exit(1)

    data = load_json(lines_path)
    max_clip = args.max_clip_seconds or data.get("max_clip_seconds") \
        or config.get("max_clip_seconds", MAX_CLIP_SECONDS)

    if data.get("tts_mode") == "two_speaker":
        print("Warning: lines.json was made with --two-speaker (single take). Lipsync needs "
              "clean per-line clips - re-run generate_voices.py WITHOUT --two-speaker.",
              file=sys.stderr)

    clips = []
    over = []
    missing = []
    panel = args.panel_start
    for ln in data.get("lines", []):
        rel = ln.get("file")
        duration = ln.get("duration")
        if rel:
            abs_path = out_dir / rel
            if not abs_path.exists():
                missing.append(ln["index"])
            elif duration is None:
                duration = round(get_audio_duration(abs_path), 3)
        ok = bool(rel) and duration is not None and duration <= max_clip
        if rel and duration is not None and duration > max_clip:
            over.append(ln["index"])
        clips.append({
            "index": ln["index"],
            "speaker": ln["speaker"],
            "voice": ln.get("voice"),
            "transcript": ln.get("text", ""),
            "duration": duration,
            "file": rel,
            "panel": panel,
            "ok": ok,
        })
        panel += 1

    manifest = {
        "title": data.get("title"),
        "language": data.get("language"),
        "max_clip_seconds": max_clip,
        "clip_count": len(clips),
        "all_ok": not over and not missing and all(c["ok"] for c in clips),
        "clips": clips,
        "seedance_handoff": (
            "Per clip: media_upload -> PUT bytes -> media_confirm(type=audio); then "
            "generate_video (model seedance_2_0) with a storyboard panel image "
            "(reference-image role) + the confirmed audio media_id (audio role). Build "
            "the prompt with seedance-2 prompt_tools.py reframe --images 1 --audios 1 "
            "--audio-transcript \"<transcript>\". Audio must be <=15s and needs at least "
            "one image/video reference."
        ),
    }

    out_path = out_dir / "lipsync.json"
    save_json(out_path, manifest)

    print(f"  Clips: {len(clips)} | OK(<= {max_clip}s): {sum(1 for c in clips if c['ok'])}",
          file=sys.stderr)
    if over:
        print(f"  Over limit ({max_clip}s): lines {over} - split these lines and re-run.",
              file=sys.stderr)
    if missing:
        print(f"  Missing clip files: lines {missing}", file=sys.stderr)
    print(json.dumps({
        "lipsync_json": str(out_path),
        "clip_count": len(clips),
        "all_ok": manifest["all_ok"],
        "over_limit": over,
        "missing": missing,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
