#!/usr/bin/env python3
"""Store the Replicate API token for the bg-music skill.

Usage:
    python3 setup_key.py YOUR_REPLICATE_API_TOKEN
    python3 setup_key.py --show
    python3 setup_key.py              # auto-import from other skills
"""

import json
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "config.json"
FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
]

DEFAULTS = {
    "default_mood": "generic",
    "default_duration": 30,
    "default_output_format": "mp3_standard",
}


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def find_existing_token():
    for path in FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                token = cfg.get("replicate_api_token", "")
                if token:
                    return token, path
            except (json.JSONDecodeError, KeyError):
                continue
    return None, None


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--show":
        config = load_config()
        token = config.get("replicate_api_token", "")
        if token:
            masked = token[:5] + "..." + token[-4:]
            print(f"Token: {masked}")
        else:
            print("No token configured in this skill.")
            existing, source = find_existing_token()
            if existing:
                masked = existing[:5] + "..." + existing[-4:]
                print(f"Found token in {source}: {masked}")
        print(f"Config: {json.dumps(config, indent=2)}")
        return

    if len(sys.argv) < 2:
        existing, source = find_existing_token()
        if existing:
            config = load_config()
            config["replicate_api_token"] = existing
            for k, v in DEFAULTS.items():
                config.setdefault(k, v)
            save_config(config)
            print(f"Replicate API token imported from {source}")
            print(f"Config saved to {CONFIG_FILE}")
            return

        print("Usage: python3 setup_key.py YOUR_REPLICATE_API_TOKEN")
        print("\nGet your token at: https://replicate.com/account/api-tokens")
        print("\nOr run without arguments to auto-import from another skill.")
        sys.exit(1)

    token = sys.argv[1].strip()
    if not token.startswith("r8_"):
        print("Warning: Replicate tokens usually start with 'r8_'. Proceeding anyway.",
              file=sys.stderr)

    config = load_config()
    config["replicate_api_token"] = token
    for k, v in DEFAULTS.items():
        config.setdefault(k, v)
    save_config(config)
    print(f"Replicate API token saved to {CONFIG_FILE}")
    print("You can now use the bg-music skill.")


if __name__ == "__main__":
    main()
