#!/usr/bin/env python3
"""Shared utilities for the avatar-talking-video skill.

Wraps Pruna's talking-head model on Replicate (prunaai/p-video-avatar): given a
portrait/angle image + an audio clip it returns an MP4 of the person speaking,
lip-synced to the audio.

Token discovery is shared with the other Replicate-based skills: it checks the
REPLICATE_API_TOKEN env var, this skill's config.json, then the configs of the
sibling skills (voice-clone, gpt-image-2, avatar-video-reel, ...).
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"

# Pruna talking-head / lip-sync model on Replicate.
MODEL = "prunaai/p-video-avatar"

# Sibling skills that may hold the shared Replicate token.
FALLBACK_CONFIGS = [
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

    # Newer replicate clients return FileOutput objects with .read().
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


def infer_avatar_dir(path):
    """Find the avatar folder (the nearest ancestor containing a videos/ dir).

    Works whether ``path`` is an angle image (``<avatar>/angles/...``), a
    generated audio clip (``<avatar>/generated-audios/...``), or the avatar
    folder itself. Returns a Path or None.
    """
    p = Path(path).expanduser().resolve()
    if p.is_file():
        p = p.parent
    for cand in [p, *p.parents]:
        if (cand / "videos").is_dir():
            return cand
    return None
