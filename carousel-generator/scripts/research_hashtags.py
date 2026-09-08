#!/usr/bin/env python3
"""Build a ranked hashtag set for a niche.

Primary source: the hashtags that the winning competitor captions already use
(from research.json). These are proven-in-niche. Optionally enriches with popular
related hashtags for a seed tag via Apify.

Ranks with a simple mix strategy so the final set blends reach (high-frequency,
broad) with niche relevance (mid/low-frequency, specific) — the pattern that
performs on Instagram.

Usage:
  python3 research_hashtags.py --run-dir runs/rupturas [--seed superartuex] [--limit 25]

Outputs (in --run-dir):
  hashtags.json   ranked list with frequency + tier
  hashtags.txt    ready-to-paste block (space separated, #-prefixed)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def enrich_from_apify(seed: str, token: str, limit: int = 30) -> Counter:
    counter: Counter = Counter()
    run_input = {"hashtags": [seed.lstrip("#")], "resultsLimit": limit, "resultsType": "posts"}
    try:
        items = C.run_apify_actor(C.DEFAULT_HASHTAG_ACTOR, run_input, token, timeout=180)
    except Exception as e:  # noqa: BLE001
        print(f"  ! hashtag enrichment skipped: {e}", file=sys.stderr)
        return counter
    for it in items:
        for h in C.extract_hashtags(C.first(it, "caption") or ""):
            counter[h] += 1
    return counter


def tier_for(freq: int, max_freq: int) -> str:
    if max_freq <= 1:
        return "niche"
    ratio = freq / max_freq
    if ratio >= 0.66:
        return "reach"
    if ratio >= 0.33:
        return "mid"
    return "niche"


def main() -> None:
    ap = argparse.ArgumentParser(description="Rank hashtags for a niche from winning captions")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--seed", help="Optional seed hashtag for Apify enrichment")
    ap.add_argument("--limit", type=int, default=25, help="Max hashtags in the final set")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    research_path = run_dir / "research.json"
    if not research_path.exists():
        print(f"Error: {research_path} not found. Run research_carousels.py first.", file=sys.stderr)
        sys.exit(1)
    research = json.loads(research_path.read_text(encoding="utf-8"))

    counter: Counter = Counter()
    for c in research.get("top_carousels", []):
        for h in c.get("hashtags", []):
            counter[h] += 1
    # Also scan any downloaded caption.txt for more coverage.
    for cap in run_dir.glob("*/*/caption.txt"):
        for h in C.extract_hashtags(cap.read_text(encoding="utf-8")):
            counter[h] += 1

    if args.seed:
        token = C.apify_token()
        if token:
            print(f"Enriching from #{args.seed} via Apify...", file=sys.stderr)
            counter.update(enrich_from_apify(args.seed, token))

    if not counter:
        print("Warning: no hashtags found in captions.", file=sys.stderr)

    max_freq = max(counter.values()) if counter else 1
    ranked = []
    for tag, freq in counter.most_common():
        ranked.append({"tag": tag, "freq": freq, "tier": tier_for(freq, max_freq)})

    # Mix strategy: interleave reach + mid + niche, cap at limit.
    by_tier = {"reach": [], "mid": [], "niche": []}
    for r in ranked:
        by_tier[r["tier"]].append(r)
    mixed, i = [], 0
    while len(mixed) < min(args.limit, len(ranked)):
        for t in ("reach", "mid", "niche"):
            if i < len(by_tier[t]):
                mixed.append(by_tier[t][i])
        i += 1
        if i > len(ranked):
            break
    mixed = mixed[: args.limit]

    (run_dir / "hashtags.json").write_text(
        json.dumps({"ranked": ranked, "selected": mixed}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    block = " ".join(f"#{r['tag']}" for r in mixed)
    (run_dir / "hashtags.txt").write_text(block + "\n", encoding="utf-8")

    print(json.dumps({
        "run_dir": str(run_dir),
        "unique_hashtags": len(ranked),
        "selected": len(mixed),
        "preview": block[:200],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
