#!/usr/bin/env python3
"""
Optional Apify provider (PAID) for robust TikTok keyword search and Instagram
topic/profile discovery -- the two surfaces with no reliable free anonymous path.

Gated on APIFY_TOKEN. Returns lists of plain dicts using the same field names as
the `Reel` dataclass (the caller maps them with Reel.from_dict), so this module
stays stdlib-only and free of a _common import.

Uses the synchronous run endpoint:
    POST https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token=...

Actor field shapes vary by version, so every mapping is defensive (.get with
multiple key fallbacks). Override the default actors via env if you prefer others:
    APIFY_TIKTOK_ACTOR     (default: clockworks~tiktok-scraper)
    APIFY_IG_ACTOR         (default: apify~instagram-scraper)
    APIFY_FACEBOOK_ACTOR   (default: apify~facebook-search-scraper)
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Optional

_BASE = "https://api.apify.com/v2/acts"
_UA = "reel-discovery/1.0"

DEFAULT_TIKTOK_ACTOR = os.environ.get("APIFY_TIKTOK_ACTOR", "clockworks~tiktok-scraper")
DEFAULT_IG_ACTOR = os.environ.get("APIFY_IG_ACTOR", "apify~instagram-scraper")
DEFAULT_FB_ACTOR = os.environ.get("APIFY_FACEBOOK_ACTOR", "apify~facebook-search-scraper")


def available(token: Optional[str]) -> bool:
    return bool(token)


def _run_actor(actor: str, run_input: dict[str, Any], token: str, timeout: int = 300) -> list[dict]:
    url = f"{_BASE}/{actor}/run-sync-get-dataset-items?token={token}"
    body = json.dumps(run_input).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    data = json.loads(raw) if raw else []
    return data if isinstance(data, list) else data.get("items", [])


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if "." in k:
            cur: Any = d
            for part in k.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
                if cur is None:
                    break
            if cur is not None:
                return cur
        elif d.get(k) is not None:
            return d[k]
    return None


# --------------------------------------------------------------------------- #
# TikTok
# --------------------------------------------------------------------------- #
def tiktok_search(query: str, limit: int, token: str, *, match_type: str = "topic") -> list[dict]:
    run_input: dict[str, Any] = {"resultsPerPage": limit, "shouldDownloadVideos": False,
                                 "shouldDownloadCovers": False}
    if match_type in ("business", "handle"):
        run_input["profiles"] = [query.lstrip("@")]
    else:
        run_input["searchQueries"] = [query]
    items = _run_actor(DEFAULT_TIKTOK_ACTOR, run_input, token)
    out: list[dict] = []
    for it in items:
        vid = str(_first(it, "id", "videoId", "awemeId") or "")
        author = _first(it, "authorMeta.name", "authorMeta.nickName", "authorName") or ""
        out.append(
            {
                "platform": "tiktok",
                "video_id": vid,
                "url": _first(it, "webVideoUrl", "videoUrl", "url")
                or (f"https://www.tiktok.com/@{author}/video/{vid}" if author and vid else ""),
                "author": author,
                "title": _first(it, "text", "title", "desc") or "",
                "views": _first(it, "playCount", "diggCount.play"),
                "likes": _first(it, "diggCount", "likesCount"),
                "comments": _first(it, "commentCount", "comments"),
                "shares": _first(it, "shareCount", "shares"),
                "published_at": _first(it, "createTimeISO", "createTime"),
                "duration_s": _first(it, "videoMeta.duration", "duration"),
                "thumbnail": _first(it, "videoMeta.coverUrl", "covers.default", "cover"),
                "metadata": {
                    "music_title": _first(it, "musicMeta.musicName", "musicMeta.title"),
                    "music_author": _first(it, "musicMeta.musicAuthor", "musicMeta.authorName"),
                    "music_original": _first(it, "musicMeta.musicOriginal"),
                    "region": _first(it, "locationCreated", "region"),
                    "saves": _first(it, "collectCount", "bookmarkCount"),
                },
                "query": query,
                "match_type": match_type,
                "source": "apify-tiktok",
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Instagram
# --------------------------------------------------------------------------- #
def instagram_search(query: str, limit: int, token: str, *, match_type: str = "topic") -> list[dict]:
    run_input: dict[str, Any] = {"resultsLimit": limit, "resultsType": "posts"}
    if match_type in ("business", "handle"):
        run_input["search"] = query.lstrip("@")
        run_input["searchType"] = "user"
        run_input["directUrls"] = [f"https://www.instagram.com/{query.lstrip('@')}/"]
    else:
        run_input["search"] = query.lstrip("#")
        run_input["searchType"] = "hashtag"
        run_input["directUrls"] = [f"https://www.instagram.com/explore/tags/{query.lstrip('#')}/"]
    items = _run_actor(DEFAULT_IG_ACTOR, run_input, token)
    out: list[dict] = []
    for it in items:
        if it.get("type") and it.get("type") not in ("Video", "video", "Sidecar"):
            continue
        sc = _first(it, "shortCode", "shortcode", "code") or ""
        out.append(
            {
                "platform": "instagram",
                "video_id": sc,
                "url": _first(it, "url") or (f"https://www.instagram.com/reel/{sc}/" if sc else ""),
                "author": _first(it, "ownerUsername", "ownerFullName", "owner.username") or "",
                "title": _first(it, "caption", "edge_media_to_caption") or "",
                "views": _first(it, "videoViewCount", "videoPlayCount", "viewsCount"),
                "likes": _first(it, "likesCount", "likeCount"),
                "comments": _first(it, "commentsCount", "commentCount"),
                "shares": None,
                "published_at": _first(it, "timestamp", "takenAtTimestamp"),
                "duration_s": _first(it, "videoDuration", "duration"),
                "thumbnail": _first(it, "displayUrl", "thumbnailUrl"),
                "media_url": _first(it, "videoUrl", "videoUrlBackup"),
                "metadata": {
                    "product_type": _first(it, "productType", "type"),
                },
                "query": query,
                "match_type": match_type,
                "source": "apify-instagram",
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Facebook
# --------------------------------------------------------------------------- #
def _fb_url_for(it: dict, vid: str) -> str:
    url = _first(it, "url", "postUrl", "videoUrl", "topLevelUrl", "facebookUrl", "link")
    if url:
        return str(url)
    return f"https://www.facebook.com/watch/?v={vid}" if vid.isdigit() else ""


def facebook_search(query: str, limit: int, token: str, *, match_type: str = "topic") -> list[dict]:
    """Facebook discovery via Apify. Actor input/output schemas drift a lot between
    actors and versions, so input keys are sent broadly and outputs mapped
    defensively. If results look wrong, set APIFY_FACEBOOK_ACTOR to an actor you
    trust and adjust the mapping below."""
    run_input: dict[str, Any] = {"resultsLimit": limit, "maxItems": limit, "maxPosts": limit}
    if match_type in ("business", "handle"):
        handle = query.lstrip("@").strip()
        page = handle if handle.startswith("http") else f"https://www.facebook.com/{handle}"
        run_input["startUrls"] = [{"url": page}]
        run_input["directUrls"] = [page]
    else:
        run_input["query"] = query
        run_input["search"] = query
        run_input["searchQueries"] = [query]
    items = _run_actor(DEFAULT_FB_ACTOR, run_input, token)
    out: list[dict] = []
    for it in items:
        # Keep only video-bearing posts when the actor flags media type.
        mtype = _first(it, "type", "mediaType", "postType")
        if mtype and str(mtype).lower() not in ("video", "reel", "watch", "videos"):
            if not _first(it, "videoUrl", "videoViewCount", "viewsCount", "playCount"):
                continue
        vid = str(_first(it, "videoId", "id", "postId", "facebookId") or "")
        author = _first(it, "pageName", "authorName", "user.name", "pageInfo.name", "ownerName") or ""
        out.append(
            {
                "platform": "facebook",
                "video_id": vid,
                "url": _fb_url_for(it, vid),
                "author": author,
                "title": _first(it, "text", "message", "caption", "title", "description") or "",
                "views": _first(it, "videoViewCount", "viewsCount", "playCount", "views", "viewCount"),
                "likes": _first(it, "likesCount", "likes", "reactionsCount", "likeCount"),
                "comments": _first(it, "commentsCount", "comments", "commentCount"),
                "shares": _first(it, "sharesCount", "shares", "shareCount", "reshareCount"),
                "published_at": _first(it, "time", "timestamp", "date", "publishedTime", "createTime"),
                "duration_s": _first(it, "duration", "videoLength", "videoDuration", "length"),
                "thumbnail": _first(it, "thumbnail", "thumbnailUrl", "previewImage", "imageUrl"),
                "media_url": _first(it, "videoUrl", "videoHdUrl", "videoSdUrl"),
                "query": query,
                "match_type": match_type,
                "source": "apify-facebook",
            }
        )
    return out
