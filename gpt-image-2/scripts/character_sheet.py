#!/usr/bin/env python3
"""Generate a clean 4-view character reference sheet with GPT Image 2.

Takes 1-3 reference images of a character and produces a single sheet with
EXACTLY four views: full-body front (three-quarter), full-body rear,
front head-and-shoulders close-up, and a 90-degree profile close-up — with
locked facial identity and costume. No expression sheet and no eye-direction
studies, so the canvas isn't flooded with extra faces.

The 4-view frame, lighting, and no-text/no-extra-figures rules are fixed. You
adapt the character to the references by passing --subject / --description /
--style. With no overrides it falls back to the storybook style and relies on
the reference images to lock identity.

Defaults: 16:9 aspect, high quality (the model's native maximum resolution).

Usage:
    python3 character_sheet.py --ref boy1.png --ref boy2.png \
        --subject "young magician boy, around 10 years old" \
        --description "Slim build, large observant eyes, messy dark-brown hair. Midnight-blue robe with gold stars and a matching pointed wizard hat." \
        -o magician_sheet.png

    # Fully custom adaptable block from a file, sci-fi style
    python3 character_sheet.py --ref robot.png \
        --subject "small exploration robot named Bolt" \
        --description-file robot_desc.txt \
        --style "Pixar-quality 3D render, soft global illumination, glossy materials" \
        --bg "soft neutral grey studio" -o bolt_sheet.png
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
GENERATE = SCRIPT_DIR / "generate_image.py"

DEFAULT_SUBJECT = "character"

DEFAULT_DESCRIPTION = (
    "Preserve the recognizable silhouette, build, posture, hair, and overall design "
    "established in the attached reference illustrations. Keep proportions and costume "
    "exactly as shown in the references."
)

DEFAULT_STYLE = (
    "Premium illustrated storybook character design. Inspired by classic European "
    "children's books, hand-painted fantasy illustration, timeless fairy-tale art, "
    "warm magical realism, and highly expressive character-animation design."
)

# Fixed 4-view structure, verbatim from the character-reference-sheet framework.
# Exactly four views — no expression sheet, no eye-direction studies (those caused
# the model to fill the canvas with many extra faces).
TEMPLATE = """CHARACTER REFERENCE SHEET FOR STYLE
Show the same {subject} from the attached reference image(s). {description}
Character reference sheet — four views on a {bg} background:
[VIEW 1 — FULL BODY, FRONT] Full-body front-facing three-quarter view of this character, full body visible head to feet.
[VIEW 2 — FULL BODY, REAR] Full-body rear view of the same character, directly from behind. Full body visible head to feet.
[VIEW 3 — FRONT CLOSE-UP] Head and shoulders close-up, straight-on front view. Sharp detail on skin texture, accessories, and costume surface detail. Chest and shoulder armour/clothing visible at the bottom of frame.
[VIEW 4 — PROFILE CLOSE-UP] Head and shoulders close-up, 90-degree left profile view. Neck and upper shoulder visible.
Lighting & presentation: Clean studio lighting — soft key light upper left, gentle fill from the right. Consistent character identity, proportions, and costume details across all four views. No text, no watermarks, no extra figures, no background environment, in the below style... {style}"""


def build_prompt(subject, description, style, bg):
    return TEMPLATE.format(
        subject=subject or DEFAULT_SUBJECT,
        description=description or DEFAULT_DESCRIPTION,
        style=style or DEFAULT_STYLE,
        bg=bg or "neutral grey",
    ).strip()


def main():
    parser = argparse.ArgumentParser(
        description="Generate a clean 4-view character reference sheet with GPT Image 2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ref", action="append", default=[], metavar="PATH",
                        help="Reference image of the character (repeatable, 1-3 recommended)")
    parser.add_argument("--subject", default=DEFAULT_SUBJECT,
                        help="Short noun phrase, e.g. 'young magician boy, around 10 years old'")
    parser.add_argument("--description", "-d", default=None,
                        help="Adaptable identity / build / hair / costume / personality block")
    parser.add_argument("--description-file", default=None,
                        help="Read the description block from a file")
    parser.add_argument("--style", default=None,
                        help="Visual style block (default: illustrated storybook)")
    parser.add_argument("--style-file", default=None, help="Read the style block from a file")
    parser.add_argument("--bg", default="neutral grey",
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
    parser.add_argument("--output", "-o", default="character_sheet.png", help="Output path")
    parser.add_argument("--print-prompt", action="store_true",
                        help="Print the assembled prompt and exit (no generation)")
    args = parser.parse_args()

    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    else:
        description = args.description
        if args.description_file:
            description = Path(args.description_file).read_text(encoding="utf-8").strip()
        style = args.style
        if args.style_file:
            style = Path(args.style_file).read_text(encoding="utf-8").strip()
        prompt = build_prompt(args.subject, description, style, args.bg)

    if args.print_prompt:
        print(prompt)
        return

    if not args.ref:
        print("Warning: no --ref images provided. Identity will be invented rather than "
              "preserved from references.", file=sys.stderr)

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

    print("Generating character reference sheet...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    Path(tmp.name).unlink(missing_ok=True)

    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            print(f"  {line}", file=sys.stderr)

    if result.returncode != 0:
        print("Error: character sheet generation failed.", file=sys.stderr)
        sys.exit(result.returncode)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout)
        return

    data["kind"] = "character_sheet"
    data["subject"] = args.subject
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
