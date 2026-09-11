#!/usr/bin/env python3
"""Optional credential setup for the video-remix skill.

You usually DON'T need this: the skill auto-discovers its credentials from the
bundled sibling skills and environment variables:

    Gemini    (frame analysis)  <- env GEMINI_API_KEY / GOOGLE_API_KEY, else asset-generator
    Replicate (avatars/voice/   <- env REPLICATE_API_TOKEN, else voice-clone / bg-music-hq /
               music/compose)       avatar-reel-composer / gpt-image-2 / avatar-invent

Resolution order (per credential):
    environment variable  ->  this skill's config.json  ->  sibling skill config

Use this only to store the keys in this skill's own git-ignored config.json.

Usage:
    python3 setup_key.py --gemini-api-key AIza...
    python3 setup_key.py --replicate-token r8_...
    python3 setup_key.py --show
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
    ap = argparse.ArgumentParser(description="Configure video-remix credentials (optional)")
    ap.add_argument("--gemini-api-key", help="Gemini API key (else reused from asset-generator)")
    ap.add_argument("--replicate-token", help="Replicate API token (else reused from sibling skills)")
    ap.add_argument("--show", action="store_true", help="Show the resolved credentials (masked)")
    args = ap.parse_args()

    config = load()

    if args.show or (not args.gemini_api_key and not args.replicate_token):
        print(f"Config file : {CONFIG_FILE}")
        print(f"Skills root : {C.SKILLS_ROOT}")
        print("Resolved credentials (env -> own config -> sibling skill):")
        print(f"  Gemini API key   : {_mask(C.gemini_key())}")
        print(f"  Replicate token  : {_mask(C.replicate_token())}")
        if not args.show:
            print("\nPass --gemini-api-key and/or --replicate-token to store them here,")
            print("or configure asset-generator / voice-clone and they'll be reused.")
            return 1
        return 0

    if args.gemini_api_key:
        config["gemini_api_key"] = args.gemini_api_key.strip()
    if args.replicate_token:
        config["replicate_api_token"] = args.replicate_token.strip()

    save(config)
    print(f"Saved to {CONFIG_FILE}")
    print(f"  Gemini API key   : {_mask(config.get('gemini_api_key'))}")
    print(f"  Replicate token  : {_mask(config.get('replicate_api_token'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
