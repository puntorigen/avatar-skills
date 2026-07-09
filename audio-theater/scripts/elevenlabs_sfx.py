#!/usr/bin/env python3
"""ElevenLabs Sound Effects backend (eleven_text_to_sound_v2).

Generates a single SFX clip from a natural-language description via the
ElevenLabs Text-to-Sound-Effects REST API and writes it to disk. Used by
audio-theater's generate_sfx.py when --backend elevenlabs (or auto with a key).

Why ElevenLabs for SFX: purpose-built text-to-sound model with markedly more
realistic foley/ambience than Stable Audio, plus native seamless looping
(loop=true) which is ideal for our ambient beds.

Docs: https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.elevenlabs.io/v1/sound-generation"
MODEL_ID = "eleven_text_to_sound_v2"
# ElevenLabs accepts 0.5-30s; longer requests are clamped.
MIN_DURATION = 0.5
MAX_DURATION = 30.0
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


def _clamp_duration(seconds):
    if seconds is None:
        return None
    return max(MIN_DURATION, min(MAX_DURATION, float(seconds)))


def generate_sfx(
    api_key,
    description,
    out_file,
    *,
    duration_seconds=None,
    loop=False,
    prompt_influence=0.4,
    output_format=DEFAULT_OUTPUT_FORMAT,
    model_id=MODEL_ID,
    timeout=180,
):
    """Generate one sound effect and save it to out_file (mp3).

    Returns True on success. duration_seconds=None lets the model auto-pick a
    natural length (best for one-shots). For loops, pass a duration (<=30s).
    """
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    body = {
        "text": description,
        "model_id": model_id,
        "loop": bool(loop),
        "prompt_influence": float(prompt_influence),
    }
    dur = _clamp_duration(duration_seconds)
    if dur is not None:
        body["duration_seconds"] = dur

    url = f"{API_URL}?output_format={output_format}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("xi-api-key", api_key)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "audio/mpeg")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        print(f"  ElevenLabs HTTP {e.code}: {detail}", file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        print(f"  ElevenLabs request failed: {e.reason}", file=sys.stderr)
        return False

    # A JSON body here means an error was returned instead of audio bytes.
    if payload[:1] in (b"{", b"["):
        print(f"  ElevenLabs returned non-audio: {payload[:300].decode('utf-8', 'replace')}",
              file=sys.stderr)
        return False

    out_file.write_bytes(payload)
    return out_file.stat().st_size > 0


def cli():
    import argparse

    SCRIPT_DIR = Path(__file__).parent
    sys.path.insert(0, str(SCRIPT_DIR))
    from _common import get_elevenlabs_api_key  # noqa: E402

    p = argparse.ArgumentParser(description="Generate one SFX via ElevenLabs")
    p.add_argument("description")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--duration", "-d", type=float, default=None)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--prompt-influence", type=float, default=0.4)
    args = p.parse_args()

    key = get_elevenlabs_api_key(required=True)
    ok = generate_sfx(
        key, args.description, args.output,
        duration_seconds=args.duration, loop=args.loop,
        prompt_influence=args.prompt_influence,
    )
    if not ok:
        sys.exit(1)
    print(args.output)


if __name__ == "__main__":
    cli()
