#!/usr/bin/env python3
"""Render a fast low-resolution preview of a timeline.json.

This is the approval-gate render — it skips the expensive parts (Remotion
titles, Ken Burns motion, beat-precision audio) and produces a 480p MP4 in
~10-30 seconds so the user can sanity-check the cut order before committing
to a full render.

What's included:
- Sub-clip cuts at correct timestamps
- Basic xfade transitions
- Background music (volume + fades)
- Burned-in shot labels (so the user can see which treatment shot maps to which clip)

What's skipped (vs render_final.py):
- Ken Burns camera motion on image segments (rendered as static)
- Remotion-rendered titles (replaced with simple drawtext placeholders)
- Captions
- Watermarks

Usage:
    python3 preview.py --timeline timeline.json -o preview.mp4
    python3 preview.py --timeline timeline.json -o preview.mp4 --no-music
    python3 preview.py --timeline timeline.json -o preview.mp4 --scale 0.4
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (PREVIEW_FPS, PREVIEW_SCALE, ffprobe_video, get_format_preset,
                     is_image, is_video, load_json, run_ffmpeg)
from _video_pipeline import (cut_subclip_silent, image_to_clip, mix_music,
                             stitch_with_concat, stitch_with_xfade)


def render_preview_clip(seg, output_path, target_w, target_h, fps, *,
                        assets_root=None, label=None, label_idx=None,
                        total_segs=None):
    """Render a single timeline segment to a normalized clip for preview."""
    source = seg["source"]
    if assets_root and not Path(source).is_absolute():
        source_path = Path(assets_root) / source
    else:
        source_path = Path(source)

    if not source_path.exists():
        print(f"  Error: source not found: {source_path}", file=sys.stderr)
        return False

    duration = seg["out_at"] - seg["in_at"]

    if is_image(source_path):
        ok = image_to_clip(
            source_path, duration, output_path,
            target_w, target_h, ken_burns=None, fps=fps,
        )
    elif is_video(source_path):
        src_in = float(seg.get("src_in", 0))
        src_out = float(seg.get("src_out", src_in + duration))
        ok = cut_subclip_silent(
            source_path, src_in, src_out, output_path,
            target_w, target_h, fps=fps,
        )
    else:
        print(f"  Warning: unsupported source type: {source_path}", file=sys.stderr)
        return False

    if not ok or label is None:
        return ok

    return _add_label(output_path, label, label_idx, total_segs, target_w, target_h)


def _add_label(video_path, label, idx, total, target_w, target_h):
    """Burn a small `[idx/total] description` label in the top-left for previews."""
    safe_label = (
        (label[:60] + "...") if len(label) > 60 else label
    ).replace("'", "").replace(":", " ").replace(",", " ")

    label_text = f"{idx + 1}/{total}  {safe_label}" if idx is not None else safe_label
    font_size = max(18, target_h // 32)
    pad_x = max(8, target_w // 60)
    pad_y = max(8, target_h // 60)

    drawtext = (
        f"drawtext=text='{label_text}':"
        f"fontcolor=white:fontsize={font_size}:"
        f"box=1:boxcolor=black@0.55:boxborderw=6:"
        f"x={pad_x}:y={pad_y}"
    )

    tmp_out = video_path.with_suffix(".labeled.mp4")
    ok = run_ffmpeg(
        ["-i", str(video_path),
         "-vf", drawtext,
         "-c:v", "libx264", "-crf", "22", "-preset", "veryfast",
         "-pix_fmt", "yuv420p",
         "-c:a", "copy",
         str(tmp_out)],
        description="Adding preview label",
        quiet=True,
    )
    if ok:
        tmp_out.replace(video_path)
        return True
    return ok


def main():
    parser = argparse.ArgumentParser(description="Render fast low-res preview from timeline.json")
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--assets-root", default=None,
                        help="Root folder for resolving relative source paths "
                             "(default: timeline's directory)")
    parser.add_argument("--scale", type=float, default=PREVIEW_SCALE,
                        help=f"Scale factor (default: {PREVIEW_SCALE})")
    parser.add_argument("--fps", type=int, default=PREVIEW_FPS,
                        help=f"Preview FPS (default: {PREVIEW_FPS})")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--no-labels", action="store_true",
                        help="Skip burned-in shot labels")
    parser.add_argument("--no-transitions", action="store_true",
                        help="Use plain concat instead of xfade")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    timeline = load_json(args.timeline)
    video_track = timeline.get("tracks", {}).get("video", [])
    if not video_track:
        print("Error: timeline has no video segments", file=sys.stderr)
        sys.exit(1)

    fmt = timeline.get("format", "reel")
    preset = get_format_preset(fmt)
    target_w = max(64, int(round(preset["width"] * args.scale)))
    target_h = max(64, int(round(preset["height"] * args.scale)))
    target_w = target_w + (target_w % 2)
    target_h = target_h + (target_h % 2)
    fps = args.fps

    assets_root = Path(args.assets_root).resolve() if args.assets_root else \
        Path(args.timeline).resolve().parent

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Rendering preview: {target_w}x{target_h}@{fps}fps, "
          f"{len(video_track)} shots ...", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="vc_preview_") as tmpdir:
        tmpdir = Path(tmpdir)
        clip_paths = []
        durations = []

        for i, seg in enumerate(video_track):
            clip_out = tmpdir / f"clip-{i:03d}.mp4"
            label = None
            if not args.no_labels:
                label = seg.get("description") or seg.get("source", "")

            ok = render_preview_clip(
                seg, clip_out, target_w, target_h, fps,
                assets_root=assets_root, label=label,
                label_idx=i, total_segs=len(video_track),
            )
            if not ok:
                print(f"  Error: failed to render clip {i}", file=sys.stderr)
                sys.exit(2)

            info = ffprobe_video(clip_out)
            actual_dur = info["duration"] if info["duration"] > 0 else (seg["out_at"] - seg["in_at"])
            clip_paths.append(clip_out)
            durations.append(actual_dur)

        stitched = tmpdir / "stitched.mp4"

        transitions = []
        for i in range(1, len(video_track)):
            t = video_track[i].get("transition_in")
            if t and not args.no_transitions:
                transitions.append((t.get("kind", "fade"), float(t.get("dur", 0.3))))
            else:
                transitions.append(("cut", 0.0))

        if args.no_transitions or len(clip_paths) == 1 or all(t[0] == "cut" for t in transitions):
            ok = stitch_with_concat(clip_paths, stitched,
                                    target_w=target_w, target_h=target_h, fps=fps)
        else:
            ok = stitch_with_xfade(clip_paths, durations, transitions,
                                   stitched, target_w, target_h, fps=fps)
            if not ok:
                print("  Warning: xfade failed, falling back to concat", file=sys.stderr)
                ok = stitch_with_concat(clip_paths, stitched,
                                        target_w=target_w, target_h=target_h, fps=fps)

        if not ok:
            print("Error: stitch failed", file=sys.stderr)
            sys.exit(2)

        current = stitched

        music = timeline.get("tracks", {}).get("music", {})
        music_path = music.get("source") if music else None
        if music_path and not args.no_music and Path(music_path).exists():
            music_out = tmpdir / "with_music.mp4"
            ok = mix_music(
                current, music_path, music_out,
                volume=float(music.get("volume", 0.7)),
                fade_in_ms=int(music.get("fade_in_ms", 500)),
                fade_out_ms=int(music.get("fade_out_ms", 2000)),
                video_has_audio=True,
            )
            if ok:
                current = music_out

        import shutil
        shutil.copy2(current, output_path)

    info = ffprobe_video(output_path)
    print(f"\nPreview written: {output_path}", file=sys.stderr)
    print(json.dumps({
        "output": str(output_path),
        "duration": info["duration"],
        "resolution": f"{info['width']}x{info['height']}",
        "shots": len(video_track),
    }, indent=2))


if __name__ == "__main__":
    main()
