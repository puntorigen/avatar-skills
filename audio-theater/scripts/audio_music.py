#!/usr/bin/env python3
"""Instrumental music generation for audio-theater (MiniMax Music 2.6).

Why this lives here and not in bg-music-hq:
- bg-music-hq targets MiniMax `music-2.5`, which has NO instrumental flag, so it
  feeds `[Inst]` structure tags + parenthetical directions through the `lyrics`
  field. music-2.5 then *sings those directions literally* ("soft piano joins…"),
  which is wrong for a score/bed.
- audio-theater always wants instrumental beds, so it uses `music-2.6`, which
  supports `is_instrumental=true`. In that mode the `lyrics` field is ignored and
  the `prompt` drives the whole generation — no sung text, ever.

We REUSE bg-music-hq's mood library (read-only) to build a rich style prompt, but
we never modify that skill. If its moods.json is missing we fall back to a small
built-in table.

Usage (CLI / importable):
    python3 audio_music.py "soft mystical underscore, strings + music box" \
        --mood pet-lullaby --duration 90 --output score.mp3
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

MODEL = "minimax/music-2.6"
BG_MUSIC_HQ_MOODS = Path.home() / ".cursor/skills/bg-music-hq/scripts/moods.json"

# Minimal fallback used only if bg-music-hq's moods.json is unavailable.
FALLBACK_MOODS = {
    "generic": {"style_keywords": "versatile, balanced, clean, modern",
                "instruments": "piano, light synths, subtle drums", "bpm_range": "90-110"},
    "cinematic": {"style_keywords": "epic, orchestral, dramatic, concert-hall reverb",
                  "instruments": "full orchestra, strings, brass, timpani", "bpm_range": "80-100"},
    "ambient": {"style_keywords": "atmospheric, ethereal, spacious, meditative",
                "instruments": "ambient pads, soft drones, distant piano", "bpm_range": "60-75"},
    "pet-lullaby": {"style_keywords": "delicate, lullaby, hushed, soothing, nursery-like",
                    "instruments": "music box, soft piano, gentle harp, celesta, soft strings",
                    "bpm_range": "50-65"},
    "podcast-bed": {"style_keywords": "ambient, minimal, unobtrusive, warm, lo-fi",
                    "instruments": "soft pads, gentle piano, minimal percussion", "bpm_range": "70-85"},
    "podcast-intro": {"style_keywords": "upbeat, catchy, bright, punchy, radio-ready",
                      "instruments": "electric guitar, snappy drums, synth stabs", "bpm_range": "100-120"},
}


def load_moods():
    """Read bg-music-hq's mood library (read-only); fall back to the small table."""
    try:
        if BG_MUSIC_HQ_MOODS.exists():
            return json.loads(BG_MUSIC_HQ_MOODS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return FALLBACK_MOODS


def build_prompt(description, mood_key, moods, *, bpm=None, key=None):
    """Compose a single instrumental style prompt (no lyrics, ever).

    Pattern: <description>, <mood style>, <instruments>, <BPM>, instrumental,
    professional production. music-2.6 uses this to drive the whole track.
    """
    mood = moods.get(mood_key) or moods.get("generic") or {}
    parts = []
    if description:
        parts.append(description.strip())
    if mood.get("style_keywords"):
        parts.append(mood["style_keywords"])
    if mood.get("instruments"):
        parts.append(mood["instruments"])
    if bpm:
        parts.append(f"{int(bpm)} BPM")
    elif mood.get("bpm_range"):
        try:
            lo, hi = mood["bpm_range"].split("-")
            parts.append(f"{(int(lo) + int(hi)) // 2} BPM")
        except (ValueError, AttributeError):
            pass
    if key:
        parts.append(key)
    parts.append("instrumental, no vocals, professional production, high-fidelity")
    # De-dupe while preserving order, then join.
    seen, out = set(), []
    for p in parts:
        p = p.strip().strip(",")
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return ", ".join(out)


def _ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _trim(path, max_seconds, *, bitrate=256000):
    path = Path(path)
    dur = _ffprobe_duration(path)
    if dur <= max_seconds or max_seconds <= 0:
        return
    import tempfile
    import shutil
    fd, tmp = tempfile.mkstemp(suffix=path.suffix)
    os.close(fd)
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-t", str(max_seconds),
         "-b:a", str(bitrate), tmp],
        capture_output=True, text=True)
    if r.returncode == 0:
        shutil.move(tmp, str(path))
    elif Path(tmp).exists():
        os.unlink(tmp)


def _run_prediction(replicate, inputs, *, poll=4, timeout=900):
    """Create + poll a MiniMax prediction (avoids replicate.run's short sync wait,
    which times out on 1-3 min music jobs). Returns the output URL or None."""
    import time

    pred = None
    try:  # newer client: run official models by name
        pred = replicate.predictions.create(model=MODEL, input=inputs)
    except TypeError:
        pred = None
    except Exception as e:  # noqa: BLE001
        print(f"  Error: could not start MiniMax job: {e}", file=sys.stderr)
        return None
    if pred is None:
        try:  # older client: needs an explicit version
            version = replicate.models.get(MODEL).latest_version
            pred = replicate.predictions.create(version=version, input=inputs)
        except Exception as e:  # noqa: BLE001
            print(f"  Error: could not start MiniMax job: {e}", file=sys.stderr)
            return None

    deadline = time.time() + timeout
    while pred.status not in ("succeeded", "failed", "canceled"):
        if time.time() > deadline:
            print("  Error: MiniMax generation timed out.", file=sys.stderr)
            return None
        time.sleep(poll)
        try:
            pred.reload()
        except Exception:  # noqa: BLE001  (transient network: retry next loop)
            time.sleep(poll)

    if pred.status != "succeeded":
        print(f"  Error: MiniMax {pred.status}: {getattr(pred, 'error', '')}", file=sys.stderr)
        return None

    output = pred.output
    if isinstance(output, (list, tuple)):
        output = output[0] if output else None
    if not output:
        print("  Error: no output returned.", file=sys.stderr)
        return None
    return str(output)


def generate(description, out_file, *, mood="generic", duration=None,
             sample_rate=44100, bitrate=256000, audio_format="mp3",
             bpm=None, key=None, token=None, prompt_override=None):
    """Generate an instrumental track with MiniMax Music 2.6 -> out_file.

    is_instrumental=True means the model ignores lyrics and never sings; the
    prompt carries the entire musical intent. Returns the prompt used, or None on
    failure. No fades are applied (the mixer owns fades/ducking/placement).
    """
    import replicate

    moods = load_moods()
    prompt = prompt_override or build_prompt(description, mood, moods, bpm=bpm, key=key)

    if token:
        os.environ["REPLICATE_API_TOKEN"] = token

    inputs = {
        "prompt": prompt,
        "lyrics": "",           # ignored when is_instrumental=true
        "is_instrumental": True,
        "sample_rate": int(sample_rate),
        "bitrate": int(bitrate),
        "audio_format": audio_format,
    }

    print(f"  Model: {MODEL} (is_instrumental=true)", file=sys.stderr)
    print(f"  Prompt: {prompt}", file=sys.stderr)
    print(f"  Generating instrumental (1-3 min)...", file=sys.stderr)

    url = _run_prediction(replicate, inputs)
    if not url:
        return None
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, str(out_file))
    except Exception as e:  # noqa: BLE001
        print(f"  Error: download failed: {e}", file=sys.stderr)
        return None

    if duration:
        _trim(out_file, int(duration), bitrate=bitrate)
    return prompt


def main():
    ap = argparse.ArgumentParser(description="Instrumental music via MiniMax Music 2.6")
    ap.add_argument("description", nargs="?", help="Music style description")
    ap.add_argument("--mood", "-m", default="generic", help="Mood preset (bg-music-hq library)")
    ap.add_argument("--output", "-o", help="Output file path (required unless --list-moods)")
    ap.add_argument("--duration", "-d", type=int, help="Max duration (trims if longer)")
    ap.add_argument("--prompt", "-p", help="Explicit prompt (overrides description+mood)")
    ap.add_argument("--sample-rate", type=int, default=44100, choices=[16000, 24000, 32000, 44100])
    ap.add_argument("--bitrate", type=int, default=256000, choices=[32000, 64000, 128000, 256000])
    ap.add_argument("--format", "-f", default="mp3", choices=["mp3", "wav", "pcm"])
    ap.add_argument("--bpm", type=int)
    ap.add_argument("--key", type=str)
    ap.add_argument("--list-moods", action="store_true")
    args = ap.parse_args()

    moods = load_moods()
    if args.list_moods:
        for k in sorted(moods):
            print(k)
        return
    if not args.description and not args.prompt:
        ap.error("Provide a description or --prompt")
    if not args.output:
        ap.error("--output is required")

    # Resolve a Replicate token via the audio-theater resolver if available.
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from _common import get_replicate_token  # noqa: E402
            token = get_replicate_token(required=True)
        except Exception:  # noqa: BLE001
            pass

    prompt = generate(
        args.description or "", args.output,
        mood=args.mood, duration=args.duration,
        sample_rate=args.sample_rate, bitrate=args.bitrate, audio_format=args.format,
        bpm=args.bpm, key=args.key, token=token, prompt_override=args.prompt,
    )
    if not prompt:
        sys.exit(1)
    print(json.dumps({"file": args.output, "model": MODEL,
                      "is_instrumental": True, "prompt": prompt}, indent=2,
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
