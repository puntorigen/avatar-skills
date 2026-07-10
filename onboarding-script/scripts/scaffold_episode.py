#!/usr/bin/env python3
"""Scaffold per-episode beat sheets (episode.json) from a curriculum.json.

Each episode gets a beat skeleton (hook -> content/demo/broll -> outro) with a
`kind` per beat (talking_head | demo | broll) and TODO placeholders for the agent
to fill with copy grounded in company_context.json. `demo` beats are pre-seeded
from the episode's `demo_targets`.

Pure stdlib.

    python3 scaffold_episode.py --curriculum onboarding/acme/curriculum.json \
        --out-dir onboarding/acme/episodes/
    python3 scaffold_episode.py --curriculum .../curriculum.json --episode create-project
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HOOK_SECS = 3
OUTRO_SECS = 5
SECS_PER_BEAT = 6  # rough pacing target


def build_beats(ep: dict) -> list[dict]:
    seconds = int(ep.get("target_seconds", 45))
    lang = ep.get("language", "en")
    topics = ep.get("topics") or [ep.get("title", "the topic")]
    demo_targets = ep.get("demo_targets") or []
    needs_demo = bool(ep.get("needs_demo")) or bool(demo_targets)

    n_total = max(4, round(seconds / SECS_PER_BEAT))
    n_mid = max(2, n_total - 2)  # excluding hook + outro
    mid_secs = max(2, round((seconds - HOOK_SECS - OUTRO_SECS) / n_mid))

    beats: list[dict] = []

    beats.append({
        "id": "b1", "kind": "talking_head", "seconds": HOOK_SECS,
        "narration": f"TODO: warm one-line hook for '{ep.get('title')}' — the promise, no jargon.",
        "on_screen": "TODO: presenter to camera; title card optional.",
        "caption": "TODO: short caption (<= 6 words).",
        "note": "Hook: say who this is for and what they'll get. Keep it to ~1 short sentence.",
    })

    # Plan the middle: place demo beats first, then one B-roll, rest talking_head.
    demo_slots = len(demo_targets) if demo_targets else (1 if needs_demo else 0)
    demo_slots = min(demo_slots, n_mid)
    broll_slot = 1 if n_mid - demo_slots >= 1 else 0
    kinds = (["demo"] * demo_slots) + (["broll"] * broll_slot)
    kinds += ["talking_head"] * (n_mid - len(kinds))

    di = 0
    for i, kind in enumerate(kinds):
        topic = topics[i % len(topics)]
        bid = f"b{i + 2}"
        beat = {
            "id": bid, "kind": kind, "seconds": mid_secs,
            "narration": f"TODO: explain '{topic}' for the new hire. Ground it in company_context.json; mark unknowns [TO CONFIRM].",
            "on_screen": "TODO: what appears on screen.",
            "caption": "TODO: short caption.",
        }
        if kind == "demo":
            tgt = demo_targets[di] if di < len(demo_targets) else {}
            di += 1
            beat["demo"] = {
                "url": tgt.get("url", ""),
                "intent": tgt.get("intent", f"TODO: describe the screen recording for '{topic}' (natural language)."),
                "language": lang,
            }
            beat["note"] = "Screen recording: the narration is the voice-over spoken while the demo plays. Needs url + intent."
        elif kind == "broll":
            beat["broll"] = f"TODO: describe a silent B-roll visual reinforcing '{topic}' (people/objects/UI, NO presenter)."
            beat["note"] = "B-roll: the narration is voice-over; describe the visual, no presenter on camera."
        else:
            beat["note"] = f"Talking-head on '{topic}'. Short spoken sentences (captions show one phrase at a time)."
        beats.append(beat)

    beats.append({
        "id": f"b{len(beats) + 1}", "kind": "talking_head", "seconds": OUTRO_SECS,
        "narration": "TODO: recap in one line + the single next action for the new hire.",
        "on_screen": "TODO: presenter to camera; end card with the next step.",
        "caption": "TODO: the next step, short.",
        "note": "Outro: one clear call to action / where to go next.",
    })
    return beats


def build_episode(ep: dict, curriculum: dict) -> dict:
    return {
        "id": ep.get("id"),
        "order": ep.get("order"),
        "slug": ep.get("slug"),
        "title": ep.get("title"),
        "company": curriculum.get("company"),
        "company_name": curriculum.get("company_name"),
        "language": ep.get("language", curriculum.get("language", "en")),
        "audience": ep.get("audience", curriculum.get("audience")),
        "target_seconds": int(ep.get("target_seconds", 45)),
        "objective": ep.get("objective", ""),
        "topics": ep.get("topics", []),
        "sources": list(ep.get("sources", [])),
        "voice": {"emotion": "warm"},
        "beats": build_beats(ep),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold per-episode beat sheets from a curriculum.")
    ap.add_argument("--curriculum", type=Path, required=True, help="curriculum.json from scaffold_curriculum.py")
    ap.add_argument("--episode", help="Only scaffold this episode id (default: all)")
    ap.add_argument("--out-dir", type=Path, help="Output dir (default: onboarding/<company>/episodes/)")
    ap.add_argument("--force", action="store_true", help="Overwrite existing episode files")
    args = ap.parse_args()

    try:
        curriculum = json.loads(args.curriculum.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not read curriculum: {exc}", file=sys.stderr)
        return 1

    episodes = curriculum.get("episodes", []) or []
    if args.episode:
        episodes = [e for e in episodes if e.get("id") == args.episode]
        if not episodes:
            print(f"ERROR: no episode with id '{args.episode}' in curriculum", file=sys.stderr)
            return 1

    out_dir = args.out_dir or (args.curriculum.parent / "episodes")
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for ep in episodes:
        dest = out_dir / f"{ep.get('slug')}.episode.json"
        if dest.exists() and not args.force:
            print(f"  skip (exists): {dest}  (use --force to overwrite)")
            continue
        data = build_episode(ep, curriculum)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  -> {dest}  ({len(data['beats'])} beats)")
        written += 1

    print(f"  {written} episode file(s) written to {out_dir}")
    print("  Next: fill each episode.json (ground in company_context.json), then check_episode.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
