#!/usr/bin/env python3
"""Re-render .analysis.md from an updated .analysis.json file."""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from analyze_video import render_markdown, to_json_safe, write_analysis_outputs  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Re-render analysis markdown from JSON")
    parser.add_argument("json_path", help="Path to .analysis.json")
    args = parser.parse_args()

    json_path = Path(args.json_path).resolve()
    if not json_path.exists():
        print(f"Error: not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    stem = json_path.name.replace(".analysis.json", "")
    _, md_path = write_analysis_outputs(data, json_path.parent, stem)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
