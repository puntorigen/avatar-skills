#!/usr/bin/env python3
"""
Facebook reel/video discovery -- the surface with NO free anonymous path.

Unlike the other three platforms, Facebook has no usable free discovery engine:
  - yt-dlp's Facebook extractor only handles INDIVIDUAL video/watch/reel URLs;
    it returns "Unsupported URL" for a Page or its /videos tab, so it cannot
    LIST a page's videos.
  - There is no anonymous JSON endpoint comparable to tikwm (TikTok) or
    web_profile_info (Instagram); the Graph API needs an app token + review, and
    facebook.com/search/videos requires login.

So discovery here is Apify-gated:
  - Paid path (robust): APIFY_TOKEN -> providers/apify.facebook_search
        topic     -> keyword search
        business  -> the Page's recent videos/reels (+ keyword search for mentions)
  - No token -> degrade to [] with a clear note (we do not guess).

To DOWNLOAD a *known* Facebook video URL (with no discovery), use the dedicated
`facebook-videos` skill (yt-dlp + ffmpeg, --cookies-from-browser for login walls).
discover.py's --download-top also pulls Facebook winners via yt-dlp once their
URLs are known.

Standalone:
    python3 search_facebook.py --business "24 Horas" --limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from _common import Reel, detect_credentials


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

    if apify_token:
        try:
            from providers import apify

            dicts = apify.facebook_search(query, limit * 2, apify_token, match_type=match_type)
            if dicts:
                return [Reel.from_dict(d) for d in dicts][:limit]
            notes.append("Facebook: Apify returned no items.")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Facebook Apify failed ({str(e)[:140]}).")

    # No reliable free anonymous path exists for Facebook discovery.
    notes.append(
        "Facebook discovery requires APIFY_TOKEN (no free anonymous search/listing: yt-dlp "
        "can't list a Page, and Graph search needs login). To pull a *known* Facebook video "
        "URL, use the facebook-videos skill; --download-top fetches discovered FB winners."
    )
    return []


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Facebook reel discovery (standalone)")
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
