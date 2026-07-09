#!/usr/bin/env python3
"""Set up or update the Gemini API key for the asset-generator skill.

Usage:
    python3 setup_key.py <GEMINI_API_KEY>
    python3 setup_key.py --show
"""

import argparse
import json
import sys
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "default_style": "illustration",
    "default_format": "png",
}


def load_config():
    if CONFIG_FILE.exists():
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        config.pop("default_model", None)
        return config
    return dict(DEFAULT_CONFIG)


def save_config(config):
    config.pop("default_model", None)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Set up Gemini API key")
    parser.add_argument("api_key", nargs="?", help="Your Gemini API key")
    parser.add_argument("--show", action="store_true", help="Show current config (key masked)")
    parser.add_argument("--set-default-style", help="Set default style preset")
    args = parser.parse_args()

    config = load_config()

    if args.show:
        display = dict(config)
        display["model"] = "gemini-3-pro-image-preview (fixed)"
        key = display.get("gemini_api_key", "")
        if key:
            display["gemini_api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        else:
            display["gemini_api_key"] = "(not set)"
        print(json.dumps(display, indent=2))
        return

    if args.api_key:
        config["gemini_api_key"] = args.api_key
        save_config(config)
        masked = args.api_key[:8] + "..." + args.api_key[-4:]
        print(f"API key saved: {masked}")
        print(f"Config file: {CONFIG_FILE}")
        print(f"Model: gemini-3-pro-image-preview")
        return

    if args.set_default_style:
        config["default_style"] = args.set_default_style
        save_config(config)
        print(f"Default style set to: {args.set_default_style}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
