#!/usr/bin/env python3
"""
filter_creators.py - turn reel-discovery output into a humans-only creator ranking.

Aggregates one or more `discovery/<slug>/results.json` files by author, DROPS
official/brand/product accounts (so you rank against real people you can actually
compete with), ranks the remaining individual creators by velocity (views/day),
and extracts any links found in their video descriptions (a first read on their
cross-platform footprint). Output: a markdown table + a JSON sidecar.

Stdlib only. Reads the schema written by reel-discovery's _common.py.

Usage:
  python3 filter_creators.py --discovery discovery \
      --slugs en-ai-coding-agents,es-agentes-ia \
      --keywords "agent,claude,coding,ia,automat,llm,cursor,codex" \
      --min-views 8000 --sort velocity --top 40 \
      --out discovery/_creators.md

  # all slugs under discovery/, no niche keyword filter:
  python3 filter_creators.py
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

# Official product / company / media accounts are NOT your competition. Extend
# with --exclude / --exclude-file. Matching is case-insensitive, exact OR
# substring on the author name.
DEFAULT_BRANDS = {
    "kimi ai", "claude", "anthropic", "openai", "chatgpt", "google", "google ai",
    "deepmind", "microsoft", "microsoft ai", "copilot", "nvidia", "meta", "meta ai",
    "android", "android studio", "unity", "unity ai", "notion", "monday", "monday.com",
    "outsystems", "base44", "luma", "luma ai", "veeam", "retool", "gemini", "perplexity",
    "replicate", "huggingface", "hugging face", "github", "aws", "amazon web services",
    "vercel", "langchain", "n8n", "make", "zapier", "ndtv", "ndtv profit",
    "el confidencial", "elconfidencial", "the daily show", "bloomberg", "cnbc",
    "forbes", "wired", "techcrunch", "the verge", "bit cloud", "bitcloud",
}

URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


def load_results(discovery: Path, slugs: list[str] | None) -> list[tuple[str, dict]]:
    out = []
    if slugs:
        files = [discovery / s / "results.json" for s in slugs]
    else:
        files = sorted(discovery.glob("*/results.json"))
    for f in files:
        if not f.exists():
            print(f"  ! skip (missing): {f}")
            continue
        try:
            out.append((f.parent.name, json.loads(f.read_text())))
        except Exception as e:  # noqa: BLE001
            print(f"  ! skip (bad json): {f} ({e})")
    return out


def is_brand(author: str, brands: set[str]) -> bool:
    a = (author or "").strip().lower()
    if not a:
        return False
    return any(b == a or b in a for b in brands)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--discovery", default="discovery", help="root folder of reel-discovery output")
    ap.add_argument("--slugs", default="", help="comma list of discovery slugs (default: all)")
    ap.add_argument("--keywords", default="", help="comma list; keep a creator only if a title/author matches one (niche filter)")
    ap.add_argument("--exclude", default="", help="comma list of extra brand/author names to drop")
    ap.add_argument("--exclude-file", default="", help="file with one brand/author name per line")
    ap.add_argument("--min-views", type=int, default=5000, help="drop creators whose best video is below this")
    ap.add_argument("--max-subs", type=int, default=0, help="optional: drop channels above N subscribers (mega media/brands); 0=off")
    ap.add_argument("--sort", choices=["velocity", "views", "engagement"], default="velocity")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--out", default="", help="markdown output path (also writes a .json sidecar); default: stdout")
    args = ap.parse_args()

    brands = set(DEFAULT_BRANDS)
    brands |= {x.strip().lower() for x in args.exclude.split(",") if x.strip()}
    if args.exclude_file:
        p = Path(args.exclude_file)
        if p.exists():
            brands |= {ln.strip().lower() for ln in p.read_text().splitlines() if ln.strip()}

    kw = [k.strip() for k in args.keywords.split(",") if k.strip()]
    kw_re = re.compile("|".join(re.escape(k) for k in kw), re.I) if kw else None

    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()] or None
    datasets = load_results(Path(args.discovery), slugs)
    if not datasets:
        print("No results.json found. Run reel-discovery first.")
        return 1

    agg: dict[str, dict] = defaultdict(lambda: {
        "name": "", "platforms": set(), "best": 0, "vel": 0.0, "eng": 0.0,
        "subs": 0, "country": "", "urls": set(), "items": [], "slugs": set(),
    })

    for slug, data in datasets:
        for r in data.get("results", []):
            author = r.get("author") or "?"
            if is_brand(author, brands):
                continue
            g = agg[author.strip().lower()]
            g["name"] = author
            g["platforms"].add(r.get("platform", "?"))
            g["slugs"].add(slug)
            g["best"] = max(g["best"], r.get("views") or 0)
            g["vel"] = max(g["vel"], r.get("velocity") or 0.0)
            g["eng"] = max(g["eng"], r.get("engagement_rate") or 0.0)
            md = r.get("metadata") or {}
            if md.get("subscribers"):
                g["subs"] = max(g["subs"], md["subscribers"])
            if md.get("channel_country"):
                g["country"] = md["channel_country"]
            for u in URL_RE.findall(r.get("description") or ""):
                g["urls"].add(u.rstrip(".,);"))
            g["items"].append({
                "platform": r.get("platform"), "views": r.get("views") or 0,
                "title": (r.get("title") or "")[:70], "url": r.get("url"),
            })

    rows = list(agg.values())
    # niche keyword filter (keep creator if any item matches)
    if kw_re:
        rows = [g for g in rows if any(kw_re.search((it["title"] or "") + " " + g["name"]) for it in g["items"])]
    rows = [g for g in rows if g["best"] >= args.min_views]
    if args.max_subs:
        rows = [g for g in rows if not (g["subs"] and g["subs"] > args.max_subs)]
    rows.sort(key=lambda x: -x[{"velocity": "vel", "views": "best", "engagement": "eng"}[args.sort]])
    rows = rows[: args.top]

    # markdown
    lines = ["# Creator shortlist (humans only)", ""]
    lines.append(f"- Source: `{args.discovery}` slugs={slugs or 'all'} | sort=`{args.sort}` | kept={len(rows)}")
    lines.append(f"- Excluded brands/official accounts: {len(brands)} names")
    lines.append("")
    lines.append("| # | Creator | Platforms | Best views | Views/day | Eng. | Subs | Country | Links |")
    lines.append("|--:|---|---|--:|--:|--:|--:|--|---|")
    for i, g in enumerate(rows, 1):
        links = " ".join(sorted(g["urls"]))[:120] if g["urls"] else "—"
        lines.append(
            f"| {i} | {g['name']} | {','.join(sorted(g['platforms']))} | "
            f"{g['best']:,} | {int(g['vel']):,} | {g['eng']*100:.1f}% | "
            f"{g['subs']:,} | {g['country'] or '—'} | {links} |"
        )

    md = "\n".join(lines) + "\n"
    if args.out:
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(md)
        sidecar = outp.with_suffix(".json")
        sidecar.write_text(json.dumps([
            {**g, "platforms": sorted(g["platforms"]), "urls": sorted(g["urls"]), "slugs": sorted(g["slugs"])}
            for g in rows
        ], ensure_ascii=False, indent=2))
        print(f"Wrote {outp} ({len(rows)} creators) + {sidecar.name}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
