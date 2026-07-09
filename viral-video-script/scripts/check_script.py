#!/usr/bin/env python3
"""Validate a viral-video-script beat sheet against the six-principle formula.

Prints a PASS/FAIL/WARN report. Exit code 0 if there are no FAILs (WARNs allowed),
1 otherwise. Pure stdlib.

    python3 check_script.py scripts_out/buldak-spicy.script.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_BEATS = ["hook", "problem", "story", "payoff"]
SPREAD_TRIGGERS = {"humor", "surprise", "awe", "curiosity", "inspiration"}
HOOK_MAX_WORDS = 14
PREMISE_MAX_WORDS = 20
WORDS_PER_SEC = 2.6  # spoken pace ceiling used for the length sanity check


def words(text: str) -> int:
    return len(re.findall(r"\b[\w'’]+\b", text or ""))


def is_todo(value: str) -> bool:
    return not value or value.strip().lower().startswith("todo")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a viral-video-script beat sheet JSON.")
    ap.add_argument("script_json", type=Path, help="Path to <slug>.script.json")
    args = ap.parse_args()

    try:
        data = json.loads(args.script_json.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  could not read JSON: {exc}", file=sys.stderr)
        return 1

    fails: list[str] = []
    warns: list[str] = []

    subject = data.get("subject", {}) or {}
    product = (subject.get("product") or "").strip()

    # Principle 1, 3, 4, 5 — required, filled-in subject fields.
    for field, principle in (
        ("format_steal", "#1 familiarity / format-steal"),
        ("credential", "#4 credential shortcut"),
        ("identity_value", "#3 identity over product"),
        ("shareable_premise", "#5 shareability"),
    ):
        if is_todo(subject.get(field, "")):
            fails.append(f"subject.{field} is empty/TODO  ({principle})")

    # Principle 5 — one-sentence, short, shareable premise.
    premise = (subject.get("shareable_premise") or "").strip()
    if not is_todo(premise):
        if words(premise) > PREMISE_MAX_WORDS:
            warns.append(
                f"shareable_premise is {words(premise)} words (aim <= {PREMISE_MAX_WORDS}); "
                "if a friend can't repeat it fast, it won't be shared (#5)."
            )
        if premise.count(".") + premise.count("!") + premise.count("?") > 1:
            warns.append("shareable_premise looks like >1 sentence; tighten to ONE sentence (#5).")

    trigger = (subject.get("share_trigger") or "").strip().lower()
    if trigger and trigger not in SPREAD_TRIGGERS:
        warns.append(
            f"share_trigger '{trigger}' rarely spreads — humor/surprise/awe travel; "
            "sadness/anger get views but don't get shared (#5)."
        )

    # Principle 6 — Hook -> Problem -> Story -> Payoff present and in order.
    beats = data.get("beats", []) or []
    order = [str(b.get("beat", "")).lower() for b in beats]
    for name in REQUIRED_BEATS:
        if name not in order:
            fails.append(f"missing beat '{name}'  (#6 story skeleton)")
    present = [b for b in order if b in REQUIRED_BEATS]
    if present != [b for b in REQUIRED_BEATS if b in present]:
        fails.append(f"beats out of order: {present} — must be Hook->Problem->Story->Payoff (#6)")

    by_name = {str(b.get("beat", "")).lower(): b for b in beats}

    # Principle 2 — curiosity-gap hook: short, no product name.
    hook = by_name.get("hook")
    if hook:
        spoken = (hook.get("spoken") or "").strip()
        if is_todo(spoken):
            fails.append("hook.spoken is empty/TODO  (#2 curiosity gap)")
        else:
            if words(spoken) > HOOK_MAX_WORDS:
                warns.append(
                    f"hook is {words(spoken)} words (~{words(spoken)/WORDS_PER_SEC:.0f}s); "
                    f"keep it <= {HOOK_MAX_WORDS} words / ~2s (#2)."
                )
            if product and re.search(re.escape(product), spoken, re.IGNORECASE):
                fails.append(
                    f"hook names the product ('{product}') — the brain instantly tags it as an ad. "
                    "Open a curiosity gap instead (#2)."
                )

    # All beats should carry spoken copy.
    for b in beats:
        name = b.get("beat", "?")
        if is_todo(b.get("spoken", "")):
            fails.append(f"beat '{name}' has no spoken copy")

    # Editing rules (#6) + length sanity.
    if not data.get("captions", False):
        warns.append("captions are off — burn in captions for dual processing + retention (#6).")
    cut = data.get("cut_every_seconds")
    if isinstance(cut, (int, float)) and cut > 4:
        warns.append(f"cut_every_seconds={cut}: cut every 2-4s; every cut resets attention (#6).")

    total_words = sum(words(b.get("spoken", "")) for b in beats if not is_todo(b.get("spoken", "")))
    target = data.get("target_seconds")
    if isinstance(target, (int, float)) and total_words:
        est = total_words / WORDS_PER_SEC
        if est > target * 1.2:
            warns.append(
                f"spoken copy ~{est:.0f}s of VO vs target {target}s — trim dead words (#6)."
            )

    # Report.
    print(f"Validating: {args.script_json}")
    print("-" * 60)
    for f in fails:
        print(f"FAIL  {f}")
    for w in warns:
        print(f"WARN  {w}")
    if not fails and not warns:
        print("PASS  all six principles satisfied.")
    elif not fails:
        print("-" * 60)
        print(f"PASS  (with {len(warns)} warning(s) to review).")
    else:
        print("-" * 60)
        print(f"FAILED  {len(fails)} hard rule(s), {len(warns)} warning(s).")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
