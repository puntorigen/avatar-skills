#!/usr/bin/env python3
"""broll-browser-recorder finalizer.

Turn a *recorded browser demo* (the base layer of a technical reel) into a
numbered, reel-ready B-roll clip, optionally with a talking avatar composited in
a picture-in-picture corner that narrates what the demo shows.

Recording happens interactively/agent-driven through ``browser_server.py`` (see
SKILL.md). This script is the finish line: it post-processes the raw recording
(trim / speed / auto-camera reframe / preset) with ``process_video.py`` and then,
if ``--avatar`` is given, composites the avatar PiP with ``broll-core``'s
``pip_overlay`` in **base-driven** mode by default — the recorded demo is the
hero and drives the length; the avatar freezes on its last frame once its
narration ends.

Output: a numbered ``NNN_<slug>.mp4`` under ``--out-dir`` plus a ``manifest.json``
entry that drops straight into ``avatar-reel-composer`` (broll_source "existing").

Examples
    # Base demo only (9:16, auto-camera reframe from the recording's manifest)
    python3 make_broll_demo.py /tmp/rec/recording.webm --max-duration 30

    # Base demo + avatar PiP narrating it (base-driven: demo sets the length)
    python3 make_broll_demo.py /tmp/rec/ --max-duration 30 \
        --avatar avatares/lolo/pip/scene01.mp4 --corner br
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CORE = _HERE.parent.parent / "broll-core" / "scripts"
if not _CORE.exists():
    raise SystemExit(f"[broll-browser-recorder] ERROR: broll-core not found at {_CORE}. "
                     "Install the broll-core skill alongside this one.")
sys.path.insert(0, str(_HERE))      # local: process_video, auto_camera
sys.path.insert(0, str(_CORE))      # shared: _common, pip_overlay
import _common as C  # noqa: E402
import pip_overlay as PIP  # noqa: E402

C.PREFIX = "broll-browser-recorder"

_PROCESS_VIDEO = _HERE / "process_video.py"


def slugify(s: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")
    return (s[:maxlen].strip("-") or "demo")


def resolve_recording(inp: Path) -> Path:
    """Accept a .webm/.mp4 file or a recording directory (find the video inside).

    The video is used *in place* so ``process_video.py`` can find the sibling
    ``manifest.json`` for auto-camera reframing.
    """
    if inp.is_dir():
        vids = sorted([*inp.glob("*.webm"), *inp.glob("*.mp4")],
                      key=lambda p: p.stat().st_mtime)
        if not vids:
            C.die(f"no .webm/.mp4 recording found in {inp}")
        return vids[-1]
    if not inp.exists():
        C.die(f"recording not found: {inp}")
    return inp


def run_process_video(recording: Path, base_out: Path, *, resolution: str, args) -> None:
    """Delegate post-processing to process_video.py (reuses auto-camera, zoom, etc.)."""
    cmd = [sys.executable, str(_PROCESS_VIDEO), str(recording), "-o", str(base_out),
           "--resolution", resolution, "--crf", str(args.crf), "--fps", str(args.fps),
           "--fit", args.fit]
    if args.preset:
        # Preset overrides the aspect-derived resolution.
        cmd += ["--preset", args.preset]
    if args.speed and args.speed != 1.0:
        cmd += ["--speed", str(args.speed)]
    if args.max_duration:
        cmd += ["--max-duration", str(args.max_duration)]
    if args.crop:
        cmd += ["--crop", args.crop]
    if args.zoom:
        cmd += ["--zoom", args.zoom]
    if args.no_auto_camera:
        cmd += ["--no-auto-camera"]
    if args.start is not None:
        cmd += ["--start", str(args.start)]
    if args.end is not None:
        cmd += ["--end", str(args.end)]
    if args.fade_in:
        cmd += ["--fade-in", str(args.fade_in)]
    if args.fade_out:
        cmd += ["--fade-out", str(args.fade_out)]
    if args.pad_color:
        cmd += ["--pad-color", args.pad_color]
    C.log(f"  $ process_video -> {base_out.name}")
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        C.die(f"process_video.py failed (rc={proc.returncode}) for {recording}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording", type=Path,
                    help="recorded demo (.webm/.mp4) or the recording directory")
    ap.add_argument("--aspect", default="9:16", choices=list(C.ASPECTS),
                    help="final reel geometry (default 9:16)")
    ap.add_argument("--out-dir", type=Path, default=Path("broll_demo"))
    ap.add_argument("--slug", default=None, help="filename slug (default from the recording name)")
    # post-process passthrough (process_video.py)
    ap.add_argument("--preset", default=None,
                    choices=["reel", "story", "short", "post", "portrait", "landscape"],
                    help="social preset (overrides --aspect geometry)")
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier")
    ap.add_argument("--max-duration", type=float, default=None,
                    help="target max output seconds; auto-calculates speed")
    ap.add_argument("--crop", default=None, help="crop x:y:w:h (else auto-camera / fit)")
    ap.add_argument("--zoom", default=None, help="zoom keyframes JSON or @file.json")
    ap.add_argument("--no-auto-camera", action="store_true",
                    help="disable auto-camera reframe from the recording manifest")
    ap.add_argument("--fit", default="pad", choices=["pad", "crop", "stretch", "blur"])
    ap.add_argument("--pad-color", default="000000")
    ap.add_argument("--start", default=None, help="trim start (seconds or HH:MM:SS)")
    ap.add_argument("--end", default=None, help="trim end")
    ap.add_argument("--fade-in", type=float, default=None)
    ap.add_argument("--fade-out", type=float, default=None)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--fps", type=int, default=C.DEFAULT_FPS)
    # avatar PiP overlay (broll-core pip_overlay)
    ap.add_argument("--avatar", type=Path, default=None,
                    help="talking avatar clip -> PiP overlay narrating the demo "
                         "(locked, face-forward pip shot)")
    ap.add_argument("--layout", default="pip-circle", choices=["pip-circle", "split"])
    ap.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"])
    ap.add_argument("--face-bias", type=float, default=0.4,
                    help="vertical crop bias for the PiP circle (0=top..1=bottom; keep the face)")
    ap.add_argument("--length", default="base", choices=["base", "avatar"],
                    help="who drives the clip length: the recorded demo (default) "
                         "or the avatar narration (short snippets)")
    args = ap.parse_args()

    C.require_tool("ffmpeg")
    C.require_tool("ffprobe")
    if args.avatar and not args.avatar.exists():
        C.die(f"--avatar not found: {args.avatar}")

    recording = resolve_recording(args.recording)
    slug = args.slug or slugify(recording.stem)
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / f"_{slug}_work"
    work.mkdir(parents=True, exist_ok=True)

    W, H = C.aspect_dims(args.aspect)
    resolution = f"{W}x{H}"
    C.log(f"[broll-browser-recorder] slug={slug} aspect={args.aspect} "
          f"length={args.length if args.avatar else 'n/a'} -> {out_dir}")

    base_clip = work / f"{slug}_base.mp4"
    run_process_video(recording, base_clip, resolution=resolution, args=args)

    idx = C.next_index(out_dir)
    final = out_dir / f"{idx:03d}_{slug}.mp4"
    if args.avatar:
        PIP.overlay_pip(base_clip, args.avatar, final, layout=args.layout,
                        corner=args.corner, aspect=args.aspect,
                        face_bias=args.face_bias, length=args.length, fps=args.fps)
    else:
        # No avatar: the base demo is the clip. Normalize the container.
        C.run(["ffmpeg", "-y", "-i", str(base_clip), "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-an", str(final), "-loglevel", "error"],
              desc=f"finalize -> {final.name}")

    entry = {
        "id": f"{idx:03d}_{slug}", "slug": slug, "clip": str(final),
        "source": "broll-browser-recorder", "recording": str(recording),
        "aspect": args.aspect, "duration": round(C.ffprobe_duration(final), 2),
        "avatar": str(args.avatar) if args.avatar else None,
        "length_mode": args.length if args.avatar else None,
        "silent": args.avatar is None, "created_at": C.now_iso(),
    }
    manifest = C.append_manifest(out_dir, entry)
    C.log(f"[done] {entry['id']} -> {final}")
    print(json.dumps({"clip": entry, "manifest": str(manifest),
                      "out_dir": str(out_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
