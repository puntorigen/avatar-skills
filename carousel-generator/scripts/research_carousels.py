#!/usr/bin/env python3
"""Research winning Instagram carousels from a list of competitor handles.

Pipeline:
  1. For each handle, pull recent posts via the Apify Instagram scraper.
  2. Classify each post as carousel / reel / image and compute engagement.
  3. Produce evidence that carousels out-perform reels (avg engagement by type).
  4. Rank the top carousels overall and download every slide + caption + hashtags.

Usage:
  python3 research_carousels.py --handles sanandoatuex_,leoquins --per-profile 12 \
      --top 6 --out-dir runs/rupturas
  python3 research_carousels.py --handles-file top10.txt --out-dir runs/rupturas

Outputs (in --out-dir):
  research.json          full structured data
  summary.md             human-readable evidence + ranked carousels
  <handle>/<shortcode>/  slide_01.jpg .. slide_NN.jpg + caption.txt + meta.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def fetch_profile_posts(handle: str, limit: int, token: str) -> list[dict]:
    handle = handle.lstrip("@").strip()
    run_input = {
        "directUrls": [f"https://www.instagram.com/{handle}/"],
        "resultsType": "posts",
        "resultsLimit": limit,
        "addParentData": False,
    }
    try:
        items = C.run_apify_actor(C.DEFAULT_IG_ACTOR, run_input, token)
    except Exception as e:  # noqa: BLE001
        print(f"  ! Apify error for @{handle}: {e}", file=sys.stderr)
        return []
    # Keep only posts belonging to this owner (search can bleed).
    out = []
    for it in items:
        owner = (C.first(it, "ownerUsername", "owner.username") or "").lower()
        if owner and owner != handle.lower():
            continue
        out.append(it)
    return out


def normalize_post(item: dict, handle: str) -> dict:
    sc = C.first(item, "shortCode", "shortcode", "code") or ""
    caption = C.first(item, "caption", "edge_media_to_caption") or ""
    ptype = C.classify_post_type(item)
    # Prefer the actor's dedicated hashtags field; fall back to caption regex.
    tags = item.get("hashtags")
    hashtags = [str(t).lstrip("#").lower() for t in tags] if isinstance(tags, list) and tags \
        else C.extract_hashtags(caption)
    return {
        "handle": handle,
        "shortcode": sc,
        "type": ptype,
        "url": C.first(item, "url") or (f"https://www.instagram.com/p/{sc}/" if sc else ""),
        "caption": caption,
        "hashtags": hashtags,
        "likes": C.first(item, "likesCount", "likeCount") or 0,
        "comments": C.first(item, "commentsCount", "commentCount") or 0,
        "views": C.first(item, "videoViewCount", "videoPlayCount"),
        "engagement": C.engagement(item),
        "timestamp": C.first(item, "timestamp", "takenAtTimestamp"),
        "slide_count": len(C.child_image_urls(item)) if ptype == "carousel" else 1,
        "_slide_urls": C.child_image_urls(item) if ptype == "carousel" else [],
        "_display_url": C.first(item, "displayUrl", "thumbnailUrl"),
    }


def type_evidence(posts: list[dict]) -> dict:
    buckets: dict[str, list[int]] = {"carousel": [], "reel": [], "image": []}
    for p in posts:
        buckets.setdefault(p["type"], []).append(p["engagement"])
    evidence = {}
    for t, vals in buckets.items():
        vals = [v for v in vals if v]
        evidence[t] = {
            "count": len(buckets[t]),
            "avg_engagement": round(sum(vals) / len(vals)) if vals else 0,
            "max_engagement": max(buckets[t]) if buckets[t] else 0,
        }
    return evidence


def download_slides(post: dict, out_dir: Path) -> list[str]:
    dest_dir = out_dir / post["handle"] / (post["shortcode"] or "post")
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, url in enumerate(post["_slide_urls"], 1):
        dest = dest_dir / f"slide_{i:02d}.jpg"
        if C.download_file(url, dest):
            saved.append(str(dest))
    if post["caption"]:
        (dest_dir / "caption.txt").write_text(post["caption"], encoding="utf-8")
    meta = {k: v for k, v in post.items() if not k.startswith("_")}
    meta["slides_downloaded"] = saved
    (dest_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return saved


def build_summary(handles: list[str], all_posts: list[dict], evidence: dict,
                  top_carousels: list[dict]) -> str:
    lines = ["# Investigación de carruseles ganadores", ""]
    lines.append(f"Handles analizados: {', '.join('@'+h for h in handles)}")
    lines.append(f"Posts recolectados: {len(all_posts)}")
    lines.append("")
    lines.append("## Evidencia: ¿carousel o reel?")
    lines.append("")
    lines.append("| Formato | Nº posts | Engagement prom. | Engagement máx. |")
    lines.append("| --- | ---: | ---: | ---: |")
    for t in ("carousel", "reel", "image"):
        e = evidence.get(t, {})
        label = {"carousel": "Carrusel", "reel": "Reel", "image": "Imagen"}[t]
        lines.append(f"| {label} | {e.get('count', 0)} | {e.get('avg_engagement', 0):,} | {e.get('max_engagement', 0):,} |")
    car = evidence.get("carousel", {}).get("avg_engagement", 0)
    reel = evidence.get("reel", {}).get("avg_engagement", 0)
    if car and reel:
        ratio = car / reel if reel else 0
        verdict = "el CARRUSEL gana" if car > reel else "el REEL gana"
        lines.append("")
        lines.append(f"**Veredicto:** {verdict} — engagement promedio de carruseles es "
                     f"{ratio:.1f}× el de los reels." if car > reel
                     else f"**Veredicto:** {verdict}.")
    lines.append("")
    lines.append("## Top carruseles (para descomponer)")
    lines.append("")
    lines.append("| # | Cuenta | Slides | Likes | Comentarios | Engagement | URL |")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | --- |")
    for i, p in enumerate(top_carousels, 1):
        lines.append(f"| {i} | @{p['handle']} | {p['slide_count']} | {p['likes']:,} | "
                     f"{p['comments']:,} | {p['engagement']:,} | {p['url']} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Research winning IG carousels from competitors")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--handles", help="Comma-separated IG handles")
    g.add_argument("--handles-file", help="File with one handle per line")
    ap.add_argument("--per-profile", type=int, default=12, help="Posts to pull per profile")
    ap.add_argument("--top", type=int, default=6, help="How many top carousels to download")
    ap.add_argument("--min-slides", type=int, default=3, help="Ignore carousels with fewer slides")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--no-download", action="store_true", help="Skip downloading slides")
    args = ap.parse_args()

    token = C.apify_token()
    if not token:
        print("Error: no Apify token found (reel-discovery/config.json or APIFY_TOKEN).", file=sys.stderr)
        sys.exit(1)

    if args.handles:
        handles = [h.strip().lstrip("@") for h in args.handles.split(",") if h.strip()]
    elif args.handles_file:
        handles = [l.strip().lstrip("@") for l in Path(args.handles_file).read_text().splitlines()
                   if l.strip() and not l.startswith("#")]
    else:
        handles = list(C.ARNOLDO_TOP10)
        print("No handles given; using Arnoldo's Top 10 default.", file=sys.stderr)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_posts: list[dict] = []
    for h in handles:
        print(f"Fetching @{h} ...", file=sys.stderr)
        items = fetch_profile_posts(h, args.per_profile, token)
        posts = [normalize_post(it, h) for it in items]
        print(f"  {len(posts)} posts "
              f"({sum(p['type']=='carousel' for p in posts)} carousels, "
              f"{sum(p['type']=='reel' for p in posts)} reels)", file=sys.stderr)
        all_posts.extend(posts)

    evidence = type_evidence(all_posts)

    carousels = [p for p in all_posts if p["type"] == "carousel" and p["slide_count"] >= args.min_slides]
    carousels.sort(key=lambda p: p["engagement"], reverse=True)
    top_carousels = carousels[: args.top]

    if not args.no_download:
        for p in top_carousels:
            n = download_slides(p, out_dir)
            print(f"  downloaded {len(n)} slides for @{p['handle']}/{p['shortcode']}", file=sys.stderr)

    research = {
        "handles": handles,
        "per_profile": args.per_profile,
        "evidence": evidence,
        "post_count": len(all_posts),
        "carousel_count": len([p for p in all_posts if p["type"] == "carousel"]),
        "top_carousels": [{k: v for k, v in p.items() if not k.startswith("_")}
                          for p in top_carousels],
    }
    (out_dir / "research.json").write_text(
        json.dumps(research, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "summary.md").write_text(
        build_summary(handles, all_posts, evidence, top_carousels), encoding="utf-8")

    print(json.dumps({
        "out_dir": str(out_dir),
        "posts": len(all_posts),
        "top_carousels": len(top_carousels),
        "evidence": evidence,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
