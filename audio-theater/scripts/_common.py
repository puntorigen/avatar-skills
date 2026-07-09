#!/usr/bin/env python3
"""Shared utilities for the audio-theater skill.

Key resolution reuses sibling skills:
- Gemini API key from the asset-generator skill (or env GEMINI_API_KEY/GOOGLE_API_KEY).
- Replicate API token from the sound-effects skill, with the usual fallbacks
  (or env REPLICATE_API_TOKEN).
"""

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"
VOICES_FILE = SCRIPT_DIR / "voices.json"

# Sibling skills we lean on.
ASSET_GENERATOR_CONFIG = Path.home() / ".cursor/skills/asset-generator/config.json"
SOUND_EFFECTS = Path.home() / ".cursor/skills/sound-effects/scripts/generate_sfx.py"
BG_MUSIC_HQ = Path.home() / ".cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py"
BG_MUSIC = Path.home() / ".cursor/skills/bg-music/scripts/generate_bgm.py"

# Where to look for a Replicate token, in order.
REPLICATE_CONFIGS = [
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
    Path.home() / ".cursor/skills/bg-music/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
]
# Where to look for a Gemini key, in order.
GEMINI_CONFIGS = [
    ASSET_GENERATOR_CONFIG,
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
]
# Where to look for an ElevenLabs key, in order (own config first).
ELEVENLABS_CONFIGS = [
    Path.home() / ".cursor/skills/bg-music/config.json",
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
]

DEFAULT_TTS_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_TEXT_MODEL = "gemini-3.5-flash"
MAX_CLIP_SECONDS = 15


# ──────────────────────────────────────────────────────────
# Config + key resolution
# ──────────────────────────────────────────────────────────

def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _read_key(path, field):
    try:
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            val = cfg.get(field, "")
            if val:
                return val
    except (json.JSONDecodeError, OSError):
        pass
    return ""


def get_gemini_api_key(*, required=True):
    """Resolve the Gemini API key: env -> own config -> asset-generator config."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    key = load_config().get("gemini_api_key", "")
    if key:
        return key
    for path in GEMINI_CONFIGS:
        key = _read_key(path, "gemini_api_key")
        if key:
            return key
    if required:
        print("Error: No Gemini API key found.", file=sys.stderr)
        print("  Set it in the asset-generator skill, export GEMINI_API_KEY, or run:",
              file=sys.stderr)
        print(f"  python3 {SCRIPT_DIR}/setup_key.py --gemini YOUR_GEMINI_API_KEY",
              file=sys.stderr)
        sys.exit(1)
    return ""


def get_replicate_token(*, required=True):
    """Resolve the Replicate token: env -> own config -> sibling skill configs."""
    token = os.environ.get("REPLICATE_API_TOKEN")
    if token:
        return token
    token = load_config().get("replicate_api_token", "")
    if token:
        return token
    for path in REPLICATE_CONFIGS:
        token = _read_key(path, "replicate_api_token")
        if token:
            return token
    if required:
        print("Error: No Replicate API token found.", file=sys.stderr)
        print("  Configure the sound-effects skill, export REPLICATE_API_TOKEN, or run:",
              file=sys.stderr)
        print(f"  python3 {SCRIPT_DIR}/setup_key.py --replicate YOUR_REPLICATE_API_TOKEN",
              file=sys.stderr)
        sys.exit(1)
    return ""


def get_elevenlabs_api_key(*, required=False):
    """Resolve the ElevenLabs API key: env -> own config -> sibling configs.

    Returns "" when not configured (callers decide whether to fall back to the
    Stable Audio backend). Pass required=True to hard-fail with instructions.
    """
    key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")
    if key:
        return key
    key = load_config().get("elevenlabs_api_key", "")
    if key:
        return key
    for path in ELEVENLABS_CONFIGS:
        key = _read_key(path, "elevenlabs_api_key")
        if key:
            return key
    if required:
        print("Error: No ElevenLabs API key found.", file=sys.stderr)
        print("  Get a free key at https://elevenlabs.io (Profile -> API Keys), then run:",
              file=sys.stderr)
        print(f"  python3 {SCRIPT_DIR}/setup_key.py --elevenlabs YOUR_ELEVENLABS_API_KEY",
              file=sys.stderr)
        sys.exit(1)
    return ""


def load_voices():
    if VOICES_FILE.exists():
        return json.loads(VOICES_FILE.read_text(encoding="utf-8"))
    return {"voices": {}, "auto_pool": [], "podcast_hosts": {}}


# ──────────────────────────────────────────────────────────
# JSON IO
# ──────────────────────────────────────────────────────────

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def slugify(text, maxlen=48):
    slug = (text or "").lower().strip()
    out = []
    for ch in slug:
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug[:maxlen] or "audio-theater"


# ──────────────────────────────────────────────────────────
# Audio helpers (ffmpeg / ffprobe)
# ──────────────────────────────────────────────────────────

def pcm_to_wav(pcm_bytes, out_path, *, channels=1, rate=24000, sample_width=2):
    """Wrap raw PCM bytes (Gemini TTS output) into a WAV container."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)
    return str(out_path)


def get_audio_duration(path):
    """Return duration in seconds via ffprobe (0.0 on failure)."""
    cmd = [
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except (ValueError, AttributeError, FileNotFoundError):
        return 0.0


def run_ffmpeg(args, *, description=""):
    """Run ffmpeg -y <args>. Returns True on success."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args
    if description:
        print(f"  ffmpeg: {description} ...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg error (exit {result.returncode}):", file=sys.stderr)
        for line in (result.stderr or "").strip().split("\n")[-6:]:
            print(f"    {line}", file=sys.stderr)
        return False
    return True


def stem_paths(output_path):
    """Derive the nomusic/music stem paths from the full-mix output path."""
    output_path = Path(output_path)
    return (output_path.with_suffix(".nomusic" + output_path.suffix),
            output_path.with_suffix(".music" + output_path.suffix))


def _amix_or_pass(filt, labels, out_label):
    """Append an amix (or a passthrough for a single label) into [out_label]."""
    if not labels:
        return False
    if len(labels) == 1:
        filt.append(f"{labels[0]}anull[{out_label}]")
    else:
        filt.append("".join(labels) +
                    f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[{out_label}]")
    return True


def ratio_from_duck_db(duck_db):
    """Map a target duck attenuation (dB, negative) to a compressor ratio."""
    amt = abs(float(duck_db or 0))
    if amt <= 0:
        return 2.0
    return max(2.0, min(20.0, 1.5 + amt))


# Music ducking. Music is the bottom layer: it should sit clearly UNDER voices+SFX
# and lower a little while they play, but the motion must be SMOOTH (broadcast-style
# music ducking), NOT a fast compressor that pumps up/down between words. So: a slow
# release that rides through inter-word gaps (only recovers in real pauses), a gentle
# attack, and a capped ratio so the duck is shallow. Keep the cue's base gain well
# below the voice so even fully recovered it never exceeds the dialogue.
MUSIC_DUCK_DB = -8.0
MUSIC_DUCK_ATTACK = 40
MUSIC_DUCK_RELEASE = 1500
MUSIC_DUCK_THRESHOLD = 0.04
MUSIC_DUCK_RATIO_CAP = 4.0  # shallow duck -> small, smooth variation (no pumping)


def assemble_content_and_music(filt, nomusic_labels, music_specs, *,
                               crossfeed=False, duck=True,
                               attack=MUSIC_DUCK_ATTACK, release=MUSIC_DUCK_RELEASE,
                               threshold=MUSIC_DUCK_THRESHOLD,
                               ratio_cap=MUSIC_DUCK_RATIO_CAP):
    """Sum the no-music CONTENT (voices + SFX) and gently duck music under it.

    Music behaves like background score: it sits under voices AND sfx and lowers a
    little while they play, recovering only in real pauses. The duck is deliberately
    SHALLOW and SLOW (ratio capped, long release) so it doesn't pump between words;
    keep the cue's base gain well under the voice so it never exceeds the dialogue.

    Args:
      nomusic_labels: ffmpeg labels to sum into the content bus (voice + sfx).
      music_specs:    list of (raw_music_label, duck_db). Empty -> no music.
      crossfeed:      apply headphone crossfeed per returned bus (linear, so the
                      full == nomusic + music recombination still holds).
      duck:           when False, music is summed raw (no sidechain).
      ratio_cap:      ceiling on the compressor ratio (keeps the duck shallow/smooth).

    Returns (nomusic_label, music_label_or_None). Each label is produced once;
    the caller splits/sums them for the full mix and the stems.
    """
    _amix_or_pass(filt, nomusic_labels, "nmraw")
    music_specs = list(music_specs or [])

    if not music_specs:
        nm = "[nmraw]"
        if crossfeed:
            filt.append("[nmraw]crossfeed=strength=0.3[nmcf]")
            nm = "[nmcf]"
        return nm, None

    n = len(music_specs)
    if duck:
        parts = "[nmkeep]" + "".join(f"[mck{i}]" for i in range(n))
        filt.append(f"[nmraw]asplit={n + 1}{parts}")
        ducked = []
        for i, (raw, duck_db) in enumerate(music_specs):
            ratio = min(ratio_from_duck_db(duck_db), ratio_cap)
            filt.append(
                f"{raw}[mck{i}]sidechaincompress=threshold={threshold}:"
                f"ratio={ratio:.1f}:attack={attack}:release={release}:makeup=1[mdk{i}]")
            ducked.append(f"[mdk{i}]")
        nm_label = "[nmkeep]"
    else:
        nm_label = "[nmraw]"
        ducked = [raw for (raw, _) in music_specs]

    _amix_or_pass(filt, ducked, "mraw")
    mu_label = "[mraw]"
    if crossfeed:
        filt.append(f"{nm_label}crossfeed=strength=0.3[nmcf]")
        filt.append(f"{mu_label}crossfeed=strength=0.3[mucf]")
        nm_label, mu_label = "[nmcf]", "[mucf]"
    return nm_label, mu_label


def finalize_stems(tmp_full, tmp_nomusic, tmp_music, full_out, nomusic_out, music_out,
                   *, target_i=-16.0, target_tp=-1.5, bitrate="192k"):
    """Combine the no-music + music pre-norm WAVs into a full mix, measure it, and
    write all three MP3s with the SAME linear gain so full == nomusic + music.
    """
    ok = run_ffmpeg(
        ["-i", str(tmp_nomusic), "-i", str(tmp_music),
         "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0:dropout_transition=0[m]",
         "-map", "[m]", "-c:a", "pcm_s16le", str(tmp_full)],
        description="combine stems -> full (pre-norm)",
    )
    if not ok:
        print("  Error: failed to combine stems into the full mix.", file=sys.stderr)
        sys.exit(1)

    gain_db, measured = shared_norm_gain_db(tmp_full, target_i=target_i, target_tp=target_tp)

    def _encode(src, dest):
        af = f"volume={gain_db:.3f}dB" if abs(gain_db) > 1e-4 else "anull"
        return run_ffmpeg(["-i", str(src), "-af", af,
                           "-c:a", "libmp3lame", "-b:a", bitrate, str(dest)],
                          description=f"encode {Path(dest).name} (gain {gain_db:+.2f} dB)")

    for src, dest in ((tmp_full, full_out), (tmp_nomusic, nomusic_out), (tmp_music, music_out)):
        if not _encode(src, dest):
            sys.exit(1)

    return {
        "final": str(full_out),
        "nomusic": str(nomusic_out),
        "music": str(music_out),
        "duration": round(get_audio_duration(full_out), 3),
        "shared_gain_db": round(gain_db, 3),
        "measured_input_i": measured.get("input_i"),
    }


def measure_loudness(path, *, target_i=-16.0, target_tp=-1.5, target_lra=11.0):
    """Measure integrated loudness + true peak of an audio file.

    Runs ffmpeg's loudnorm analysis pass (print_format=json) and returns the
    parsed dict (input_i, input_tp, input_lra, ...). Returns {} on failure.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    err = result.stderr or ""
    start = err.rfind("{")
    end = err.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(err[start:end + 1])
    except json.JSONDecodeError:
        return {}


def shared_norm_gain_db(path, *, target_i=-16.0, target_tp=-1.5):
    """Linear gain (dB) that brings `path` to target loudness without exceeding
    target true peak. Integrated loudness shifts 1:1 with a fixed gain, so the
    same gain applied to partition stems keeps full == nomusic + music exactly.
    Returns (gain_db, measured_dict).
    """
    m = measure_loudness(path, target_i=target_i, target_tp=target_tp)
    if not m:
        return 0.0, {}
    try:
        in_i = float(m.get("input_i"))
        in_tp = float(m.get("input_tp"))
    except (TypeError, ValueError):
        return 0.0, m
    # Hit the loudness target, but cap so the true peak stays <= target_tp.
    gain_loud = target_i - in_i
    gain_peak = target_tp - in_tp
    return min(gain_loud, gain_peak), m


def make_silence(out_path, seconds, *, rate=24000):
    """Write a mono WAV of N seconds of silence."""
    ok = run_ffmpeg([
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate={rate}",
        "-t", f"{max(0.01, seconds):.3f}", str(out_path),
    ], description=f"silence {seconds:.2f}s")
    return str(out_path) if ok else None


def format_timecode(seconds):
    """Seconds -> MM:SS.mmm"""
    seconds = max(0.0, float(seconds))
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:06.3f}"


# ──────────────────────────────────────────────────────────
# Replicate
# ──────────────────────────────────────────────────────────

def run_replicate(model, inputs, *, token=None):
    """Run a Replicate model and return its output."""
    import replicate

    if token:
        os.environ["REPLICATE_API_TOKEN"] = token
    elif "REPLICATE_API_TOKEN" not in os.environ:
        os.environ["REPLICATE_API_TOKEN"] = get_replicate_token()

    print(f"  Replicate: {model} ...", file=sys.stderr)
    return replicate.run(model, input=inputs)


def resolve_out_dir(out):
    """Resolve and create the output directory."""
    p = Path(out)
    p.mkdir(parents=True, exist_ok=True)
    return p
