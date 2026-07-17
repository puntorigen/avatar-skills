#!/usr/bin/env python3
"""Copy a driving video's MOTION onto OUR avatar via bytedance/dreamactor-m2.0.

Take an avatar (a look/location, or its default), one driving VIDEO, and produce
a B-roll clip where the AVATAR re-performs the video's movement, facial
expressions and lip movements. DreamActor M2.0 combines the appearance of the
reference image (the avatar's identity-anchored hero for the chosen look) with
the motion of the driving video, so the result IS the avatar copying the video.

  avatar look -> hero image  +  driving video
    -> bytedance/dreamactor-m2.0
    -> download -> mute (-an)  [master narration is re-laid by avatar-reel-composer]
    -> <avatar>/broll/actor-copy/<NNN>_<slug>.mp4  + manifest.json

The OUTPUT keeps the REFERENCE IMAGE's resolution (feed a 9:16 hero -> 9:16
clip). The clip is MUTED on disk by default (broll convention).

SINGLE SUBJECT RULE: DreamActor copies ONE subject. The driving video must show
exactly ONE animated character (a person OR an animal) visible in the scene. If
the video shows more than one, either use a clip/segment with a single character,
or pass --segments to split it into single-character time ranges — each range is
processed separately and the results are stitched into one clip.

A bare avatar name routes under ./avatares/<name> (repo convention; override with
AVATARES_ROOT); an explicit path is used as-is.

Usage:
    # Default look: copy a single-character dance/gesture video onto the avatar
    python3 make_actor_copy.py nora --video downloads/dance.mp4 \
      --slug nora-copies-dance

    # A specific location/look of the avatar
    python3 make_actor_copy.py nora --location cafe_barista \
      --video downloads/barista_moves.mp4

    # Video has two people at different moments -> segment (each with ONE
    # character) then stitch. Ranges accept seconds or M:SS / H:MM:SS.
    python3 make_actor_copy.py nora --video interview.mp4 \
      --segments "0-8,15-22,0:40-0:52" --slug nora-copies-host

    # Override the reference image directly (skip look resolution)
    python3 make_actor_copy.py --image avatares/nora/refs/nora_hero.png --video clip.mp4
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _common as C  # noqa: E402

SINGLE_SUBJECT_NOTICE = (
    "  NOTE: DreamActor copies ONE subject. The driving video must show exactly "
    "ONE animated\n        character (a person OR an animal) in scene. If it shows "
    "more than one, use a\n        single-character clip, or --segments to split "
    "into single-character ranges (stitched)."
)


def _parse_time(tok: str) -> float:
    """Parse seconds, M:SS or H:MM:SS into seconds."""
    tok = tok.strip()
    parts = tok.split(":")
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"bad time value: {tok!r}")
    if len(vals) == 1:
        return vals[0]
    if len(vals) == 2:
        return vals[0] * 60 + vals[1]
    if len(vals) == 3:
        return vals[0] * 3600 + vals[1] * 60 + vals[2]
    raise argparse.ArgumentTypeError(f"bad time value: {tok!r}")


def parse_segments(text: str, max_duration: float):
    """Parse 'start-end,start-end,...' -> [(start, duration), ...] in seconds."""
    segs = []
    for raw in text.split(","):
        raw = raw.strip()
        if not raw:
            continue
        # split on the last '-' so 'M:SS-M:SS' still works (times have no '-')
        if "-" not in raw:
            raise argparse.ArgumentTypeError(f"segment must be 'start-end': {raw!r}")
        a, b = raw.rsplit("-", 1)
        start, end = _parse_time(a), _parse_time(b)
        dur = end - start
        if dur <= 0:
            raise argparse.ArgumentTypeError(f"segment end must be after start: {raw!r}")
        if dur > max_duration:
            raise argparse.ArgumentTypeError(
                f"segment {raw!r} is {dur:g}s > model max {max_duration:g}s; split it further.")
        segs.append((start, dur))
    if not segs:
        raise argparse.ArgumentTypeError("no valid segments parsed from --segments.")
    return segs


def next_index(items, gen_dir):
    import re
    nums = []
    for it in items:
        m = re.match(r"(\d+)_", str(it.get("file", "")))
        if m:
            nums.append(int(m.group(1)))
    for f in gen_dir.glob("[0-9][0-9][0-9]_*"):
        m = re.match(r"(\d+)_", f.name)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def run_model_to_clip(model_ref, image_path, video_path, cut_first_second,
                      token, raw_path, out_path, *, muted):
    """Run DreamActor once and write a (muted-by-default) clip. Returns (url, info)."""
    inputs = {
        "image": open(str(image_path), "rb"),
        "video": open(str(video_path), "rb"),
        "cut_first_second": cut_first_second,
    }
    try:
        output = C.run_replicate(model_ref, inputs, token=token)
    finally:
        for fh in inputs.values():
            if hasattr(fh, "close"):
                try:
                    fh.close()
                except Exception:  # noqa: BLE001
                    pass

    if isinstance(output, (list, tuple)) and output:
        output = output[0]
    video_url = C.to_url(output)
    if video_url is None and not hasattr(output, "read"):
        print(f"Error: the model returned no video. Response: {output!r}", file=sys.stderr)
        sys.exit(1)

    if not C.save_output(output, raw_path):
        print("Error: failed to save the generated video.", file=sys.stderr)
        sys.exit(1)
    if muted:
        C.mute_clip(raw_path, out_path)
        try:
            Path(raw_path).unlink()
        except OSError:
            pass
    else:
        Path(raw_path).replace(out_path)
    return video_url, C.ffprobe_video(out_path)


def main():
    ap = argparse.ArgumentParser(
        description="Copy a video's motion onto our avatar via bytedance/dreamactor-m2.0.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("avatar", nargs="?", default=None,
                    help="Avatar folder or bare name (a bare name routes under ./avatares/<name>). "
                         "Optional if --image is inside an avatar folder.")
    ap.add_argument("--video", type=Path, required=True,
                    help="Driving video whose MOTION/expressions/lips are copied onto the avatar. "
                         "Must show exactly ONE animated character (person or animal).")
    ap.add_argument("--location", "--look", dest="location", default="default",
                    help="Which avatar look to use (default: 'default'). A name under "
                         "<avatar>/locations/<loc>/ selects that look's hero image.")
    ap.add_argument("--image", type=Path, default=None,
                    help="Explicit reference image (overrides look resolution). Its resolution "
                         "sets the output resolution.")
    ap.add_argument("--avatar-dir", type=Path, default=None,
                    help="Avatar folder (alias for the positional arg / inferred from --image).")
    ap.add_argument("--aspect", default="9:16",
                    choices=["9:16", "16:9", "1:1", "4:3", "3:4"],
                    help="Target output aspect when falling back to a camera angle "
                         "(9:16 default; 16:9 prefers _169.png angles for YouTube). "
                         "Ignored when --image is given (that image's ratio wins).")
    # Driving-video segment selection
    ap.add_argument("--segments", default=None,
                    help="Comma-separated 'start-end' ranges (seconds or M:SS/H:MM:SS), each with "
                         "ONLY ONE character on screen. Each range is processed separately and the "
                         "results are stitched into one clip. Use for multi-character source videos.")
    ap.add_argument("--trim-start", type=float, default=0.0,
                    help="Start offset (s) into the driving video (single-clip mode; default 0).")
    ap.add_argument("--trim-duration", type=float, default=None,
                    help="Length (s) of the driving segment to use (single-clip mode; default: "
                         "whole video, auto-capped at 30s).")
    ap.add_argument("--max-duration", type=float, default=C.VIDEO_MAX_DURATION,
                    help=f"Auto-trim cap in seconds (default {C.VIDEO_MAX_DURATION:g}, the model max).")
    # Model params
    ap.add_argument("--keep-first-second", action="store_true",
                    help="Keep the model's 1-second lead-in transition (cut_first_second=false). "
                         "Default: cut it.")
    ap.add_argument("--model-version", default=None,
                    help="Pin a specific Replicate version hash (default: latest of the model).")
    # Output
    ap.add_argument("--keep-audio", action="store_true",
                    help="Keep the generated audio (default: mute, broll convention). "
                         "Ignored in --segments mode (stitched output is always muted).")
    ap.add_argument("--no-fit-image", action="store_true",
                    help="Do not auto-fit the reference image to the model's size limits.")
    ap.add_argument("--slug", default=None, help="Output slug (default: from avatar+look).")
    ap.add_argument("--out-subdir", default="broll/actor-copy",
                    help="Subfolder under the avatar dir (default broll/actor-copy).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Resolve/prepare inputs and print the plan without calling the model.")
    args = ap.parse_args()

    if args.segments and (args.trim_start or args.trim_duration is not None):
        ap.error("--segments cannot be combined with --trim-start/--trim-duration.")

    # --- Resolve avatar dir (a bare name routes under ./avatares/<name>) ---
    avatar_dir = None
    if args.avatar_dir:
        avatar_dir = C.resolve_avatar_dir(args.avatar_dir)
    elif args.avatar:
        avatar_dir = C.resolve_avatar_dir(args.avatar)
        if not avatar_dir.is_dir():
            ap.error(f"Avatar folder not found: {avatar_dir} (a bare name resolves under "
                     f"./avatares/; pass an explicit path or set AVATARES_ROOT).")
    elif args.image:
        avatar_dir = C.infer_avatar_dir(args.image)
    if avatar_dir is None:
        ap.error("Could not determine the avatar folder. Pass the avatar positional / "
                 "--avatar-dir, or an --image inside an avatar folder.")

    # --- Resolve the reference image (look -> hero, or explicit --image) ---
    if args.image:
        image_path = args.image.expanduser().resolve()
        location = None
    else:
        location = args.location
        image_path = C.resolve_reference_image(avatar_dir, location, aspect=args.aspect)
        if image_path is None:
            avail = ", ".join(C.list_locations(avatar_dir))
            ap.error(f"No hero image found for avatar '{avatar_dir.name}' look "
                     f"'{location}'. Available looks: {avail}. Generate one with "
                     f"avatar-invent / avatar-location, or pass --image.")
    if not image_path.exists():
        ap.error(f"Reference image not found: {image_path}")

    # --- Resolve the driving video ---
    video_path = args.video.expanduser().resolve()
    if not video_path.exists():
        ap.error(f"Driving video not found: {video_path}")

    print(SINGLE_SUBJECT_NOTICE, file=sys.stderr)

    work_dir = avatar_dir / args.out_subdir / "_work"

    # --- Prepare the reference image once (shared across any segments) ---
    fit_image, img_meta = C.prepare_image(image_path, work_dir, disable_fit=args.no_fit_image)

    # --- Parse segments (if any) ---
    seg_ranges = None
    if args.segments:
        try:
            seg_ranges = parse_segments(args.segments, args.max_duration)
        except argparse.ArgumentTypeError as e:
            ap.error(str(e))

    cut_first_second = not args.keep_first_second
    model_ref = args.model_version and f"{C.MODEL}:{args.model_version}" or C.MODEL

    if seg_ranges:
        prepared = []
        for i, (start, dur) in enumerate(seg_ranges, 1):
            drive, vmeta = C.prepare_video(
                video_path, work_dir, trim_start=start, trim_duration=dur,
                max_duration=args.max_duration,
                out_name=f"{video_path.stem}_seg{i:02d}_drive.mp4")
            prepared.append({"start": start, "duration": dur,
                             "video": str(drive), "prep": vmeta})
        vid_summary = {"mode": "segments", "count": len(prepared), "segments": prepared}
    else:
        drive, vmeta = C.prepare_video(video_path, work_dir, trim_start=args.trim_start,
                                       trim_duration=args.trim_duration,
                                       max_duration=args.max_duration)
        vid_summary = {"mode": "single", "prepared_video": str(drive), "prep": vmeta}

    plan = {
        "avatar": avatar_dir.name,
        "location": location or "(explicit --image)",
        "reference_image": str(image_path),
        "prepared_image": str(fit_image),
        "image_fit": img_meta,
        "driving_video": str(video_path),
        "video_prep": vid_summary,
        "cut_first_second": cut_first_second,
        "model": model_ref,
    }
    print("Plan:", file=sys.stderr)
    print(json.dumps(plan, ensure_ascii=False, indent=2), file=sys.stderr)

    if args.dry_run:
        print(json.dumps({"dry_run": True, **plan}, ensure_ascii=False))
        return

    token = C.get_replicate_token()

    gen_dir = avatar_dir / args.out_subdir
    gen_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = gen_dir / "manifest.json"
    manifest = {"items": []}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
                manifest = loaded
        except json.JSONDecodeError:
            pass

    idx = next_index(manifest["items"], gen_dir)
    slug = args.slug or f"{avatar_dir.name}-{C.slugify(location or 'ref')}-{video_path.stem}"
    base = f"{idx:03d}_{C.slugify(slug)}"
    out_path = gen_dir / f"{base}.mp4"

    seg_records = None
    if seg_ranges:
        if args.keep_audio:
            print("  (--keep-audio ignored in --segments mode: stitched output is muted)",
                  file=sys.stderr)
        seg_clips = []
        seg_records = []
        for i, seg in enumerate(prepared, 1):
            print(f"  [segment {i}/{len(prepared)}] {seg['start']:g}s +{seg['duration']:g}s ...",
                  file=sys.stderr)
            seg_out = work_dir / f"{base}_seg{i:02d}.mp4"
            seg_raw = work_dir / f"_{base}_seg{i:02d}_raw.mp4"
            url, info = run_model_to_clip(model_ref, fit_image, seg["video"],
                                          cut_first_second, token, seg_raw, seg_out, muted=True)
            seg_clips.append(seg_out)
            seg_records.append({
                "index": i, "start": seg["start"], "duration": seg["duration"],
                "clip": str(seg_out), "source_url": url,
                "width": info.get("width"), "height": info.get("height"),
                "duration_actual": (round(info["duration"], 2) if info.get("duration") else None),
            })
        print(f"  Stitching {len(seg_clips)} segment(s) -> {out_path.name} ...", file=sys.stderr)
        C.concat_clips(seg_clips, out_path)
        for c in seg_clips:
            try:
                Path(c).unlink()
            except OSError:
                pass
        out_info = C.ffprobe_video(out_path)
        muted = True
        video_url = None
    else:
        raw_path = gen_dir / f"_{base}_raw.mp4"
        muted = not args.keep_audio
        video_url, out_info = run_model_to_clip(model_ref, fit_image, drive,
                                                cut_first_second, token, raw_path, out_path,
                                                muted=muted)

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    entry = {
        "file": out_path.name,
        "type": "broll-actor-copy",
        "model": model_ref,
        "avatar": avatar_dir.name,
        "location": location,
        "reference_image": str(image_path),
        "prepared_image": (str(fit_image) if img_meta.get("fitted") else None),
        "driving_video": str(video_path),
        "mode": ("segments" if seg_ranges else "single"),
        "segments": seg_records,
        "trim_start": (None if seg_ranges else args.trim_start),
        "trim_duration": (None if seg_ranges else vmeta.get("trim_duration")),
        "cut_first_second": cut_first_second,
        "muted": muted,
        "width": out_info.get("width"),
        "height": out_info.get("height"),
        "duration_actual": (round(out_info["duration"], 2) if out_info.get("duration") else None),
        "source_url": video_url,
        "created_at": now,
    }
    manifest["items"].append(entry)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")

    print(f"\nDone — broll: {out_path}  ({entry['duration_actual']}s, "
          f"{entry['width']}x{entry['height']}, "
          f"{'muted' if entry['muted'] else 'with audio'}"
          f"{', ' + str(len(seg_records)) + ' segments' if seg_records else ''})", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)
    print(json.dumps({
        "video": str(out_path),
        "duration": entry["duration_actual"],
        "width": entry["width"],
        "height": entry["height"],
        "avatar": avatar_dir.name,
        "location": location,
        "mode": entry["mode"],
        "segments": (len(seg_records) if seg_records else None),
        "reference_image": str(image_path),
        "driving_video": str(video_path),
        "manifest": str(manifest_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
