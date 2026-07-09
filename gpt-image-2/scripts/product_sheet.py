#!/usr/bin/env python3
"""Generate a clean 4-view product reference sheet with GPT Image 2.

Produces a single sheet with EXACTLY four views: front three-quarter, rear
straight-on, a front close-up, and a left-side profile close-up — in a
photorealistic product-photography style, with consistent identity, colour,
materials, and hardware/surface details across all four views.

The 4-view frame, lighting, and no-text / no-extra-objects rules are fixed.
You adapt it to the product by passing --product (the noun phrase) and the
per-view detail slots (--front / --rear / --closeup / --profile), plus an
optional --style. Pass a product photo with --ref to lock the exact look.

Defaults: 16:9 aspect, high quality (the model's native maximum resolution),
neutral grey background, photorealistic product photography style.

Usage:
    python3 product_sheet.py --ref iphone.png \
        --product "iPhone 17 Pro Max in Cosmic Orange" \
        --front "6.9-inch Super Retina XDR display, Dynamic Island, anodized aluminum unibody, Camera Control on the right edge, USB-C on the bottom." \
        --rear "Full-width camera plateau, three 48MP lenses in a triangular pattern, LiDAR + LED flash, recessed Ceramic Shield glass panel, centred Apple logo." \
        --closeup "Dynamic Island housing the front camera, Ceramic Shield 2 glass, precision-machined frame edges, Action + volume buttons on the left." \
        --profile "Camera plateau thickness tapering into the unibody, 8.75mm body, seamless matte aluminum to glass transitions." \
        -o iphone_sheet.png

    # Minimal: let the agent's --product carry most of the detail
    python3 product_sheet.py --ref sneaker.png \
        --product "white leather low-top sneaker with a gum rubber sole" \
        -o sneaker_sheet.png
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
GENERATE = SCRIPT_DIR / "generate_image.py"

DEFAULT_PRODUCT = "product"
DEFAULT_STYLE = "Photorealistic product photography style."
DEFAULT_BG = "neutral grey"

# Fixed 4-view structure, from the product-reference-sheet framework.
OPENING = ("PRODUCT REFERENCE SHEET TEMPLATE\n"
           "Product reference sheet — four views on a {bg} background:")

VIEW1 = ("[VIEW 1 — FRONT, THREE-QUARTER] Front-facing three-quarter view of the {product}. "
         "Full product visible top to bottom.")
VIEW2 = ("[VIEW 2 — REAR, STRAIGHT-ON] Full rear view of the same {product}, directly from "
         "behind. Full product visible.")
VIEW3 = "[VIEW 3 — FRONT CLOSE-UP] Top third close-up, straight-on front view."
VIEW4 = "[VIEW 4 — PROFILE, LEFT SIDE] Full left-profile close-up showing the product edge-on."

CONSISTENCY = ("Lighting & presentation: Clean studio lighting — soft key light upper left, "
               "gentle fill from the right. Consistent product identity, proportions, colour, "
               "materials, and surface details across all four views.")
TAIL = "No text, no watermarks, no extra objects, no background environment."


def _view(base, detail):
    detail = (detail or "").strip()
    return f"{base} {detail}" if detail else base


def build_prompt(product, front, rear, closeup, profile, style, bg):
    product = product or DEFAULT_PRODUCT
    style = (style or DEFAULT_STYLE).strip()
    lighting = CONSISTENCY + (f" {style}" if style else "") + f" {TAIL}"
    lines = [
        OPENING.format(bg=bg or DEFAULT_BG),
        _view(VIEW1.format(product=product), front),
        _view(VIEW2.format(product=product), rear),
        _view(VIEW3, closeup),
        _view(VIEW4, profile),
        lighting,
    ]
    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser(
        description="Generate a clean 4-view product reference sheet with GPT Image 2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ref", action="append", default=[], metavar="PATH",
                        help="Reference image of the product (repeatable, locks the exact look)")
    parser.add_argument("--product", "-p", default=DEFAULT_PRODUCT,
                        help="Product noun phrase, e.g. 'iPhone 17 Pro Max in Cosmic Orange'")
    parser.add_argument("--front", default=None,
                        help="VIEW 1 detail: what the front three-quarter view should show")
    parser.add_argument("--rear", default=None,
                        help="VIEW 2 detail: what the rear straight-on view should show")
    parser.add_argument("--closeup", default=None,
                        help="VIEW 3 detail: what the front close-up should show")
    parser.add_argument("--profile", default=None,
                        help="VIEW 4 detail: what the left-side profile should show")
    parser.add_argument("--style", default=None,
                        help="Visual style (default: 'Photorealistic product photography style.')")
    parser.add_argument("--style-file", default=None, help="Read the style block from a file")
    parser.add_argument("--bg", default=DEFAULT_BG,
                        help="Background description (default: 'neutral grey')")
    parser.add_argument("--prompt-file", default=None,
                        help="Bypass the scaffold and use this complete prompt verbatim")
    parser.add_argument("--aspect-ratio", "-ar", default="16:9",
                        help="Output ratio (default: 16:9)")
    parser.add_argument("--quality", "-q", default="high",
                        choices=["low", "medium", "high", "auto"],
                        help="Fidelity (default: high = native maximum)")
    parser.add_argument("--count", "-n", type=int, default=1, help="Variations (1-10)")
    parser.add_argument("--pad-color", default="auto",
                        help="Canvas-extension fill: 'auto' (sample) or hex (default: auto)")
    parser.add_argument("--output", "-o", default="product_sheet.png", help="Output path")
    parser.add_argument("--print-prompt", action="store_true",
                        help="Print the assembled prompt and exit (no generation)")
    args = parser.parse_args()

    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    else:
        style = args.style
        if args.style_file:
            style = Path(args.style_file).read_text(encoding="utf-8").strip()
        prompt = build_prompt(args.product, args.front, args.rear, args.closeup,
                              args.profile, style, args.bg)

    if args.print_prompt:
        print(prompt)
        return

    if not args.ref:
        print("Note: no --ref provided. The product will be rendered from the description "
              "rather than matched to a reference photo.", file=sys.stderr)

    tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    tmp.write(prompt)
    tmp.close()

    cmd = [
        sys.executable, str(GENERATE),
        "--prompt-file", tmp.name,
        "--aspect-ratio", args.aspect_ratio,
        "--quality", args.quality,
        "--count", str(args.count),
        "--pad-color", args.pad_color,
        "--output", args.output,
    ]
    for ref in args.ref:
        cmd.extend(["--ref", ref])

    print("Generating product reference sheet...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    Path(tmp.name).unlink(missing_ok=True)

    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            print(f"  {line}", file=sys.stderr)

    if result.returncode != 0:
        print("Error: product sheet generation failed.", file=sys.stderr)
        sys.exit(result.returncode)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout)
        return

    data["kind"] = "product_sheet"
    data["product"] = args.product
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
