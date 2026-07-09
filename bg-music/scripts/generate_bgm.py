#!/usr/bin/env python3
"""Generate background music using ElevenLabs Music on Replicate.

Usage:
    python3 generate_bgm.py "gentle piano melody" --mood calm --duration 30 --output bgm.mp3
    python3 generate_bgm.py "upbeat happy vibe" -m uplifting -d 30 -n 3 -o happy.mp3
    python3 generate_bgm.py --list-moods
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"
MOODS_FILE = SCRIPT_DIR / "moods.json"

FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
]

MODEL = "elevenlabs/music"


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def load_moods():
    if MOODS_FILE.exists():
        return json.loads(MOODS_FILE.read_text(encoding="utf-8"))
    return {}


def get_replicate_token():
    token = os.environ.get("REPLICATE_API_TOKEN")
    if token:
        return token

    config = load_config()
    token = config.get("replicate_api_token", "")
    if token:
        return token

    for path in FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                t = cfg.get("replicate_api_token", "")
                if t:
                    return t
            except (json.JSONDecodeError, KeyError):
                continue

    print("Error: No Replicate API token found.", file=sys.stderr)
    print(f"Run: python3 {SCRIPT_DIR}/setup_key.py YOUR_REPLICATE_API_TOKEN", file=sys.stderr)
    sys.exit(1)


def enhance_prompt(description, mood_key, moods, *, bpm=None, musical_key=None):
    """Enhance a natural-language description into a music-optimized prompt."""
    mood = moods.get(mood_key, moods.get("generic", {}))
    style_keywords = mood.get("style_keywords", "professional, clean, well-mixed")
    instruments = mood.get("instruments", "mixed instrumentation")
    prompt_suffix = mood.get("prompt_suffix", "background music, instrumental, professional quality")

    parts = [description]
    parts.append(style_keywords)
    parts.append(instruments)

    if bpm:
        parts.append(f"{bpm} BPM")

    if musical_key:
        parts.append(musical_key)

    parts.append(prompt_suffix)

    return ", ".join(parts)


def download_file(url, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading: {output_path.name} ...", file=sys.stderr)
    urllib.request.urlretrieve(str(url), str(output_path))
    return str(output_path)


def generate_music(prompt, *, duration_ms=30000, output_format="mp3_standard", token=None):
    """Call ElevenLabs Music on Replicate and return the output URL."""
    import replicate

    if token:
        os.environ["REPLICATE_API_TOKEN"] = token
    elif "REPLICATE_API_TOKEN" not in os.environ:
        os.environ["REPLICATE_API_TOKEN"] = get_replicate_token()

    inputs = {
        "prompt": prompt,
        "music_length_ms": int(duration_ms),
        "force_instrumental": True,
        "output_format": output_format,
    }

    duration_sec = duration_ms / 1000
    print(f"  Model: {MODEL}", file=sys.stderr)
    print(f"  Prompt: {prompt}", file=sys.stderr)
    print(f"  Duration: {duration_sec:.1f}s ({duration_ms}ms) | Format: {output_format}", file=sys.stderr)
    print(f"  Generating...", file=sys.stderr)

    output = replicate.run(MODEL, input=inputs)
    return output


def apply_fades(file_path, *, fade_in_ms=500, fade_out_ms=1500):
    """Apply fade-in and fade-out to an audio file using ffmpeg."""
    file_path = Path(file_path)
    if not file_path.exists():
        return str(file_path)

    duration_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    result = subprocess.run(duration_cmd, capture_output=True, text=True)
    try:
        total_duration = float(result.stdout.strip())
    except (ValueError, AttributeError):
        print(f"  Warning: could not read duration, skipping fades.", file=sys.stderr)
        return str(file_path)

    filters = []

    if fade_in_ms > 0:
        fade_in_sec = fade_in_ms / 1000.0
        filters.append(f"afade=t=in:st=0:d={fade_in_sec:.3f}")

    if fade_out_ms > 0:
        fade_out_sec = fade_out_ms / 1000.0
        fade_out_start = max(0, total_duration - fade_out_sec)
        filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_sec:.3f}")

    if not filters:
        return str(file_path)

    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=file_path.suffix)
    os.close(tmp_fd)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(file_path),
        "-af", ",".join(filters),
        "-b:a", "192k",
        tmp_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: fade failed: {result.stderr.strip()[-200:]}", file=sys.stderr)
        if Path(tmp_path).exists():
            os.unlink(tmp_path)
        return str(file_path)

    import shutil
    shutil.move(tmp_path, str(file_path))

    fade_parts = []
    if fade_in_ms > 0:
        fade_parts.append(f"in={fade_in_ms}ms")
    if fade_out_ms > 0:
        fade_parts.append(f"out={fade_out_ms}ms")
    print(f"  Fades applied: {', '.join(fade_parts)}", file=sys.stderr)

    return str(file_path)


def resolve_output_path(output_arg, description, variation_index=None, *, output_format="mp3_standard"):
    """Build the output file path."""
    ext = ".wav" if output_format.startswith("wav_") else ".mp3"

    if output_arg:
        p = Path(output_arg)
        if variation_index is not None:
            stem = p.stem
            suffix = p.suffix or ext
            return p.parent / f"{stem}_{variation_index}{suffix}"
        if not p.suffix:
            p = p.with_suffix(ext)
        return p

    slug = description.lower()
    for ch in " ,.'\"!?;:()[]{}":
        slug = slug.replace(ch, "_")
    slug = "_".join(part for part in slug.split("_") if part)[:40]

    if variation_index is not None:
        return Path(f"{slug}_{variation_index}{ext}")
    return Path(f"{slug}{ext}")


def list_moods(moods):
    print("\nAvailable mood presets:\n")
    print(f"  {'Mood':<14} {'Label':<14} {'Dur.':<8} Description")
    print(f"  {'─' * 14} {'─' * 14} {'─' * 8} {'─' * 40}")
    for key, m in sorted(moods.items()):
        label = m.get("label", key)
        dur = m.get("default_duration", "?")
        desc = m.get("description", "")
        print(f"  {key:<14} {label:<14} {str(dur) + 's':<8} {desc}")
    print()


def main():
    moods = load_moods()
    config = load_config()

    parser = argparse.ArgumentParser(
        description="Generate background music using ElevenLabs Music",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("description", nargs="?", help="Natural-language description of the music")
    parser.add_argument("--mood", "-m", default=config.get("default_mood", "generic"),
                        help="Emotional mood preset (default: generic)")
    parser.add_argument("--duration", "-d", type=float,
                        help="Duration in seconds (5-300)")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--variations", "-n", type=int, default=1,
                        help="Number of variations (1-5, default: 1)")
    parser.add_argument("--output-format", "-f",
                        default=config.get("default_output_format", "mp3_standard"),
                        choices=["mp3_standard", "mp3_high_quality",
                                 "wav_16khz", "wav_22khz", "wav_24khz", "wav_cd_quality"],
                        help="Audio format (default: mp3_standard)")
    parser.add_argument("--raw-prompt", action="store_true",
                        help="Use prompt as-is without enhancement")
    parser.add_argument("--fade-in", type=float, default=500,
                        help="Fade-in duration in ms (default: 500)")
    parser.add_argument("--fade-out", type=float, default=1500,
                        help="Fade-out duration in ms (default: 1500)")
    parser.add_argument("--no-fade", action="store_true",
                        help="Disable fade-in and fade-out")
    parser.add_argument("--bpm", type=int, help="Suggest BPM in the prompt")
    parser.add_argument("--key", type=str, help="Suggest musical key (e.g. 'C major', 'A minor')")
    parser.add_argument("--list-moods", action="store_true",
                        help="Show available mood presets")

    args = parser.parse_args()

    if args.list_moods:
        list_moods(moods)
        sys.exit(0)

    if not args.description:
        parser.error("description is required (or use --list-moods)")

    mood_key = args.mood
    if mood_key not in moods:
        print(f"Warning: Unknown mood '{mood_key}', using 'generic'.", file=sys.stderr)
        mood_key = "generic"

    mood = moods.get(mood_key, {})
    duration_sec = args.duration or mood.get("default_duration", config.get("default_duration", 30))
    duration_sec = max(5, min(300, float(duration_sec)))
    duration_ms = int(duration_sec * 1000)

    if args.raw_prompt:
        prompt = args.description
    else:
        prompt = enhance_prompt(
            args.description, mood_key, moods,
            bpm=args.bpm, musical_key=args.key,
        )

    token = get_replicate_token()
    variations = max(1, min(5, args.variations))

    results = []
    for i in range(variations):
        var_idx = (i + 1) if variations > 1 else None

        output_url = generate_music(
            prompt,
            duration_ms=duration_ms,
            output_format=args.output_format,
            token=token,
        )

        if not output_url:
            print(f"  Error: No output returned for variation {i + 1}", file=sys.stderr)
            continue

        url = str(output_url)
        out_path = resolve_output_path(
            args.output, args.description, var_idx,
            output_format=args.output_format,
        )
        saved = download_file(url, out_path)

        if not args.no_fade:
            saved = apply_fades(
                saved,
                fade_in_ms=args.fade_in,
                fade_out_ms=args.fade_out,
            )

        results.append(str(saved))
        print(f"  Saved: {saved}", file=sys.stderr)

    output_json = {
        "files": results,
        "prompt": prompt,
        "raw_description": args.description,
        "mood": mood_key,
        "duration_sec": duration_sec,
        "duration_ms": duration_ms,
        "output_format": args.output_format,
        "fades": not args.no_fade,
        "fade_in_ms": args.fade_in if not args.no_fade else 0,
        "fade_out_ms": args.fade_out if not args.no_fade else 0,
    }
    if args.bpm:
        output_json["bpm"] = args.bpm
    if args.key:
        output_json["key"] = args.key

    print(json.dumps(output_json, indent=2))


if __name__ == "__main__":
    main()
