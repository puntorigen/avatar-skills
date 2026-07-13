#!/usr/bin/env python3
"""Validate a rule-of-six-edit cut sheet against Murch's hierarchy.

Enforces the doctrine: emotion (#1) and story (#2) are required on every cut and
can never be sacrificed; lower criteria may be sacrificed only from the BOTTOM up
(space_3d, then plane_2d, then eye_trace, then rhythm — no gaps). Every criterion
must be either addressed or explicitly sacrificed.

Prints a PASS/FAIL/WARN report. Exit 0 if there are no FAILs (WARNs allowed), 1
otherwise. Pure stdlib.

    python3 check_cuts.py cuts_out/my-reel.cutsheet.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Weights (Murch) and the give-up order (first-to-sacrifice ... last).
WEIGHTS = {
    "emotion": 0.51,
    "story": 0.23,
    "rhythm": 0.10,
    "eye_trace": 0.07,
    "plane_2d": 0.05,
    "space_3d": 0.04,
}
CRITERIA = list(WEIGHTS.keys())              # top -> bottom
GIVE_UP_ORDER = ["space_3d", "plane_2d", "eye_trace", "rhythm"]  # first-to-sacrifice ...
NEVER_SACRIFICE = {"emotion", "story"}


def is_todo(value) -> bool:
    if not isinstance(value, str):
        return not value
    v = value.strip().lower()
    return not v or v.startswith("todo")


def cut_score(cut: dict, sac: set[str]) -> float:
    """Coverage = sum of weights of criteria that are addressed AND not sacrificed."""
    total = 0.0
    for c in CRITERIA:
        if c in sac:
            continue
        if not is_todo(cut.get(c, "")):
            total += WEIGHTS[c]
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a rule-of-six-edit cut sheet JSON.")
    ap.add_argument("cutsheet_json", type=Path, help="Path to <slug>.cutsheet.json")
    args = ap.parse_args()

    try:
        data = json.loads(args.cutsheet_json.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  could not read JSON: {exc}", file=sys.stderr)
        return 1

    fails: list[str] = []
    warns: list[str] = []

    if is_todo(data.get("emotional_throughline", "")):
        warns.append("emotional_throughline is empty/TODO — name the feeling ARC of the whole reel (#1).")

    cuts = data.get("cuts", []) or []
    if not cuts:
        fails.append("no cuts defined — nothing to evaluate.")

    seen_ids: set[str] = set()
    for idx, cut in enumerate(cuts):
        cid = str(cut.get("id") or f"#{idx + 1}")
        if cid in seen_ids:
            warns.append(f"cut '{cid}': duplicate id.")
        seen_ids.add(cid)

        # Top two are mandatory.
        if is_todo(cut.get("emotion", "")):
            fails.append(f"cut '{cid}': emotion is empty/TODO — the cut isn't motivated (#1).")
        if is_todo(cut.get("story", "")):
            fails.append(f"cut '{cid}': story is empty/TODO — every cut must deliver new info (#2).")

        # Sacrifices: never the top two, and a valid bottom-up prefix (no gaps).
        raw_sac = cut.get("sacrifices", []) or []
        sac = {str(s).strip().lower() for s in raw_sac}

        bad = sac & NEVER_SACRIFICE
        if bad:
            fails.append(
                f"cut '{cid}': sacrifices {sorted(bad)} — never sacrifice emotion/story (doctrine)."
            )
        unknown = sac - set(CRITERIA)
        if unknown:
            warns.append(f"cut '{cid}': unknown sacrifice(s) {sorted(unknown)} — ignored.")

        sac_lower = sac & set(GIVE_UP_ORDER)
        k = len(sac_lower)
        expected_prefix = set(GIVE_UP_ORDER[:k])
        if sac_lower != expected_prefix:
            fails.append(
                f"cut '{cid}': sacrifice out of order {sorted(sac_lower)} — give up from the "
                "bottom: space_3d -> plane_2d -> eye_trace -> rhythm, no gaps (doctrine)."
            )
        if "rhythm" in sac_lower:
            warns.append(
                f"cut '{cid}': sacrificing rhythm (10%) is a high price — re-time the cut before "
                "giving up rhythm (#3)."
            )

        # Every criterion must be addressed or explicitly sacrificed.
        for c in CRITERIA:
            if c in NEVER_SACRIFICE:
                continue  # already checked above (mandatory, filled)
            if is_todo(cut.get(c, "")) and c not in sac:
                warns.append(
                    f"cut '{cid}': {c} is neither addressed nor sacrificed — consider it or list it "
                    "in sacrifices."
                )

        score = cut_score(cut, sac)
        if score < 0.74 - 1e-9:  # below emotion+story floor => a top criterion is missing/TODO
            warns.append(
                f"cut '{cid}': coverage {score:.0%} is below the emotion+story floor (74%) — "
                "a top criterion is unaddressed."
            )

    # Report.
    print(f"Validating: {args.cutsheet_json}")
    print("-" * 64)
    for f in fails:
        print(f"FAIL  {f}")
    for w in warns:
        print(f"WARN  {w}")
    if not fails and not warns:
        print(f"PASS  all {len(cuts)} cut(s) satisfy the hierarchy.")
    elif not fails:
        print("-" * 64)
        print(f"PASS  (with {len(warns)} warning(s) to review).")
    else:
        print("-" * 64)
        print(f"FAILED  {len(fails)} hard rule(s), {len(warns)} warning(s).")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
