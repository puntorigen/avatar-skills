#!/usr/bin/env python3
"""Generate a talking-head avatar video from text + a camera-angle image.

Pipeline (two stages):

  1. TTS: synthesize the text in the avatar's cloned voice by delegating to the
     `voice-clone` skill (generate_speech.py). It reuses the avatar's trained
     voice, or trains one first from --source if the avatar has none yet.
  2. Lip-sync video: send the camera-angle image (`image`) and the generated
     mp3 (`audio`) to prunaai/p-video-avatar on Replicate at the chosen
     resolution, and download the resulting MP4.

Output: <avatar>/generated-videos/<NNN>_<slug>.mp4 plus a manifest.json entry
recording the text, voice_id, image, audio, and all the video params used.

Usage:
    # Text -> cloned-voice audio -> talking-head video, using a camera angle:
    python3 generate_video.py "Hola, soy Lolo" \
        --image lolo/angles/skill_test/lolo_push_in.png

    # Force a higher resolution and a custom visual prompt:
    python3 generate_video.py "Big news today!" \
        --image lolo/angles/skill_test/lolo_push_in.png \
        --resolution 1080p --emotion happy \
        --video-prompt "The person is talking and smiling warmly."

    # Reuse an already-generated mp3 instead of running TTS:
    python3 generate_video.py --audio lolo/generated-audios/001_hola.mp3 \
        --image lolo/angles/skill_test/lolo_push_in.png

    # Train the voice first if the avatar has none yet:
    python3 generate_video.py "Hello there" \
        --image lolo/angles/skill_test/lolo_push_in.png \
        --source lolo/videos/2026-05-16_voice/voice_concat.mp3
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _common import (  # noqa: E402
    MODEL,
    get_replicate_token,
    infer_avatar_dir,
    run_replicate,
    save_output,
    to_url,
)

DEFAULT_VOICE_CLONE_SCRIPT = (
    Path.home() / ".cursor/skills/voice-clone/scripts/generate_speech.py"
)
RESOLUTIONS = ["720p", "1080p"]
DEFAULT_VIDEO_PROMPT = "The person is talking."
# Forwarded verbatim to voice-clone's generate_speech.py.
EMOTIONS = ["auto", "happy", "sad", "angry", "fearful", "disgusted",
            "surprised", "calm", "fluent", "neutral"]


def slugify(text: str, maxlen: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:maxlen].strip("-") or "video"


def next_index(items: list, gen_dir: Path) -> int:
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


def enrich_from_audio_manifest(avatar_dir: Path, audio_path: Path) -> dict:
    """Look up voice-clone's audio manifest entry for the generated mp3.

    Returns voice_name / model / emotion / language_boost when the entry exists,
    so the video manifest carries the full voice record (best-effort).
    """
    man = avatar_dir / "generated-audios" / "manifest.json"
    if not man.exists():
        return {}
    try:
        items = json.loads(man.read_text(encoding="utf-8")).get("items", [])
    except (json.JSONDecodeError, OSError):
        return {}
    for it in items:
        if it.get("file") == audio_path.name:
            return {k: it.get(k) for k in
                    ("voice_id", "voice_name", "voice_train_model",
                     "emotion", "language_boost")}
    return {}


def load_talking_profile(avatar_dir: Path, explicit_path: Path | None,
                         disabled: bool) -> dict:
    """Load the avatar's reusable talking profile (video_prompt / negative_prompt).

    The profile keeps the p-video-avatar prompt consistent with the avatar's
    real on-camera personality across clips. Resolution:
      explicit --profile  ->  <avatar>/talking_profile.json  ->  {} (none).
    Returns {} when disabled or absent.
    """
    if disabled:
        return {}
    path = explicit_path.expanduser() if explicit_path else (avatar_dir / "talking_profile.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: could not read talking profile {path}: {e}", file=sys.stderr)
        return {}
    data["_path"] = str(path)
    return data


def run_tts(args, avatar_dir: Path, voice_clone_script: Path) -> dict:
    """Call voice-clone's generate_speech.py and parse its JSON result.

    Returns a dict with at least: audio, voice_id, emotion, language_boost.
    """
    cmd = [sys.executable, str(voice_clone_script)]
    if args.text_file:
        cmd += ["--text-file", str(args.text_file)]
    else:
        cmd += [args.text]
    cmd += ["--avatar-dir", str(avatar_dir)]
    if args.name:
        cmd += ["--name", args.name]
    if args.voice_id:
        cmd += ["--voice-id", args.voice_id]
    if args.source:
        cmd += ["--source", args.source]
    cmd += ["--emotion", args.emotion]
    cmd += ["--language-boost", args.language_boost]
    cmd += ["--speed", str(args.speed)]
    cmd += ["--volume", str(args.volume)]
    cmd += ["--pitch", str(args.pitch)]
    cmd += ["--audio-format", "mp3"]

    print("  [1/2] Synthesizing audio via voice-clone ...", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip()
        print(tail, file=sys.stderr)
        print("Error: TTS step (voice-clone) failed.", file=sys.stderr)
        sys.exit(1)
    # generate_speech.py prints a JSON object as its last stdout block.
    try:
        start = proc.stdout.index("{")
        return json.loads(proc.stdout[start:])
    except (ValueError, json.JSONDecodeError):
        print(proc.stdout, file=sys.stderr)
        print("Error: could not parse voice-clone output.", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(
        description="Generate a talking-head avatar video (TTS + prunaai/p-video-avatar).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # --- Stage 1: what to say ---
    ap.add_argument("text", nargs="?", default=None,
                    help="Text the avatar should say (or use --text-file / --audio)")
    ap.add_argument("--text-file", type=Path, default=None,
                    help="Read the text to say from a file")
    ap.add_argument("--audio", type=Path, default=None,
                    help="Use this existing mp3/wav directly and SKIP TTS (the lip-sync driver)")
    # --- Avatar + image ---
    ap.add_argument("--image", type=Path, default=None,
                    help="Avatar portrait / camera-angle image (from avatar-camera-angles). "
                         "Defaults to <avatar>/frames/frame_0001.png if omitted.")
    ap.add_argument("--avatar-dir", type=Path, default=None,
                    help="Avatar folder (auto-inferred from --image/--audio if omitted)")
    # --- Voice options (forwarded to voice-clone) ---
    ap.add_argument("--name", default=None, help="Trained voice name to use/create (auto if omitted)")
    ap.add_argument("--voice-id", default=None, help="Use this MiniMax voice_id directly")
    ap.add_argument("--source", default=None,
                    help="Audio/voice or video to TRAIN the voice if the avatar has none yet")
    ap.add_argument("--emotion", default="auto", choices=EMOTIONS,
                    help="Delivery style for TTS; 'auto' lets MiniMax choose")
    ap.add_argument("--language-boost", default="detect",
                    help="'detect' (auto) or a MiniMax locale (e.g. Spanish, English)")
    ap.add_argument("--speed", type=float, default=1.0, help="TTS speed (0.5-2.0)")
    ap.add_argument("--volume", type=float, default=1.0, help="TTS volume (0-10)")
    ap.add_argument("--pitch", type=int, default=0, help="TTS pitch in semitones (-12..12)")
    # --- Stage 2: video options (prunaai/p-video-avatar) ---
    ap.add_argument("--resolution", default="720p", choices=RESOLUTIONS,
                    help="Output video resolution (default: 720p)")
    ap.add_argument("--video-prompt", default=None,
                    help="What the person is doing while speaking. If omitted, uses the avatar's "
                         f"talking_profile.json, else {DEFAULT_VIDEO_PROMPT!r}")
    ap.add_argument("--negative-prompt", default=None,
                    help="What to avoid in the video. If omitted, uses the profile's negative_prompt.")
    ap.add_argument("--profile", type=Path, default=None,
                    help="Talking-profile JSON (video_prompt/negative_prompt). "
                         "Default: <avatar>/talking_profile.json if it exists.")
    ap.add_argument("--no-profile", action="store_true",
                    help="Ignore any talking_profile.json and use the basic default prompt.")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for reproducible generation")
    ap.add_argument("--disable-prompt-upsampling", action="store_true",
                    help="Use --video-prompt verbatim (skip automatic visual-prompt enhancement)")
    ap.add_argument("--out-name", default=None, help="Output filename (without extension)")
    ap.add_argument("--voice-clone-script", default=str(DEFAULT_VOICE_CLONE_SCRIPT),
                    help="Path to voice-clone's generate_speech.py")
    args = ap.parse_args()

    # --- Resolve avatar dir ---
    avatar_dir = None
    if args.avatar_dir:
        avatar_dir = args.avatar_dir.expanduser().resolve()
    elif args.image:
        avatar_dir = infer_avatar_dir(args.image)
    elif args.audio:
        avatar_dir = infer_avatar_dir(args.audio)
    if avatar_dir is None:
        ap.error("Could not determine the avatar folder. Pass --avatar-dir, or an "
                 "--image/--audio inside an avatar folder (one containing a videos/ dir).")

    # --- Resolve the image (camera angle / portrait) ---
    if args.image:
        image_path = args.image.expanduser().resolve()
    else:
        image_path = avatar_dir / "frames" / "frame_0001.png"
        print(f"  No --image given; defaulting to {image_path}", file=sys.stderr)
    if not image_path.exists():
        ap.error(f"Image not found: {image_path}. Generate one with the "
                 f"avatar-camera-angles skill and pass it via --image.")

    # --- Resolve the driving audio (existing file or TTS) ---
    text = None
    if args.audio:
        audio_path = args.audio.expanduser().resolve()
        if not audio_path.exists():
            ap.error(f"Audio not found: {audio_path}")
        tts_meta = {"voice_id": args.voice_id, "voice_name": args.name,
                    "emotion": None, "language_boost": None}
        print(f"  Using provided audio (skipping TTS): {audio_path}", file=sys.stderr)
    else:
        if args.text_file:
            if not args.text_file.exists():
                ap.error(f"--text-file not found: {args.text_file}")
            text = args.text_file.read_text(encoding="utf-8").strip()
        elif args.text:
            text = args.text.strip()
        else:
            ap.error("Provide the text to say (positional or --text-file), or pass --audio.")
        if not text:
            ap.error("The text is empty.")

        vc_script = Path(args.voice_clone_script).expanduser()
        if not vc_script.exists():
            ap.error(f"voice-clone script not found: {vc_script}")
        tts_meta = run_tts(args, avatar_dir, vc_script)
        audio_path = Path(tts_meta["audio"]).expanduser().resolve()
        # Enrich with the fuller record voice-clone wrote to its audio manifest
        # (voice_name / train model aren't in generate_speech.py's stdout JSON).
        tts_meta = {**enrich_from_audio_manifest(avatar_dir, audio_path), **tts_meta}
        print(f"  Audio ready: {audio_path}  (voice_id: {tts_meta.get('voice_id')})", file=sys.stderr)

    token = get_replicate_token()

    # --- Resolve prompts: explicit flag > avatar talking profile > basic default ---
    profile = load_talking_profile(avatar_dir, args.profile, args.no_profile)
    if args.video_prompt is not None:
        video_prompt = args.video_prompt
    elif profile.get("video_prompt"):
        video_prompt = profile["video_prompt"]
        print(f"  Using talking profile video_prompt ({profile['_path']})", file=sys.stderr)
    else:
        video_prompt = DEFAULT_VIDEO_PROMPT
    if args.negative_prompt is not None:
        negative_prompt = args.negative_prompt
    else:
        negative_prompt = profile.get("negative_prompt")

    # --- Stage 2: lip-sync video ---
    inputs = {
        "image": open(str(image_path), "rb"),
        "audio": open(str(audio_path), "rb"),
        "resolution": args.resolution,
        "video_prompt": video_prompt,
        "disable_prompt_upsampling": args.disable_prompt_upsampling,
    }
    if negative_prompt:
        inputs["negative_prompt"] = negative_prompt
    if args.seed is not None:
        inputs["seed"] = args.seed

    print(f"  [2/2] Generating talking-head video ({args.resolution}) — this can take a few minutes ...",
          file=sys.stderr)
    try:
        output = run_replicate(MODEL, inputs, token=token)
    finally:
        for fh in (inputs["image"], inputs["audio"]):
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass

    if isinstance(output, (list, tuple)) and output:
        output = output[0]
    video_url = to_url(output)  # FileOutput exposes .url even when readable
    if video_url is None and not hasattr(output, "read"):
        print(f"Error: the model returned no video. Response: {output!r}", file=sys.stderr)
        sys.exit(1)

    # --- Save + manifest ---
    gen_dir = avatar_dir / "generated-videos"
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
    slug_seed = text or audio_path.stem
    base = args.out_name or f"{idx:03d}_{slugify(slug_seed)}"
    out_path = gen_dir / f"{base}.mp4"
    saved = save_output(output, out_path)
    if not saved:
        print("Error: failed to save the generated video.", file=sys.stderr)
        sys.exit(1)

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    entry = {
        "file": out_path.name,
        "text": text,
        "image": str(image_path),
        "audio": str(audio_path),
        "voice_id": tts_meta.get("voice_id"),
        "voice_name": tts_meta.get("voice_name"),
        "voice_train_model": tts_meta.get("voice_train_model"),
        "emotion": tts_meta.get("emotion"),
        "language_boost": tts_meta.get("language_boost"),
        "speed": (args.speed if text is not None else None),
        "volume": (args.volume if text is not None else None),
        "pitch": (args.pitch if text is not None else None),
        "model": MODEL,
        "resolution": args.resolution,
        "video_prompt": video_prompt,
        "negative_prompt": negative_prompt,
        "profile": profile.get("_path"),
        "seed": args.seed,
        "disable_prompt_upsampling": args.disable_prompt_upsampling,
        "source_url": video_url,
        "created_at": now,
    }
    manifest["items"].append(entry)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\nDone — video: {out_path}", file=sys.stderr)
    print(f"  image: {image_path.name}  |  audio: {audio_path.name}  |  {args.resolution}", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)
    print(json.dumps({
        "video": str(out_path),
        "image": str(image_path),
        "audio": str(audio_path),
        "voice_id": tts_meta.get("voice_id"),
        "resolution": args.resolution,
        "manifest": str(manifest_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
