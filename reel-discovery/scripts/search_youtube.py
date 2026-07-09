#!/usr/bin/env python3
"""
YouTube reel/short discovery.

Primary: YouTube Data API v3 (search.list -> videos.list) for real keyword
search + exact view/like/comment counts. Needs YT_API_KEY (free Google Cloud
key, 10k units/day; search.list=100 units, videos.list=1 unit).

Fallback (no key): `yt-dlp "ytsearchN:<query>"` with full extraction, which
still yields view_count/like_count/duration per item.

Can be run standalone for debugging:
    python3 search_youtube.py --topic "ai tools" --limit 15
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
from typing import Any, Optional

from _common import (
    Reel,
    RateLimiter,
    detect_credentials,
    extract_hashtags,
    http_json,
    parse_iso8601_duration,
    qs,
    to_int,
    to_iso,
)

API = "https://www.googleapis.com/youtube/v3"
_rl = RateLimiter(per_sec=5.0)  # the API is generous; just avoid bursts
_CATEGORY_CACHE: dict[str, dict[str, str]] = {}  # region -> {categoryId: title}


def _order_for(sort: str) -> str:
    if sort in ("views", "velocity"):
        return "viewCount"
    if sort == "recent":
        return "date"
    return "relevance"


def _video_duration_param(max_duration: Optional[int]) -> str:
    if max_duration is None:
        return "any"
    if max_duration <= 240:
        return "short"  # < 4 min (best proxy for Shorts/reels)
    if max_duration <= 1200:
        return "medium"
    return "any"


def _published_after(since_days: Optional[int]) -> Optional[str]:
    if not since_days:
        return None
    from datetime import timedelta

    from _common import now_utc

    return (now_utc() - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Data API path
# --------------------------------------------------------------------------- #
def _api_search_ids(
    api_key: str,
    *,
    q: Optional[str] = None,
    channel_id: Optional[str] = None,
    order: str = "relevance",
    region: Optional[str] = None,
    lang: Optional[str] = None,
    duration: str = "any",
    published_after: Optional[str] = None,
    max_results: int = 50,
) -> list[str]:
    _rl.wait()
    url = f"{API}/search?" + qs(
        {
            "key": api_key,
            "part": "snippet",
            "type": "video",
            "q": q,
            "channelId": channel_id,
            "order": order,
            "regionCode": region,
            "relevanceLanguage": lang,
            "videoDuration": duration,
            "publishedAfter": published_after,
            "maxResults": min(max_results, 50),
        }
    )
    data = http_json(url) or {}
    return [
        it["id"]["videoId"]
        for it in data.get("items", [])
        if it.get("id", {}).get("videoId")
    ]


def _api_resolve_channel(api_key: str, business: str) -> Optional[str]:
    _rl.wait()
    url = f"{API}/search?" + qs(
        {"key": api_key, "part": "snippet", "type": "channel", "q": business, "maxResults": 1}
    )
    data = http_json(url) or {}
    items = data.get("items", [])
    return items[0]["id"]["channelId"] if items else None


def _api_video_categories(api_key: str, region: Optional[str]) -> dict[str, str]:
    """Map categoryId -> human title for a region (cached). 1 quota unit, best-effort."""
    key = (region or "US").upper()
    if key in _CATEGORY_CACHE:
        return _CATEGORY_CACHE[key]
    mapping: dict[str, str] = {}
    try:
        _rl.wait()
        url = f"{API}/videoCategories?" + qs(
            {"key": api_key, "part": "snippet", "regionCode": key}
        )
        data = http_json(url) or {}
        for it in data.get("items", []):
            cid = it.get("id")
            title = (it.get("snippet") or {}).get("title")
            if cid and title:
                mapping[str(cid)] = title
    except Exception:  # noqa: BLE001 - enrichment is optional, never fatal
        mapping = {}
    _CATEGORY_CACHE[key] = mapping
    return mapping


def _api_channels(api_key: str, channel_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch channel-level publishing context (subscribers, size, country). Best-effort."""
    out: dict[str, dict[str, Any]] = {}
    ids = [c for c in dict.fromkeys(channel_ids) if c]
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        try:
            _rl.wait()
            url = f"{API}/channels?" + qs(
                {"key": api_key, "part": "snippet,statistics", "id": ",".join(batch)}
            )
            data = http_json(url) or {}
            for it in data.get("items", []):
                st = it.get("statistics", {})
                sn = it.get("snippet", {})
                out[it.get("id", "")] = {
                    "subscribers": (
                        None if st.get("hiddenSubscriberCount") else to_int(st.get("subscriberCount"))
                    ),
                    "channel_video_count": to_int(st.get("videoCount")),
                    "channel_view_count": to_int(st.get("viewCount")),
                    "channel_country": sn.get("country"),
                    "channel_created_at": to_iso(sn.get("publishedAt")),
                }
        except Exception:  # noqa: BLE001 - enrichment is optional, never fatal
            continue
    return out


def _pick_thumbnails(thumbs: Optional[dict[str, Any]]) -> Optional[dict[str, str]]:
    thumbs = thumbs or {}
    out: dict[str, str] = {}
    for size in ("maxres", "standard", "high", "medium", "default"):
        u = (thumbs.get(size) or {}).get("url")
        if u:
            out[size] = u
    return out or None


def _api_hydrate(
    api_key: str,
    video_ids: list[str],
    query: str,
    match_type: str,
    region: Optional[str] = None,
) -> list[Reel]:
    cat_map = _api_video_categories(api_key, region)
    reels: list[Reel] = []
    channel_ids: list[str] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        _rl.wait()
        url = f"{API}/videos?" + qs(
            {
                "key": api_key,
                "part": "snippet,statistics,contentDetails,status,topicDetails",
                "id": ",".join(batch),
            }
        )
        data = http_json(url) or {}
        for it in data.get("items", []):
            stats = it.get("statistics", {})
            snip = it.get("snippet", {})
            content = it.get("contentDetails", {})
            status = it.get("status", {})
            topic = it.get("topicDetails", {})
            vid = it.get("id", "")
            title = snip.get("title", "")
            desc = snip.get("description", "") or ""
            tags = snip.get("tags") or None
            cat_id = snip.get("categoryId")
            channel_id = snip.get("channelId")
            if channel_id:
                channel_ids.append(channel_id)
            topic_cats = [
                u.rsplit("/", 1)[-1] for u in (topic.get("topicCategories") or []) if u
            ] or None
            metadata: dict[str, Any] = {
                "category_id": cat_id,
                "default_language": snip.get("defaultLanguage"),
                "default_audio_language": snip.get("defaultAudioLanguage"),
                "live_broadcast_content": snip.get("liveBroadcastContent"),
                "definition": content.get("definition"),
                "dimension": content.get("dimension"),
                "projection": content.get("projection"),
                "caption": content.get("caption") == "true",
                "licensed_content": content.get("licensedContent"),
                "license": status.get("license"),
                "privacy_status": status.get("privacyStatus"),
                "embeddable": status.get("embeddable"),
                "made_for_kids": status.get("madeForKids"),
                "topic_categories": topic_cats,
                "channel_id": channel_id,
                "tags_count": len(tags) if tags else 0,
                "description_length": len(desc),
                "thumbnails": _pick_thumbnails(snip.get("thumbnails")),
            }
            reels.append(
                Reel(
                    platform="youtube",
                    video_id=vid,
                    url=f"https://www.youtube.com/watch?v={vid}",
                    author=snip.get("channelTitle", ""),
                    title=title,
                    views=to_int(stats.get("viewCount")),
                    likes=to_int(stats.get("likeCount")),
                    comments=to_int(stats.get("commentCount")),
                    shares=None,
                    published_at=to_iso(snip.get("publishedAt")),
                    duration_s=parse_iso8601_duration(content.get("duration")),
                    thumbnail=(snip.get("thumbnails", {}).get("high") or {}).get("url"),
                    description=desc or None,
                    tags=tags,
                    hashtags=extract_hashtags(title, desc) or None,
                    category=cat_map.get(str(cat_id)) if cat_id else None,
                    language=snip.get("defaultAudioLanguage") or snip.get("defaultLanguage"),
                    metadata=metadata,
                    query=query,
                    match_type=match_type,
                    source="youtube-api",
                )
            )
    if channel_ids:
        ch_info = _api_channels(api_key, channel_ids)
        for r in reels:
            cid = (r.metadata or {}).get("channel_id")
            info = ch_info.get(cid) if cid else None
            if info and r.metadata is not None:
                r.metadata.update(info)
    return reels


# --------------------------------------------------------------------------- #
# yt-dlp fallback
# --------------------------------------------------------------------------- #
def _ytsearch_fallback(query: str, match_type: str, limit: int) -> list[Reel]:
    n = min(max(limit * 2, 10), 25)  # full extraction is slow; keep modest
    cmd = ["yt-dlp", f"ytsearch{n}:{query}", "-J", "--no-warnings"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(out.stderr.strip()[-300:] or "yt-dlp ytsearch failed")
    data = json.loads(out.stdout)
    reels: list[Reel] = []
    for e in data.get("entries", []):
        if not e:
            continue
        vid = str(e.get("id") or "")
        title = (e.get("title") or "").strip()
        desc = e.get("description") or ""
        tags = e.get("tags") or None
        cats = e.get("categories") or None
        height = e.get("height")
        metadata: dict[str, Any] = {
            "channel_id": e.get("channel_id"),
            "subscribers": to_int(e.get("channel_follower_count")),
            "categories": cats,
            "definition": ("hd" if (height or 0) >= 720 else "sd") if height else None,
            "width": e.get("width"),
            "height": height,
            "fps": e.get("fps"),
            "availability": e.get("availability"),
            "live_status": e.get("live_status"),
            "age_limit": e.get("age_limit"),
            "tags_count": len(tags) if tags else 0,
            "description_length": len(desc),
        }
        reels.append(
            Reel(
                platform="youtube",
                video_id=vid,
                url=e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
                author=e.get("channel") or e.get("uploader") or "",
                title=title,
                views=to_int(e.get("view_count")),
                likes=to_int(e.get("like_count")),
                comments=to_int(e.get("comment_count")),
                published_at=to_iso(e.get("timestamp") or e.get("upload_date")),
                duration_s=e.get("duration"),
                thumbnail=e.get("thumbnail"),
                description=desc or None,
                tags=tags,
                hashtags=extract_hashtags(title, desc) or None,
                category=cats[0] if cats else None,
                language=e.get("language"),
                metadata=metadata,
                query=query,
                match_type=match_type,
                source="yt-dlp",
            )
        )
    return reels


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #
def search(
    query: str,
    *,
    match_type: str = "topic",
    limit: int = 15,
    sort: str = "views",
    region: Optional[str] = None,
    lang: Optional[str] = None,
    since_days: Optional[int] = None,
    max_duration: Optional[int] = None,
    api_key: Optional[str] = None,
    notes: Optional[list[str]] = None,
    **_ignored: Any,
) -> list[Reel]:
    notes = notes if notes is not None else []
    api_key = api_key or detect_credentials()["yt_api_key"]

    if not api_key:
        notes.append("YouTube: no YT_API_KEY -> using slower yt-dlp ytsearch fallback.")
        try:
            return _ytsearch_fallback(query, match_type, limit)
        except Exception as e:  # noqa: BLE001
            notes.append(f"YouTube yt-dlp fallback failed: {str(e)[:160]}")
            return []

    try:
        order = _order_for(sort)
        duration = _video_duration_param(max_duration)
        published_after = _published_after(since_days)
        ids: list[str] = []
        if match_type in ("business", "handle"):
            channel_id = _api_resolve_channel(api_key, query)
            if channel_id:
                ids += _api_search_ids(
                    api_key, channel_id=channel_id, order=order, duration=duration,
                    published_after=published_after, max_results=50,
                )
        # Keyword search always runs (captures third-party reels for a business).
        ids += _api_search_ids(
            api_key, q=query, order=order, region=region, lang=lang, duration=duration,
            published_after=published_after, max_results=50,
        )
        ids = list(dict.fromkeys(ids))  # de-dupe, keep order
        if not ids:
            return []
        return _api_hydrate(api_key, ids, query, match_type, region=region)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:300] if hasattr(e, "read") else ""
        notes.append(f"YouTube Data API HTTP {e.code} ({body}); trying yt-dlp fallback.")
        try:
            return _ytsearch_fallback(query, match_type, limit)
        except Exception as e2:  # noqa: BLE001
            notes.append(f"YouTube yt-dlp fallback failed: {str(e2)[:160]}")
            return []
    except Exception as e:  # noqa: BLE001
        notes.append(f"YouTube search failed: {str(e)[:160]}")
        return []


def _cli() -> int:
    ap = argparse.ArgumentParser(description="YouTube reel discovery (standalone)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic")
    g.add_argument("--business")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--sort", default="views")
    ap.add_argument("--region")
    ap.add_argument("--lang")
    ap.add_argument("--since", type=int, dest="since_days")
    ap.add_argument("--max-duration", type=int)
    args = ap.parse_args()
    query = args.topic or args.business
    match_type = "topic" if args.topic else "business"
    notes: list[str] = []
    reels = search(
        query, match_type=match_type, limit=args.limit, sort=args.sort,
        region=args.region, lang=args.lang, since_days=args.since_days,
        max_duration=args.max_duration, notes=notes,
    )
    print(json.dumps({"notes": notes, "count": len(reels),
                       "reels": [r.to_dict() for r in reels]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
