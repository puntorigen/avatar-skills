#!/usr/bin/env python3
"""Shared utilities for the broll-generator skill.

Generates hyper-realistic complementary B-roll clips with Pruna's fast video
model on Replicate (``prunaai/p-video``): text-to-video, native exact duration
(1-20s), 720p/1080p, and selectable aspect ratio. The B-roll never contains the
main avatar/presenter — only the people and situations described — so it can sit
under an avatar voice-over in a final composite.

Token discovery is shared with the other Replicate-based skills: it checks the
REPLICATE_API_TOKEN env var, this skill's config.json, then the configs of the
sibling skills (avatar-talking-video, voice-clone, gpt-image-2, ...).
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

# Pruna fast text/image/audio-to-video model on Replicate.
MODEL = "prunaai/p-video"

# Sibling skills that may already hold the shared Replicate token.
FALLBACK_CONFIGS = [
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


def run_replicate(model, inputs, *, token=None, max_retries=4):
    """Run a Replicate model and return the raw output.

    Hardened against transient network errors: uses a generous httpx timeout
    (so the model's server-side ``Prefer: wait`` window can't trip the default
    read timeout) and retries transient failures with backoff.
    """
    import time

    replicate = _require_replicate()

    tok = token or os.environ.get("REPLICATE_API_TOKEN") or get_replicate_token()
    os.environ["REPLICATE_API_TOKEN"] = tok

    try:
        import httpx
        client = replicate.Client(api_token=tok,
                                  timeout=httpx.Timeout(900.0, connect=30.0))
        runner = lambda: client.run(model, input=inputs)  # noqa: E731
    except Exception:  # noqa: BLE001 -- fall back to the module-level runner
        runner = lambda: replicate.run(model, input=inputs)  # noqa: E731

    print(f"  Running Replicate model: {model} ...", file=sys.stderr)
    last = None
    for attempt in range(1, max_retries + 1):
        try:
            return runner()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  ! replicate attempt {attempt}/{max_retries} failed: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(min(8 * attempt, 30))
    raise last


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

    # A list output -> take the first element.
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

def _has(binary):
    from shutil import which
    return which(binary) is not None


def finalize_clip(src, dst, target_seconds, *, keep_audio=False):
    """Trim ``src`` to exactly ``target_seconds`` and strip audio by default.

    If ffmpeg is unavailable, falls back to copying the raw clip untouched.
    """
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not _has("ffmpeg"):
        print("  ffmpeg not found - keeping raw clip (length/audio untouched).", file=sys.stderr)
        if src.resolve() != dst.resolve():
            dst.write_bytes(src.read_bytes())
        return str(dst)

    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-t", f"{float(target_seconds):.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "18", "-movflags", "+faststart",
    ]
    if keep_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd.append(str(dst))

    print(f"  Normalizing to {target_seconds}s -> {dst.name}", file=sys.stderr)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  ffmpeg failed, keeping raw clip:\n{res.stderr[-600:]}", file=sys.stderr)
        if src.resolve() != dst.resolve():
            dst.write_bytes(src.read_bytes())
    return str(dst)


def probe_video(path):
    """Return {duration, width, height, fps} via ffprobe (best-effort)."""
    if not _has("ffprobe"):
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
            fps = round(float(n) / float(d), 2) if float(d) else None
        return {
            "duration": round(float(fmt.get("duration", 0)), 2) if fmt.get("duration") else None,
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
    return t[:maxlen].strip("-") or "broll"


def next_index(items, gen_dir):
    nums = []
    for it in items:
        m = re.match(r"(\d+)_", str(it.get("file", "")))
        if m:
            nums.append(int(m.group(1)))
    for f in Path(gen_dir).glob("[0-9][0-9][0-9]_*"):
        m = re.match(r"(\d+)_", f.name)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


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
