#!/usr/bin/env python3
"""Turn ONE [start,end] window of a real video into a clean B-roll clip.

This is the found-footage workhorse — the counterpart of broll-generator's
generate_broll.py. Given a YouTube URL (downloads ONLY that window) or a local
file (cuts it directly), it produces a 9:16, audio-stripped clip normalized to
the reel format, and appends a provenance + license entry to a broll-compatible
manifest.json.

Output: <out-dir>/<NNN>_<slug>.mp4 + a manifest.json entry. A JSON summary is
printed to stdout for an orchestrating skill.

Examples:
    # From YouTube (downloads only 02:12-02:18), saved into an avatar's broll/found/:
    python3 cut_segment.py --url "https://youtu.be/VIDEOID" --start 132 --end 138 \
        --description "Bourdain comiendo pho en un puesto callejero de Hanoi" \
        --avatar-dir /path/to/lolo

    # From an already-downloaded local file:
    python3 cut_segment.py --input clip.mp4 --start 5 --end 11 \
        --description "olas rompiendo al atardecer" --fit blur --out-dir ./broll
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# Reel format defaults (match avatar-reel-composer's reel preset).
DEFAULT_W, DEFAULT_H, DEFAULT_FPS = 1080, 1920, 30


def resolve_out_dir(args) -> tuple[Path, Path]:
    """Found clips live under <avatar>/broll/found/ with their own manifest,
    kept separate from generated broll so indices never collide."""
    if args.avatar_dir:
        avatar_dir = Path(args.avatar_dir).expanduser().resolve()
        if avatar_dir.is_dir():
            out_dir = avatar_dir / "broll" / "found"
            out_dir.mkdir(parents=True, exist_ok=True)
            return out_dir, out_dir / "manifest.json"
    out_dir = Path(args.out_dir or (Path.cwd() / "broll-found")).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir, out_dir / "manifest.json"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cut one [start,end] window of a real video into a clean 9:16 B-roll clip.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="YouTube URL/ID — only the window is downloaded.")
    src.add_argument("--input", help="Local video file to cut.")
    ap.add_argument("--start", type=float, required=True, help="Window start (seconds).")
    ap.add_argument("--end", type=float, required=True, help="Window end (seconds).")
    ap.add_argument("--description", required=True, help="What the clip shows (for the manifest/storyboard).")
    ap.add_argument("--fit", default="crop", choices=["crop", "pad", "blur"],
                    help="16:9->9:16 strategy. DEFAULT 'crop' = center crop-to-fill that covers the "
                         "WHOLE 9:16 frame (never letterbox/pad a downscaled copy). 'pad' (black bars) "
                         "and 'blur' (blurred backfill) are opt-in only when cropping would cut out "
                         "essential content.")
    ap.add_argument("--width", type=int, default=DEFAULT_W)
    ap.add_argument("--height", type=int, default=DEFAULT_H)
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS)
    ap.add_argument("--max-height", type=int, default=720, help="Max source height to download (default 720).")
    ap.add_argument("--keep-audio", action="store_true", help="Keep audio (off by default for clean B-roll).")
    ap.add_argument("--cookies-from-browser", help="Browser for cookies on bot-gated videos.")
    ap.add_argument("--frame", action="store_true", help="Also save a midpoint frame jpg for visual review.")
    ap.add_argument("--avatar-dir", help="Avatar folder; saves to <avatar>/broll/found/.")
    ap.add_argument("--out-dir", help="Explicit output folder (default ./broll-found).")
    ap.add_argument("--out-name", help="Override the output filename stem (without extension).")
    args = ap.parse_args()

    if args.end <= args.start:
        print("Error: --end must be greater than --start.", file=sys.stderr)
        return 1
    seg_dur = round(args.end - args.start, 3)

    out_dir, manifest_path = resolve_out_dir(args)
    manifest = C.load_manifest(manifest_path)
    idx = C.next_index(manifest["items"], out_dir)
    stem = args.out_name or f"{idx:03d}_{C.slugify(args.description)}"
    final_path = out_dir / f"{stem}.mp4"

    # 1) get a local source covering the window
    info: dict = {}
    cleanup_tmp: Path | None = None
    if args.url:
        info = C.ytdlp_info(args.url, args.cookies_from_browser)
        tmpdir = Path(tempfile.mkdtemp(prefix="bf_dl_"))
        cleanup_tmp = tmpdir
        section = C.download_section(
            args.url, args.start, args.end, tmpdir / "section",
            max_height=args.max_height, cookies_browser=args.cookies_from_browser)
        if not section or not section.exists():
            print("Error: section download failed.", file=sys.stderr)
            return 2
        # The downloaded file IS the window, so cut from 0.
        local_src, lstart, lend = section, 0.0, seg_dur
    else:
        local_src = Path(args.input).expanduser().resolve()
        if not local_src.exists():
            print(f"Error: input not found: {local_src}", file=sys.stderr)
            return 2
        lstart, lend = args.start, args.end

    # 2) cut + normalize to 9:16
    ok = C.cut_and_normalize(
        local_src, final_path, start=lstart, end=lend,
        W=args.width, H=args.height, fps=args.fps, fit=args.fit,
        strip_audio=not args.keep_audio)
    if not ok or not final_path.exists():
        print("Error: ffmpeg normalization failed.", file=sys.stderr)
        return 3

    frame_path = None
    if args.frame:
        frame_path = C.extract_frame(final_path, seg_dur / 2.0,
                                     out_dir / f"{stem}.jpg")

    if cleanup_tmp:
        import shutil
        shutil.rmtree(cleanup_tmp, ignore_errors=True)

    probe = C.probe_video(final_path)
    lic = C.license_summary(info.get("license"))
    vid = info.get("video_id") or (C.extract_video_id(args.url) if args.url else None)

    entry = {
        "index": idx,
        "file": final_path.name,
        "path": str(final_path),
        "description": args.description,
        "source": "youtube" if args.url else "local",
        "source_url": (args.url if args.url and args.url.startswith("http")
                       else (f"https://www.youtube.com/watch?v={vid}" if vid else None)),
        "source_video_id": vid,
        "source_title": info.get("title"),
        "channel": info.get("channel"),
        "channel_url": info.get("channel_url"),
        "license": lic["license"],
        "reusable": lic["reusable"],
        "rights_note": lic["note"],
        "segment": {"start": args.start, "end": args.end},
        "fit": args.fit,
        "aspect_ratio": "9:16",
        "audio": bool(args.keep_audio),
        "duration_sec": probe.get("duration", seg_dur),
        "width": probe.get("width"),
        "height": probe.get("height"),
        "fps_actual": probe.get("fps"),
        "frame": str(frame_path) if frame_path else None,
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    manifest["items"].append(entry)
    C.write_manifest(manifest_path, manifest)

    print(f"Done: {final_path}", file=sys.stderr)
    if not lic["reusable"]:
        print(f"  RIGHTS: {lic['note']}", file=sys.stderr)
    print(json.dumps({
        "video": str(final_path), "manifest": str(manifest_path),
        **{k: entry[k] for k in ("description", "duration_sec", "width", "height",
                                 "license", "reusable", "source_url", "segment")},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
