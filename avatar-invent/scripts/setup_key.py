#!/usr/bin/env python3
"""Configure / inspect the API keys avatar-invent needs.

Keys are normally reused from sibling skills (no setup needed):
  - ElevenLabs  -> audio-theater/config.json   (voice design)
  - Replicate   -> gpt-image-2 / voice-clone / ...  (hero still + MiniMax clone)
  - Gemini      -> asset-generator/config.json  (only for --generator gemini)

Usage:
    python3 setup_key.py --show
    python3 setup_key.py --elevenlabs sk_...
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
    ap = argparse.ArgumentParser(description="Configure avatar-invent API keys")
    ap.add_argument("--show", action="store_true", help="Show resolved keys (masked)")
    ap.add_argument("--elevenlabs", help="Set the ElevenLabs API key")
    ap.add_argument("--replicate", help="Set the Replicate API token")
    ap.add_argument("--gemini", help="Set the Gemini API key")
    args = ap.parse_args()

    cfg = C.load_config()
    changed = False
    if args.elevenlabs:
        cfg["elevenlabs_api_key"] = args.elevenlabs.strip(); changed = True
    if args.replicate:
        cfg["replicate_api_token"] = args.replicate.strip(); changed = True
    if args.gemini:
        cfg["gemini_api_key"] = args.gemini.strip(); changed = True
    if changed:
        C.save_config(cfg)
        print(f"Saved to {C.CONFIG_FILE}")

    if args.show or not changed:
        el = C.get_elevenlabs_api_key(required=False)
        rep = C.get_replicate_token(required=False)
        gem = C.get_gemini_api_key(required=False)
        print("avatar-invent resolved keys (env -> own config -> sibling skills):")
        print(f"  elevenlabs_api_key  : {mask(el)}  (voice design)")
        print(f"  replicate_api_token : {mask(rep)}  (hero still + MiniMax clone)")
        print(f"  gemini_api_key      : {mask(gem)}  (optional, --generator gemini)")
        print(f"  config file         : {C.CONFIG_FILE}")
        if not el:
            print("\n  ! No ElevenLabs key. Set audio-theater's key or run --elevenlabs KEY.",
                  file=sys.stderr)
        if not rep:
            print("  ! No Replicate token. Configure gpt-image-2/voice-clone or run --replicate TOKEN.",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
