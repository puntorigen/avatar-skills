#!/usr/bin/env python3
"""
reel-discovery orchestrator.

Given a --topic (keyword/hashtag) or --business (brand name/handle), search
YouTube, TikTok and Instagram for top-performing public reels, normalize every
hit into one schema, rank by views/engagement/velocity/recency, and write a
unified manifest (results.json + results.md) under discovery/<slug>/.

Optionally --download-top N grabs the top N MP4s into discovery/<slug>/videos/
(yt-dlp for YouTube/TikTok with tikwm fallback; direct media URL for Instagram),
ready for the video-scene-analysis -> reel-restyle pipeline.

Examples:
    python3 discover.py --topic "ai productivity" --limit 30 --sort velocity
    python3 discover.py --business nike --platforms youtube,tiktok --download-top 5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import search_facebook
import search_instagram
import search_tiktok
import search_youtube
from _common import (
    UA,
    VALID_PLATFORMS,
    VALID_SORTS,
    Reel,
    detect_credentials,
    now_utc,
    rank,
    slugify,
    write_outputs,
)

SEARCHERS = {
    "youtube": search_youtube.search,
    "tiktok": search_tiktok.search,
    "instagram": search_instagram.search,
    "facebook": search_facebook.search,
}


# --------------------------------------------------------------------------- #
# Download (top N)
# --------------------------------------------------------------------------- #
def _ytdlp_download(url: str, dest_base: Path, fmt: str = "bv*+ba/b") -> Path:
    cmd = ["yt-dlp", url, "-f", fmt, "--merge-output-format", "mp4",
           "-o", f"{dest_base}.%(ext)s",
           "--no-progress", "--no-warnings", "--no-playlist"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    media = [f for f in dest_base.parent.glob(dest_base.name + ".*")
             if f.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")]
    if out.returncode != 0 or not media:
        raise RuntimeError(out.stderr.strip()[-300:] or "yt-dlp download failed")
    return media[0]


def _tikwm_download(video_url: str, dest_base: Path) -> Path:
    api = f"https://www.tikwm.com/api/?url={urllib.parse.quote(video_url, safe='')}&hd=1"
    req = urllib.request.Request(api, headers={"User-Agent": UA, "Referer": "https://www.tikwm.com/"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = json.loads(resp.read().decode("utf-8", "ignore"))
    data = (raw or {}).get("data") or {}
    play = data.get("hdplay") or data.get("play") or data.get("wmplay")
    if not play:
        raise RuntimeError("tikwm: no playable URL")
    if play.startswith("/"):
        play = "https://www.tikwm.com" + play
    return _direct_download(play, dest_base.with_suffix(".mp4"),
                            referer="https://www.tikwm.com/")


def _direct_download(url: str, dest: Path, referer: str = "") -> Path:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def download_top(reels: list[Reel], videos_dir: Path, top_n: int) -> list[dict]:
    videos_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for i, r in enumerate(reels[:top_n]):
        base = videos_dir / f"{i + 1:02d}_{r.platform}_{r.video_id}"
        entry = {"rank": i + 1, "platform": r.platform, "url": r.url, "video_id": r.video_id}
        try:
            if r.platform == "youtube":
                f = _ytdlp_download(r.url, base)
            elif r.platform == "tiktok":
                try:
                    f = _ytdlp_download(r.url, base)
                except Exception:
                    f = _tikwm_download(r.url, base)
            elif r.platform == "facebook":
                # yt-dlp handles individual FB video/watch/reel URLs; fall back to
                # a direct media_url if Apify supplied one. Prefer Facebook's `hd`
                # progressive -- a naive bv*+ba grabs a smaller height-tagged DASH
                # stream instead (same quirk handled by the facebook-videos skill).
                try:
                    f = _ytdlp_download(r.url, base, fmt="hd/b/bv*+ba/sd")
                except Exception:
                    if r.media_url:
                        f = _direct_download(r.media_url, base.with_suffix(".mp4"),
                                             referer="https://www.facebook.com/")
                    else:
                        raise
            else:  # instagram
                if r.media_url:
                    f = _direct_download(r.media_url, base.with_suffix(".mp4"),
                                         referer="https://www.instagram.com/")
                else:
                    f = _ytdlp_download(r.url, base)  # usually 401; best effort
            entry["file"] = f.name
            entry["bytes"] = f.stat().st_size
            print(f"  [{i + 1}] {r.platform} {r.video_id}: downloaded {f.name}")
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)[:200]
            print(f"  [{i + 1}] {r.platform} {r.video_id}: FAILED ({str(e)[:120]})", file=sys.stderr)
        manifest.append(entry)
    (videos_dir / "download_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    return manifest


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Discover + rank top public reels by topic or business")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic", help="Free-text topic / keyword / hashtag")
    g.add_argument("--business", help="Brand name or @handle")
    ap.add_argument("--platforms", default="youtube,tiktok,instagram",
                    help="Comma list of: youtube,tiktok,instagram")
    ap.add_argument("--limit", type=int, default=30, help="Total ranked results to keep")
    ap.add_argument("--per-platform", type=int, default=15, help="Cap per platform before merge")
    ap.add_argument("--sort", choices=list(VALID_SORTS), default="views")
    ap.add_argument("--min-views", type=int, default=None)
    ap.add_argument("--since", type=int, dest="since_days", default=None, help="Only last N days")
    ap.add_argument("--max-duration", type=int, default=None, help="Max seconds (reels: e.g. 180)")
    ap.add_argument("--region", default=None, help="YouTube regionCode (e.g. US, CL)")
    ap.add_argument("--lang", default=None, help="YouTube relevanceLanguage (e.g. en, es)")
    ap.add_argument("--out-dir", type=Path, default=Path("discovery"))
    ap.add_argument("--slug", default=None, help="Override output subfolder name")
    ap.add_argument("--download-top", type=int, default=0, help="Download top N as MP4")
    ap.add_argument("--timezone", default="America/Santiago")
    ap.add_argument("--yt-api-key", default=None)
    ap.add_argument("--apify-token", default=None)
    args = ap.parse_args()

    query = (args.topic or args.business).strip()
    match_type = "topic" if args.topic else "business"
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    bad = [p for p in platforms if p not in VALID_PLATFORMS]
    if bad:
        ap.error(f"Unknown platform(s): {bad}. Choose from {VALID_PLATFORMS}.")

    creds = detect_credentials()
    yt_key = args.yt_api_key or creds["yt_api_key"]
    apify_token = args.apify_token or creds["apify_token"]
    notes: list[str] = []
    if not yt_key and "youtube" in platforms:
        notes.append("YT_API_KEY not set -> YouTube uses the slower yt-dlp fallback.")
    if not apify_token:
        notes.append("APIFY_TOKEN not set -> TikTok keyword + Instagram topic run on free "
                     "best-effort sources only.")

    print(f"Discovering '{query}' ({match_type}) across {platforms} ...")
    all_reels: list[Reel] = []
    counts: dict[str, int] = {}
    for p in platforms:
        try:
            found = SEARCHERS[p](
                query,
                match_type=match_type,
                limit=args.per_platform,
                sort=args.sort,
                region=args.region,
                lang=args.lang,
                since_days=args.since_days,
                max_duration=args.max_duration,
                api_key=yt_key,
                apify_token=apify_token,
                notes=notes,
            )
        except TypeError:
            # searcher with a narrower signature (defensive)
            found = SEARCHERS[p](query, match_type=match_type, limit=args.per_platform, notes=notes)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{p}: searcher crashed ({str(e)[:160]})")
            found = []
        counts[p] = len(found)
        print(f"  {p}: {len(found)} raw hit(s)")
        all_reels += found

    ranked = rank(
        all_reels,
        sort=args.sort,
        limit=args.limit,
        per_platform=args.per_platform,
        min_views=args.min_views,
        since_days=args.since_days,
        max_duration=args.max_duration,
    )

    slug = args.slug or slugify(query)
    out_dir = args.out_dir / slug
    meta = {
        "query": query,
        "match_type": match_type,
        "platforms": platforms,
        "sort": args.sort,
        "filters": {
            "min_views": args.min_views,
            "since_days": args.since_days,
            "max_duration": args.max_duration,
            "region": args.region,
            "lang": args.lang,
        },
        "raw_counts": counts,
        "credentials": {"yt_api_key": bool(yt_key), "apify_token": bool(apify_token)},
        "generated_at": now_utc().isoformat(),
        "notes": notes,
    }
    json_path, md_path = write_outputs(ranked, out_dir, meta)

    print(f"\nRanked {len(ranked)} reel(s) (sort={args.sort}).")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    for i, r in enumerate(ranked[:10]):
        v = f"{r.views:,}" if r.views else (f"~{r.likes:,}L" if r.likes else "?")
        print(f"  {i + 1:2d}. [{r.platform}] {v} views  {(r.title or '')[:54]}  {r.url}")
    if notes:
        print("\nNotes:")
        for n in notes:
            print(f"  - {n}")

    if args.download_top > 0 and ranked:
        print(f"\nDownloading top {min(args.download_top, len(ranked))} to {out_dir / 'videos'} ...")
        download_top(ranked, out_dir / "videos", args.download_top)
        print(f"  Hand off to: video-scene-analysis on {out_dir / 'videos'}/*.mp4")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
