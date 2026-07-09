#!/usr/bin/env python3
"""Generate images with OpenAI GPT Image 2 on Replicate.

GPT Image 2 follows instructions precisely and preserves the identity of
reference images at high fidelity -- ideal for character consistency,
storyboards, editing, and text-in-image work.

The model natively supports only 1:1 / 3:2 / 2:3 and has no size/resolution
control -- it outputs at its native maximum (long edge ~1536px), and quality
only changes fidelity (we default to high). This wrapper adds 16:9 / 9:16 /
4:3 / 3:4 output by generating at the nearest native ratio and seamlessly
extending the canvas with the sampled background color -- at native
resolution, never upscaled.

Usage:
    # Text -> image (highest native quality, reframed to 16:9)
    python3 generate_image.py "a red origami crane on a wooden table" \
        --aspect-ratio 16:9 --quality high -o crane.png

    # Long prompt from a file
    python3 generate_image.py --prompt-file board.txt \
        --aspect-ratio 16:9 -o storyboard.png

    # Edit / compose with reference images (identity preserved automatically)
    python3 generate_image.py "the same character riding a bicycle through Paris" \
        --ref char1.png --ref char2.png --quality high -o scene.png

    # Several variations in one call
    python3 generate_image.py "logo for a coffee brand called 'EMBER'" \
        --aspect-ratio 1:1 --count 4 -o ember.png
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    MODEL, ALL_RATIOS, NATIVE_RATIOS,
    get_replicate_token, generate_gpt_image, nearest_native_ratio,
    iter_output_items, save_output_item, reframe_image,
)


def resolve_output_path(output_arg, prompt, fmt, index=None):
    """Build the output file path, numbering variations when needed."""
    ext = f".{ 'jpg' if fmt == 'jpeg' else fmt }"
    if output_arg:
        p = Path(output_arg)
        if not p.suffix:
            p = p.with_suffix(ext)
        if index is not None:
            return p.parent / f"{p.stem}_{index}{p.suffix}"
        return p

    slug = (prompt or "image").lower()
    for ch in " ,.'\"!?;:()[]{}/\\\n\t":
        slug = slug.replace(ch, "_")
    slug = "_".join(part for part in slug.split("_") if part)[:48] or "image"
    if index is not None:
        return Path(f"{slug}_{index}{ext}")
    return Path(f"{slug}{ext}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate images with GPT Image 2 (openai/gpt-image-2) on Replicate.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt", nargs="?", help="Prompt text (or use --prompt-file)")
    parser.add_argument("--prompt-file", help="Read the prompt from a file (best for long prompts)")
    parser.add_argument("--ref", action="append", default=[], metavar="PATH",
                        help="Reference image (repeatable). Sent as input_images; identity is preserved.")
    parser.add_argument("--aspect-ratio", "-ar", default="3:2", choices=list(ALL_RATIOS.keys()),
                        help="Output ratio. Native: 1:1, 3:2, 2:3. Extended (canvas-reframed at native "
                             "resolution): 16:9, 9:16, 4:3, 3:4. Default: 3:2")
    parser.add_argument("--quality", "-q", default="high", choices=["low", "medium", "high", "auto"],
                        help="Fidelity / detail (default: high = the model's maximum). The model has no "
                             "size input; pixel dimensions are fixed by --aspect-ratio (~1536px long edge).")
    parser.add_argument("--format", "-f", dest="fmt", default="png", choices=["png", "webp", "jpeg"],
                        help="Output format (default: png)")
    parser.add_argument("--compression", type=int, default=90,
                        help="Output compression 0-100 (default: 90). Affects webp/jpeg; png stays lossless.")
    parser.add_argument("--background", default="auto", choices=["auto", "opaque", "transparent"],
                        help="Background handling (default: auto). Transparency support is limited.")
    parser.add_argument("--moderation", default="auto", choices=["auto", "low"],
                        help="Content moderation strictness (default: auto)")
    parser.add_argument("--pad-color", default="auto",
                        help="Fill color for canvas extension: 'auto' (sample border) or hex like #1a1a1a")
    parser.add_argument("--count", "-n", type=int, default=1,
                        help="Number of images to generate, 1-10 (default: 1)")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--openai-key", help="Optional: bring your own OpenAI API key (pay OpenAI directly)")
    args = parser.parse_args()

    # Resolve prompt.
    if args.prompt_file:
        pf = Path(args.prompt_file)
        if not pf.exists():
            parser.error(f"--prompt-file not found: {pf}")
        prompt = pf.read_text(encoding="utf-8").strip()
    elif args.prompt:
        prompt = args.prompt
    else:
        parser.error("Provide a prompt or --prompt-file")

    if not prompt:
        parser.error("Prompt is empty")

    count = max(1, min(10, args.count))
    compression = max(0, min(100, args.compression))
    native_ratio = nearest_native_ratio(args.aspect_ratio)
    needs_reframe = args.aspect_ratio not in NATIVE_RATIOS

    if needs_reframe:
        print(f"  Note: gpt-image-2 has no native {args.aspect_ratio}; generating at {native_ratio} "
              f"(native resolution) then extending the canvas to exact {args.aspect_ratio}. No upscaling.",
              file=sys.stderr)

    token = get_replicate_token()

    # Open reference images (model owns nothing; we close after the call).
    ref_handles = []
    for ref in args.ref:
        rp = Path(ref)
        if not rp.exists():
            print(f"Error: reference image not found: {rp}", file=sys.stderr)
            sys.exit(1)
        ref_handles.append(open(str(rp), "rb"))

    try:
        output = generate_gpt_image(
            prompt,
            input_images=ref_handles or None,
            aspect_ratio=native_ratio,
            quality=args.quality,
            count=count,
            output_format=args.fmt,
            background=args.background,
            moderation=args.moderation,
            output_compression=compression,
            openai_api_key=args.openai_key,
            token=token,
        )
    finally:
        for fh in ref_handles:
            fh.close()

    items = iter_output_items(output)
    if not items:
        print("Error: model returned no images.", file=sys.stderr)
        sys.exit(1)

    results = []
    multiple = len(items) > 1
    for i, item in enumerate(items, start=1):
        idx = i if multiple else None
        out_path = resolve_output_path(args.output, prompt, args.fmt, idx)
        saved = save_output_item(item, out_path)
        if not saved:
            continue

        dims = None
        if needs_reframe:
            saved, dims = reframe_image(
                saved,
                target_ratio_name=args.aspect_ratio,
                pad_color=args.pad_color,
            )
        results.append(saved)
        print(f"  Saved: {saved}" + (f" ({dims})" if dims else ""), file=sys.stderr)

    if not results:
        print("Error: failed to save any images.", file=sys.stderr)
        sys.exit(1)

    print(json.dumps({
        "files": results,
        "model": MODEL,
        "prompt": prompt,
        "aspect_ratio": args.aspect_ratio,
        "native_ratio": native_ratio,
        "quality": args.quality,
        "format": args.fmt,
        "compression": compression,
        "background": args.background,
        "references": [str(r) for r in args.ref],
    }, indent=2))


if __name__ == "__main__":
    main()
