#!/usr/bin/env python3
"""Shared utilities for the gpt-image-2 skill.

Wraps OpenAI GPT Image 2 on Replicate (openai/gpt-image-2). The model outputs
at its native maximum size (long edge ~1536px) -- there is no size/resolution
input, and quality only controls fidelity, not pixel count. It also supports
only 1:1 / 3:2 / 2:3, so the one piece of post-processing here is exact
16:9 / 9:16 / 4:3 / 3:4 framing via a seamless background-color canvas
extension. This happens at native resolution: nothing is ever upscaled.

Token discovery is shared with the other Replicate-based skills: it checks
the REPLICATE_API_TOKEN env var, this skill's config.json, then the configs
of the sibling skills (avatar-video-reel, brand-asset-studio, etc.).
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"

# gpt-image-2 model on Replicate.
MODEL = "openai/gpt-image-2"

# Sibling skills that may hold the shared Replicate token.
FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
    Path.home() / ".cursor/skills/bg-music/config.json",
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/video-compose/config.json",
]

# Native aspect ratios gpt-image-2 supports, as width/height floats.
NATIVE_RATIOS = {"1:1": 1.0, "3:2": 1.5, "2:3": 2.0 / 3.0}
# Convenience aliases the model can't do natively. They generate at the
# nearest native ratio and are then reframed (canvas-extended) to the exact
# target -- at native resolution, never upscaled.
ALIAS_RATIOS = {"16:9": 16.0 / 9.0, "9:16": 9.0 / 16.0, "4:3": 4.0 / 3.0, "3:4": 3.0 / 4.0}
ALL_RATIOS = {**NATIVE_RATIOS, **ALIAS_RATIOS}

# Native output sizes the model produces per native aspect ratio. gpt-image-2
# has no size/resolution input, so these are the maximum available.
NATIVE_SIZES = {"1:1": (1024, 1024), "3:2": (1536, 1024), "2:3": (1024, 1536)}


# --------------------------------------------------------------------------
# Config / token
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Replicate
# --------------------------------------------------------------------------
def run_replicate(model, inputs, *, token=None):
    """Run a Replicate model and return the raw output.

    High-quality gpt-image-2 renders can take well over a minute, longer than
    the replicate client's default httpx read timeout. We use a client with a
    generous read timeout and retry on transient network errors.
    """
    import time
    import replicate

    if token:
        os.environ["REPLICATE_API_TOKEN"] = token
    elif "REPLICATE_API_TOKEN" not in os.environ:
        os.environ["REPLICATE_API_TOKEN"] = get_replicate_token()

    print(f"  Running Replicate model: {model} ...", file=sys.stderr)

    try:
        import httpx
        client = replicate.Client(
            api_token=os.environ.get("REPLICATE_API_TOKEN"),
            timeout=httpx.Timeout(900.0, connect=30.0),
        )
        runner = client.run
    except Exception:
        runner = lambda m, **kw: replicate.run(m, **kw)

    last_err = None
    for attempt in range(4):
        try:
            return runner(model, input=inputs)
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            transient = any(
                k in name for k in ("Timeout", "ReadError", "ConnectError",
                                    "RemoteProtocol", "PoolTimeout", "ConnectTimeout")
            )
            last_err = e
            if not transient or attempt == 3:
                raise
            wait = 5 * (2 ** attempt)
            print(f"  [retry {attempt + 1}/3] transient error {name}: {e}; "
                  f"waiting {wait}s ...", file=sys.stderr)
            time.sleep(wait)
    if last_err:
        raise last_err


def _extract_url(item):
    """Pull a URL string out of a Replicate FileOutput-like object."""
    u = getattr(item, "url", None)
    if isinstance(u, str):
        return u
    if callable(u):
        try:
            return u()
        except Exception:
            return None
    return None


def iter_output_items(output):
    """Normalize a Replicate output into a flat list of items."""
    if output is None:
        return []
    if isinstance(output, (list, tuple)):
        return list(output)
    return [output]


def save_output_item(item, output_path):
    """Persist a single Replicate output item (FileOutput, URL, or bytes)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Newer replicate clients return FileOutput objects with .read().
    if hasattr(item, "read"):
        try:
            data = item.read()
            output_path.write_bytes(data)
            return str(output_path)
        except Exception:
            pass

    url = item if isinstance(item, str) else _extract_url(item)
    if url and str(url).startswith("http"):
        return download_file(url, output_path)

    try:
        output_path.write_bytes(bytes(item))
        return str(output_path)
    except (TypeError, ValueError):
        print(f"  Warning: could not interpret output item of type {type(item)}", file=sys.stderr)
        return None


def download_file(url, output_path):
    """Download a URL to a local path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading: {output_path.name} ...", file=sys.stderr)
    urllib.request.urlretrieve(str(url), str(output_path))
    return str(output_path)


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------
def nearest_native_ratio(ratio_name):
    """Map any requested ratio name to the closest natively supported one."""
    if ratio_name in NATIVE_RATIOS:
        return ratio_name
    target = ALL_RATIOS[ratio_name]
    return min(NATIVE_RATIOS, key=lambda n: abs(NATIVE_RATIOS[n] - target))


def generate_gpt_image(prompt, *, input_images=None, aspect_ratio="3:2", quality="high",
                       count=1, output_format="png", background="auto",
                       moderation="auto", output_compression=90,
                       openai_api_key=None, token=None):
    """Call gpt-image-2 and return the raw Replicate output.

    aspect_ratio must be one of the model's native values (1:1, 3:2, 2:3).
    quality is the only fidelity control (high = best detail); the model has no
    size input, so output is at its native maximum (long edge ~1536px).
    File handles in input_images are NOT closed here; the caller owns them.
    """
    inputs = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "number_of_images": int(count),
        "output_format": output_format,
        "background": background,
        "moderation": moderation,
        "output_compression": int(output_compression),
    }
    if input_images:
        inputs["input_images"] = input_images
    if openai_api_key:
        inputs["openai_api_key"] = openai_api_key

    native = NATIVE_SIZES.get(aspect_ratio)
    print(f"  Model: {MODEL}", file=sys.stderr)
    print(f"  Quality: {quality} | Native ratio: {aspect_ratio}"
          + (f" (~{native[0]}x{native[1]})" if native else "")
          + f" | Images: {count} | Format: {output_format}", file=sys.stderr)
    if input_images:
        print(f"  Reference images: {len(input_images)}", file=sys.stderr)
    print(f"  Generating (this may take 1-3 minutes)...", file=sys.stderr)

    return run_replicate(MODEL, inputs, token=token)


# --------------------------------------------------------------------------
# Image post-processing (Pillow)
# --------------------------------------------------------------------------
def _require_pillow():
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Error: Pillow is required. Run:", file=sys.stderr)
        print(f"  pip3 install -r {SCRIPT_DIR}/requirements.txt", file=sys.stderr)
        sys.exit(1)


def sample_background_color(img, frac=0.02):
    """Estimate the dominant background color from a thin border frame.

    Returns an (R, G, B) tuple. Used to seamlessly extend the canvas when
    padding to a wider/taller aspect ratio, so the result has no visible bars.
    """
    from PIL import Image

    rgb = img.convert("RGB")
    w, h = rgb.size
    border = max(2, int(min(w, h) * frac))

    px = rgb.load()
    rs = gs = bs = n = 0
    # Top + bottom strips.
    for y in list(range(border)) + list(range(h - border, h)):
        for x in range(0, w, max(1, w // 256)):
            r, g, b = px[x, y]
            rs += r; gs += g; bs += b; n += 1
    # Left + right strips.
    for x in list(range(border)) + list(range(w - border, w)):
        for y in range(0, h, max(1, h // 256)):
            r, g, b = px[x, y]
            rs += r; gs += g; bs += b; n += 1

    if n == 0:
        return (255, 255, 255)
    return (round(rs / n), round(gs / n), round(bs / n))


def pad_to_aspect(img, target_ratio, pad_color="auto"):
    """Extend the canvas (never crop) so the image matches target_ratio.

    target_ratio is width/height. The image is centered and the new area is
    filled with pad_color (an (R,G,B) tuple, or "auto" to sample the border).
    """
    from PIL import Image

    rgb = img.convert("RGB")
    w, h = rgb.size
    src_ratio = w / h
    if abs(src_ratio - target_ratio) < 1e-3:
        return rgb

    if isinstance(pad_color, str) and pad_color == "auto":
        fill = sample_background_color(rgb)
    elif isinstance(pad_color, str):
        fill = _parse_hex_color(pad_color)
    else:
        fill = tuple(pad_color)

    if target_ratio > src_ratio:
        new_w, new_h = round(h * target_ratio), h
    else:
        new_w, new_h = w, round(w / target_ratio)

    canvas = Image.new("RGB", (new_w, new_h), fill)
    canvas.paste(rgb, ((new_w - w) // 2, (new_h - h) // 2))
    return canvas


def _parse_hex_color(value):
    s = value.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return (255, 255, 255)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def reframe_image(src_path, *, target_ratio_name, pad_color="auto"):
    """Reframe a generated image to an exact aspect ratio, saving in place.

    The canvas is extended (never cropped, never upscaled) so the image matches
    target_ratio_name. The new margin is filled with the sampled background
    color so a uniform studio/board background extends seamlessly. This keeps
    the model's native resolution -- it only changes the framing.

    Returns (final_path, "WxH").
    """
    _require_pillow()
    from PIL import Image

    src_path = Path(src_path)
    img = Image.open(str(src_path)).convert("RGB")
    target_ratio = ALL_RATIOS[target_ratio_name]

    img = pad_to_aspect(img, target_ratio, pad_color=pad_color)
    img.save(str(src_path))
    return str(src_path), f"{img.size[0]}x{img.size[1]}"
