#!/usr/bin/env python3
"""
TikTok reel discovery.

Free path (no key): tikwm.com public API.
  - topic     -> /api/feed/search?keywords=...   (true keyword search), with a
                 /api/challenge/posts?challenge_name=<hashtag> fallback.
  - business  -> /api/user/posts?unique_id=<handle>  plus a keyword search on the
                 brand name (captures third-party reels).
  tikwm returns play_count / digg_count / comment_count / share_count, so reels
  rank by real views even without an API key. Rate-limited ~1 req/sec.

yt-dlp fallback: full extraction of `tiktok.com/@handle` (counts present) when
tikwm is down and a handle is known.

Paid upgrade: APIFY_TOKEN unlocks robust keyword search via providers/apify.py.

Standalone:
    python3 search_tiktok.py --topic "ai tools" --limit 15
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
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

FEED_SEARCH = "https://www.tikwm.com/api/feed/search"
CHALLENGE = "https://www.tikwm.com/api/challenge/posts"
USER_POSTS = "https://www.tikwm.com/api/user/posts"
_rl = RateLimiter(per_sec=1.0)  # tikwm rate-limits hard


def _hashtag_candidates(topic: str) -> list[str]:
    """Derive hashtag names from a free-text topic ('ai tools' -> aitools, ai, tools)."""
    words = re.findall(r"[a-z0-9]+", topic.lower())
    cands = ["".join(words)] + words
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:4]


def _video_from_tikwm(v: dict, query: str, match_type: str) -> Optional[Reel]:
    vid = str(v.get("video_id") or v.get("id") or v.get("aweme_id") or "")
    if not vid:
        return None
    author = (v.get("author") or {})
    handle = author.get("unique_id") or author.get("uniqueId") or ""
    play = v.get("play") or v.get("hdplay") or v.get("wmplay")
    if isinstance(play, str) and play.startswith("/"):
        play = "https://www.tikwm.com" + play
    caption = (v.get("title") or "").strip()
    hashtags = extract_hashtags(caption)
    music = v.get("music_info") or {}
    metadata = {
        "region": v.get("region"),
        "music_title": music.get("title"),
        "music_author": music.get("author"),
        "music_original": music.get("original"),
        "is_ad": v.get("is_ad"),
        "saves": to_int(v.get("collect_count")),
        "downloads": to_int(v.get("download_count")),
        "hashtag_count": len(hashtags),
        "description_length": len(caption),
    }
    return Reel(
        platform="tiktok",
        video_id=vid,
        url=f"https://www.tiktok.com/@{handle}/video/{vid}" if handle else (v.get("share_url") or ""),
        author=handle,
        title=caption,
        views=to_int(v.get("play_count")),
        likes=to_int(v.get("digg_count")),
        comments=to_int(v.get("comment_count")),
        shares=to_int(v.get("share_count")),
        published_at=to_iso(v.get("create_time")),
        duration_s=to_int(v.get("duration")),
        thumbnail=v.get("cover") or v.get("origin_cover"),
        media_url=play if isinstance(play, str) and play.startswith("http") else None,
        hashtags=hashtags or None,
        metadata=metadata,
        query=query,
        match_type=match_type,
        source="tikwm",
    )


def _tikwm_paged(base: str, params: dict[str, Any], limit: int, query: str,
                 match_type: str, max_pages: int = 6) -> list[Reel]:
    reels: list[Reel] = []
    cursor = "0"
    for _ in range(max_pages):
        _rl.wait()
        raw = http_json(f"{base}?" + qs({**params, "cursor": cursor})) or {}
        if raw.get("code") not in (0, None):
            break
        data = raw.get("data") or {}
        vids = data.get("videos") or data.get("aweme_list") or []
        for v in vids:
            r = _video_from_tikwm(v, query, match_type)
            if r:
                reels.append(r)
        if len(reels) >= limit or not data.get("hasMore"):
            break
        cursor = str(data.get("cursor") or "0")
    return reels


def _ytdlp_handle(handle: str, limit: int, query: str, match_type: str) -> list[Reel]:
    cmd = ["yt-dlp", f"https://www.tiktok.com/@{handle.lstrip('@')}", "-J",
           "--no-warnings", "--playlist-end", str(min(limit, 30))]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(out.stderr.strip()[-300:] or "yt-dlp tiktok listing failed")
    data = json.loads(out.stdout)
    reels: list[Reel] = []
    for e in data.get("entries", []) or []:
        if not e:
            continue
        vid = str(e.get("id") or "")
        caption = (e.get("title") or e.get("description") or "").strip()
        hashtags = extract_hashtags(e.get("title"), e.get("description"))
        metadata = {
            "music_title": e.get("track"),
            "music_author": e.get("artist") or e.get("creator"),
            "hashtag_count": len(hashtags),
            "description_length": len(caption),
        }
        reels.append(
            Reel(
                platform="tiktok",
                video_id=vid,
                url=e.get("webpage_url") or f"https://www.tiktok.com/@{handle}/video/{vid}",
                author=e.get("uploader") or handle,
                title=caption,
                views=to_int(e.get("view_count")),
                likes=to_int(e.get("like_count")),
                comments=to_int(e.get("comment_count")),
                shares=to_int(e.get("repost_count")),
                published_at=to_iso(e.get("timestamp") or e.get("upload_date")),
                duration_s=e.get("duration"),
                thumbnail=e.get("thumbnail"),
                hashtags=hashtags or None,
                metadata=metadata,
                query=query,
                match_type=match_type,
                source="yt-dlp",
            )
        )
    return reels


def search(
    query: str,
    *,
    match_type: str = "topic",
    limit: int = 15,
    sort: str = "views",
    apify_token: Optional[str] = None,
    notes: Optional[list[str]] = None,
    **_ignored: Any,
) -> list[Reel]:
    notes = notes if notes is not None else []
    apify_token = apify_token or detect_credentials()["apify_token"]

    # Paid path first if available (most reliable keyword search).
    if apify_token:
        try:
            from providers import apify

            dicts = apify.tiktok_search(query, limit * 2, apify_token, match_type=match_type)
            if dicts:
                return backfill_publishing_meta([Reel.from_dict(d) for d in dicts])
            notes.append("TikTok: Apify returned no items; falling back to tikwm.")
        except Exception as e:  # noqa: BLE001
            notes.append(f"TikTok Apify failed ({str(e)[:140]}); falling back to tikwm.")

    reels: list[Reel] = []
    try:
        if match_type in ("business", "handle"):
            handle = query.lstrip("@")
            reels += _tikwm_paged(USER_POSTS, {"unique_id": handle, "count": 34}, limit, query, match_type)
            # Brand keyword search captures third-party reels mentioning the business.
            reels += _tikwm_paged(FEED_SEARCH, {"keywords": query, "count": 30, "hd": 1},
                                  limit, query, match_type)
            if not reels:
                notes.append("TikTok: tikwm empty for handle; trying yt-dlp.")
                reels += _ytdlp_handle(handle, limit, query, match_type)
        else:
            reels += _tikwm_paged(FEED_SEARCH, {"keywords": query, "count": 30, "hd": 1},
                                  limit, query, match_type)
            if len(reels) < limit:
                for tag in _hashtag_candidates(query):
                    reels += _tikwm_paged(CHALLENGE, {"challenge_name": tag, "count": 30},
                                          limit, query, match_type)
                    if len(reels) >= limit:
                        break
    except Exception as e:  # noqa: BLE001
        notes.append(f"TikTok search error: {str(e)[:160]}")

    if not reels:
        notes.append("TikTok: no results (tikwm may be down/rate-limited; set APIFY_TOKEN for "
                     "robust keyword search).")
    return backfill_publishing_meta(reels)


def _cli() -> int:
    ap = argparse.ArgumentParser(description="TikTok reel discovery (standalone)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic")
    g.add_argument("--business")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--sort", default="views")
    args = ap.parse_args()
    query = args.topic or args.business
    match_type = "topic" if args.topic else "business"
    notes: list[str] = []
    reels = search(query, match_type=match_type, limit=args.limit, sort=args.sort, notes=notes)
    print(json.dumps({"notes": notes, "count": len(reels),
                       "reels": [r.to_dict() for r in reels]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
