#!/usr/bin/env python3
"""
Instagram reel discovery -- the hardest surface.

Free path (best-effort, no login):
  - business/handle -> Instagram's anonymous web profile endpoint
        /api/v1/users/web_profile_info/?username=<h>  (with x-ig-app-id header).
    Returns recent media incl. video_view_count for reels.
  - topic/hashtag   -> /api/v1/tags/web_info/?tag_name=<tag>  (often gated).
    Both endpoints get rate-limited/blocked frequently; on failure we degrade to
    [] with a clear note rather than guessing.

Paid path (robust): APIFY_TOKEN -> providers/apify.instagram_search (topic+profile).

For a thorough free profile scrape, prefer the browser-based `instagram-scraper`
/ `instagram-videos` skills (they drive a real browser via the MCP); this script
is the no-browser, scriptable best-effort.

Standalone:
    python3 search_instagram.py --business nike --limit 15
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from _common import (
    Reel,
    RateLimiter,
    backfill_publishing_meta,
    detect_credentials,
    extract_hashtags,
    http_json,
    qs,
    to_int,
    to_iso,
)

IG_APP_ID = "936619743392459"  # public web app id used by instagram.com itself
WEB_PROFILE = "https://www.instagram.com/api/v1/users/web_profile_info/"
TAG_INFO = "https://www.instagram.com/api/v1/tags/web_info/"
_rl = RateLimiter(per_sec=0.7)


def _ig_headers() -> dict[str, str]:
    return {
        "x-ig-app-id": IG_APP_ID,
        "Accept": "*/*",
        "Referer": "https://www.instagram.com/",
        "X-Requested-With": "XMLHttpRequest",
    }


def _node_to_reel(node: dict, query: str, match_type: str) -> Optional[Reel]:
    sc = node.get("shortcode") or node.get("code")
    if not sc:
        return None
    cap = ""
    edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    if edges:
        cap = (edges[0].get("node") or {}).get("text") or ""
    owner = node.get("owner") or {}
    is_video = bool(node.get("is_video"))
    hashtags = extract_hashtags(cap)
    metadata = {
        "product_type": node.get("product_type") or ("clips" if is_video else "image"),
        "is_video": is_video,
        "hashtag_count": len(hashtags),
        "description_length": len(cap),
    }
    return Reel(
        platform="instagram",
        video_id=sc,
        url=f"https://www.instagram.com/reel/{sc}/" if is_video else f"https://www.instagram.com/p/{sc}/",
        author=owner.get("username") or node.get("username") or "",
        title=cap,
        views=to_int(node.get("video_view_count") or node.get("video_play_count")),
        likes=to_int((node.get("edge_liked_by") or node.get("edge_media_preview_like") or {}).get("count")),
        comments=to_int((node.get("edge_media_to_comment") or {}).get("count")),
        shares=None,
        published_at=to_iso(node.get("taken_at_timestamp")),
        duration_s=node.get("video_duration"),
        thumbnail=node.get("display_url") or node.get("thumbnail_src"),
        media_url=node.get("video_url"),
        hashtags=hashtags or None,
        metadata=metadata,
        query=query,
        match_type=match_type,
        source="ig-web",
    )


def _free_profile(handle: str, limit: int, query: str, notes: list[str]) -> list[Reel]:
    _rl.wait()
    try:
        data = http_json(f"{WEB_PROFILE}?" + qs({"username": handle.lstrip("@")}),
                         headers=_ig_headers()) or {}
    except Exception as e:  # noqa: BLE001
        notes.append(f"Instagram web profile blocked ({str(e)[:120]}); use the browser "
                     "instagram-scraper skill or set APIFY_TOKEN.")
        return []
    user = (data.get("data") or {}).get("user") or {}
    media = (user.get("edge_owner_to_timeline_media") or {}).get("edges") or []
    reels = [r for e in media if (r := _node_to_reel(e.get("node") or {}, query, "business"))]
    # Prefer video reels but keep image posts as weak signal if nothing else.
    videos = [r for r in reels if r.media_url or "/reel/" in r.url]
    chosen = videos or reels
    if not chosen:
        notes.append(f"Instagram: no public media parsed for @{handle}.")
    return chosen[:limit]


def _free_hashtag(tag: str, limit: int, query: str, notes: list[str]) -> list[Reel]:
    _rl.wait()
    try:
        data = http_json(f"{TAG_INFO}?" + qs({"tag_name": tag.lstrip("#")}),
                         headers=_ig_headers()) or {}
    except Exception as e:  # noqa: BLE001
        notes.append(f"Instagram hashtag endpoint gated ({str(e)[:100]}); set APIFY_TOKEN for "
                     "reliable IG topic search.")
        return []
    out: list[Reel] = []
    payload = data.get("data") or data
    # Newer shape: data.top.sections[].layout_content.medias[].media
    for bucket in ("top", "recent"):
        sections = ((payload.get(bucket) or {}).get("sections")) or []
        for sec in sections:
            for m in (sec.get("layout_content") or {}).get("medias", []) or []:
                node = m.get("media") or {}
                r = _media_v1_to_reel(node, query)
                if r:
                    out.append(r)
    # Older graphql shape fallback.
    edges = ((payload.get("graphql") or {}).get("hashtag") or {})\
        .get("edge_hashtag_to_media", {}).get("edges", [])
    for e in edges:
        r = _node_to_reel(e.get("node") or {}, query, "topic")
        if r:
            out.append(r)
    if not out:
        notes.append(f"Instagram: hashtag '#{tag}' returned no parseable media (commonly gated "
                     "without login).")
    return out[:limit]


def _media_v1_to_reel(node: dict, query: str) -> Optional[Reel]:
    """Map the api/v1 media object (different field names than graphql node)."""
    code = node.get("code")
    if not code:
        return None
    cap = ((node.get("caption") or {}) or {}).get("text") or ""
    user = node.get("user") or {}
    hashtags = extract_hashtags(cap)
    _IG_MEDIA_TYPE = {1: "image", 2: "clips", 8: "carousel"}
    metadata = {
        "product_type": node.get("product_type") or _IG_MEDIA_TYPE.get(node.get("media_type")),
        "hashtag_count": len(hashtags),
        "description_length": len(cap),
    }
    return Reel(
        platform="instagram",
        video_id=code,
        url=f"https://www.instagram.com/reel/{code}/",
        author=user.get("username") or "",
        title=cap,
        views=to_int(node.get("play_count") or node.get("view_count")),
        likes=to_int(node.get("like_count")),
        comments=to_int(node.get("comment_count")),
        published_at=to_iso(node.get("taken_at")),
        duration_s=node.get("video_duration"),
        thumbnail=(node.get("image_versions2") or {}).get("candidates", [{}])[0].get("url"),
        hashtags=hashtags or None,
        metadata=metadata,
        query=query,
        match_type="topic",
        source="ig-web",
    )


def search(
    query: str,
    *,
    match_type: str = "topic",
    limit: int = 15,
    apify_token: Optional[str] = None,
    notes: Optional[list[str]] = None,
    **_ignored: Any,
) -> list[Reel]:
    notes = notes if notes is not None else []
    apify_token = apify_token or detect_credentials()["apify_token"]

    if apify_token:
        try:
            from providers import apify

            dicts = apify.instagram_search(query, limit * 2, apify_token, match_type=match_type)
            if dicts:
                return backfill_publishing_meta([Reel.from_dict(d) for d in dicts])
            notes.append("Instagram: Apify returned no items; trying free best-effort.")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Instagram Apify failed ({str(e)[:140]}); trying free best-effort.")

    if match_type in ("business", "handle"):
        return backfill_publishing_meta(_free_profile(query, limit, query, notes))

    # topic: try each derived hashtag until something parses.
    import re

    words = re.findall(r"[a-z0-9]+", query.lower())
    tags = ["".join(words)] + words
    seen, out = set(), []
    for t in tags:
        if not t or t in seen:
            continue
        seen.add(t)
        out += _free_hashtag(t, limit, query, notes)
        if len(out) >= limit:
            break
    if not out:
        notes.append("Instagram topic discovery has no reliable free path -- set APIFY_TOKEN, or "
                     "search a specific business/handle instead.")
    return backfill_publishing_meta(out[:limit])


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Instagram reel discovery (standalone)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic")
    g.add_argument("--business")
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args()
    query = args.topic or args.business
    match_type = "topic" if args.topic else "business"
    notes: list[str] = []
    reels = search(query, match_type=match_type, limit=args.limit, notes=notes)
    print(json.dumps({"notes": notes, "count": len(reels),
                       "reels": [r.to_dict() for r in reels]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
