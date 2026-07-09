#!/usr/bin/env python3
"""Store credentials for the reel-discovery skill in a git-ignored config.json.

The skill reads credentials with this precedence: environment variable first,
then this config.json. Env vars: YT_API_KEY (YouTube Data API v3, free) and
APIFY_TOKEN (optional, paid -- robust TikTok keyword + Instagram topic search).

Usage:
    python3 setup_key.py --yt-api-key AIza...          # set the YouTube key
    python3 setup_key.py --apify-token apify_api_...   # set the Apify token
    python3 setup_key.py --yt-api-key AIza... --apify-token apify_...
    python3 setup_key.py --show                        # print what's stored (masked)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def save(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _mask(v: str) -> str:
    return f"{v[:6]}...{v[-4:]} (len {len(v)})" if v and len(v) > 12 else ("<set>" if v else "<empty>")


def main() -> int:
    ap = argparse.ArgumentParser(description="Configure reel-discovery credentials")
    ap.add_argument("--yt-api-key", help="YouTube Data API v3 key")
    ap.add_argument("--apify-token", help="Apify API token (optional, paid)")
    ap.add_argument("--show", action="store_true", help="Show stored values (masked)")
    args = ap.parse_args()

    config = load()

    if args.show or (not args.yt_api_key and not args.apify_token):
        print(f"Config: {CONFIG_FILE}")
        print(f"  YT_API_KEY  : {_mask(config.get('YT_API_KEY', ''))}")
        print(f"  APIFY_TOKEN : {_mask(config.get('APIFY_TOKEN', ''))}")
        if not args.show:
            print("\nPass --yt-api-key and/or --apify-token to set values.")
            return 1
        return 0

    if args.yt_api_key:
        key = args.yt_api_key.strip()
        if not key.startswith("AIza"):
            print("Warning: YouTube API keys usually start with 'AIza'. Proceeding anyway.",
                  file=sys.stderr)
        config["YT_API_KEY"] = key
    if args.apify_token:
        config["APIFY_TOKEN"] = args.apify_token.strip()

    save(config)
    print(f"Saved to {CONFIG_FILE}")
    print(f"  YT_API_KEY  : {_mask(config.get('YT_API_KEY', ''))}")
    print(f"  APIFY_TOKEN : {_mask(config.get('APIFY_TOKEN', ''))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
