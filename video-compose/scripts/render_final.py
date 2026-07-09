#!/usr/bin/env python3
"""Render the final composite video from timeline.json.

Pipeline:
  1. For each video segment in timeline.tracks.video[]:
     - Cut sub-clip from source video (with silent audio track), OR
     - Render image as clip with optional Ken Burns motion
  2. Stitch clips with xfade transitions
  3. Overlay each title (ProRes 4444 MOV with alpha) at its in_at/out_at window
  4. Mix background music with fades
  5. Optionally burn in captions

Usage:
    python3 render_final.py --timeline timeline.json --titles-dir titles/ -o final.mp4
    python3 render_final.py --timeline timeline.json -o final.mp4   # no titles
    python3 render_final.py ... --no-music
    python3 render_final.py ... --motion-intensity medium

Notes:
  - This is the slow / high-quality renderer. Use preview.py for quick iteration.
  - The titles directory must contain {title.id}.mov files matching the
    timeline's titles[] entries (output of render_titles.py).
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (ffprobe_video, get_format_preset, is_image, is_video,
                     load_json, run_ffmpeg)
from _video_pipeline import (cut_subclip_silent, image_to_clip, mix_music,
                             overlay_titles, stitch_with_concat,
                             stitch_with_xfade)


def render_segment(seg, output_path, target_w, target_h, fps, *,
                   assets_root=None, motion_intensity="subtle"):
    """Render a single timeline segment to a normalized clip."""
    source = seg["source"]
    if assets_root and not Path(source).is_absolute():
        source_path = Path(assets_root) / source
    else:
        source_path = Path(source)

    if not source_path.exists():
        print(f"  Error: source not found: {source_path}", file=sys.stderr)
        return False

    duration = seg["out_at"] - seg["in_at"]
    ken_burns = seg.get("ken_burns", "none")

    if is_image(source_path):
        return image_to_clip(
            source_path, duration, output_path,
            target_w, target_h,
            ken_burns=(ken_burns if ken_burns != "none" else "push_in"),
            intensity=motion_intensity, fps=fps,
        )
    elif is_video(source_path):
        src_in = float(seg.get("src_in", 0))
        src_out = float(seg.get("src_out", src_in + duration))
        return cut_subclip_silent(
            source_path, src_in, src_out, output_path,
            target_w, target_h, fps=fps,
        )
    else:
        print(f"  Warning: unsupported source type: {source_path}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Render final composite video from timeline.json")
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--titles-dir", default=None,
                        help="Directory with rendered title .mov files. "
                             "If omitted, titles are skipped.")
    parser.add_argument("--assets-root", default=None,
                        help="Root folder for resolving relative source paths "
                             "(default: timeline's directory)")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--no-transitions", action="store_true")
    parser.add_argument("--motion-intensity", default="subtle",
                        choices=["subtle", "medium", "strong"])
    parser.add_argument("--watermark", default=None,
                        help="Optional watermark image (PNG with alpha) overlaid top-right")
    parser.add_argument("--watermark-scale", type=float, default=0.18)
    parser.add_argument("--watermark-opacity", type=float, default=0.7)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    timeline = load_json(args.timeline)
    video_track = timeline.get("tracks", {}).get("video", [])
    if not video_track:
        print("Error: timeline has no video segments", file=sys.stderr)
        sys.exit(1)

    fmt = timeline.get("format", "reel")
    preset = get_format_preset(fmt)
    target_w = int(timeline.get("width", preset["width"]))
    target_h = int(timeline.get("height", preset["height"]))
    fps = int(timeline.get("fps", 30))

    assets_root = Path(args.assets_root).resolve() if args.assets_root else \
        Path(args.timeline).resolve().parent

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Rendering final reel: {target_w}x{target_h}@{fps}fps, "
          f"{len(video_track)} shots, "
          f"target duration {timeline.get('total_duration', 0):.1f}s ...",
          file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="vc_final_") as tmpdir:
        tmpdir = Path(tmpdir)
        clip_paths = []
        durations = []

        for i, seg in enumerate(video_track):
            clip_out = tmpdir / f"clip-{i:03d}.mp4"
            print(f"  [{i+1}/{len(video_track)}] {seg.get('source', '?')} "
                  f"({seg['out_at'] - seg['in_at']:.2f}s, "
                  f"ken_burns={seg.get('ken_burns', 'none')}) ...", file=sys.stderr)
            ok = render_segment(
                seg, clip_out, target_w, target_h, fps,
                assets_root=assets_root, motion_intensity=args.motion_intensity,
            )
            if not ok:
                print(f"  Error: failed to render shot {i}", file=sys.stderr)
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

        titles = timeline.get("tracks", {}).get("titles", []) or []
        if titles and args.titles_dir:
            titles_dir = Path(args.titles_dir).resolve()
            print(f"  Overlaying {len(titles)} title(s) ...", file=sys.stderr)
            title_clips = []
            for t in titles:
                tid = t.get("id") or f"t_unknown"
                t_path = titles_dir / f"{tid}.mov"
                if not t_path.exists():
                    print(f"    Warning: missing title clip {t_path}; skipping",
                          file=sys.stderr)
                    continue
                title_clips.append({
                    "path": str(t_path),
                    "in_at": float(t["in_at"]),
                    "out_at": float(t["out_at"]),
                })

            if title_clips:
                titled = tmpdir / "with_titles.mp4"
                ok = overlay_titles(current, title_clips, titled,
                                    target_w=target_w, target_h=target_h)
                if ok:
                    current = titled
                else:
                    print("  Warning: title overlay failed; proceeding without titles",
                          file=sys.stderr)

        music = timeline.get("tracks", {}).get("music", {}) or {}
        music_path = music.get("source") if music else None
        if music_path and not args.no_music and Path(music_path).exists():
            with_music = tmpdir / "with_music.mp4"
            ok = mix_music(
                current, music_path, with_music,
                volume=float(music.get("volume", 0.7)),
                fade_in_ms=int(music.get("fade_in_ms", 500)),
                fade_out_ms=int(music.get("fade_out_ms", 2000)),
                video_has_audio=True,
            )
            if ok:
                current = with_music

        if args.watermark and Path(args.watermark).exists():
            wm_out = tmpdir / "with_wm.mp4"
            wm_w = int(target_w * args.watermark_scale)
            margin = int(target_w * 0.04)
            vf = (f"[1:v]scale={wm_w}:-1,format=rgba,"
                  f"colorchannelmixer=aa={args.watermark_opacity}[wm];"
                  f"[0:v][wm]overlay=W-w-{margin}:{margin}[vout]")
            ok = run_ffmpeg(
                ["-i", str(current), "-i", str(args.watermark),
                 "-filter_complex", vf,
                 "-map", "[vout]", "-map", "0:a?",
                 "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                 "-pix_fmt", "yuv420p",
                 "-c:a", "copy", str(wm_out)],
                description="Adding watermark",
            )
            if ok:
                current = wm_out

        shutil.copy2(str(current), str(output_path))

    info = ffprobe_video(output_path)
    print(f"\nFinal reel written: {output_path}", file=sys.stderr)
    print(json.dumps({
        "output": str(output_path),
        "duration": info["duration"],
        "resolution": f"{info['width']}x{info['height']}",
        "shots": len(video_track),
        "titles_overlaid": len(timeline.get("tracks", {}).get("titles", []) or []),
    }, indent=2))


if __name__ == "__main__":
    main()
