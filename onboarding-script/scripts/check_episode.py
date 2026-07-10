#!/usr/bin/env python3
"""Validate onboarding episode beat sheets before rendering.

Prints a PASS/FAIL/WARN report per file. Exit code 0 if there are no FAILs across
all inputs (WARNs allowed), 1 otherwise. Pure stdlib.

    python3 check_episode.py onboarding/acme/episodes/*.episode.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VALID_KINDS = {"talking_head", "demo", "broll"}
SENTENCE_MAX_WORDS = 14      # caption-friendliness: split longer sentences
WORDS_PER_SEC = 2.6          # spoken pace ceiling for the length sanity check


def words(text: str) -> int:
    return len(re.findall(r"\b[\w'’]+\b", text or ""))


def is_todo(text: str) -> bool:
    t = (text or "").strip()
    return not t or t.lower().startswith("todo")


def long_sentences(text: str) -> list[str]:
    out = []
    for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        if words(s) > SENTENCE_MAX_WORDS:
            out.append(s)
    return out


def check_episode(path: Path) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []
    try:
        ep = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"could not read JSON: {exc}"], []

    for field in ("id", "slug", "order", "title", "language", "target_seconds"):
        if ep.get(field) in (None, ""):
            fails.append(f"missing top-level field '{field}'")

    # slug should be zero-padded-order + id-ish.
    order = ep.get("order")
    slug = ep.get("slug") or ""
    if isinstance(order, int) and not slug.startswith(f"{order:02d}"):
        warns.append(f"slug '{slug}' doesn't start with the zero-padded order '{order:02d}_' (breaks file ordering).")

    beats = ep.get("beats", []) or []
    if not beats:
        fails.append("no beats")
        return fails, warns

    seen_ids = set()
    has_vo = False
    for i, b in enumerate(beats, start=1):
        bid = b.get("id", f"#{i}")
        if bid in seen_ids:
            warns.append(f"duplicate beat id '{bid}'")
        seen_ids.add(bid)

        kind = b.get("kind")
        if kind not in VALID_KINDS:
            fails.append(f"beat '{bid}': kind '{kind}' not in {sorted(VALID_KINDS)}")

        narration = b.get("narration", "")
        if is_todo(narration):
            fails.append(f"beat '{bid}': narration is empty/TODO")
        else:
            has_vo = True
            if "[TO CONFIRM]" in narration:
                warns.append(f"beat '{bid}': narration has an unresolved [TO CONFIRM] — verify or ask before shipping.")
            for s in long_sentences(narration):
                warns.append(f"beat '{bid}': long sentence ({words(s)} words) — split for captions: \"{s[:60]}...\"")

        if kind == "demo":
            demo = b.get("demo") or {}
            if not (demo.get("url") or "").strip():
                fails.append(f"beat '{bid}': demo has no url (the recorder needs a URL to open).")
            if is_todo(demo.get("intent", "")):
                fails.append(f"beat '{bid}': demo has no intent (natural-language description of the recording).")
        elif kind == "broll":
            if is_todo(b.get("broll", "")):
                warns.append(f"beat '{bid}': broll visual not described.")

        if is_todo(b.get("caption", "")):
            warns.append(f"beat '{bid}': no caption text (burned-in captions boost retention).")

    if not has_vo:
        fails.append("no beat carries a voice-over (narration) — nothing to narrate/tile.")

    # Length sanity vs target.
    total_words = sum(words(b.get("narration", "")) for b in beats if not is_todo(b.get("narration", "")))
    target = ep.get("target_seconds")
    if isinstance(target, (int, float)) and total_words:
        est = total_words / WORDS_PER_SEC
        if est > target * 1.25:
            warns.append(f"VO is ~{est:.0f}s vs target {target}s — trim to keep the reel tight.")

    # Storyboard tiling sanity: scene.text is the verbatim narration, joined by single
    # spaces. A stray double space / newline in narration would break that guarantee.
    for b in beats:
        n = b.get("narration", "")
        if not is_todo(n) and ("\n" in n or "  " in n):
            warns.append(f"beat '{b.get('id')}': narration has a newline/double-space — normalize (storyboard tiles on single spaces).")

    return fails, warns


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate onboarding episode beat sheets.")
    ap.add_argument("episodes", nargs="+", help="episode.json file(s) or a directory")
    args = ap.parse_args()

    files: list[Path] = []
    for p in args.episodes:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("*.episode.json")))
        else:
            files.append(path)
    if not files:
        print("ERROR: no episode.json inputs", file=sys.stderr)
        return 1

    total_fails = 0
    for f in files:
        fails, warns = check_episode(f)
        print(f"\n{f.name}")
        print("-" * 60)
        for x in fails:
            print(f"FAIL  {x}")
        for w in warns:
            print(f"WARN  {w}")
        if not fails and not warns:
            print("PASS  ready to render.")
        elif not fails:
            print(f"PASS  (with {len(warns)} warning(s) to review).")
        else:
            print(f"FAILED  {len(fails)} hard rule(s), {len(warns)} warning(s).")
        total_fails += len(fails)

    print("\n" + "=" * 60)
    print(f"{'FAILED' if total_fails else 'PASS'}  {len(files)} file(s), {total_fails} hard failure(s) total.")
    return 1 if total_fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
