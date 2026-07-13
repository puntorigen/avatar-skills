#!/usr/bin/env python3
"""Scaffold a rule-of-six-edit cut sheet (JSON), pre-structured with the hierarchy.

Creates <out>/<slug>.cutsheet.json with one entry per cut, each carrying the six
Murch criteria (emotion, story, rhythm, eye_trace, plane_2d, space_3d) as "TODO:"
placeholders for the agent to fill top-down, plus an optional `sound` axis per cut
and a top-level `soundtrack` intent (the soundtrack-vs-picture move; not validated).
Pure stdlib, no install needed.

Two modes:
  # N blank cuts
  python3 scaffold.py my-reel --cuts 6 --language es --out cuts_out/
  # one cut per scene boundary of an avatar-reel-composer storyboard
  python3 scaffold.py my-reel --from-storyboard path/to/storyboard.json --out cuts_out/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The six criteria, top (most important) -> bottom (first to sacrifice).
CRITERIA = ["emotion", "story", "rhythm", "eye_trace", "plane_2d", "space_3d"]

CRITERION_TODO = {
    "emotion": "TODO: the feeling this cut serves/evokes right now (#1, 51%) — if unnamed, the cut isn't motivated",
    "story": "TODO: the NEW info this cut delivers (#2, 23%) — no new info => drop/shorten the shot",
    "rhythm": "TODO: why HERE — cut on a completed thought (the blink point), on the breath/beat; keep it snappy, not Dragnet-mechanical (#3, 10%)",
    "eye_trace": "TODO: where the eye is; carried to the same part of the 9:16 frame across the cut? (#4, 7%)",
    "plane_2d": "TODO: framing / eye-line / 180° line / screen direction; change angle >=30° vs the previous shot (no 2-yard jump) (#5, 5%)",
    "space_3d": "TODO: spatial continuity note — usually the first to sacrifice (#6, 4%)",
}

# Optional soundtrack axis (not one of the six weighted criteria; serves #1/#3).
SOUND_TODO = (
    "TODO (optional, #1/#3): soundtrack move at this cut — a SPLIT (voice/music runs across the "
    "cut) vs a HARD SYNC (beat on the frame); which music edit if a bed is in play "
    "(handoff outro / variation shift / intro punch). Blank = pure picture cut."
)
SOUNDTRACK_TODO = (
    "TODO (optional): music-bed intent — mood + where it ENTERS / SHIFTS / RESOLVES against the "
    "cuts (intro on the hook, variation on the pivot, outro on the close)"
)


def blank_cut(cut_id: str, at: str = "", frm: str = "", to: str = "") -> dict:
    cut = {
        "id": cut_id,
        "at": at or f"TODO: where this cut lands (scene boundary or timecode)",
        "from": frm or "TODO: the outgoing shot",
        "to": to or "TODO: the incoming shot",
    }
    for c in CRITERIA:
        cut[c] = CRITERION_TODO[c]
    cut["sound"] = SOUND_TODO
    cut["sacrifices"] = []
    cut["note"] = ""
    return cut


def cuts_from_storyboard(sb: dict) -> list[dict]:
    scenes = sb.get("scenes", []) or []
    if len(scenes) < 2:
        raise SystemExit(
            "ERROR: storyboard has < 2 scenes — no boundaries to cut. Use --cuts N instead."
        )

    def label(scene: dict) -> str:
        typ = scene.get("type", "?")
        sid = scene.get("id", "?")
        text = (scene.get("text") or scene.get("broll_description") or "").strip()
        snippet = (text[:40] + "…") if len(text) > 40 else text
        return f"{sid} [{typ}]" + (f' "{snippet}"' if snippet else "")

    cuts = []
    for i in range(len(scenes) - 1):
        a, b = scenes[i], scenes[i + 1]
        cuts.append(
            blank_cut(
                f"c{i + 1}",
                at=f'{a.get("id", "?")} -> {b.get("id", "?")}',
                frm=label(a),
                to=label(b),
            )
        )
    return cuts


def build(slug: str, language: str, platform: str, cuts: list[dict], reel_ref: str = "") -> dict:
    return {
        "slug": slug,
        "language": language,
        "platform": platform,
        "reel_ref": reel_ref,
        "emotional_throughline": "TODO: the feeling ARC of the whole reel (e.g. 'unease -> recognition -> relief')",
        "soundtrack": SOUNDTRACK_TODO,
        "hierarchy": {
            "emotion": 0.51,
            "story": 0.23,
            "rhythm": 0.10,
            "eye_trace": 0.07,
            "plane_2d": 0.05,
            "space_3d": 0.04,
        },
        "cuts": cuts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a rule-of-six-edit cut sheet JSON.")
    ap.add_argument("slug", help="Short kebab-case id, e.g. my-reel")
    ap.add_argument("--cuts", type=int, default=6, help="Number of blank cuts (default: 6)")
    ap.add_argument(
        "--from-storyboard",
        type=Path,
        default=None,
        help="Seed one cut per scene boundary from an avatar-reel-composer storyboard.json",
    )
    ap.add_argument("--language", default="en", help="Notes language code (default: en)")
    ap.add_argument(
        "--platform",
        default="reels",
        choices=["reels", "tiktok", "shorts"],
        help="Target platform (default: reels)",
    )
    ap.add_argument("--out", type=Path, default=Path("."), help="Output directory (default: .)")
    ap.add_argument("--force", action="store_true", help="Overwrite if the file already exists")
    args = ap.parse_args()

    reel_ref = ""
    if args.from_storyboard:
        try:
            sb = json.loads(args.from_storyboard.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: could not read storyboard: {exc}", file=sys.stderr)
            return 1
        cuts = cuts_from_storyboard(sb)
        reel_ref = str(args.from_storyboard)
    else:
        n = max(1, args.cuts)
        cuts = [blank_cut(f"c{i + 1}") for i in range(n)]

    args.out.mkdir(parents=True, exist_ok=True)
    dest = args.out / f"{args.slug}.cutsheet.json"
    if dest.exists() and not args.force:
        print(f"ERROR: {dest} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    data = build(args.slug, args.language, args.platform, cuts, reel_ref)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  -> {dest}  ({len(cuts)} cut(s))")
    print("  Fill emotion + story first on every cut, then validate with check_cuts.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
