#!/usr/bin/env python3
"""Generate image assets for web and mobile apps using Google Gemini 3 Pro Image.

Usage:
    python3 generate_asset.py "a friendly robot" [options]

    # With reference images (use {image1}, {image2}, etc. in prompt to refer to them):
    python3 generate_asset.py "a rabbit using a computer showing {image1}" \
        --ref screenshot.png --style illustration -o rabbit.png

    # Multiple references (up to 14):
    python3 generate_asset.py "combine the style of {image1} with the subject from {image2}" \
        --ref style_ref.png --ref subject.png -o combined.png

Options:
    --style STYLE        Style preset (icon, illustration, photo, logo, etc.)
    --aspect-ratio AR    Aspect ratio (1:1, 16:9, 9:16, etc.)
    --resolution RES     Resolution: 1K, 2K, 4K
    --transparent        Remove background for transparent PNG
    --format FMT         Output format: png (default), webp, jpeg
    --output PATH        Output file path
    --ref PATH           Reference image (repeatable, up to 14). Use {image1}..{imageN} in prompt.
    --thinking LEVEL     Thinking level: high (default, best quality) or low (faster)
    --count N            Number of variations (1-4)
    --sizes SIZES        Also export at these sizes (comma-separated, e.g. "64,128,256")
    --raw-prompt         Use prompt as-is without style wrapping
    --list-styles        List available style presets
"""

import argparse
import json
import os
import re
import sys
import time
from io import BytesIO
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"
STYLES_FILE = SCRIPT_DIR / "styles.json"

MODEL_NAME = "gemini-3-pro-image-preview"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 10.0

BG_CANDIDATES = [
    ("FF00FF", "magenta (#FF00FF)"),
    ("00FF00", "bright green (#00FF00)"),
    ("0000FF", "blue (#0000FF)"),
    ("FF0000", "red (#FF0000)"),
    ("00FFFF", "cyan (#00FFFF)"),
    ("FFFF00", "yellow (#FFFF00)"),
]

COLOR_KEYWORDS = {
    "FF00FF": ["magenta", "pink", "purple", "violet", "fuchsia", "rose", "lavender", "plum"],
    "00FF00": ["green", "lime", "emerald", "mint", "forest", "olive", "leaf", "grass", "plant",
               "tree", "nature", "vet", "stethoscope", "#65a30d", "#a3e635", "#00ff00"],
    "0000FF": ["blue", "navy", "cobalt", "azure", "ocean", "sea", "water", "sky", "indigo"],
    "FF0000": ["red", "scarlet", "crimson", "ruby", "fire", "flame", "blood", "cherry", "tomato"],
    "00FFFF": ["cyan", "teal", "turquoise", "aqua", "aquamarine"],
    "FFFF00": ["yellow", "gold", "golden", "amber", "lemon", "sunshine", "sunflower", "blonde",
               "#d97706", "#fef3c7"],
}


def load_config():
    if not CONFIG_FILE.exists():
        print("Error: No config found. Run setup_key.py first:", file=sys.stderr)
        print(f"  python3 {SCRIPT_DIR}/setup_key.py YOUR_GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_styles():
    if not STYLES_FILE.exists():
        return {}
    return json.loads(STYLES_FILE.read_text(encoding="utf-8"))


def list_styles():
    styles = load_styles()
    print("Available style presets:\n")
    for key, style in styles.items():
        recommended = []
        if style.get("recommended_aspect_ratio"):
            recommended.append(f"ratio={style['recommended_aspect_ratio']}")
        if style.get("recommended_transparent"):
            recommended.append("transparent")
        rec_str = f" [{', '.join(recommended)}]" if recommended else ""
        print(f"  {key:16s} {style['name']}: {style['description']}{rec_str}")


# ──────────────────────────────────────────────────────────
# Natural language prompt pipeline (optimized for Gemini 3 Pro Image)
# ──────────────────────────────────────────────────────────

def pick_bg_color(user_prompt, ref_paths=None):
    """Pick a solid background color that won't conflict with the subject.

    Analyzes the prompt text for color keywords, then samples dominant colors
    from any reference images. Returns (hex, label) for the best candidate.
    """
    prompt_lower = user_prompt.lower()

    conflicting = set()
    for hex_code, keywords in COLOR_KEYWORDS.items():
        for kw in keywords:
            if kw in prompt_lower:
                conflicting.add(hex_code)
                break

    if ref_paths:
        try:
            from PIL import Image as PILImage
            import numpy as np
        except ImportError:
            pass
        else:
            for rp in ref_paths:
                p = Path(rp)
                if not p.exists():
                    continue
                try:
                    img = PILImage.open(str(p)).convert("RGB")
                    img_small = img.resize((64, 64), PILImage.LANCZOS)
                    pixels = np.array(img_small).reshape(-1, 3).astype(float)

                    for hex_code, _ in BG_CANDIDATES:
                        target = np.array([int(hex_code[i:i+2], 16) for i in (0, 2, 4)], dtype=float)
                        dists = np.sqrt(np.sum((pixels - target) ** 2, axis=1))
                        if np.min(dists) < 80:
                            conflicting.add(hex_code)
                except Exception:
                    continue

    for hex_code, label in BG_CANDIDATES:
        if hex_code not in conflicting:
            return hex_code, label

    return BG_CANDIDATES[0][0], BG_CANDIDATES[0][1]


def build_natural_prompt(user_prompt, style_key, styles, transparent=False,
                         aspect_ratio=None, bg_color_info=None):
    """Build a natural-language prompt optimized for Gemini 3 Pro Image.

    Uses the recommended formula:
    [Subject + Adjectives] doing [Action] in [Location/Context].
    [Composition/Camera Angle]. [Lighting/Atmosphere]. [Style/Media].
    [Specific Constraint/Text].

    Gemini 3 Pro understands natural language better than rigid section headers.
    """
    style_data = styles.get(style_key, {})
    parts = []

    parts.append(user_prompt.rstrip(". "))

    if style_data:
        aesthetic = style_data.get("aesthetic", "")
        if aesthetic:
            parts.append(aesthetic)
        qualities = style_data.get("qualities", [])
        if qualities:
            parts.append(", ".join(qualities))

    if style_data.get("default_framing"):
        parts.append(style_data["default_framing"])

    if transparent and bg_color_info:
        hex_code, label = bg_color_info
        parts.append(f"The background is plain #{hex_code} {label}. "
                     f"No shadows, no gradients, no floor, no reflections — "
                     f"just a single flat #{hex_code} color filling the entire background")

    constraints = list(style_data.get("default_constraints", []))
    if constraints:
        parts.append(". ".join(constraints))

    return ". ".join(p.rstrip(". ") for p in parts if p) + "."


def build_reference_contents(prompt, ref_images, ref_paths):
    """Build the contents array for Gemini, interleaving text and images optimally.

    Strategy based on Gemini 3 Pro Image best practices:
    - Single reference without placeholder: image BEFORE text (best for edits/restyling)
    - Single reference with placeholder: interleave at placeholder position
    - Multiple references: interleave naturally at placeholder positions
    - Without placeholders: references appended with role descriptions
    """
    has_placeholders = bool(re.search(r"\{image\d+\}", prompt))

    if has_placeholders:
        return _interleave_prompt_and_images(prompt, ref_images)

    if len(ref_images) == 1:
        return [ref_images[0], prompt]

    contents = []
    for i, img in enumerate(ref_images):
        label = f"Reference image {i + 1}"
        if ref_paths and i < len(ref_paths):
            name = Path(ref_paths[i]).stem
            label = f"Reference image {i + 1} ({name})"
        contents.append(f"{label}:")
        contents.append(img)
    contents.append(f"\nInstruction: {prompt}")
    return contents


def _interleave_prompt_and_images(prompt, ref_images):
    """Split prompt at {image1}, {image2}, etc. and interleave with PIL images."""
    parts = re.split(r"(\{image\d+\})", prompt)
    contents = []
    for part in parts:
        m = re.match(r"\{image(\d+)\}", part)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(ref_images):
                if contents and isinstance(contents[-1], str):
                    contents[-1] = contents[-1].rstrip()
                contents.append(ref_images[idx])
            else:
                contents.append(part)
        else:
            if part:
                contents.append(part)

    return contents


def generate_image(client, prompt_or_contents, aspect_ratio, resolution,
                   reference_paths=None, thinking_level="high"):
    """Call Gemini 3 Pro Image API to generate an image.

    Supports both plain text prompts and pre-built content arrays with
    interleaved images. Includes retry logic with exponential backoff.
    """
    from google.genai import types
    from PIL import Image as PILImage

    image_config_kwargs = {}
    if aspect_ratio:
        image_config_kwargs["aspect_ratio"] = aspect_ratio
    if resolution:
        image_config_kwargs["image_size"] = resolution

    config = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(**image_config_kwargs) if image_config_kwargs else None,
    )

    if isinstance(prompt_or_contents, str):
        ref_images = []
        if reference_paths:
            for rp in reference_paths:
                p = Path(rp)
                if p.exists():
                    ref_images.append(PILImage.open(str(p)))
                else:
                    print(f"Warning: Reference image not found: {rp}", file=sys.stderr)

        if ref_images:
            has_placeholders = bool(re.search(r"\{image\d+\}", prompt_or_contents))
            if has_placeholders:
                contents = _interleave_prompt_and_images(prompt_or_contents, ref_images)
            elif len(ref_images) == 1:
                contents = [ref_images[0], prompt_or_contents]
            else:
                contents = [prompt_or_contents] + ref_images
        else:
            contents = [prompt_or_contents]
    else:
        contents = prompt_or_contents

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            )

            images = []
            text_parts = []
            for part in response.candidates[0].content.parts:
                if part.text is not None:
                    text_parts.append(part.text)
                elif part.inline_data is not None:
                    img = PILImage.open(BytesIO(part.inline_data.data))
                    images.append(img)

            if text_parts:
                print(f"Model response: {' '.join(text_parts)}", file=sys.stderr)

            return images

        except Exception as e:
            last_error = e
            error_str = str(e)

            if "429" in error_str:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                delay = min(delay, 300)
                print(f"Rate limited, waiting {delay:.0f}s (attempt {attempt + 1}/{MAX_RETRIES})...",
                      file=sys.stderr)
                time.sleep(delay)
            elif "400" in error_str:
                print(f"Bad request: {e}", file=sys.stderr)
                break
            elif "403" in error_str:
                print(f"Content policy or access error: {e}", file=sys.stderr)
                break
            else:
                print(f"Attempt {attempt + 1} failed: {e}", file=sys.stderr)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(5)

    print(f"Error: All {MAX_RETRIES} attempts failed. Last error: {last_error}", file=sys.stderr)
    return []


def remove_background(image, chroma_hex=None):
    """Remove background, returning RGBA image.

    If chroma_hex is provided, uses fast chroma-key removal targeting that
    exact color. Falls back to rembg ML if no chroma color given.
    """
    if chroma_hex:
        return _chroma_remove(image, chroma_hex)

    try:
        from rembg import remove
        return remove(image)
    except ImportError:
        print("Warning: rembg not installed. Run: pip3 install rembg", file=sys.stderr)
        print("Returning image without background removal.", file=sys.stderr)
        return image


def _chroma_remove(image, color_hex, tolerance=40):
    """Remove a solid-color background via chroma keying.

    Works globally on every pixel (including enclosed interior regions like
    gaps between arms and body, stethoscope holes, between legs, etc.).

    Two-pass approach handles both flat and textured/gradient backgrounds:
      Pass 1 (RGB): exact chroma match with tolerance — catches flat bg.
      Pass 2 (HSV hue): catches desaturated/lighter/darker variants of the
             chroma hue that Gemini sometimes renders as textured backgrounds.
    Then:
      Despill to neutralize chroma contamination on edge pixels.
      1px alpha erosion to eat the outermost fringe ring.
    """
    import numpy as np
    from PIL import Image as PILImage, ImageFilter
    import colorsys

    img = image.convert("RGBA")
    data = np.array(img, dtype=np.float64)

    tr = int(color_hex[0:2], 16)
    tg = int(color_hex[2:4], 16)
    tb = int(color_hex[4:6], 16)
    target = np.array([tr, tg, tb], dtype=np.float64)

    rgb = data[:, :, :3]
    dist = np.sqrt(np.sum((rgb - target) ** 2, axis=2))

    hard = float(tolerance)
    soft = hard + 60.0

    # Pass 1: RGB distance — catches flat chroma background
    alpha = np.where(dist < hard, 0.0,
            np.where(dist < soft,
                     ((dist - hard) / (soft - hard)) * 255.0,
                     data[:, :, 3]))

    # Pass 2: HSV hue match — catches textured/gradient variants of the chroma
    target_h, target_s, _ = colorsys.rgb_to_hsv(tr / 255.0, tg / 255.0, tb / 255.0)

    r_norm = data[:, :, 0] / 255.0
    g_norm = data[:, :, 1] / 255.0
    b_norm = data[:, :, 2] / 255.0

    cmax = np.maximum(np.maximum(r_norm, g_norm), b_norm)
    cmin = np.minimum(np.minimum(r_norm, g_norm), b_norm)
    delta = cmax - cmin

    hue = np.zeros_like(cmax)
    mask_r = (cmax == r_norm) & (delta > 0)
    mask_g = (cmax == g_norm) & (delta > 0)
    mask_b = (cmax == b_norm) & (delta > 0)
    hue[mask_r] = (((g_norm[mask_r] - b_norm[mask_r]) / delta[mask_r]) % 6) / 6.0
    hue[mask_g] = (((b_norm[mask_g] - r_norm[mask_g]) / delta[mask_g]) + 2) / 6.0
    hue[mask_b] = (((r_norm[mask_b] - g_norm[mask_b]) / delta[mask_b]) + 4) / 6.0

    sat = np.where(cmax > 0, delta / cmax, 0)

    hue_diff = np.abs(hue - target_h)
    hue_diff = np.minimum(hue_diff, 1.0 - hue_diff)

    # Saturated chroma variants (textured/gradient bg with visible color)
    hue_match_saturated = (hue_diff < 0.08) & (sat > 0.08)
    # Washed-out / near-white variants: very low saturation but high lightness
    # and the little color they have is in the chroma hue family
    hue_match_washed = (hue_diff < 0.12) & (sat > 0.01) & (sat < 0.15) & (cmax > 0.75)
    hue_match = hue_match_saturated | hue_match_washed

    still_opaque = alpha > 128
    hue_kill = hue_match & still_opaque

    if np.any(hue_kill):
        hue_hard = 0.03
        hue_soft = 0.08
        hue_alpha = np.where(hue_diff < hue_hard, 0.0,
                   np.where(hue_diff < hue_soft,
                            ((hue_diff - hue_hard) / (hue_soft - hue_hard)) * 255.0,
                            255.0))
        combined = np.where(hue_kill, np.minimum(alpha, hue_alpha), alpha)
        alpha = combined

    # Despill: suppress chroma contamination on surviving edge pixels
    alive = alpha > 0
    if np.any(alive):
        spill_strength = np.clip(1.0 - (dist - hard) / (soft * 2.0 - hard), 0, 1)
        hue_spill = hue_match & alive
        spill_strength[hue_spill] = np.maximum(
            spill_strength[hue_spill],
            np.clip(1.0 - hue_diff[hue_spill] / 0.08, 0, 0.7)
        )
        spill_mask = alive & (spill_strength > 0)

        if np.any(spill_mask):
            high_channels = [i for i in range(3) if target[i] > 128]
            low_channels = [i for i in range(3) if target[i] <= 128]

            if high_channels and low_channels:
                low_ref = np.min(np.stack([data[:, :, c] for c in low_channels], axis=-1), axis=-1)
                for c in high_channels:
                    ch = data[:, :, c]
                    excess = ch[spill_mask] - low_ref[spill_mask]
                    reduction = excess * spill_strength[spill_mask] * 0.85
                    ch[spill_mask] = np.clip(ch[spill_mask] - np.maximum(reduction, 0), 0, 255)

    data[:, :, 3] = alpha

    # Erode alpha by 1px to eat the outermost fringe ring
    result = PILImage.fromarray(data.astype(np.uint8))
    a_channel = result.split()[3]
    a_eroded = a_channel.filter(ImageFilter.MinFilter(3))
    result.putalpha(a_eroded)

    return result


def trim_transparent(image, padding=0):
    """Crop an RGBA image to the bounding box of non-transparent pixels.

    Adds optional padding (in pixels) around the trimmed content.
    Returns the original image unchanged if it has no alpha channel
    or if all pixels are transparent.
    """
    if image.mode != "RGBA":
        return image

    import numpy as np
    alpha = np.array(image.split()[3])
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)

    if not rows.any():
        return image

    top, bottom = np.argmax(rows), alpha.shape[0] - np.argmax(rows[::-1])
    left, right = np.argmax(cols), alpha.shape[1] - np.argmax(cols[::-1])

    if padding > 0:
        top = max(0, top - padding)
        left = max(0, left - padding)
        bottom = min(alpha.shape[0], bottom + padding)
        right = min(alpha.shape[1], right + padding)

    return image.crop((left, top, right, bottom))


def save_image(image, output_path, fmt="png"):
    """Save image in the specified format."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "jpeg" or fmt == "jpg":
        if image.mode == "RGBA":
            bg = __import__("PIL").Image.new("RGB", image.size, (255, 255, 255))
            bg.paste(image, mask=image.split()[3])
            image = bg
        image.save(str(output_path), "JPEG", quality=95)
    elif fmt == "webp":
        image.save(str(output_path), "WEBP", quality=95, lossless=image.mode == "RGBA")
    else:
        image.save(str(output_path), "PNG")

    return output_path


def export_sizes(image, base_path, sizes, fmt="png"):
    """Export image at multiple square sizes."""
    from PIL import Image as PILImage
    base = Path(base_path)
    stem = base.stem
    parent = base.parent
    parent.mkdir(parents=True, exist_ok=True)

    exported = []
    for size in sizes:
        resized = image.copy()
        resized = resized.resize((size, size), PILImage.LANCZOS)
        ext = "jpg" if fmt == "jpeg" else fmt
        size_path = parent / f"{stem}_{size}x{size}.{ext}"
        save_image(resized, size_path, fmt)
        exported.append(str(size_path))
        print(f"  Exported: {size_path} ({size}x{size})", file=sys.stderr)

    return exported


def main():
    parser = argparse.ArgumentParser(description="Generate image assets with Google Gemini 3 Pro Image")
    parser.add_argument("prompt", nargs="?", help="Description of the asset to generate")
    parser.add_argument("--style", "-s", default=None, help="Style preset name")
    parser.add_argument("--aspect-ratio", "-ar", default=None,
                        help="Aspect ratio (1:1, 16:9, 9:16, 3:2, 2:3, 3:4, 4:3, 4:5, 5:4, 21:9)")
    parser.add_argument("--resolution", "-r", default=None, choices=["1K", "2K", "4K"],
                        help="Resolution (1K default, 2K, 4K)")
    parser.add_argument("--transparent", "-t", action="store_true",
                        help="Remove background for transparent PNG")
    parser.add_argument("--format", "-f", default=None, choices=["png", "webp", "jpeg"],
                        help="Output format")
    parser.add_argument("--output", "-o", default=None, help="Output file path")
    parser.add_argument("--ref", action="append", dest="references", metavar="PATH",
                        help="Reference image (repeatable, up to 14). Use {image1}..{imageN} in prompt.")
    parser.add_argument("--reference", dest="reference_legacy", metavar="PATH",
                        help=argparse.SUPPRESS)
    parser.add_argument("--thinking", default="high", choices=["high", "low"],
                        help="Thinking level: high (default, best quality) or low (faster)")
    parser.add_argument("--count", "-n", type=int, default=1, help="Number of variations (1-4)")
    parser.add_argument("--sizes", help="Export at multiple sizes (comma-separated, e.g. 64,128,256)")
    parser.add_argument("--raw-prompt", action="store_true", help="Use prompt as-is, no style wrapping")
    parser.add_argument("--list-styles", action="store_true", help="List available style presets")

    args = parser.parse_args()

    if args.list_styles:
        list_styles()
        return

    if not args.prompt:
        parser.print_help()
        sys.exit(1)

    config = load_config()
    styles = load_styles()

    api_key = config.get("gemini_api_key", "")
    if not api_key:
        print("Error: No API key configured. Run:", file=sys.stderr)
        print(f"  python3 {SCRIPT_DIR}/setup_key.py YOUR_GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    try:
        from google import genai
        from PIL import Image as PILImage
    except ImportError:
        print("Error: google-genai not installed. Run: pip3 install google-genai", file=sys.stderr)
        sys.exit(1)

    style_choice = args.style or config.get("default_style", "illustration")
    fmt = args.format or config.get("default_format", "png")

    aspect_ratio = args.aspect_ratio
    if not aspect_ratio and style_choice in styles:
        aspect_ratio = styles[style_choice].get("recommended_aspect_ratio")

    transparent = args.transparent
    if not transparent and not args.format and style_choice in styles:
        transparent = styles[style_choice].get("recommended_transparent", False)
        if transparent and not args.transparent:
            transparent = False

    if transparent:
        fmt = "png"

    ref_paths = args.references or []
    if args.reference_legacy and not ref_paths:
        ref_paths = [args.reference_legacy]

    if len(ref_paths) > 14:
        print("Warning: Gemini 3 Pro Image supports up to 14 reference images. Using first 14.",
              file=sys.stderr)
        ref_paths = ref_paths[:14]

    ext = "jpg" if fmt == "jpeg" else fmt
    output_base = args.output or f"asset.{ext}"

    print(f"Model: {MODEL_NAME}", file=sys.stderr)
    print(f"Style: {style_choice}", file=sys.stderr)
    print(f"Aspect ratio: {aspect_ratio or 'default'}", file=sys.stderr)
    print(f"Thinking: {args.thinking}", file=sys.stderr)
    if args.resolution:
        print(f"Resolution: {args.resolution}", file=sys.stderr)
    if transparent:
        print(f"Background removal: enabled", file=sys.stderr)
    if ref_paths:
        print(f"Reference images: {len(ref_paths)}", file=sys.stderr)
        for i, rp in enumerate(ref_paths, 1):
            print(f"  {{image{i}}}: {rp}", file=sys.stderr)

    client = genai.Client(api_key=api_key)

    # Load reference images
    ref_images = []
    if ref_paths:
        for rp in ref_paths:
            p = Path(rp)
            if p.exists():
                ref_images.append(PILImage.open(str(p)))
            else:
                print(f"Warning: Reference image not found: {rp}", file=sys.stderr)

    # Pick a background color that doesn't conflict with the subject
    bg_color_info = None
    if transparent:
        bg_hex, bg_label = pick_bg_color(args.prompt, ref_paths or None)
        bg_color_info = (bg_hex, bg_label)
        print(f"Background color: #{bg_hex} ({bg_label})", file=sys.stderr)

    # Build prompt and contents
    if args.raw_prompt:
        full_prompt = args.prompt
        if transparent and bg_color_info:
            hex_code, label = bg_color_info
            bg_hint = (f"The background is plain #{hex_code} {label}. "
                       f"No shadows, no gradients, no floor, no reflections — "
                       f"just a single flat #{hex_code} color filling the entire background")
            full_prompt = full_prompt.rstrip(". ") + f". {bg_hint}."
        if ref_images:
            contents = build_reference_contents(full_prompt, ref_images, ref_paths)
        else:
            contents = full_prompt
    else:
        full_prompt = build_natural_prompt(
            args.prompt, style_choice, styles,
            transparent=transparent,
            aspect_ratio=aspect_ratio,
            bg_color_info=bg_color_info,
        )
        if ref_images:
            contents = build_reference_contents(full_prompt, ref_images, ref_paths)
        else:
            contents = full_prompt

    print(f"Generating...", file=sys.stderr)

    count = min(max(args.count, 1), 4)
    all_images = []

    for i in range(count):
        images = generate_image(
            client, contents,
            aspect_ratio, args.resolution,
            thinking_level=args.thinking,
        )
        all_images.extend(images)
        if not images:
            print(f"Warning: No image returned for attempt {i+1}", file=sys.stderr)

    if not all_images:
        print("Error: No images were generated. Try a different prompt.", file=sys.stderr)
        sys.exit(1)

    for idx, image in enumerate(all_images):
        if transparent:
            chroma_hex = bg_color_info[0] if bg_color_info else None
            method_label = f"chroma key #{chroma_hex}" if chroma_hex else "ML (rembg)"
            print(f"Removing background ({method_label})...", file=sys.stderr)
            image = remove_background(image, chroma_hex=chroma_hex)
            before = image.size
            image = trim_transparent(image, padding=2)
            print(f"Trimmed: {before[0]}x{before[1]} → {image.size[0]}x{image.size[1]}", file=sys.stderr)

        if idx == 0 and len(all_images) == 1:
            out_path = output_base
        else:
            base = Path(output_base)
            out_path = str(base.parent / f"{base.stem}_{idx+1}{base.suffix}")

        saved = save_image(image, out_path, fmt)
        print(f"Saved: {saved} ({image.size[0]}x{image.size[1]}, {image.mode})", file=sys.stderr)

        if args.sizes:
            size_list = [int(s.strip()) for s in args.sizes.split(",")]
            export_sizes(image, out_path, size_list, fmt)

    output_json = {
        "prompt": args.prompt,
        "full_prompt": full_prompt if isinstance(contents, str) else args.prompt,
        "style": style_choice,
        "model": MODEL_NAME,
        "aspect_ratio": aspect_ratio,
        "resolution": args.resolution,
        "thinking": args.thinking,
        "transparent": transparent,
        "format": fmt,
        "reference_images": ref_paths if ref_paths else None,
        "files": [str(Path(output_base).parent / f"{Path(output_base).stem}_{i+1}{Path(output_base).suffix}")
                  if len(all_images) > 1 else str(output_base) for i in range(len(all_images))],
    }
    print(json.dumps(output_json, indent=2))


if __name__ == "__main__":
    main()
