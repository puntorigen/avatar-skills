#!/usr/bin/env python3
"""
Download public TikTok videos with upload-datetime filenames.

Unlike Instagram, TikTok does not 401 anonymous tooling, so this skill needs
no browser mirror. It uses yt-dlp as the primary engine (listing + download)
and the tikwm.com public API as a no-watermark fallback for any item yt-dlp
fails on.

Accepts a profile URL, a single video URL, or a short link (vm./vt.tiktok.com),
or a pre-fetched listing JSON (yt-dlp --flat-playlist -J output).

Each video is saved as YYYY-MM-DD_HH-MM-SS.mp4 in the chosen timezone, using
the exact upload timestamp (yt-dlp `timestamp` or tikwm `create_time`).

Usage:
    python3 download_profile_videos.py \\
        --url "https://www.tiktok.com/@username" \\
        --output-dir out/tiktok \\
        [--engine hybrid|ytdlp|tikwm] \\
        [--timezone America/Santiago] \\
        [--max 50] \\
        [--manifest out/tiktok/videos_manifest.json]

    # or from a pre-fetched listing:
    yt-dlp --flat-playlist -J "https://www.tiktok.com/@username" > listing.json
    python3 download_profile_videos.py --listing-json listing.json --output-dir out/tiktok
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
TIKWM_VIDEO = "https://www.tikwm.com/api/?url={url}&hd=1"
TIKWM_POSTS = "https://www.tikwm.com/api/user/posts?unique_id={handle}&count=34&cursor={cursor}"
VIDEO_URL_RE = re.compile(r"tiktok\.com/@[^/]+/(video|photo)/(\d+)")
SHORT_HOST_RE = re.compile(r"^https?://(vm|vt|m)\.tiktok\.com/", re.I)


# --------------------------------------------------------------------------- #
# URL helpers
# --------------------------------------------------------------------------- #
def resolve_short_url(url: str, timeout: int = 20) -> str:
    """Follow redirects for vm./vt. short links to the canonical video URL."""
    if not SHORT_HOST_RE.match(url):
        return url
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl() or url
    except (urllib.error.URLError, ValueError):
        return url


def handle_from_url(url: str) -> str | None:
    m = re.search(r"tiktok\.com/@([^/?#]+)", url)
    return m.group(1) if m else None


def is_photo_url(url: str) -> bool:
    m = VIDEO_URL_RE.search(url or "")
    return bool(m and m.group(1) == "photo")


def canonical_video_url(handle: str, vid: str) -> str:
    return f"https://www.tiktok.com/@{handle}/video/{vid}"


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #
def ytdlp_list(url: str, limit: int | None) -> list[dict]:
    """Flat-playlist listing via yt-dlp. Works for profile or single video."""
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--no-warnings"]
    if limit:
        cmd += ["--playlist-end", str(limit)]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(out.stderr.strip()[:500] or "yt-dlp listing failed")
    data = json.loads(out.stdout)
    entries = data.get("entries")
    if entries is None:  # single video
        entries = [data]
    items: list[dict] = []
    for e in entries:
        if not e:
            continue
        vid = str(e.get("id") or "")
        webpage = e.get("url") or e.get("webpage_url") or ""
        items.append(
            {
                "id": vid,
                "url": webpage,
                "title": (e.get("title") or "").strip(),
                "timestamp": e.get("timestamp"),  # often null in flat mode
            }
        )
    return items


def tikwm_list(handle: str, limit: int | None) -> list[dict]:
    """Profile listing via tikwm user/posts (fallback when yt-dlp listing fails)."""
    items: list[dict] = []
    cursor = "0"
    for _ in range(40):  # safety cap on pagination
        raw = _http_json(TIKWM_POSTS.format(handle=handle, cursor=cursor))
        data = (raw or {}).get("data") or {}
        for v in data.get("videos", []):
            vid = str(v.get("video_id") or v.get("id") or "")
            if not vid:
                continue
            items.append(
                {
                    "id": vid,
                    "url": canonical_video_url(handle, vid),
                    "title": (v.get("title") or "").strip(),
                    "timestamp": v.get("create_time"),
                }
            )
            if limit and len(items) >= limit:
                return items[:limit]
        if not data.get("hasMore"):
            break
        cursor = str(data.get("cursor") or "0")
        time.sleep(1.0)  # be gentle with tikwm
    return items


def list_videos(url: str, limit: int | None) -> list[dict]:
    try:
        items = ytdlp_list(url, limit)
        if items:
            return items
    except Exception as e:  # noqa: BLE001 - fall back regardless of cause
        print(f"  yt-dlp listing failed ({e}); trying tikwm...", file=sys.stderr)
    handle = handle_from_url(url)
    if not handle:
        raise SystemExit("Could not list videos and no @handle to fall back on.")
    return tikwm_list(handle, limit)


# --------------------------------------------------------------------------- #
# Download engines
# --------------------------------------------------------------------------- #
def _http_json(url: str, timeout: int = 30) -> dict | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://www.tikwm.com/"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _http_download(url: str, dest: Path, timeout: int = 120) -> int:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://www.tikwm.com/"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


def ytdlp_download(url: str, tmp_base: Path) -> tuple[Path, int | None, str]:
    """Download a single video with yt-dlp. Returns (file, timestamp, title)."""
    info_path = tmp_base.with_suffix(".info.json")
    cmd = [
        "yt-dlp",
        url,
        "-f", "bv*+ba/b",
        "-o", f"{tmp_base}.%(ext)s",
        "--write-info-json",
        "--no-progress",
        "--no-warnings",
        "--no-playlist",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    files = sorted(tmp_base.parent.glob(tmp_base.name + ".*"))
    media = [f for f in files if f.suffix not in {".json"} and not f.name.endswith(".info.json")]
    if out.returncode != 0 or not media:
        raise RuntimeError(out.stderr.strip()[-400:] or "yt-dlp download failed")
    ts = title = None
    if info_path.exists():
        info = json.loads(info_path.read_text())
        ts = info.get("timestamp")
        title = (info.get("title") or "").strip()
        info_path.unlink(missing_ok=True)
    return media[0], ts, title or ""


def tikwm_download(url: str, tmp_base: Path) -> tuple[Path, int | None, str]:
    """Download a single video (no watermark) via tikwm. Returns (file, ts, title)."""
    raw = _http_json(TIKWM_VIDEO.format(url=urllib.parse.quote(url, safe="")))
    if not raw or raw.get("code") != 0:
        raise RuntimeError(f"tikwm error: {(raw or {}).get('msg', 'no response')}")
    data = raw["data"]
    play = data.get("hdplay") or data.get("play") or data.get("wmplay")
    if not play:
        raise RuntimeError("tikwm returned no playable URL")
    if play.startswith("/"):
        play = "https://www.tikwm.com" + play
    dest = tmp_base.with_suffix(".mp4")
    _http_download(play, dest)
    return dest, data.get("create_time"), (data.get("title") or "").strip()


def download_one(
    item: dict, tmp_base: Path, engine: str
) -> tuple[Path, int | None, str, str]:
    """Returns (file, timestamp, title, source). Honors engine preference + fallback."""
    url = item["url"]
    if engine == "tikwm":
        f, ts, title = tikwm_download(url, tmp_base)
        return f, ts, title, "tikwm"
    if engine == "ytdlp":
        f, ts, title = ytdlp_download(url, tmp_base)
        return f, ts, title, "ytdlp"
    # hybrid: yt-dlp primary, tikwm fallback
    try:
        f, ts, title = ytdlp_download(url, tmp_base)
        return f, ts, title, "ytdlp"
    except Exception as e:  # noqa: BLE001
        print(f"    yt-dlp failed ({str(e)[:120]}); falling back to tikwm", file=sys.stderr)
        f, ts, title = tikwm_download(url, tmp_base)
        return f, ts, title, "tikwm"


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #
def local_filename(ts: int | None, tz: ZoneInfo, vid: str) -> str:
    if not ts:
        return f"unknown_{vid}"
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz)
    return dt.strftime("%Y-%m-%d_%H-%M-%S")


def dedupe_names(items: list[dict]) -> None:
    seen: dict[str, int] = {}
    for item in items:
        base = item["local"]
        n = seen.get(base, 0) + 1
        seen[base] = n
        item["file"] = f"{base}.mp4" if n == 1 else f"{base}_{n}.mp4"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Download public TikTok videos with datetime names")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="TikTok profile, video, or short URL")
    src.add_argument("--listing-json", type=Path, help="Pre-fetched yt-dlp --flat-playlist -J output")
    ap.add_argument("--output-dir", type=Path, required=True, help="Folder for .mp4 files")
    ap.add_argument("--engine", choices=["hybrid", "ytdlp", "tikwm"], default="hybrid")
    ap.add_argument("--timezone", default="America/Santiago", help="IANA tz for filenames")
    ap.add_argument("--max", type=int, default=None, help="Max videos to download")
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--delay-ms", type=int, default=800, help="Delay between videos")
    ap.add_argument("--include-images", action="store_true", help="Attempt /photo/ posts too")
    args = ap.parse_args()

    tz = ZoneInfo(args.timezone)

    # 1) Build the listing.
    if args.listing_json:
        raw = json.loads(args.listing_json.read_text())
        entries = raw.get("entries", raw) if isinstance(raw, dict) else raw
        if isinstance(raw, dict) and "entries" not in raw:
            entries = [raw]
        videos = [
            {
                "id": str(e.get("id") or ""),
                "url": e.get("url") or e.get("webpage_url") or "",
                "title": (e.get("title") or "").strip(),
                "timestamp": e.get("timestamp"),
            }
            for e in entries
            if e
        ]
    else:
        url = resolve_short_url(args.url.strip())
        print(f"Listing videos for: {url}")
        videos = list_videos(url, args.max)

    if args.max:
        videos = videos[: args.max]
    if not args.include_images:
        videos = [v for v in videos if not is_photo_url(v["url"])]
    if not videos:
        print("No videos found.")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (args.output_dir / "videos_manifest.json")
    print(f"Found {len(videos)} video(s). Engine={args.engine}. Downloading to {args.output_dir}")

    # 2) Download each, capture exact timestamp.
    manifest: list[dict] = []
    tmp_by_id: dict[str, Path] = {}
    for i, item in enumerate(videos):
        vid = item["id"] or f"idx{i}"
        tmp_base = args.output_dir / f".tmp_{vid}"
        try:
            f, ts, title, source = download_one(item, tmp_base, args.engine)
        except Exception as e:  # noqa: BLE001
            print(f"  - {vid}: FAILED ({str(e)[:160]})", file=sys.stderr)
            manifest.append({"id": vid, "url": item["url"], "error": str(e)[:300]})
            continue
        ts = ts or item.get("timestamp")
        local = local_filename(ts, tz, vid)
        tmp_by_id[vid] = f
        manifest.append(
            {
                "id": vid,
                "url": item["url"],
                "title": (title or item.get("title") or "")[:160],
                "timestamp": ts,
                "uploadDate": (
                    datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz).isoformat()
                    if ts else None
                ),
                "source": source,
                "local": local,
            }
        )
        print(f"  - {vid}: ok via {source} ({f.stat().st_size} bytes)")
        if i < len(videos) - 1:
            time.sleep(args.delay_ms / 1000.0)

    # 3) Datetime rename (collisions -> _2, _3).
    ok = [m for m in manifest if "local" in m]
    dedupe_names(ok)
    for item in ok:
        src_path = tmp_by_id[item["id"]]
        dst = args.output_dir / item["file"]
        if dst.exists() and dst.resolve() != src_path.resolve():
            dst.unlink()
        src_path.rename(dst)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    failed = [m for m in manifest if "error" in m]
    print(f"\nDone. {len(ok)} downloaded, {len(failed)} failed -> {args.output_dir}")
    print(f"Manifest: {manifest_path}")
    for item in sorted(ok, key=lambda x: x["local"], reverse=True):
        print(f"  {item['file']}  ({item['source']})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
