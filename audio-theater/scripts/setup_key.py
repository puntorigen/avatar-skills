#!/usr/bin/env python3
"""Configure / inspect API keys for the audio-theater skill.

Keys are normally reused from sibling skills:
- Gemini API key from asset-generator
- Replicate API token from sound-effects (with fallbacks)

Usage:
    python3 setup_key.py                       # auto-import from sibling skills (no overwrite)
    python3 setup_key.py --show                # show what's configured (masked)
    python3 setup_key.py --gemini KEY          # set Gemini API key
    python3 setup_key.py --replicate r8_TOKEN  # set Replicate API token
    python3 setup_key.py --elevenlabs KEY      # set ElevenLabs API key (realistic SFX backend)
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    load_config, save_config, get_gemini_api_key, get_replicate_token,
    get_elevenlabs_api_key,
)


def mask(value):
    if not value:
        return "(not set)"
    if len(value) <= 12:
        return "***"
    return value[:6] + "..." + value[-4:]


def main():
    parser = argparse.ArgumentParser(description="Configure audio-theater API keys")
    parser.add_argument("--show", action="store_true", help="Show current config (masked)")
    parser.add_argument("--gemini", help="Set the Gemini API key")
    parser.add_argument("--replicate", help="Set the Replicate API token")
    parser.add_argument("--elevenlabs", help="Set the ElevenLabs API key (realistic SFX)")
    args = parser.parse_args()

    config = load_config()

    if args.show:
        gem = config.get("gemini_api_key", "") or get_gemini_api_key(required=False)
        rep = config.get("replicate_api_token", "") or get_replicate_token(required=False)
        el = config.get("elevenlabs_api_key", "") or get_elevenlabs_api_key(required=False)
        print("audio-theater configuration:")
        print(f"  gemini_api_key      : {mask(gem)}")
        print(f"  replicate_api_token : {mask(rep)}")
        print(f"  elevenlabs_api_key  : {mask(el)}")
        print(f"  sfx_backend         : {config.get('default_sfx_backend', 'auto')}"
              f" (-> {'elevenlabs' if el else 'sound-effects'} when auto)")
        print(f"  tts_model           : {config.get('default_tts_model', 'gemini-3.1-flash-tts-preview')}")
        print(f"  text_model          : {config.get('default_text_model', 'gemini-3.5-flash')}")
        print(f"  config file         : {SCRIPT_DIR.parent / 'config.json'}")
        return

    changed = False
    if args.gemini:
        config["gemini_api_key"] = args.gemini.strip()
        changed = True
        print(f"Gemini API key saved: {mask(config['gemini_api_key'])}")
    if args.replicate:
        token = args.replicate.strip()
        if not token.startswith("r8_"):
            print("Warning: Replicate tokens usually start with 'r8_'. Proceeding anyway.",
                  file=sys.stderr)
        config["replicate_api_token"] = token
        changed = True
        print(f"Replicate API token saved: {mask(token)}")
    if args.elevenlabs:
        config["elevenlabs_api_key"] = args.elevenlabs.strip()
        changed = True
        print(f"ElevenLabs API key saved: {mask(config['elevenlabs_api_key'])}")

    if changed:
        save_config(config)
        print(f"Config saved to {SCRIPT_DIR.parent / 'config.json'}")
        return

    # No explicit values -> auto-import from siblings without overwriting.
    gem = get_gemini_api_key(required=False)
    rep = get_replicate_token(required=False)
    if gem and not config.get("gemini_api_key"):
        config["gemini_api_key"] = gem
        print(f"Gemini API key imported: {mask(gem)}")
    if rep and not config.get("replicate_api_token"):
        config["replicate_api_token"] = rep
        print(f"Replicate API token imported: {mask(rep)}")

    save_config(config)
    print("\nResolved keys (env/own/sibling):")
    print(f"  gemini_api_key      : {mask(gem)}")
    print(f"  replicate_api_token : {mask(rep)}")
    if not gem:
        print("\nNo Gemini key found. Set asset-generator's key or run with --gemini KEY.",
              file=sys.stderr)
    if not rep:
        print("No Replicate token found. Configure sound-effects or run with --replicate TOKEN.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
