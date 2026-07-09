#!/usr/bin/env python3
"""Scaffold a viral-video-script beat sheet (JSON) pre-structured with the formula.

Creates <out>/<slug>.script.json with every field the formula needs and the
Hook -> Problem -> Story -> Payoff beats, each carrying a "TODO:" placeholder for
the agent to replace. Pure stdlib, no install needed.

    python3 scaffold.py buldak-spicy --product "Buldak instant ramen" \
        --language en --platform tiktok --seconds 32 --out scripts_out/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Rough beat budget as a fraction of total seconds (Hook/Problem/Story/Payoff).
BEAT_SPLIT = {"hook": 0.07, "problem": 0.18, "story": 0.60, "payoff": 0.15}

BEAT_NOTE = {
    "hook": "Curiosity gap + credential. NO product name. Use the stolen format's opener.",
    "problem": "The tension the viewer already feels, framed at the IDENTITY layer.",
    "story": "The recognizable format plays out; product enters naturally, never as a pitch.",
    "payoff": "Resolve the gap + identity reward, then the lightest possible product/CTA.",
}


def build_template(slug: str, product: str, language: str, platform: str, seconds: int) -> dict:
    beats = []
    for name in ("hook", "problem", "story", "payoff"):
        beats.append(
            {
                "beat": name,
                "seconds": max(1, round(seconds * BEAT_SPLIT[name])),
                "spoken": f"TODO: spoken copy for the {name}",
                "on_screen": f"TODO: on-screen action for the {name}",
                "caption": f"TODO: burned-in caption text for the {name}",
                "note": BEAT_NOTE[name],
            }
        )
    return {
        "slug": slug,
        "language": language,
        "platform": platform,
        "target_seconds": seconds,
        "subject": {
            "product": product,
            "audience": "TODO: who is watching (drives identity layer + tone)",
            "format_steal": "TODO: a proven format to steal (reaction / challenge / office tour / 'hey chef ...')",
            "credential": "TODO: the authority shown in the first 2s (e.g. 'Korean street-food chef')",
            "identity_value": "TODO: layer-3 value — what watching/owning this MEANS about the viewer",
            "share_trigger": "surprise",
            "shareable_premise": "TODO: the whole video in ONE sentence a friend could repeat",
        },
        "captions": True,
        "cut_every_seconds": 3,
        "beats": beats,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a viral-video-script beat sheet JSON.")
    ap.add_argument("slug", help="Short kebab-case id, e.g. buldak-spicy")
    ap.add_argument("--product", required=True, help="Product / brand / topic")
    ap.add_argument("--language", default="en", help="Spoken language code (default: en)")
    ap.add_argument(
        "--platform",
        default="tiktok",
        choices=["tiktok", "reels", "shorts"],
        help="Target platform (default: tiktok)",
    )
    ap.add_argument("--seconds", type=int, default=32, help="Target length in seconds (default: 32)")
    ap.add_argument("--out", type=Path, default=Path("."), help="Output directory (default: .)")
    ap.add_argument("--force", action="store_true", help="Overwrite if the file already exists")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    dest = args.out / f"{args.slug}.script.json"
    if dest.exists() and not args.force:
        print(f"ERROR: {dest} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    data = build_template(args.slug, args.product, args.language, args.platform, args.seconds)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  -> {dest}")
    print("  Fill every TODO, then validate with check_script.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
