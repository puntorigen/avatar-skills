#!/usr/bin/env python3
"""Remove background from an image, producing a transparent PNG.

Usage:
    python3 remove_bg.py <input_image> [--output output.png]
    python3 remove_bg.py <input_image> --method chroma --color 00FF00
    python3 remove_bg.py input_dir/ --batch --output output_dir/

Methods:
    ml (default)    - ML-based removal using rembg (best quality)
    chroma          - Chroma key removal by color (fast, for green screen images)
"""

import argparse
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow not installed. Run: pip3 install Pillow", file=sys.stderr)
    sys.exit(1)


def remove_bg_ml(image):
    """Remove background using rembg ML model."""
    try:
        from rembg import remove
        return remove(image)
    except ImportError:
        print("Error: rembg not installed. Run: pip3 install rembg", file=sys.stderr)
        sys.exit(1)


def remove_bg_chroma(image, color_hex="00FF00", tolerance=30):
    """Remove background by chroma keying a specific color."""
    import numpy as np

    img = image.convert("RGBA")
    data = np.array(img)

    r_target = int(color_hex[0:2], 16)
    g_target = int(color_hex[2:4], 16)
    b_target = int(color_hex[4:6], 16)

    r, g, b, a = data[:, :, 0], data[:, :, 1], data[:, :, 2], data[:, :, 3]

    mask = (
        (abs(r.astype(int) - r_target) < tolerance) &
        (abs(g.astype(int) - g_target) < tolerance) &
        (abs(b.astype(int) - b_target) < tolerance)
    )

    data[mask] = [0, 0, 0, 0]

    return Image.fromarray(data)


def process_image(input_path, output_path, method="ml", chroma_color="00FF00", tolerance=30):
    """Process a single image."""
    img = Image.open(input_path)

    if method == "chroma":
        result = remove_bg_chroma(img, chroma_color, tolerance)
    else:
        result = remove_bg_ml(img)

    result.save(str(output_path), "PNG")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Remove image background")
    parser.add_argument("input", help="Input image path or directory (with --batch)")
    parser.add_argument("--output", "-o", help="Output path (file or directory)")
    parser.add_argument("--method", "-m", choices=["ml", "chroma"], default="ml",
                        help="Removal method: ml (rembg) or chroma (color key)")
    parser.add_argument("--color", default="00FF00",
                        help="Chroma key color hex (default: 00FF00 green)")
    parser.add_argument("--tolerance", type=int, default=30,
                        help="Chroma key color tolerance (default: 30)")
    parser.add_argument("--batch", action="store_true",
                        help="Process all images in directory")
    args = parser.parse_args()

    input_path = Path(args.input)

    if args.batch and input_path.is_dir():
        output_dir = Path(args.output) if args.output else input_path / "transparent"
        output_dir.mkdir(parents=True, exist_ok=True)

        extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
        images = [f for f in input_path.iterdir() if f.suffix.lower() in extensions]

        print(f"Processing {len(images)} images...", file=sys.stderr)
        for img_path in sorted(images):
            out_path = output_dir / f"{img_path.stem}.png"
            process_image(img_path, out_path, args.method, args.color, args.tolerance)
            print(f"  {img_path.name} -> {out_path.name}", file=sys.stderr)

        print(f"Done. Output: {output_dir}", file=sys.stderr)
    else:
        if not input_path.exists():
            print(f"Error: File not found: {args.input}", file=sys.stderr)
            sys.exit(1)

        if args.output:
            output_path = Path(args.output)
        else:
            output_path = input_path.parent / f"{input_path.stem}_nobg.png"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = process_image(input_path, output_path, args.method, args.color, args.tolerance)
        print(f"Saved: {result}", file=sys.stderr)


if __name__ == "__main__":
    main()
