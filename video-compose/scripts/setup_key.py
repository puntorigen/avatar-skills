#!/usr/bin/env python3
"""Store the Replicate API token for the video-compose skill.

Usage:
    python3 setup_key.py YOUR_REPLICATE_API_TOKEN
    python3 setup_key.py --show
    python3 setup_key.py              # auto-import from another skill's config
"""

import json
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "config.json"
FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
    Path.home() / ".cursor/skills/bg-music/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
]

DEFAULTS = {
    "default_format": "reel",
    "default_target_duration": 30,
    "default_music_volume": 0.7,
    "default_min_shot_duration": 1.2,
    "beat_snap_tolerance": 0.25,
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


def find_existing_gemini_key():
    candidates = [
        Path.home() / ".cursor/skills/asset-generator/config.json",
        Path.home() / ".cursor/skills/avatar-video-reel/config.json",
        Path.home() / ".cursor/skills/character-animations/config.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                key = cfg.get("gemini_api_key", "")
                if key:
                    return key, path
            except (json.JSONDecodeError, KeyError):
                continue
    return None, None


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--show":
        config = load_config()
        token = config.get("replicate_api_token", "")
        gemini = config.get("gemini_api_key", "")
        if token:
            masked = token[:5] + "..." + token[-4:]
            print(f"Replicate token: {masked}")
        else:
            print("No Replicate token configured in this skill.")
            existing, source = find_existing_token()
            if existing:
                masked = existing[:5] + "..." + existing[-4:]
                print(f"Found Replicate token in {source}: {masked}")
        if gemini:
            masked = gemini[:6] + "..." + gemini[-4:]
            print(f"Gemini key: {masked}")
        else:
            print("No Gemini key configured in this skill.")
            existing, source = find_existing_gemini_key()
            if existing:
                masked = existing[:6] + "..." + existing[-4:]
                print(f"Found Gemini key in {source}: {masked}")
        print(f"Config: {json.dumps(config, indent=2)}")
        return

    if len(sys.argv) < 2:
        config = load_config()
        any_imported = False

        existing, source = find_existing_token()
        if existing and not config.get("replicate_api_token"):
            config["replicate_api_token"] = existing
            print(f"Replicate API token imported from {source}")
            any_imported = True

        gemini, gsource = find_existing_gemini_key()
        if gemini and not config.get("gemini_api_key"):
            config["gemini_api_key"] = gemini
            print(f"Gemini API key imported from {gsource}")
            any_imported = True

        for k, v in DEFAULTS.items():
            config.setdefault(k, v)

        if any_imported or not CONFIG_FILE.exists():
            save_config(config)
            print(f"Config saved to {CONFIG_FILE}")
            return

        if not (config.get("replicate_api_token") or config.get("gemini_api_key")):
            print("Usage: python3 setup_key.py YOUR_REPLICATE_API_TOKEN")
            print("\nGet your token at: https://replicate.com/account/api-tokens")
            print("\nOr run without arguments to auto-import from another skill.")
            sys.exit(1)

        print("Config already populated.")
        return

    token = sys.argv[1].strip()
    if not token.startswith("r8_"):
        print("Warning: Replicate tokens usually start with 'r8_'. Proceeding anyway.",
              file=sys.stderr)

    config = load_config()
    config["replicate_api_token"] = token

    gemini, gsource = find_existing_gemini_key()
    if gemini and not config.get("gemini_api_key"):
        config["gemini_api_key"] = gemini
        print(f"Gemini API key imported from {gsource}")

    for k, v in DEFAULTS.items():
        config.setdefault(k, v)
    save_config(config)
    print(f"Replicate API token saved to {CONFIG_FILE}")
    print("You can now use the video-compose skill.")


if __name__ == "__main__":
    main()
