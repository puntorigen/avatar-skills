#!/usr/bin/env python3
"""Generate a hyper-realistic complementary B-roll clip with Pruna p-video.

The clip reinforces an idea visually (people in situations, environments,
objects) WITHOUT the main avatar/presenter, so it can sit under an avatar
voice-over in a final composite reel.

Backend: prunaai/p-video on Replicate (text-to-video, exact 1-20s duration,
720p/1080p). Audio is disabled so the clip is clean B-roll for voice-over.

Pipeline:
  1. Wrap the scene description in a photoreal/cinematic prompt with a camera
     move + "whole frame stays in motion" cues (unless --raw-prompt)
  2. Generate with p-video at the exact requested duration (e.g. 3 or 6s), 720p
  3. Normalize to the exact duration and strip audio (ffmpeg, best-effort)
  4. Save to <out-dir>/<NNN>_<slug>.mp4 + append a manifest.json entry

Output JSON (stdout) carries the saved path and metadata for orchestration.

Examples:
    python3 generate_broll.py "manos sosteniendo un smartphone en penumbra, \
revisando Instagram de noche, primer plano" --duration 6 --camera push_in

    python3 generate_broll.py "mujer pensativa mirando por la ventana al atardecer, \
plano medio, luz cálida de contraluz" --duration 3 --camera pan_right \
--avatar-dir /path/to/lolo
"""

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


REALISM_PREFIX = (
    "Hyper-realistic cinematic B-roll footage, shot on a full-frame cinema camera "
    "with a fast prime lens and shallow depth of field. Natural, motivated lighting, "
    "lifelike skin texture and pores, subtle film grain and a filmic color grade. "
    "Photographic and true to life (not animated, not CGI). Scene: "
)

# Camera-movement presets. Every shot gets a deliberate camera move so the WHOLE
# frame moves (not just the subject) — the #1 fix for the "static background"
# tell that makes AI B-roll look fake.
CAMERA_PRESETS = {
    "handheld": "Filmed with a subtle handheld camera: gentle, organic drift, breathing motion and natural micro-shake throughout the whole clip.",
    "push_in": "Continuous slow, smooth cinematic dolly push-in toward the subject across the entire shot.",
    "pull_out": "Continuous slow, smooth cinematic dolly pull-out away from the subject across the entire shot.",
    "pan_left": "Continuous slow camera pan to the left across the entire shot.",
    "pan_right": "Continuous slow camera pan to the right across the entire shot.",
    "orbit": "Slow camera orbit gliding around the subject across the entire shot.",
    "static": "Locked-off tripod framing with no camera movement, while the scene itself stays fully alive with natural motion.",
}

# Always-on clause forcing the entire frame to stay in motion for the full clip.
MOTION_CLAUSE = (
    " The entire frame stays alive with continuous, natural motion for the full duration: "
    "the subject breathes and shifts, hair and clothing move, and out-of-focus background "
    "elements, ambient light and bokeh drift and flicker. Realistic motion blur. "
    "Never a frozen or static background, no still-photo-come-to-life effect."
)

# Performance clause so people are alive WITHOUT looking frantic. Aims for the
# middle ground: natural and restrained (not a mannequin, not flailing).
# Speech/mouth motion is conditioned on conversation so solo/pensive subjects stay quiet.
PEOPLE_PERFORMANCE = (
    " Any people in the shot move with natural, relaxed and controlled body language: "
    "subtle, purposeful hand and head gestures, small weight shifts, lively eyes and "
    "believable facial expressions; when they are in conversation their lips move and they "
    "react to each other as they speak. Keep all movement realistic, calm and restrained — "
    "ordinary human behavior, never stiff or mannequin-like and never exaggerated, frantic, "
    "flailing or theatrical."
)

CONSTRAINTS = (
    " No on-screen text, captions, subtitles, watermark or logos. The main presenter/host "
    "does NOT appear in this shot — show only the people, objects and environment described."
)


def build_prompt(description, raw=False, aspect_ratio="9:16", camera="handheld", action=None):
    if raw:
        return description
    cam = CAMERA_PRESETS.get(camera, CAMERA_PRESETS["handheld"])
    act = f" Continuous action: {action.strip()}." if action else ""
    framing = ""
    if aspect_ratio == "9:16":
        framing = " Vertical 9:16 framing composed for mobile social media."
    elif aspect_ratio == "16:9":
        framing = " Horizontal 16:9 cinematic framing."
    return (f"{REALISM_PREFIX}{description.strip()}.{act} {cam}"
            f"{MOTION_CLAUSE}{PEOPLE_PERFORMANCE}{CONSTRAINTS}{framing}")


def resolve_out_dir(args):
    """Return (out_dir, manifest_path). Prefers an avatar's broll/ folder."""
    avatar_dir = None
    if args.avatar_dir:
        avatar_dir = Path(args.avatar_dir).expanduser().resolve()

    if avatar_dir and avatar_dir.is_dir():
        out_dir = avatar_dir / "broll"
    elif args.out_dir:
        out_dir = Path(args.out_dir).expanduser().resolve()
    else:
        out_dir = Path.cwd() / "broll"

    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir, out_dir / "manifest.json"


def main():
    ap = argparse.ArgumentParser(
        description="Generate hyper-realistic complementary B-roll clips with Pruna p-video (Replicate).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("description", help="Scene description (what the B-roll should show).")
    ap.add_argument("--duration", type=int, default=6,
                    help="Clip length in seconds (1-20; use 3 or 6 for reel inserts). Default: 6.")
    ap.add_argument("--aspect-ratio", default="9:16",
                    choices=["16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "1:1"],
                    help="Output aspect ratio. Default: 9:16 (reels).")
    ap.add_argument("--resolution", default="720p", choices=["720p", "1080p"],
                    help="Output resolution. Default: 720p.")
    ap.add_argument("--fps", type=int, default=24, choices=[24, 48],
                    help="Frames per second. Default: 24.")
    ap.add_argument("--camera", default="handheld",
                    choices=list(CAMERA_PRESETS.keys()),
                    help="Camera movement so the whole frame moves (avoids static-background look). Default: handheld.")
    ap.add_argument("--action", default=None,
                    help="Explicit continuous performance for the people (gestures, talking, "
                         "reactions). Fixes the 'mannequin' look in scenes with people interacting.")
    ap.add_argument("--seed", type=int, default=None, help="Reproducible generation seed.")
    ap.add_argument("--draft", action="store_true",
                    help="Draft mode: fast, lower-quality preview for iterating on the prompt.")
    ap.add_argument("--no-upsample", action="store_true",
                    help="Disable prompt upsampling (honor the prompt verbatim).")
    ap.add_argument("--keep-audio", action="store_true",
                    help="Keep generated audio (off by default for clean B-roll).")
    ap.add_argument("--raw-prompt", action="store_true",
                    help="Use the description verbatim (skip the realism/camera wrapper).")
    ap.add_argument("--avatar-dir", default=None,
                    help="Avatar folder; saves to <avatar>/broll/.")
    ap.add_argument("--out-dir", default=None,
                    help="Explicit output folder (default ./broll or <avatar>/broll).")
    ap.add_argument("--out-name", default=None,
                    help="Override the output filename stem (without extension).")
    args = ap.parse_args()

    if args.duration < 1 or args.duration > 20:
        print("Error: --duration must be between 1 and 20 seconds.", file=sys.stderr)
        sys.exit(1)

    prompt = build_prompt(args.description, raw=args.raw_prompt,
                          aspect_ratio=args.aspect_ratio, camera=args.camera,
                          action=args.action)

    out_dir, manifest_path = resolve_out_dir(args)
    manifest = C.load_manifest(manifest_path)
    idx = C.next_index(manifest["items"], out_dir)
    stem = args.out_name or f"{idx:03d}_{C.slugify(args.description)}"
    raw_path = out_dir / f".{stem}.raw.mp4"
    final_path = out_dir / f"{stem}.mp4"

    print(f"Scene: {args.description}", file=sys.stderr)
    print(f"Camera: {args.camera} | {args.duration}s | {args.resolution} | {args.aspect_ratio}", file=sys.stderr)
    print(f"Prompt: {prompt}", file=sys.stderr)
    print(f"Output: {final_path}", file=sys.stderr)

    inputs = {
        "prompt": prompt,
        "duration": args.duration,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "fps": args.fps,
        "draft": bool(args.draft),
        "prompt_upsampling": not args.no_upsample,
        "save_audio": bool(args.keep_audio),
    }
    if args.seed is not None:
        inputs["seed"] = args.seed

    output = C.run_replicate(C.MODEL, inputs, token=C.get_replicate_token())
    saved_raw = C.save_output(output, raw_path)
    if not saved_raw or not Path(saved_raw).exists():
        print("Error: p-video generation failed (no output).", file=sys.stderr)
        sys.exit(2)

    C.finalize_clip(saved_raw, final_path, args.duration, keep_audio=bool(args.keep_audio))
    try:
        Path(saved_raw).unlink(missing_ok=True)
    except OSError:
        pass

    info = C.probe_video(final_path)
    source_url = C.to_url(output if not isinstance(output, (list, tuple)) else (output[0] if output else None))

    entry = {
        "index": idx,
        "file": final_path.name,
        "path": str(final_path),
        "description": args.description,
        "prompt": prompt,
        "model": C.MODEL,
        "camera": args.camera,
        "action": args.action,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "fps": args.fps,
        "requested_duration": args.duration,
        "draft": bool(args.draft),
        "prompt_upsampling": not args.no_upsample,
        "audio": bool(args.keep_audio),
        "seed": args.seed,
        "source_url": source_url,
        "duration_sec": info.get("duration"),
        "width": info.get("width"),
        "height": info.get("height"),
        "fps_actual": info.get("fps"),
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    manifest["items"].append(entry)
    C.write_manifest(manifest_path, manifest)

    print(f"Done: {final_path}", file=sys.stderr)
    print(f"Manifest: {manifest_path}", file=sys.stderr)

    print(json.dumps({
        "video": str(final_path),
        "manifest": str(manifest_path),
        **{k: entry[k] for k in (
            "description", "duration_sec", "width", "height",
            "aspect_ratio", "model", "camera", "requested_duration",
        )},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
