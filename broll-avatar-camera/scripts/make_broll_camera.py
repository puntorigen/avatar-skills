#!/usr/bin/env python3
"""Animate ONE action/POV start frame into a short B-roll clip via prunaai/p-video-avatar.

This is the "avatar SEEN doing something" B-roll, built on the SAME model as our
talking-heads (avatar-talking-video → prunaai/p-video-avatar), so the avatar's
face/wardrobe/room stay consistent between talking shots and action shots.

  start frame (image) + beat narration (audio) + ACTION (video_prompt) [+ negative_prompt]
    -> prunaai/p-video-avatar
    -> download -> mute (-an)  [the master narration is laid back on by avatar-reel-composer]
    -> <avatar>/broll/camera/<NNN>_<slug>.mp4  + manifest.json

Why audio: p-video-avatar is audio-driven. Pass the EXACT narration slice for this beat:
  - the avatar LIP-SYNCS to it when the mouth is visible (looks like the avatar saying
    that line while doing the action), and
  - the clip length follows the audio, so the clip matches its reel slot exactly.
We still MUTE the output so the composer overlays the same master narration (no double
audio); the lip-sync visuals remain.

video_prompt = the ACTION (this is the model's "how the person behaves while speaking"):
  short, positive, e.g. "takes a book from a shelf and reads it while talking".
negative_prompt = keywords to keep OUT (extra people, distorted hands, text/watermark,
  scene cuts, ...). A sensible action-broll default is used unless you pass --negative-prompt.

Usage:
    # Action beat that plays under a narration line (lip-sync if the face/mouth is visible):
    python3 make_broll_camera.py --avatar-dir antiguo \
      --image antiguo/broll/camera/_frames/antiguo_shelf_reach_916.png \
      --audio antiguo/reels/NNN_slug/scenes/chunk_s4.mp3 \
      --action "takes a book from a shelf and looks at it while talking" \
      --slug antiguo-shelf-book

    # Quick test without a cloned-voice beat (uses the model's BUILT-IN generic TTS — not
    # the avatar's real voice; only for scouting motion):
    python3 make_broll_camera.py --avatar-dir antiguo --image frame_916.png \
      --voice-script "Numbers remember what we forget." \
      --action "writes numbers in an open book" --slug antiguo-writes

Notes:
- p-video-avatar works best when the avatar (ideally the face) is in frame. For a
  FACE-FREE beat or a precise start->end object move, use seedance-2 start+end instead.
- Clip is MUTED by default (broll convention). Pass --keep-audio to keep the driven audio
  (handy for a standalone lip-sync QA preview).
- No-freeze rule (project): the clip length follows the audio, so pass the exact beat
  slice and the clip matches its slot (the composer trims, never freezes).
"""

import argparse
import datetime
import json
import re
import sys
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    MODEL, get_replicate_token, infer_avatar_dir, run_replicate, save_output,
    to_url, mute_clip, ffprobe_duration,
)

RESOLUTIONS = ["720p", "1080p"]

# Action-broll default: keep extra people / mangled anatomy / on-screen text / cuts out.
# (Deliberately does NOT include "looking away from camera" — in an action shot the avatar
# SHOULD look at what they're doing, not the lens.)
DEFAULT_NEGATIVE_PROMPT = (
    "multiple people, extra person, extra limbs, distorted hands, deformed fingers, "
    "warped or melting objects, morphing book, subtitles, text, captions, watermark, "
    "logo, blurry, low quality, scene change, hard cut, camera flash"
)


def slugify(text, maxlen=48):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:maxlen].strip("-") or "broll"


def next_index(items, gen_dir):
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


def load_negative_from_profile(avatar_dir, explicit_path, disabled):
    """Best-effort: reuse the avatar's talking_profile.json negative_prompt as a fallback."""
    if disabled:
        return None
    path = explicit_path.expanduser() if explicit_path else (avatar_dir / "talking_profile.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("negative_prompt")
    except (json.JSONDecodeError, OSError):
        return None


def main():
    ap = argparse.ArgumentParser(
        description="Animate an action start frame into a B-roll clip via prunaai/p-video-avatar.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--image", type=Path, required=True,
                    help="Start frame (first frame). Feed a 9:16 frame for a 9:16 clip.")
    ap.add_argument("--audio", type=Path, default=None,
                    help="Beat narration slice that DRIVES the clip: lip-sync (if the mouth is "
                         "visible) + sets the clip length. Pass the exact slice for this beat.")
    ap.add_argument("--video-prompt", "--action", "--prompt", dest="video_prompt", default=None,
                    help="The ACTION (model's 'how the person behaves while speaking'): short, "
                         "positive, e.g. \"takes a book from a shelf while talking\".")
    ap.add_argument("--video-prompt-file", type=Path, default=None,
                    help="Read --video-prompt from a file.")
    ap.add_argument("--negative-prompt", default=None,
                    help="Keywords to keep OUT. Default: an action-broll preset (or the avatar's "
                         "talking_profile.json negative_prompt via --use-profile-negative).")
    ap.add_argument("--use-profile-negative", action="store_true",
                    help="Use the avatar talking_profile.json negative_prompt as the default "
                         "instead of the built-in action-broll preset.")
    ap.add_argument("--profile", type=Path, default=None, help="talking_profile.json path.")
    ap.add_argument("--strength-negative-prompt", type=float, default=None,
                    help="Negative-prompt strength (model default 0.5).")
    # Built-in TTS fallback (generic voice — only for quick scouting, NOT the cloned voice).
    ap.add_argument("--voice-script", default=None,
                    help="Words to speak via the model's BUILT-IN TTS when no --audio is given "
                         "(generic voice, not the avatar's clone — scouting only).")
    ap.add_argument("--voice", default=None, help="Built-in TTS voice (with --voice-script).")
    ap.add_argument("--voice-language", default=None,
                    help="Built-in TTS language/accent (with --voice-script).")
    ap.add_argument("--voice-prompt", default=None,
                    help="Built-in TTS delivery style (with --voice-script).")
    ap.add_argument("--avatar-dir", type=Path, default=None,
                    help="Avatar folder (auto-inferred from --image if omitted).")
    ap.add_argument("--resolution", default="720p", choices=RESOLUTIONS)
    ap.add_argument("--disable-prompt-upsampling", action="store_true",
                    help="Use --video-prompt verbatim (skip automatic visual-prompt enhancement).")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--keep-audio", action="store_true",
                    help="Keep the driven audio (default: mute, broll convention).")
    ap.add_argument("--slug", default=None, help="Output slug (default: from the action).")
    ap.add_argument("--out-subdir", default="broll/camera",
                    help="Subfolder under the avatar dir (default broll/camera).")
    args = ap.parse_args()

    image_path = args.image.expanduser().resolve()
    if not image_path.exists():
        ap.error(f"Start image not found: {image_path}")

    video_prompt = None
    if args.video_prompt_file:
        video_prompt = args.video_prompt_file.read_text(encoding="utf-8").strip()
    elif args.video_prompt:
        video_prompt = args.video_prompt.strip()
    if not video_prompt:
        ap.error("Provide --video-prompt/--action (what the avatar is doing in the shot).")

    audio_path = None
    if args.audio:
        audio_path = args.audio.expanduser().resolve()
        if not audio_path.exists():
            ap.error(f"--audio not found: {audio_path}")
    if audio_path is None and not args.voice_script:
        ap.error("Provide --audio (the beat narration slice; recommended) or --voice-script "
                 "(built-in generic TTS, for quick tests only).")

    avatar_dir = (args.avatar_dir.expanduser().resolve() if args.avatar_dir
                  else infer_avatar_dir(image_path))
    if avatar_dir is None:
        ap.error("Could not determine the avatar folder; pass --avatar-dir.")

    # Resolve the negative prompt: explicit > profile (opt-in) > action-broll preset.
    if args.negative_prompt is not None:
        negative_prompt = args.negative_prompt
    elif args.use_profile_negative:
        negative_prompt = load_negative_from_profile(avatar_dir, args.profile, False) \
            or DEFAULT_NEGATIVE_PROMPT
    else:
        negative_prompt = DEFAULT_NEGATIVE_PROMPT

    token = get_replicate_token()

    inputs = {
        "image": open(str(image_path), "rb"),
        "resolution": args.resolution,
        "video_prompt": video_prompt,
        "disable_prompt_upsampling": args.disable_prompt_upsampling,
    }
    if audio_path is not None:
        inputs["audio"] = open(str(audio_path), "rb")
    else:
        inputs["voice_script"] = args.voice_script
        if args.voice:
            inputs["voice"] = args.voice
        if args.voice_language:
            inputs["voice_language"] = args.voice_language
        if args.voice_prompt:
            inputs["voice_prompt"] = args.voice_prompt
    if negative_prompt:
        inputs["negative_prompt"] = negative_prompt
        if args.strength_negative_prompt is not None:
            inputs["strength_negative_prompt"] = args.strength_negative_prompt
    if args.seed is not None:
        inputs["seed"] = args.seed

    drive = f"audio-driven ({audio_path.name})" if audio_path else "built-in TTS"
    print(f"  Animating action frame via {MODEL} ({args.resolution}, {drive}) ...",
          file=sys.stderr)
    try:
        output = run_replicate(MODEL, inputs, token=token)
    finally:
        for k in ("image", "audio"):
            fh = inputs.get(k)
            if hasattr(fh, "close"):
                try:
                    fh.close()
                except Exception:  # noqa: BLE001
                    pass

    if isinstance(output, (list, tuple)) and output:
        output = output[0]
    video_url = to_url(output)
    if video_url is None and not hasattr(output, "read"):
        print(f"Error: the model returned no video. Response: {output!r}", file=sys.stderr)
        sys.exit(1)

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
    base = f"{idx:03d}_{slugify(args.slug or video_prompt)}"
    raw_path = gen_dir / f"_{base}_raw.mp4"
    out_path = gen_dir / f"{base}.mp4"

    if not save_output(output, raw_path):
        print("Error: failed to save the generated video.", file=sys.stderr)
        sys.exit(1)

    if args.keep_audio:
        raw_path.replace(out_path)
    else:
        mute_clip(raw_path, out_path)
        try:
            raw_path.unlink()
        except OSError:
            pass

    dur = ffprobe_duration(out_path)
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    entry = {
        "file": out_path.name,
        "type": "broll-avatar-camera",
        "model": MODEL,
        "image": str(image_path),
        "audio": (str(audio_path) if audio_path else None),
        "audio_driven": bool(audio_path),
        "video_prompt": video_prompt,
        "negative_prompt": negative_prompt,
        "strength_negative_prompt": args.strength_negative_prompt,
        "voice_script": (args.voice_script if not audio_path else None),
        "resolution": args.resolution,
        "disable_prompt_upsampling": args.disable_prompt_upsampling,
        "muted": (not args.keep_audio),
        "seed": args.seed,
        "duration_actual": (round(dur, 2) if dur else None),
        "source_url": video_url,
        "created_at": now,
    }
    manifest["items"].append(entry)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")

    print(f"\nDone — broll: {out_path}  ({entry['duration_actual']}s, "
          f"{'muted' if entry['muted'] else 'with audio'})", file=sys.stderr)
    print(json.dumps({
        "video": str(out_path),
        "duration": entry["duration_actual"],
        "image": str(image_path),
        "audio": entry["audio"],
        "video_prompt": video_prompt,
        "resolution": args.resolution,
        "manifest": str(manifest_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
