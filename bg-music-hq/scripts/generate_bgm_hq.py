#!/usr/bin/env python3
"""Generate high-quality background music using MiniMax Music 2.5 on Replicate.

This model produces full-length songs with vocals, instrumentation, and
structure control. For instrumental BGM, we use [Inst] structure tags and
parenthetical instrument directions instead of lyrics.

Usage:
    python3 generate_bgm_hq.py "clean modern background for tech presentation" \
        --mood presentation --duration 60 --output bgm.mp3

    python3 generate_bgm_hq.py "smooth jazz for podcast intro" \
        --mood podcast-intro --output intro.mp3

    python3 generate_bgm_hq.py --lyrics lyrics.txt --prompt "indie folk, warm" \
        --output folk_song.mp3

    python3 generate_bgm_hq.py --list-moods
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
    Path.home() / ".cursor/skills/bg-music/config.json",
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
]

MODEL = "minimax/music-2.5"


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


def build_prompt(description, mood_key, moods, *, bpm=None, musical_key=None):
    """Build a style prompt from a description and mood preset."""
    mood = moods.get(mood_key, moods.get("generic", {}))
    style_keywords = mood.get("style_keywords", "professional, clean, well-mixed")
    instruments = mood.get("instruments", "mixed instrumentation")

    parts = [description]
    parts.append(style_keywords)
    parts.append(instruments)

    if bpm:
        parts.append(f"{bpm} BPM")
    else:
        bpm_range = mood.get("bpm_range", "90-110")
        lo, hi = bpm_range.split("-")
        mid = (int(lo) + int(hi)) // 2
        parts.append(f"{mid} BPM")

    if musical_key:
        parts.append(musical_key)

    parts.append("instrumental, professional production, high-fidelity")

    return ", ".join(parts)


def build_lyrics_from_mood(mood_key, moods):
    """Build instrumental lyrics from the mood's structure template."""
    mood = moods.get(mood_key, moods.get("generic", {}))
    structure = mood.get("structure")
    if structure:
        return structure
    return "[Intro]\n(Soft opening)\n\n[Inst]\n(Main theme, instrumental)\n\n[Outro]\n(Gentle fade)"


def download_file(url, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading: {output_path.name} ...", file=sys.stderr)
    urllib.request.urlretrieve(str(url), str(output_path))
    size_kb = output_path.stat().st_size / 1024
    print(f"  Downloaded: {size_kb:.0f} KB", file=sys.stderr)
    return str(output_path)


def generate_music(prompt, lyrics, *, sample_rate=44100, bitrate=256000,
                   audio_format="mp3", token=None):
    """Call MiniMax Music 2.5 on Replicate and return the output URL."""
    import replicate

    if token:
        os.environ["REPLICATE_API_TOKEN"] = token
    elif "REPLICATE_API_TOKEN" not in os.environ:
        os.environ["REPLICATE_API_TOKEN"] = get_replicate_token()

    inputs = {
        "lyrics": lyrics,
        "sample_rate": int(sample_rate),
        "bitrate": int(bitrate),
        "audio_format": audio_format,
    }
    if prompt:
        inputs["prompt"] = prompt

    print(f"  Model: {MODEL}", file=sys.stderr)
    print(f"  Prompt: {prompt or '(none)'}", file=sys.stderr)
    lyrics_preview = lyrics.replace("\n", " | ")[:120]
    print(f"  Lyrics: {lyrics_preview}...", file=sys.stderr)
    print(f"  Quality: {sample_rate}Hz / {bitrate // 1000}kbps / {audio_format}", file=sys.stderr)
    print(f"  Generating (this may take 1-3 minutes)...", file=sys.stderr)

    output = replicate.run(MODEL, input=inputs)
    return output


def apply_fades(file_path, *, fade_in_ms=500, fade_out_ms=2000):
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

    print(f"  Track duration: {total_duration:.1f}s", file=sys.stderr)

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
        "-b:a", "256k",
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


def trim_duration(file_path, max_seconds):
    """Trim an audio file to a maximum duration using ffmpeg."""
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
        return str(file_path)

    if total_duration <= max_seconds:
        return str(file_path)

    print(f"  Trimming from {total_duration:.1f}s to {max_seconds}s...", file=sys.stderr)

    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=file_path.suffix)
    os.close(tmp_fd)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(file_path),
        "-t", str(max_seconds),
        "-b:a", "256k",
        tmp_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if Path(tmp_path).exists():
            os.unlink(tmp_path)
        return str(file_path)

    import shutil
    shutil.move(tmp_path, str(file_path))
    print(f"  Trimmed to {max_seconds}s", file=sys.stderr)
    return str(file_path)


def resolve_output_path(output_arg, description, audio_format="mp3", variation_index=None):
    """Build the output file path."""
    ext = f".{audio_format}"
    if output_arg:
        p = Path(output_arg)
        if variation_index is not None:
            stem = p.stem
            suffix = p.suffix or ext
            return p.parent / f"{stem}_{variation_index}{suffix}"
        if not p.suffix:
            p = p.with_suffix(ext)
        return p

    slug = (description or "bgm_hq").lower()
    for ch in " ,.'\"!?;:()[]{}":
        slug = slug.replace(ch, "_")
    slug = "_".join(part for part in slug.split("_") if part)[:40]

    if variation_index is not None:
        return Path(f"{slug}_{variation_index}{ext}")
    return Path(f"{slug}{ext}")


def list_moods(moods):
    print("\nAvailable mood presets:\n")
    print(f"  {'Mood':<16} {'Label':<16} {'Dur.':<8} {'BPM':<12} Description")
    print(f"  {'─' * 16} {'─' * 16} {'─' * 8} {'─' * 12} {'─' * 44}")
    for key, m in sorted(moods.items()):
        label = m.get("label", key)
        dur = m.get("default_duration", "?")
        bpm = m.get("bpm_range", "?")
        desc = m.get("description", "")
        print(f"  {key:<16} {label:<16} {str(dur) + 's':<8} {bpm:<12} {desc}")
    print()


def main():
    moods = load_moods()
    config = load_config()

    parser = argparse.ArgumentParser(
        description="Generate high-quality background music using MiniMax Music 2.5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s "clean modern background for keynote" --mood keynote -o keynote.mp3
  %(prog)s "smooth jazz for podcast intro" --mood podcast-intro -o intro.mp3
  %(prog)s --lyrics song.txt --prompt "indie folk, warm, acoustic" -o song.mp3
  %(prog)s "upbeat jingle" --mood podcast-intro --variations 3 -o jingle.mp3
  %(prog)s --list-moods
""",
    )
    parser.add_argument("description", nargs="?",
                        help="Natural-language description of the music style")
    parser.add_argument("--mood", "-m",
                        default=config.get("default_mood", "presentation"),
                        help="Mood preset (default: presentation)")
    parser.add_argument("--lyrics", "-l",
                        help="Path to a lyrics file (with structure tags)")
    parser.add_argument("--lyrics-text", "-L",
                        help="Inline lyrics string (with structure tags)")
    parser.add_argument("--prompt", "-p",
                        help="Explicit style prompt (overrides description+mood)")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--duration", "-d", type=int,
                        help="Max duration in seconds (trims if longer)")
    parser.add_argument("--variations", "-n", type=int, default=1,
                        help="Number of variations (1-5, default: 1)")
    parser.add_argument("--sample-rate", type=int,
                        default=config.get("default_sample_rate", 44100),
                        choices=[16000, 24000, 32000, 44100],
                        help="Audio sample rate (default: 44100)")
    parser.add_argument("--bitrate", type=int,
                        default=config.get("default_bitrate", 256000),
                        choices=[32000, 64000, 128000, 256000],
                        help="Audio bitrate (default: 256000)")
    parser.add_argument("--format", "-f",
                        default=config.get("default_format", "mp3"),
                        choices=["mp3", "wav", "pcm"],
                        help="Output audio format (default: mp3)")
    parser.add_argument("--raw-prompt", action="store_true",
                        help="Use description as prompt directly, skip mood enhancement")
    parser.add_argument("--instrumental", action="store_true", default=True,
                        help="Generate instrumental only (default: true)")
    parser.add_argument("--with-vocals", action="store_true",
                        help="Allow vocals (requires lyrics with actual words)")
    parser.add_argument("--fade-in", type=float, default=500,
                        help="Fade-in duration in ms (default: 500)")
    parser.add_argument("--fade-out", type=float, default=2000,
                        help="Fade-out duration in ms (default: 2000)")
    parser.add_argument("--no-fade", action="store_true",
                        help="Disable fade-in and fade-out")
    parser.add_argument("--bpm", type=int,
                        help="Suggest BPM in the prompt")
    parser.add_argument("--key", type=str,
                        help="Suggest musical key (e.g. 'C major', 'A minor')")
    parser.add_argument("--list-moods", action="store_true",
                        help="Show available mood presets")

    args = parser.parse_args()

    if args.list_moods:
        list_moods(moods)
        sys.exit(0)

    if not args.description and not args.lyrics and not args.lyrics_text and not args.prompt:
        parser.error("Provide a description, --lyrics file, --lyrics-text, or --prompt")

    mood_key = args.mood
    if mood_key not in moods:
        print(f"Warning: Unknown mood '{mood_key}', using 'generic'.", file=sys.stderr)
        mood_key = "generic"

    # --- Build the style prompt ---
    if args.prompt:
        prompt = args.prompt
    elif args.raw_prompt and args.description:
        prompt = args.description
    elif args.description:
        prompt = build_prompt(
            args.description, mood_key, moods,
            bpm=args.bpm, musical_key=args.key,
        )
    else:
        mood = moods.get(mood_key, {})
        prompt = build_prompt(
            mood.get("description", "background music"), mood_key, moods,
            bpm=args.bpm, musical_key=args.key,
        )

    # --- Build the lyrics ---
    if args.lyrics:
        lyrics_path = Path(args.lyrics)
        if not lyrics_path.exists():
            print(f"Error: Lyrics file not found: {args.lyrics}", file=sys.stderr)
            sys.exit(1)
        lyrics = lyrics_path.read_text(encoding="utf-8").strip()
    elif args.lyrics_text:
        lyrics = args.lyrics_text
    elif args.with_vocals:
        print("Error: --with-vocals requires --lyrics or --lyrics-text", file=sys.stderr)
        sys.exit(1)
    else:
        lyrics = build_lyrics_from_mood(mood_key, moods)

    token = get_replicate_token()
    variations = max(1, min(5, args.variations))
    audio_format = args.format

    results = []
    for i in range(variations):
        var_idx = (i + 1) if variations > 1 else None

        print(f"\n{'=' * 50}", file=sys.stderr)
        if variations > 1:
            print(f"  Variation {i + 1}/{variations}", file=sys.stderr)
        print(f"{'=' * 50}", file=sys.stderr)

        output = generate_music(
            prompt, lyrics,
            sample_rate=args.sample_rate,
            bitrate=args.bitrate,
            audio_format=audio_format,
            token=token,
        )

        if not output:
            print(f"  Error: No output returned for variation {i + 1}", file=sys.stderr)
            continue

        url = str(output) if isinstance(output, str) else str(output)
        out_path = resolve_output_path(args.output, args.description, audio_format, var_idx)
        saved = download_file(url, out_path)

        if args.duration:
            saved = trim_duration(saved, args.duration)

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
        "lyrics": lyrics,
        "mood": mood_key,
        "model": MODEL,
        "sample_rate": args.sample_rate,
        "bitrate": args.bitrate,
        "format": audio_format,
        "fades": not args.no_fade,
        "fade_in_ms": args.fade_in if not args.no_fade else 0,
        "fade_out_ms": args.fade_out if not args.no_fade else 0,
    }
    if args.duration:
        output_json["max_duration"] = args.duration
    if args.bpm:
        output_json["bpm"] = args.bpm
    if args.key:
        output_json["key"] = args.key
    if args.description:
        output_json["raw_description"] = args.description

    print(json.dumps(output_json, indent=2))


if __name__ == "__main__":
    main()
