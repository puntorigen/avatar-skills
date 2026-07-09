#!/usr/bin/env python3
"""Resize and export image assets for platform-specific sizes.

Usage:
    python3 resize_assets.py <input_image> --preset ios-icon --output icons/
    python3 resize_assets.py <input_image> --sizes 16,32,64,128,256,512 --output sizes/
    python3 resize_assets.py <input_image> --preset android-icon --format webp --output res/

Presets:
    ios-icon        iOS app icon sizes (all required sizes)
    android-icon    Android adaptive icon sizes (mdpi to xxxhdpi + play store)
    favicon         Web favicon sizes
    pwa-icon        Progressive Web App icon sizes
    social-media    Social media profile/cover sizes
    custom          Use --sizes for custom dimensions
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow not installed. Run: pip3 install Pillow", file=sys.stderr)
    sys.exit(1)


PRESETS = {
    "ios-icon": {
        "description": "iOS App Icon sizes",
        "sizes": [
            {"name": "icon-20@1x", "width": 20, "height": 20},
            {"name": "icon-20@2x", "width": 40, "height": 40},
            {"name": "icon-20@3x", "width": 60, "height": 60},
            {"name": "icon-29@1x", "width": 29, "height": 29},
            {"name": "icon-29@2x", "width": 58, "height": 58},
            {"name": "icon-29@3x", "width": 87, "height": 87},
            {"name": "icon-40@1x", "width": 40, "height": 40},
            {"name": "icon-40@2x", "width": 80, "height": 80},
            {"name": "icon-40@3x", "width": 120, "height": 120},
            {"name": "icon-60@2x", "width": 120, "height": 120},
            {"name": "icon-60@3x", "width": 180, "height": 180},
            {"name": "icon-76@1x", "width": 76, "height": 76},
            {"name": "icon-76@2x", "width": 152, "height": 152},
            {"name": "icon-83.5@2x", "width": 167, "height": 167},
            {"name": "icon-1024", "width": 1024, "height": 1024},
        ],
    },
    "android-icon": {
        "description": "Android adaptive icon sizes",
        "sizes": [
            {"name": "mipmap-mdpi/ic_launcher", "width": 48, "height": 48},
            {"name": "mipmap-hdpi/ic_launcher", "width": 72, "height": 72},
            {"name": "mipmap-xhdpi/ic_launcher", "width": 96, "height": 96},
            {"name": "mipmap-xxhdpi/ic_launcher", "width": 144, "height": 144},
            {"name": "mipmap-xxxhdpi/ic_launcher", "width": 192, "height": 192},
            {"name": "playstore-icon", "width": 512, "height": 512},
        ],
    },
    "favicon": {
        "description": "Web favicon sizes",
        "sizes": [
            {"name": "favicon-16", "width": 16, "height": 16},
            {"name": "favicon-32", "width": 32, "height": 32},
            {"name": "favicon-48", "width": 48, "height": 48},
            {"name": "apple-touch-icon", "width": 180, "height": 180},
            {"name": "favicon-192", "width": 192, "height": 192},
            {"name": "favicon-512", "width": 512, "height": 512},
        ],
    },
    "pwa-icon": {
        "description": "Progressive Web App icon sizes",
        "sizes": [
            {"name": "pwa-64", "width": 64, "height": 64},
            {"name": "pwa-72", "width": 72, "height": 72},
            {"name": "pwa-128", "width": 128, "height": 128},
            {"name": "pwa-144", "width": 144, "height": 144},
            {"name": "pwa-152", "width": 152, "height": 152},
            {"name": "pwa-192", "width": 192, "height": 192},
            {"name": "pwa-256", "width": 256, "height": 256},
            {"name": "pwa-384", "width": 384, "height": 384},
            {"name": "pwa-512", "width": 512, "height": 512},
        ],
    },
    "social-media": {
        "description": "Social media image sizes",
        "sizes": [
            {"name": "og-image", "width": 1200, "height": 630},
            {"name": "twitter-card", "width": 1200, "height": 600},
            {"name": "instagram-square", "width": 1080, "height": 1080},
            {"name": "instagram-story", "width": 1080, "height": 1920},
            {"name": "linkedin-banner", "width": 1584, "height": 396},
            {"name": "youtube-thumbnail", "width": 1280, "height": 720},
        ],
    },
}


def resize_image(img, width, height, preserve_aspect=True):
    """Resize image, optionally preserving aspect ratio with padding."""
    if preserve_aspect and (img.width / img.height) != (width / height):
        img_ratio = img.width / img.height
        target_ratio = width / height

        if img_ratio > target_ratio:
            new_w = width
            new_h = int(width / img_ratio)
        else:
            new_h = height
            new_w = int(height * img_ratio)

        resized = img.resize((new_w, new_h), Image.LANCZOS)

        if img.mode == "RGBA":
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        else:
            canvas = Image.new("RGB", (width, height), (255, 255, 255))

        x = (width - new_w) // 2
        y = (height - new_h) // 2
        canvas.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)
        return canvas
    else:
        return img.resize((width, height), Image.LANCZOS)


def save_output(img, path, fmt="png"):
    """Save image in the specified format."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt in ("jpeg", "jpg"):
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        img.save(str(path), "JPEG", quality=95)
    elif fmt == "webp":
        img.save(str(path), "WEBP", quality=95, lossless=img.mode == "RGBA")
    else:
        img.save(str(path), "PNG")


def main():
    parser = argparse.ArgumentParser(description="Resize assets for platform-specific sizes")
    parser.add_argument("input", nargs="?", help="Input image path")
    parser.add_argument("--preset", "-p",
                        help=f"Size preset ({', '.join(PRESETS.keys())})")
    parser.add_argument("--sizes", help="Custom sizes as WxH pairs or square sizes (e.g. '64,128,256' or '1200x630,1080x1080')")
    parser.add_argument("--output", "-o", default=".", help="Output directory")
    parser.add_argument("--format", "-f", default="png", choices=["png", "webp", "jpeg"],
                        help="Output format")
    parser.add_argument("--no-padding", action="store_true",
                        help="Stretch to fill instead of padding to preserve aspect ratio")
    parser.add_argument("--list-presets", action="store_true", help="List available presets")

    args = parser.parse_args()

    if args.list_presets:
        print("Available presets:\n")
        for key, preset in PRESETS.items():
            sizes_str = ", ".join(f"{s['width']}x{s['height']}" for s in preset["sizes"])
            print(f"  {key:16s} {preset['description']}")
            print(f"                   Sizes: {sizes_str}\n")
        return

    if not args.preset and not args.sizes:
        parser.print_help()
        print("\nError: Specify --preset or --sizes", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    img = Image.open(str(input_path))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = "jpg" if args.format == "jpeg" else args.format

    sizes_to_export = []

    if args.preset:
        if args.preset not in PRESETS:
            print(f"Error: Unknown preset '{args.preset}'. Use --list-presets to see options.", file=sys.stderr)
            sys.exit(1)
        sizes_to_export = PRESETS[args.preset]["sizes"]
        print(f"Preset: {args.preset} ({PRESETS[args.preset]['description']})", file=sys.stderr)

    if args.sizes:
        for s in args.sizes.split(","):
            s = s.strip()
            if "x" in s:
                w, h = s.split("x")
                sizes_to_export.append({"name": f"{w}x{h}", "width": int(w), "height": int(h)})
            else:
                sz = int(s)
                sizes_to_export.append({"name": f"{sz}x{sz}", "width": sz, "height": sz})

    result = {"input": str(input_path), "output_dir": str(output_dir), "files": []}

    for size_spec in sizes_to_export:
        w, h = size_spec["width"], size_spec["height"]
        name = size_spec["name"]

        resized = resize_image(img, w, h, preserve_aspect=not args.no_padding)

        if "/" in name:
            out_path = output_dir / f"{name}.{ext}"
        else:
            out_path = output_dir / f"{name}.{ext}"

        save_output(resized, out_path, args.format)
        result["files"].append({"name": name, "path": str(out_path), "size": f"{w}x{h}"})
        print(f"  {out_path} ({w}x{h})", file=sys.stderr)

    print(f"\nExported {len(sizes_to_export)} files to {output_dir}", file=sys.stderr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
