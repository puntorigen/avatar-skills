#!/usr/bin/env python3
"""Shared utilities for the broll-avatar-camera skill.

Wraps Pruna's talking-avatar model on Replicate (``prunaai/p-video-avatar``) — the SAME
model our talking-heads use (avatar-talking-video) — driven here from ONE gpt-image-2
start frame of our avatar DOING something, plus the beat's narration audio. The audio
both lip-syncs the avatar (when the mouth is visible) and sets the clip length; the
``video_prompt`` carries the ACTION ("takes a book from a shelf while talking") and
``negative_prompt`` keeps unwanted stuff out. Using the same model as the rest of the
reel maximizes identity/look consistency between talking and action shots.

For a controlled object move with a precise start AND end pose (or a face-free beat where
a talking-avatar model would hallucinate a face), use seedance-2 with start+end frames
instead — see SKILL.md.

Token discovery is shared with the other Replicate-based skills: env var
REPLICATE_API_TOKEN, this skill's config.json, then the sibling skills' configs.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"

# Pruna talking-avatar / lip-sync model on Replicate (image + audio + video_prompt).
# Same model as avatar-talking-video, for a consistent avatar look across shots.
MODEL = "prunaai/p-video-avatar"

# Sibling skills that may hold the shared Replicate token.
FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/avatar-talking-video/config.json",
    Path.home() / ".cursor/skills/voice-clone/config.json",
    Path.home() / ".cursor/skills/gpt-image-2/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/video-compose/config.json",
]


def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def get_replicate_token():
    """Resolve the Replicate API token: env -> local config -> sibling skills."""
    token = os.environ.get("REPLICATE_API_TOKEN")
    if token:
        return token
    token = load_config().get("replicate_api_token", "")
    if token:
        return token
    for path in FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                t = cfg.get("replicate_api_token", "")
                if t:
                    return t
            except (json.JSONDecodeError, OSError):
                continue
    print("Error: No Replicate API token found.", file=sys.stderr)
    print("  Set REPLICATE_API_TOKEN or add replicate_api_token to a sibling skill config.",
          file=sys.stderr)
    print("  Get a token at: https://replicate.com/account/api-tokens", file=sys.stderr)
    sys.exit(1)


def _require_replicate():
    try:
        import replicate  # noqa: F401
    except ImportError:
        print("Error: the 'replicate' package is required. Run:", file=sys.stderr)
        print(f"  pip3 install -r {SKILL_DIR}/scripts/requirements.txt", file=sys.stderr)
        sys.exit(1)
    return __import__("replicate")


def run_replicate(model, inputs, *, token=None):
    """Run a Replicate model and return the raw output."""
    replicate = _require_replicate()
    if token:
        os.environ["REPLICATE_API_TOKEN"] = token
    elif "REPLICATE_API_TOKEN" not in os.environ:
        os.environ["REPLICATE_API_TOKEN"] = get_replicate_token()
    print(f"  Running Replicate model: {model} ...", file=sys.stderr)
    return replicate.run(model, input=inputs)


def to_url(value):
    """Pull a URL string out of a Replicate FileOutput-like object or string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    u = getattr(value, "url", None)
    if isinstance(u, str):
        return u
    if callable(u):
        try:
            return u()
        except Exception:  # noqa: BLE001
            return None
    return None


def save_output(item, output_path):
    """Persist a Replicate output (FileOutput, URL string, or bytes) to disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(item, "read"):
        try:
            output_path.write_bytes(item.read())
            return str(output_path)
        except Exception:  # noqa: BLE001
            pass
    url = item if isinstance(item, str) else to_url(item)
    if url and str(url).startswith("http"):
        print(f"  Downloading: {output_path.name} ...", file=sys.stderr)
        urllib.request.urlretrieve(str(url), str(output_path))
        return str(output_path)
    try:
        output_path.write_bytes(bytes(item))
        return str(output_path)
    except (TypeError, ValueError):
        print(f"  Warning: could not interpret output of type {type(item)}", file=sys.stderr)
        return None


def infer_avatar_dir(path):
    """Find the avatar folder (nearest ancestor containing a refs/ or videos/ dir)."""
    p = Path(path).expanduser().resolve()
    if p.is_file():
        p = p.parent
    for cand in [p, *p.parents]:
        if (cand / "refs").is_dir() or (cand / "videos").is_dir():
            return cand
    return None


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def mute_clip(src, dst):
    """Strip audio from src -> dst (broll convention; VO is added later)."""
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found on PATH (needed to mute the clip).")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-an", "-c:v", "copy", str(dst)],
        check=True, capture_output=True, text=True,
    )
    return str(dst)
