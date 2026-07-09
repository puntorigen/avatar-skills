#!/usr/bin/env python3
"""Search YouTube for candidate B-roll source videos about a topic or person.

Modeled on the reel-discovery skill, but trimmed to what broll-finder needs:
candidate videos (title, channel, views, license, duration) ranked for use as
COMPLEMENTARY footage. A YouTube Data API key (YT_API_KEY) gives exact counts
and a real Creative-Commons filter; otherwise it falls back to `yt-dlp ytsearch`.

Standalone:
    python3 search.py --query "anthony bourdain street food" --limit 12
    python3 search.py --query "ocean waves drone" --creative-commons --sort views
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def write_reports(rows: list[dict], out_json: Path, out_md: Path, query: str, notes: list[str]) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    C.write_manifest(out_json, {"query": query, "count": len(rows), "notes": notes, "candidates": rows})

    lines = [f"# YouTube candidates — {query}", ""]
    if notes:
        lines += ["> " + n for n in notes] + [""]
    lines += ["| # | views | dur | license | channel | title | url |",
              "|--:|------:|----:|---------|---------|-------|-----|"]
    for i, r in enumerate(rows, 1):
        views = f"{r['views']:,}" if r.get("views") else "?"
        dur = C.fmt_ts(r["duration_s"]) if r.get("duration_s") else "?"
        lic = "CC" if r.get("license") == "creativeCommon" else "std"
        title = (r.get("title") or "").replace("|", "/")[:60]
        lines.append(f"| {i} | {views} | {dur} | {lic} | "
                     f"{(r.get('channel') or '')[:20]} | {title} | {r.get('url')} |")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Search YouTube for B-roll source candidates.")
    ap.add_argument("--query", required=True, help="Topic or person (e.g. 'anthony bourdain vietnam').")
    ap.add_argument("--limit", type=int, default=12, help="Max candidates to keep (default 12).")
    ap.add_argument("--sort", default="relevance",
                    choices=["relevance", "views", "recent"], help="Ranking (default relevance).")
    ap.add_argument("--region", help="Region code for the Data API (e.g. US, CL).")
    ap.add_argument("--lang", help="Relevance language for the Data API (e.g. en, es).")
    ap.add_argument("--since", type=int, dest="since_days", help="Only videos from the last N days.")
    ap.add_argument("--max-duration", type=int,
                    help="Drop candidates longer than N seconds (long videos are slow to scan).")
    ap.add_argument("--creative-commons", action="store_true",
                    help="Only Creative-Commons-licensed videos (safer to republish, with attribution).")
    ap.add_argument("-o", "--out-dir", default=".", help="Where to write candidates.json / candidates.md.")
    args = ap.parse_args()

    notes: list[str] = []
    rows = C.youtube_search(
        args.query, limit=args.limit, sort=args.sort, region=args.region, lang=args.lang,
        since_days=args.since_days, max_duration=args.max_duration,
        creative_commons=args.creative_commons, notes=notes)

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_json = out_dir / "candidates.json"
    out_md = out_dir / "candidates.md"
    write_reports(rows, out_json, out_md, args.query, notes)

    for n in notes:
        print(f"[search] {n}", file=sys.stderr)
    print(json.dumps({"query": args.query, "count": len(rows),
                      "candidates_json": str(out_json), "candidates_md": str(out_md)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
