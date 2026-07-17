#!/usr/bin/env python3
"""Shared utilities for the broll-actor-copy skill.

Wraps ByteDance's DreamActor M2.0 motion-transfer model on Replicate
(``bytedance/dreamactor-m2.0``): given ONE reference image of a subject and a
driving video, it re-performs the video's motion / facial expressions / lip
movements with the reference subject and returns a single MP4. The OUTPUT keeps
the REFERENCE IMAGE's resolution (so the avatar's hero image sets the clip
resolution — feed a 9:16 hero for a 9:16 clip).

Here the reference image is one of OUR avatar's identity-anchored heroes (default
look = top-level ``refs/<slug>_hero.png``; a named look =
``locations/<loc>/refs/<slug>__<loc>_hero.png``), so the resulting B-roll IS the
avatar copying the driving video's performance. The clip is muted on disk
(broll convention); avatar-reel-composer re-lays the master narration.

Token discovery is shared with the other Replicate-based skills: env var
REPLICATE_API_TOKEN, this skill's config.json, then the sibling skills' configs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"

# ByteDance DreamActor M2.0 (image + driving video -> motion-copied video).
# Left unpinned (latest) like the sibling talking-head skill; pass --model-version
# to make_actor_copy.py to pin a specific version.
#   verified version at authoring time:
#   b23bf8e6d5f31dd67ad219fac057fd43d3ac38fc58343025ab557be74a9450ca
MODEL = "bytedance/dreamactor-m2.0"

# Model input constraints (from the Replicate schema).
IMG_MAX_BYTES = int(4.7 * 1024 * 1024)   # image max size 4.7 MB
IMG_MIN_SIDE = 480                        # image min side (each dim >= 480)
IMG_ENV_LONG = 1920                       # image fits within a 1920x1080 box
IMG_ENV_SHORT = 1080                      # (either orientation)
VIDEO_MAX_DURATION = 30.0                 # driving video max 30 s
VIDEO_MAX_LONG = 2048                     # driving video fits within 2048x1440
VIDEO_MAX_SHORT = 1440

# Sibling skills that may hold the shared Replicate token.
FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/avatar-talking-video/config.json",
    Path.home() / ".cursor/skills/broll-avatar-camera/config.json",
    Path.home() / ".cursor/skills/voice-clone/config.json",
    Path.home() / ".cursor/skills/gpt-image-2/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/video-compose/config.json",
]


# --------------------------------------------------------------------------- #
# Config / token
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Replicate
# --------------------------------------------------------------------------- #
def _require_replicate():
    try:
        import replicate  # noqa: F401
    except ImportError:
        print("Error: the 'replicate' package is required. Run:", file=sys.stderr)
        print(f"  pip3 install -r {SCRIPT_DIR}/requirements.txt", file=sys.stderr)
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
                                  timeout=httpx.Timeout(1800.0, connect=30.0))
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


# --------------------------------------------------------------------------- #
# Avatar / location / image resolution
# --------------------------------------------------------------------------- #
def slugify(text, maxlen=48):
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:maxlen].strip("-") or "actor-copy"


def try_load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def resolve_avatar_dir(raw):
    """Route a bare avatar name under ./avatares/ (repo convention).

    A bare name (no path separator) goes to ``avatares/<name>``; an explicit or
    absolute path is respected as-is. Override the root with AVATARES_ROOT.
    """
    raw = str(raw)
    p = Path(raw).expanduser()
    seps = os.sep + (os.altsep or "")
    if not p.is_absolute() and not any(s in raw for s in seps):
        p = Path(os.environ.get("AVATARES_ROOT") or "avatares") / raw
    return p.resolve()


def infer_avatar_dir(path):
    """Find the avatar folder (nearest ancestor containing a refs/ or videos/ dir)."""
    p = Path(path).expanduser().resolve()
    if p.is_file():
        p = p.parent
    for cand in [p, *p.parents]:
        if (cand / "refs").is_dir() or (cand / "videos").is_dir():
            return cand
    return None


def _first_existing(paths):
    for p in paths:
        if p and Path(p).exists():
            return Path(p)
    return None


def resolve_reference_image(avatar_dir, location=None):
    """Resolve the avatar's identity-anchored hero image for a given look.

    Mirrors avatar-location's layout:
      - default look  -> <avatar>/refs/<slug>_hero.png (then _hero_master.png)
      - named location -> <avatar>/locations/<loc>/refs/<slug>__<loc>_hero.png
                          (then that look's _hero_master.png)
    Falls back to the styled hero, then the identity master, then a camera
    angle, then the first extracted frame. Returns a Path or None.
    """
    avatar_dir = Path(avatar_dir).expanduser().resolve()
    slug = avatar_dir.name
    loc = (location or "default").strip()

    if loc in ("", "default"):
        cand = _first_existing([
            avatar_dir / "refs" / f"{slug}_hero.png",
            avatar_dir / "refs" / f"{slug}_hero_master.png",
        ])
        if cand:
            return cand
        # fall back to any 9:16 camera angle, then the styled/master heroes, then a frame
        angles = sorted((avatar_dir / "angles").glob("*_916.png"))
        cand = _first_existing([
            *(angles[:1]),
            *sorted((avatar_dir / "refs").glob(f"{slug}_hero*.png"))[:1],
            avatar_dir / "frames" / "frame_0001.png",
        ])
        return cand

    loc_dir = avatar_dir / "locations" / loc
    if not loc_dir.is_dir():
        return None
    refs = loc_dir / "refs"
    cand = _first_existing([
        refs / f"{slug}__{loc}_hero.png",
        refs / f"{slug}__{loc}_hero_master.png",
    ])
    if cand:
        return cand
    angles = sorted((loc_dir / "angles").glob("*_916.png"))
    return _first_existing([
        *sorted(refs.glob(f"{slug}__{loc}_hero*.png"))[:1],
        *(angles[:1]),
    ])


def list_locations(avatar_dir):
    """Return available look names: ['default', <loc>, ...]."""
    avatar_dir = Path(avatar_dir).expanduser().resolve()
    out = ["default"]
    loc_root = avatar_dir / "locations"
    if loc_root.is_dir():
        out += sorted(p.name for p in loc_root.iterdir() if p.is_dir())
    return out


# --------------------------------------------------------------------------- #
# ffmpeg / ffprobe
# --------------------------------------------------------------------------- #
def _require(bin_name):
    if not shutil.which(bin_name):
        raise SystemExit(f"{bin_name} not found on PATH (needed by broll-actor-copy).")


def ffprobe_video(path):
    """Return {width, height, duration, fps} for a video (best-effort)."""
    _require("ffprobe")
    out = subprocess.run(
        ["ffprobe", "-v", "error",
         "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    info = {"width": None, "height": None, "duration": None, "fps": None}
    try:
        data = json.loads(out.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        info["width"] = stream.get("width")
        info["height"] = stream.get("height")
        rate = stream.get("r_frame_rate") or ""
        if "/" in rate:
            num, den = rate.split("/", 1)
            den = float(den)
            info["fps"] = (float(num) / den) if den else None
        elif rate:
            info["fps"] = float(rate)
        info["duration"] = float(data.get("format", {}).get("duration"))
    except (json.JSONDecodeError, ValueError, TypeError, IndexError, ZeroDivisionError):
        pass
    return info


def ffprobe_duration(path):
    return ffprobe_video(path).get("duration")


def mute_clip(src, dst):
    """Strip audio from src -> dst (broll convention; VO is added later)."""
    _require("ffmpeg")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-an", "-c:v", "copy", str(dst)],
        check=True, capture_output=True, text=True,
    )
    return str(dst)


def concat_clips(clips, out_path, *, fps=None):
    """Concatenate muted video clips into one (VO is re-laid later).

    Uses the concat filter with per-input fps/SAR/format normalization so
    segments that share resolution (all produced from the same hero image) join
    cleanly even if their timebase differs. A single clip is just copied.
    """
    clips = [str(Path(c)) for c in clips]
    if not clips:
        raise ValueError("concat_clips: no clips to join.")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if len(clips) == 1:
        shutil.copyfile(clips[0], out_path)
        return str(out_path)

    _require("ffmpeg")
    if fps is None:
        fps = ffprobe_video(clips[0]).get("fps") or 30.0
    cmd = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", c]
    pre = [f"[{i}:v]fps={fps},setsar=1,format=yuv420p[v{i}]" for i in range(len(clips))]
    labels = "".join(f"[v{i}]" for i in range(len(clips)))
    fc = ";".join(pre) + ";" + labels + f"concat=n={len(clips)}:v=1:a=0[v]"
    cmd += ["-filter_complex", fc, "-map", "[v]",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return str(out_path)


def _even(n):
    n = int(round(n))
    return n - (n % 2)


def prepare_image(image_path, work_dir, *, disable_fit=False):
    """Ensure the reference image satisfies DreamActor's constraints.

    Constraints: JPEG/PNG, each side in [480 .. ], fits within a 1920x1080 box
    (either orientation), file <= 4.7 MB. Only rewrites the image when a change
    is actually needed, so a compliant hero is passed through untouched (its
    resolution then flows straight to the output clip).

    Returns (path, meta) where meta records whether/why it was refitted.
    """
    from PIL import Image  # local import: only needed here

    image_path = Path(image_path).expanduser().resolve()
    meta = {"fitted": False, "reason": None,
            "orig_size": None, "final_size": None}
    if disable_fit:
        return image_path, meta

    im = Image.open(image_path)
    w, h = im.size
    meta["orig_size"] = [w, h]
    long_side, short_side = max(w, h), min(w, h)

    scale = 1.0
    reasons = []
    if short_side < IMG_MIN_SIDE:
        scale = IMG_MIN_SIDE / short_side
        reasons.append(f"upscale (short {short_side}<{IMG_MIN_SIDE})")
    fit = min(IMG_ENV_LONG / (long_side * scale), IMG_ENV_SHORT / (short_side * scale), 1.0)
    if fit < 1.0:
        scale *= fit
        reasons.append("downscale to 1920x1080 envelope")

    need_resize = abs(scale - 1.0) > 1e-6
    too_big = image_path.stat().st_size > IMG_MAX_BYTES
    if too_big:
        reasons.append(f">4.7MB ({image_path.stat().st_size} bytes)")

    if not need_resize and not too_big:
        meta["final_size"] = [w, h]
        return image_path, meta

    if need_resize:
        w, h = _even(w * scale), _even(h * scale)
        im = im.resize((max(w, 1), max(h, 1)), Image.LANCZOS)

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / f"{image_path.stem}_fit.jpg"
    rgb = im.convert("RGB")
    quality = 92
    rgb.save(out, "JPEG", quality=quality)
    while out.stat().st_size > IMG_MAX_BYTES and quality > 40:
        quality -= 8
        rgb.save(out, "JPEG", quality=quality)

    meta.update({"fitted": True, "reason": "; ".join(reasons),
                 "final_size": [w, h], "jpeg_quality": quality})
    return out, meta


def prepare_video(video_path, work_dir, *, trim_start=0.0, trim_duration=None,
                  max_duration=VIDEO_MAX_DURATION, out_name=None):
    """Trim / downscale the driving video to fit DreamActor's constraints.

    - Caps the duration at ``max_duration`` (30 s) unless ``trim_duration`` is
      set explicitly; honours ``trim_start`` for choosing a segment.
    - Downscales to the 2048x1440 envelope if the source is larger.
    Only re-encodes when a change is needed. ``out_name`` disambiguates the
    intermediate filename (needed when preparing several segments of one source
    so they don't overwrite each other). Returns (path, meta).
    """
    video_path = Path(video_path).expanduser().resolve()
    info = ffprobe_video(video_path)
    dur, w, h = info.get("duration"), info.get("width"), info.get("height")
    meta = {"trimmed": False, "scaled": False, "orig": info,
            "trim_start": trim_start, "trim_duration": None}

    eff_dur = None
    if trim_duration is not None:
        eff_dur = float(trim_duration)
    elif dur is not None and (dur - trim_start) > max_duration:
        eff_dur = max_duration
    need_trim = trim_start > 0 or eff_dur is not None

    vf = None
    if w and h and (max(w, h) > VIDEO_MAX_LONG or min(w, h) > VIDEO_MAX_SHORT):
        long_side, short_side = max(w, h), min(w, h)
        s = min(VIDEO_MAX_LONG / long_side, VIDEO_MAX_SHORT / short_side)
        vf = f"scale={_even(w * s)}:{_even(h * s)}"
        meta["scaled"] = True

    if not need_trim and vf is None:
        return video_path, meta

    _require("ffmpeg")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / (out_name or f"{video_path.stem}_drive.mp4")
    cmd = ["ffmpeg", "-y"]
    if trim_start > 0:
        cmd += ["-ss", f"{trim_start:.3f}"]
    cmd += ["-i", str(video_path)]
    if eff_dur is not None:
        cmd += ["-t", f"{eff_dur:.3f}"]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    meta.update({"trimmed": need_trim, "trim_duration": eff_dur})
    return out, meta
