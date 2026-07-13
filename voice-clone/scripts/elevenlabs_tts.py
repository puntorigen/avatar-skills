#!/usr/bin/env python3
"""Studio-quality TTS with ElevenLabs — a drop-in backend for the reel pipeline.

Mirrors generate_speech.py's CLI/JSON contract (writes
<avatar>/generated-audios/<out-name>.mp3 and prints {"audio": ...}) so
narrate.py can call either MiniMax (default) or ElevenLabs per the storyboard
`voice.engine`.

Two modes:
  1. CREATE a permanent voice from a Voice-Design preview's generated_voice_id
     (one-time; obtained from avatar-invent design_voice.py):
       python3 elevenlabs_tts.py --create-from <GENERATED_ID> \
           --avatar-dir aurora --name aurora \
           --voice-name "Aurora" --voice-description "..."
     -> POST /v1/text-to-voice ; saves <avatar>/voices/<name>_el.json ; prints {"voice_id"}.

  2. SYNTHESIZE one chunk with an existing ElevenLabs voice_id:
       python3 elevenlabs_tts.py --text-file t.txt --avatar-dir aurora \
           --voice-id <EL_VOICE_ID> --speed 0.9 --out-name foo
     -> POST /v1/text-to-speech/{voice_id} ; prints {"audio","voice_id"}.

Unused MiniMax flags (--emotion/--language-boost/--pitch/--volume/--audio-format)
are accepted and ignored so narrate.py can pass one arg set to either backend.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# MiniMax honours <#x#> as x seconds of silence server-side; ElevenLabs does NOT
# (it would drop/mis-read the token). We strip the markers and splice REAL
# silence of the same length, so the meditation's breathing pauses survive.
_PAUSE_RE = re.compile(r"<#\s*(\d+(?:\.\d+)?)\s*#>")
# Reuse avatar-invent's key discovery + JSON IO (shared across sibling skills).
_INVENT = SCRIPT_DIR.parent.parent / "avatar-invent" / "scripts"
sys.path.insert(0, str(_INVENT))
import _common as C  # noqa: E402

API_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


def _headers(api_key: str, *, accept="application/json"):
    return {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": accept}


def _post_json(path: str, body: dict, api_key: str, timeout=180) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}{path}", data=json.dumps(body).encode("utf-8"),
        method="POST", headers=_headers(api_key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600] if e.fp else ""
        raise RuntimeError(f"ElevenLabs HTTP {e.code} on {path}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"ElevenLabs request failed: {e.reason}") from None


def _post_audio(path: str, body: dict, api_key: str, out_path: Path, timeout=300):
    url = f"{API_BASE}{path}?output_format={body.pop('_output_format', DEFAULT_OUTPUT_FORMAT)}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers=_headers(api_key, accept="audio/mpeg"))
    last = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(resp.read())
            return
        except urllib.error.HTTPError as e:
            code = e.code
            detail = e.read().decode("utf-8", "replace")[:400] if e.fp else ""
            last = f"HTTP {code}: {detail}"
            if code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 * attempt)
                continue
            raise RuntimeError(f"ElevenLabs TTS {last}") from None
        except urllib.error.URLError as e:
            last = str(e.reason)
            if attempt < 3:
                time.sleep(2 * attempt)
                continue
            raise RuntimeError(f"ElevenLabs TTS request failed: {last}") from None


def _split_pauses(text: str):
    """Split text into an ordered sequence of ('say', str) / ('gap', seconds).

    Consecutive markers accumulate; empty spoken bits are dropped. Returns the
    sequence plus the total pause seconds (for logging)."""
    seq = []
    last = 0
    total_gap = 0.0
    for m in _PAUSE_RE.finditer(text):
        spoken = text[last:m.start()].strip()
        if spoken:
            seq.append(("say", spoken))
        gap = float(m.group(1))
        if seq and seq[-1][0] == "gap":
            seq[-1] = ("gap", seq[-1][1] + gap)
        else:
            seq.append(("gap", gap))
        total_gap += gap
        last = m.end()
    tail = text[last:].strip()
    if tail:
        seq.append(("say", tail))
    if not seq:
        seq = [("say", text.strip() or " ")]
    return seq, total_gap


def _ffmpeg_concat_with_silence(parts, out_path: Path, *, sr=44100):
    """Concatenate an ordered list of ('audio', path) / ('silence', secs) into
    out_path (mp3), inserting exact silences via anullsrc."""
    if len(parts) == 1 and parts[0][0] == "audio":
        Path(parts[0][1]).replace(out_path)
        return
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    labels = []
    idx = 0
    for kind, val in parts:
        if kind == "audio":
            cmd += ["-i", str(val)]
        else:
            cmd += ["-f", "lavfi", "-t", f"{float(val):.3f}", "-i",
                    f"anullsrc=r={sr}:cl=mono"]
        labels.append(f"[{idx}:a]")
        idx += 1
    filt = "".join(labels) + f"concat=n={idx}:v=0:a=1[out]"
    cmd += ["-filter_complex", filt, "-map", "[out]",
            "-ar", str(sr), "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k",
            str(out_path)]
    subprocess.run(cmd, check=True)


def _voice_record_path(avatar_dir: Path, name: str) -> Path:
    return avatar_dir / "voices" / f"{name}_el.json"


def create_voice(api_key, *, generated_voice_id, voice_name, voice_description,
                 avatar_dir: Path, name: str) -> dict:
    body = {"voice_name": voice_name, "voice_description": voice_description,
            "generated_voice_id": generated_voice_id}
    print(f"  ElevenLabs create voice '{voice_name}' from preview {generated_voice_id} ...",
          file=sys.stderr)
    resp = _post_json("/text-to-voice", body, api_key)
    voice_id = resp.get("voice_id")
    if not voice_id:
        raise RuntimeError(f"no voice_id returned: {json.dumps(resp)[:300]}")
    rec = {
        "name": name, "provider": "elevenlabs/text-to-voice",
        "voice_id": voice_id, "generated_voice_id": generated_voice_id,
        "voice_name": voice_name, "voice_description": voice_description,
    }
    rp = _voice_record_path(avatar_dir, name)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  saved: {rp}", file=sys.stderr)
    return rec


def resolve_voice_id(avatar_dir: Path, name: str | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    if name:
        rp = _voice_record_path(avatar_dir, name)
        rec = C.try_load_json(rp) if rp.exists() else None
        if rec and rec.get("voice_id"):
            return rec["voice_id"]
    # Any *_el.json in voices/.
    vdir = avatar_dir / "voices"
    for rp in sorted(vdir.glob("*_el.json")):
        rec = C.try_load_json(rp)
        if rec and rec.get("voice_id"):
            return rec["voice_id"]
    raise SystemExit("No ElevenLabs voice_id (pass --voice-id or create one with --create-from).")


def main():
    ap = argparse.ArgumentParser(description="ElevenLabs TTS backend for the reel pipeline.")
    ap.add_argument("text", nargs="?", default=None)
    ap.add_argument("--text-file", type=Path, default=None)
    ap.add_argument("--avatar-dir", type=Path, required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--voice-id", default=None)
    ap.add_argument("--out-name", default=None)
    ap.add_argument("-o", "--out-dir", type=Path, default=None,
                    help="Output dir (default <avatar>/generated-audios)")
    # ElevenLabs voice settings.
    ap.add_argument("--model-id", default=DEFAULT_MODEL)
    ap.add_argument("--speed", type=float, default=1.0, help="0.25-4.0 (voice_settings.speed)")
    ap.add_argument("--stability", type=float, default=0.5)
    ap.add_argument("--similarity-boost", type=float, default=0.75)
    ap.add_argument("--style", type=float, default=0.0)
    ap.add_argument("--no-speaker-boost", action="store_true")
    ap.add_argument("--output-format", default=DEFAULT_OUTPUT_FORMAT)
    # Create-voice mode.
    ap.add_argument("--create-from", default=None, help="generated_voice_id to persist")
    ap.add_argument("--voice-name", default=None)
    ap.add_argument("--voice-description", default=None)
    # Accepted-but-ignored (MiniMax compat so narrate can pass one arg set).
    for ignored in ("--emotion", "--language-boost", "--volume", "--pitch",
                    "--audio-format", "--source", "--sample-rate", "--bitrate", "--channel"):
        ap.add_argument(ignored, default=None)
    args = ap.parse_args()

    avatar_dir = args.avatar_dir.expanduser().resolve()
    name = args.name or avatar_dir.name
    api_key = C.get_elevenlabs_api_key(required=True)

    if args.create_from:
        if not (args.voice_name and args.voice_description):
            ap.error("--create-from needs --voice-name and --voice-description.")
        rec = create_voice(
            api_key, generated_voice_id=args.create_from,
            voice_name=args.voice_name, voice_description=args.voice_description,
            avatar_dir=avatar_dir, name=name)
        print(json.dumps({"voice_id": rec["voice_id"], "record": str(_voice_record_path(avatar_dir, name))},
                         ensure_ascii=False))
        return 0

    if args.text_file:
        text = args.text_file.expanduser().read_text(encoding="utf-8").strip()
    elif args.text:
        text = args.text.strip()
    else:
        ap.error("Falta el texto (arg o --text-file).")
    if not text:
        ap.error("Texto vacío.")

    voice_id = resolve_voice_id(avatar_dir, name, args.voice_id)
    speed = max(0.25, min(4.0, float(args.speed)))
    settings = {
        "stability": args.stability,
        "similarity_boost": args.similarity_boost,
        "style": args.style,
        "use_speaker_boost": not args.no_speaker_boost,
        "speed": speed,
    }

    out_dir = (args.out_dir.expanduser().resolve() if args.out_dir
               else avatar_dir / "generated-audios")
    out_dir.mkdir(parents=True, exist_ok=True)
    base = args.out_name or "audio"
    out_path = out_dir / f"{base}.mp3"

    seq, total_gap = _split_pauses(text)
    n_say = sum(1 for k, _ in seq if k == "say")
    print(f"  ElevenLabs TTS ({args.model_id}, speed={speed}) -> {out_path.name} "
          f"[{n_say} segment(s), {total_gap:.1f}s pauses]", file=sys.stderr)

    def _tts_segment(seg_text: str, dest: Path):
        body = {"text": seg_text, "model_id": args.model_id,
                "voice_settings": settings, "_output_format": args.output_format}
        _post_audio(f"/text-to-speech/{voice_id}", body, api_key, dest)

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        parts = []
        for i, (kind, val) in enumerate(seq):
            if kind == "say":
                seg = tdp / f"seg_{i:02d}.mp3"
                _tts_segment(val, seg)
                parts.append(("audio", seg))
            else:
                parts.append(("silence", val))
        _ffmpeg_concat_with_silence(parts, out_path)

    print(json.dumps({"audio": str(out_path), "voice_id": voice_id,
                      "model": args.model_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
