#!/usr/bin/env python3
"""Render a viral-video-script beat sheet into a shooting script + narration track.

Reads <slug>.script.json and writes, next to it:
  <slug>.script.md      human shooting script (beats, timing, VO, on-screen, captions)
  <slug>.narration.txt  the clean spoken VO only (feed to voice-clone / narrate.py)

Pure stdlib.

    python3 render_script.py scripts_out/buldak-spicy.script.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(data: dict) -> str:
    s = data.get("subject", {}) or {}
    beats = data.get("beats", []) or []
    total = sum(int(b.get("seconds", 0) or 0) for b in beats)

    lines: list[str] = []
    lines.append(f"# {data.get('slug', 'script')} — viral video script")
    lines.append("")
    lines.append(
        f"- **Product:** {s.get('product', '—')}  ·  **Audience:** {s.get('audience', '—')}"
    )
    lines.append(
        f"- **Platform:** {data.get('platform', '—')}  ·  **Language:** {data.get('language', '—')}"
        f"  ·  **Target:** {data.get('target_seconds', '—')}s (beats sum to {total}s)"
    )
    lines.append(f"- **Format stolen (#1):** {s.get('format_steal', '—')}")
    lines.append(f"- **Credential (#4):** {s.get('credential', '—')}")
    lines.append(f"- **Identity value (#3):** {s.get('identity_value', '—')}")
    lines.append(
        f"- **Shareable premise (#5):** {s.get('shareable_premise', '—')}"
        f"  ·  **trigger:** {s.get('share_trigger', '—')}"
    )
    lines.append(
        f"- **Captions:** {'on' if data.get('captions') else 'OFF'}"
        f"  ·  **Cut every:** {data.get('cut_every_seconds', '—')}s (#6)"
    )
    lines.append("")
    lines.append("| t | Beat | Spoken (VO) | On-screen | Caption |")
    lines.append("|---|------|-------------|-----------|---------|")
    clock = 0
    for b in beats:
        dur = int(b.get("seconds", 0) or 0)
        span = f"{clock}–{clock + dur}s"
        clock += dur
        lines.append(
            f"| {span} | **{b.get('beat', '?')}** | {md_escape(b.get('spoken', ''))} "
            f"| {md_escape(b.get('on_screen', ''))} | {md_escape(b.get('caption', ''))} |"
        )
    lines.append("")
    lines.append("> Editing (#6): cut any frame not delivering new info; keep clips a few seconds; "
                 "burn in captions; zero dead space.")
    lines.append("")
    return "\n".join(lines)


def render_narration(data: dict) -> str:
    out = []
    for b in data.get("beats", []) or []:
        spoken = (b.get("spoken") or "").strip()
        if spoken and not spoken.lower().startswith("todo"):
            out.append(spoken)
    return "\n\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a viral-video-script beat sheet.")
    ap.add_argument("script_json", type=Path, help="Path to <slug>.script.json")
    args = ap.parse_args()

    try:
        data = json.loads(args.script_json.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not read JSON: {exc}", file=sys.stderr)
        return 1

    stem = args.script_json.name.removesuffix(".script.json").removesuffix(".json")
    out_dir = args.script_json.parent
    md_path = out_dir / f"{stem}.script.md"
    txt_path = out_dir / f"{stem}.narration.txt"

    md_path.write_text(render_markdown(data), encoding="utf-8")
    txt_path.write_text(render_narration(data), encoding="utf-8")

    print(f"  -> {md_path}")
    print(f"  -> {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
