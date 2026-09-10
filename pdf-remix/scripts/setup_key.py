#!/usr/bin/env python3
"""Optional credential setup for the pdf-remix skill.

You usually DON'T need this: the skill auto-discovers its credentials from the
bundled sibling skills (Gemini key from asset-generator, Apify token from
reel-discovery) and from environment variables. Use this only if you want to
store the keys in this skill's own git-ignored config.json.

Resolution order (per credential):
    environment variable  ->  this skill's config.json  ->  sibling skill config

Fonts are a separate one-time step: `python3 setup_fonts.py`.

Usage:
    python3 setup_key.py --gemini-api-key AIza...        # store Gemini key here
    python3 setup_key.py --apify-token apify_api_...      # store Apify token here
    python3 setup_key.py --show                           # print what's resolved
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

CONFIG_FILE = C.CONFIG_FILE


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def save(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _mask(v: str | None) -> str:
    if not v:
        return "<not found>"
    return f"{v[:6]}...{v[-4:]} (len {len(v)})" if len(v) > 12 else "<set>"


def main() -> int:
    ap = argparse.ArgumentParser(description="Configure pdf-remix credentials (optional)")
    ap.add_argument("--gemini-api-key", help="Gemini API key (else reused from asset-generator)")
    ap.add_argument("--apify-token", help="Apify API token (else reused from reel-discovery)")
    ap.add_argument("--show", action="store_true", help="Show the resolved credentials (masked)")
    args = ap.parse_args()

    config = load()

    if args.show or (not args.gemini_api_key and not args.apify_token):
        print(f"Config file : {CONFIG_FILE}")
        print(f"Skills root : {C.SKILLS_ROOT}")
        print("Resolved credentials (env -> own config -> sibling skill):")
        print(f"  Gemini API key : {_mask(C.gemini_key())}")
        print(f"  Apify token    : {_mask(C.apify_token())}")
        if not args.show:
            print("\nPass --gemini-api-key and/or --apify-token to store them here,")
            print("or configure asset-generator / reel-discovery and they'll be reused.")
            print("Fonts: run  python3 setup_fonts.py")
            return 1
        return 0

    if args.gemini_api_key:
        config["gemini_api_key"] = args.gemini_api_key.strip()
    if args.apify_token:
        config["APIFY_TOKEN"] = args.apify_token.strip()

    save(config)
    print(f"Saved to {CONFIG_FILE}")
    print(f"  Gemini API key : {_mask(config.get('gemini_api_key'))}")
    print(f"  Apify token    : {_mask(config.get('APIFY_TOKEN'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
