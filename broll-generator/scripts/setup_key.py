#!/usr/bin/env python3
"""Store the Replicate API token for the broll-generator skill.

Usage:
    python3 setup_key.py YOUR_REPLICATE_API_TOKEN
    python3 setup_key.py --show

The token is shared with the other Replicate-based skills. If a sibling skill
(avatar-talking-video, voice-clone, gpt-image-2, ...) already has a valid token
configured, this skill discovers it automatically and you do not need to run
this. Run it only to set or refresh the token.
"""

import json
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


def load():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--show":
        config = load()
        tok = config.get("replicate_api_token", "")
        if tok:
            print(f"replicate_api_token: {tok[:6]}...{tok[-3:]} (len {len(tok)})")
        else:
            print("No token stored in this skill's config (it may be inherited from a sibling skill).")
        return

    token = sys.argv[1].strip()
    if not token.startswith("r8_"):
        print("Warning: Replicate tokens usually start with 'r8_'. Proceeding anyway.", file=sys.stderr)

    config = load()
    config["replicate_api_token"] = token
    save(config)
    print(f"Replicate API token saved to {CONFIG_FILE}")


if __name__ == "__main__":
    main()
