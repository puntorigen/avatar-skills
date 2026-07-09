#!/usr/bin/env python3
"""Store the Replicate API token for the avatar-reel-composer skill.

Usage:
    python3 setup_key.py YOUR_REPLICATE_API_TOKEN
    python3 setup_key.py --show

This skill orchestrates the sibling Replicate-based skills (voice-clone,
avatar-talking-video, broll-generator), which discover the shared token on their
own. You normally do NOT need to run this — it is only here to set or refresh the
token if no sibling skill has one configured.
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
