#!/usr/bin/env python3
"""Shared utilities for the video-bg-replace skill.

Replaces the background of a talking-head clip: extract a temporally-stable
matte of the speaker with Robust Video Matting (RVM) on Replicate, then
composite the speaker over a new background video/image with ffmpeg.

Backend: ``arielreplicate/robust_video_matting`` (recurrent net with temporal
memory, so the matte does not flicker frame-to-frame the way per-image
background removers do). RVM returns a SINGLE video per run; ``output_type``
selects what it renders:
  - ``alpha-mask``    -> grayscale matte  (Route A: alphamerge with original RGB)
  - ``green-screen``  -> speaker on green (Route B: chromakey + despill)

Token discovery is shared with the other Replicate-based skills: it checks the
REPLICATE_API_TOKEN env var, this skill's config.json, then the configs of the
sibling skills (broll-generator, avatar-talking-video, voice-clone, ...).
"""

import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"

# Robust Video Matting on Replicate. The version is pinned for reproducibility
# but can be overridden on the CLI (--rvm-version) or set to "" to use latest.
RVM_MODEL = "arielreplicate/robust_video_matting"
RVM_VERSION = "2d2de06a76a837a4ba92b6164bf8bfd3ddb524a1fb64b0d8ae055af17fa22503"

# Sibling skills that may already hold the shared Replicate token.
FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/broll-generator/config.json",
    Path.home() / ".cursor/skills/avatar-talking-video/config.json",
    Path.home() / ".cursor/skills/voice-clone/config.json",
    Path.home() / ".cursor/skills/gpt-image-2/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
    Path.home() / ".cursor/skills/bg-music/config.json",
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
    print(f"  Run: python3 {SCRIPT_DIR}/setup_key.py YOUR_REPLICATE_API_TOKEN", file=sys.stderr)
    print("  Get a token at: https://replicate.com/account/api-tokens", file=sys.stderr)
    sys.exit(1)


def _require_replicate():
    try:
        import replicate  # noqa: F401
    except ImportError:
        print("Error: the 'replicate' package is required. Run:", file=sys.stderr)
        print(f"  pip3 install -r {SKILL_DIR}/requirements.txt", file=sys.stderr)
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


def rvm_model_ref(version=None):
    """Build the 'owner/model[:version]' reference for RVM."""
    ver = RVM_VERSION if version is None else version
    return f"{RVM_MODEL}:{ver}" if ver else RVM_MODEL


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

    if isinstance(item, (list, tuple)) and item:
        item = item[0]

    if hasattr(item, "read"):
        try:
            output_path.write_bytes(item.read())
            return str(output_path)
        except Exception:  # noqa: BLE001
            pass

    url = item if isinstance(item, str) else to_url(item)
    if url and str(url).startswith("http"):
        return download_file(url, output_path)

    try:
        output_path.write_bytes(bytes(item))
        return str(output_path)
    except (TypeError, ValueError):
        print(f"  Warning: could not interpret output of type {type(item)}", file=sys.stderr)
        return None


def download_file(url, output_path):
    """Download a URL to a local path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading: {output_path.name} ...", file=sys.stderr)
    urllib.request.urlretrieve(str(url), str(output_path))
    return str(output_path)


# ──────────────────────────────────────────────────────────
# ffmpeg / ffprobe helpers
# ──────────────────────────────────────────────────────────

def has_binary(binary):
    from shutil import which
    return which(binary) is not None


def run_ffmpeg(args, *, description="ffmpeg"):
    """Run ffmpeg with the given args (without the leading 'ffmpeg -y')."""
    if not has_binary("ffmpeg"):
        print("Error: ffmpeg not found on PATH.", file=sys.stderr)
        sys.exit(1)
    cmd = ["ffmpeg", "-y", *args]
    print(f"  {description} ...", file=sys.stderr)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  ffmpeg failed:\n{res.stderr[-1500:]}", file=sys.stderr)
        return False
    return True


def probe_video(path):
    """Return {duration, width, height, fps} via ffprobe (best-effort)."""
    if not has_binary("ffprobe"):
        return {}
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format", {})
        fps = None
        rate = stream.get("r_frame_rate", "")
        if rate and "/" in rate:
            n, d = rate.split("/")
            fps = round(float(n) / float(d), 3) if float(d) else None
        return {
            "duration": round(float(fmt.get("duration", 0)), 3) if fmt.get("duration") else None,
            "width": stream.get("width"),
            "height": stream.get("height"),
            "fps": fps,
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
        return {}


# ──────────────────────────────────────────────────────────
# Naming / manifest helpers
# ──────────────────────────────────────────────────────────

def slugify(text, maxlen=40):
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:maxlen].strip("-") or "clip"


def load_manifest(manifest_path):
    manifest_path = Path(manifest_path)
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
                return loaded
        except json.JSONDecodeError:
            pass
    return {"items": []}


def write_manifest(manifest_path, manifest):
    Path(manifest_path).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def infer_avatar_dir(path):
    """Find the avatar folder (nearest ancestor containing a videos/ dir)."""
    p = Path(path).expanduser().resolve()
    if p.is_file():
        p = p.parent
    for cand in [p, *p.parents]:
        if (cand / "videos").is_dir():
            return cand
    return None
