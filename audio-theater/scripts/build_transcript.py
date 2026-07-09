#!/usr/bin/env python3
"""Build transcript.md from lines.json / words.json + cues.json.

- theater / lipsync: timecoded lines with [SFX: id] placeholders inserted at their
  start, plus a "Sound effects & music" section listing every cue.
- podcast: clean show-notes (speaker turns) plus the cue list.

Usage:
    python3 build_transcript.py --out audio-theater/ep
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import load_json, resolve_out_dir, format_timecode  # noqa: E402


def load_optional(path):
    p = Path(path)
    return load_json(p) if p.exists() else None


def cue_marker(cue):
    where = format_timecode(cue.get("start", 0.0))
    typ = cue.get("type", "sfx")
    return f"`[{typ.upper()}: {cue.get('id')}]` ({where}) — {cue.get('description', '')}"


def build_lines_section(lines_data, cues):
    """Interleave line turns with one-shot cue markers by timecode."""
    out = []
    lines = lines_data.get("lines", [])
    has_timing = any(ln.get("start") is not None for ln in lines)

    # Build a sorted list of cue markers to drop inline (by start time).
    cue_points = sorted(
        [(float(c.get("start", 0.0) or 0.0), c) for c in cues],
        key=lambda x: x[0],
    )
    ci = 0

    for ln in lines:
        ln_start = ln.get("start")
        # Drop any cues that occur before this line starts.
        if has_timing and ln_start is not None:
            while ci < len(cue_points) and cue_points[ci][0] <= ln_start:
                out.append(f"- {cue_marker(cue_points[ci][1])}")
                out.append("")
                ci += 1
        tc = f"`[{format_timecode(ln_start)}]` " if ln_start is not None else ""
        tag = f"_[{', '.join(ln['tags'])}]_ " if ln.get("tags") else ""
        out.append(f"**{ln['speaker']}:** {tc}{tag}{ln['text']}")
        out.append("")

    # Any remaining cues after the last line.
    while ci < len(cue_points):
        out.append(f"- {cue_marker(cue_points[ci][1])}")
        out.append("")
        ci += 1
    return out


def build_podcast_section(lines_data):
    out = []
    for ln in lines_data.get("lines", []):
        tc = f"`[{format_timecode(ln['start'])}]` " if ln.get("start") is not None else ""
        out.append(f"**{ln['speaker']}:** {tc}{ln['text']}")
        out.append("")
    return out


def main():
    parser = argparse.ArgumentParser(description="Build transcript.md")
    parser.add_argument("--out", "-o", required=True, help="Project folder")
    parser.add_argument("--output-name", default="transcript.md", help="Output filename")
    args = parser.parse_args()

    out_dir = resolve_out_dir(args.out)
    lines_data = load_optional(out_dir / "lines.json")
    if not lines_data:
        print(f"Error: {out_dir / 'lines.json'} not found. Run generate_voices.py first.",
              file=sys.stderr)
        sys.exit(1)
    cues_data = load_optional(out_dir / "cues.json") or {"cues": []}
    cues = cues_data.get("cues", [])
    words_data = load_optional(out_dir / "words.json")

    title = lines_data.get("title") or "Audio Theater"
    mode = lines_data.get("mode") or "theater"
    language = lines_data.get("language") or "?"
    duration = lines_data.get("duration")

    md = [f"# {title}", ""]
    meta = f"_Mode: {mode} · Language: {language}"
    if duration is not None:
        meta += f" · Duration: {format_timecode(duration)}"
    if words_data:
        meta += f" · Transcription: {words_data.get('backend')}"
    meta += "_"
    md.append(meta)
    md.append("")

    md.append("## Transcript")
    md.append("")
    if mode == "podcast":
        md += build_podcast_section(lines_data)
    else:
        md += build_lines_section(lines_data, cues)

    if cues:
        md.append("## Sound effects & music")
        md.append("")
        md.append("| Cue | Type | Start | End | Source | Description |")
        md.append("|-----|------|-------|-----|--------|-------------|")
        for c in cues:
            start = format_timecode(c.get("start", 0.0))
            end = format_timecode(c["end"]) if c.get("end") is not None else "-"
            src = c.get("mood") or c.get("category") or "-"
            file = c.get("file") or "(not generated)"
            md.append(f"| `{c.get('id')}` | {c.get('type')} | {start} | {end} | "
                      f"{src} | {c.get('description', '')} — `{file}` |")
        md.append("")

    transcript_path = out_dir / args.output_name
    transcript_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"  transcript: {transcript_path}", file=sys.stderr)
    print(json.dumps({
        "transcript": str(transcript_path),
        "mode": mode,
        "line_count": len(lines_data.get("lines", [])),
        "cue_count": len(cues),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
