#!/usr/bin/env python3
"""Configure / inspect the API keys avatar-location needs.

A location only re-uses the image skills, so keys are normally inherited from
sibling skills (no setup needed):
  - Replicate -> gpt-image-2 / avatar-invent  (identity-anchored hero + angles)
  - Gemini    -> asset-generator              (only for --generator gemini)

Usage:
    python3 setup_key.py --show
    python3 setup_key.py --replicate r8_...
    python3 setup_key.py --gemini AIza...
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _common as C  # noqa: E402


def mask(value):
    if not value:
        return "(not set)"
    if len(value) <= 12:
        return "***"
    return value[:6] + "..." + value[-4:]


def main():
    ap = argparse.ArgumentParser(description="Configure avatar-location API keys")
    ap.add_argument("--show", action="store_true", help="Show resolved keys (masked)")
    ap.add_argument("--replicate", help="Set the Replicate API token")
    ap.add_argument("--gemini", help="Set the Gemini API key")
    args = ap.parse_args()

    cfg = C.load_config()
    changed = False
    if args.replicate:
        cfg["replicate_api_token"] = args.replicate.strip(); changed = True
    if args.gemini:
        cfg["gemini_api_key"] = args.gemini.strip(); changed = True
    if changed:
        C.save_config(cfg)
        print(f"Saved to {C.CONFIG_FILE}")

    if args.show or not changed:
        rep = C.get_replicate_token(required=False)
        gem = C.get_gemini_api_key(required=False)
        print("avatar-location resolved keys (env -> own config -> sibling skills):")
        print(f"  replicate_api_token : {mask(rep)}  (hero + angles via gpt-image-2)")
        print(f"  gemini_api_key      : {mask(gem)}  (optional, --generator gemini)")
        print(f"  config file         : {C.CONFIG_FILE}")
        if not rep:
            print("\n  ! No Replicate token. Configure gpt-image-2/avatar-invent or run --replicate TOKEN.",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
