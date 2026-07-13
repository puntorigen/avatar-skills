#!/usr/bin/env python3
"""Render a rule-of-six-edit cut sheet into an edit sheet + director notes.

Reads <slug>.cutsheet.json and writes, next to it:
  <slug>.cutsheet.md   human edit sheet (per-cut criteria table, sacrifices, coverage
                       score, and the optional Soundtrack-moves section)
  <slug>.cutnotes.txt  plain per-cut director notes (keep/sacrifice + Sound) for assembly/review

Pure stdlib.

    python3 render_cuts.py cuts_out/my-reel.cutsheet.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WEIGHTS = {
    "emotion": 0.51,
    "story": 0.23,
    "rhythm": 0.10,
    "eye_trace": 0.07,
    "plane_2d": 0.05,
    "space_3d": 0.04,
}
CRITERIA = list(WEIGHTS.keys())
LABEL = {
    "emotion": "Emotion",
    "story": "Story",
    "rhythm": "Rhythm",
    "eye_trace": "Eye-trace",
    "plane_2d": "2D plane",
    "space_3d": "3D space",
}


def is_todo(value) -> bool:
    if not isinstance(value, str):
        return not value
    v = value.strip().lower()
    return not v or v.startswith("todo")


def md_escape(text) -> str:
    return (str(text) if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def score(cut: dict, sac: set[str]) -> float:
    return sum(
        WEIGHTS[c] for c in CRITERIA if c not in sac and not is_todo(cut.get(c, ""))
    )


def render_markdown(data: dict) -> str:
    cuts = data.get("cuts", []) or []
    lines: list[str] = []
    lines.append(f"# {data.get('slug', 'cut-sheet')} — Rule of Six edit sheet")
    lines.append("")
    lines.append(
        f"- **Platform:** {data.get('platform', '—')}  ·  **Language:** {data.get('language', '—')}"
        f"  ·  **Cuts:** {len(cuts)}"
    )
    if data.get("reel_ref"):
        lines.append(f"- **Storyboard:** `{data.get('reel_ref')}`")
    lines.append(f"- **Emotional throughline:** {data.get('emotional_throughline', '—')}")
    if not is_todo(data.get("soundtrack", "")):
        lines.append(f"- **Soundtrack:** {md_escape(data.get('soundtrack'))}")
    lines.append("")
    lines.append(
        "> Hierarchy (top wins): **Emotion 51% > Story 23% > Rhythm 10% > "
        "Eye-trace 7% > 2D 5% > 3D 4%.** Sacrifice from the bottom up; never sacrifice emotion."
    )
    lines.append("")
    lines.append(
        "| Cut | At | Emotion (#1) | Story (#2) | Rhythm (#3) | Eye-trace (#4) | 2D (#5) | 3D (#6) | Sacrifices | Cov |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for cut in cuts:
        sac = {str(s).strip().lower() for s in (cut.get("sacrifices", []) or [])}

        def cell(c: str) -> str:
            if c in sac:
                return "_(sacrificed)_"
            val = cut.get(c, "")
            return md_escape(val) if not is_todo(val) else "—"

        cov = score(cut, sac)
        lines.append(
            "| "
            + " | ".join(
                [
                    f"**{md_escape(cut.get('id', '?'))}**",
                    md_escape(cut.get("at", "")),
                    cell("emotion"),
                    cell("story"),
                    cell("rhythm"),
                    cell("eye_trace"),
                    cell("plane_2d"),
                    cell("space_3d"),
                    md_escape(", ".join(LABEL.get(s, s) for s in sorted(sac))) or "—",
                    f"{cov:.0%}",
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append(
        "> Doctrine: an ideal cut satisfies all six; when they conflict, give up 3D, then 2D, "
        "then eye-trace, then rhythm — and take the cut that lands the **emotion**."
    )
    lines.append("")

    # Soundtrack moves (optional axis — the soundtrack-vs-picture relationship per cut).
    sound_rows = [
        (cut.get("id", "?"), cut.get("at", ""), cut.get("sound"))
        for cut in cuts
        if not is_todo(cut.get("sound", ""))
    ]
    if sound_rows:
        lines.append("## Soundtrack moves (sound axis — serves #1/#3)")
        lines.append("")
        for cid, at, snd in sound_rows:
            at_s = f" ({md_escape(at)})" if at else ""
            lines.append(f"- **{md_escape(cid)}**{at_s}: {md_escape(snd)}")
        lines.append("")
        lines.append(
            "> Split the edit (let the voice/music run across the cut); reserve the hard-cut "
            "punch (beat on the frame) for the moment that earns it — never weld every "
            "transition to one frame."
        )
        lines.append("")

    return "\n".join(lines)


def render_notes(data: dict) -> str:
    out: list[str] = []
    out.append(f"# {data.get('slug', 'cut-sheet')} — director notes")
    tl = data.get("emotional_throughline", "")
    if not is_todo(tl):
        out.append(f"# throughline: {tl}")
    st = data.get("soundtrack", "")
    if not is_todo(st):
        out.append(f"# soundtrack: {str(st).strip()}")
    out.append("")
    for cut in data.get("cuts", []) or []:
        sac = {str(s).strip().lower() for s in (cut.get("sacrifices", []) or [])}
        cid = cut.get("id", "?")
        at = cut.get("at", "")
        out.append(f"CUT {cid} ({at}): {cut.get('from', '')} -> {cut.get('to', '')}")
        for c in CRITERIA:
            if c in sac:
                out.append(f"  {LABEL[c]}: [SACRIFICED]")
            elif not is_todo(cut.get(c, "")):
                out.append(f"  {LABEL[c]}: {str(cut.get(c)).strip()}")
        if not is_todo(cut.get("sound", "")):
            out.append(f"  Sound: {str(cut.get('sound')).strip()}")
        note = (cut.get("note") or "").strip()
        if note:
            out.append(f"  note: {note}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a rule-of-six-edit cut sheet.")
    ap.add_argument("cutsheet_json", type=Path, help="Path to <slug>.cutsheet.json")
    args = ap.parse_args()

    try:
        data = json.loads(args.cutsheet_json.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not read JSON: {exc}", file=sys.stderr)
        return 1

    stem = args.cutsheet_json.name.removesuffix(".cutsheet.json").removesuffix(".json")
    out_dir = args.cutsheet_json.parent
    md_path = out_dir / f"{stem}.cutsheet.md"
    txt_path = out_dir / f"{stem}.cutnotes.txt"

    md_path.write_text(render_markdown(data), encoding="utf-8")
    txt_path.write_text(render_notes(data), encoding="utf-8")

    print(f"  -> {md_path}")
    print(f"  -> {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
