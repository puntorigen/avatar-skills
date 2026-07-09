#!/usr/bin/env python3
"""
Download public YouTube videos with upload-datetime filenames.

YouTube is yt-dlp's strongest platform: no browser mirror (Instagram) and no
third-party fallback (TikTok) are needed. This is a single-engine script.
It requires `ffmpeg` to merge YouTube's separate video+audio (DASH) streams.

Accepts a channel URL (@handle, /channel/UC..., /c/..., /user/...), a playlist,
a single video (watch?v=, youtu.be/), or a short (/shorts/) -- or a pre-fetched
listing JSON (yt-dlp --flat-playlist -J output).

A bare channel URL expands to BOTH the /videos and /shorts tabs by default.

Each video is saved as YYYY-MM-DD_HH-MM-SS.mp4 in the chosen timezone, using
the exact upload `timestamp` (from each video's info.json). Videos with only
date precision fall back to YYYY-MM-DD_00-00-00.mp4.

Usage:
    python3 download_channel_videos.py \\
        --url "https://www.youtube.com/@channel" \\
        --output-dir out/youtube \\
        [--max-height 720] \\
        [--timezone America/Santiago] \\
        [--max 50] \\
        [--cookies-from-browser chrome] \\
        [--manifest out/youtube/videos_manifest.json]

    # or from a pre-fetched listing:
    yt-dlp --flat-playlist -J "https://www.youtube.com/@channel/videos" > listing.json
    python3 download_channel_videos.py --listing-json listing.json --output-dir out/youtube
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# A bare channel root looks like one of these (no trailing tab/playlist/video).
CHANNEL_ROOT_RE = re.compile(
    r"^https?://(?:www\.)?youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)/?(?:[?#].*)?$",
    re.I,
)
TAB_SUFFIXES = ("/videos", "/shorts", "/streams", "/featured", "/playlists")


# --------------------------------------------------------------------------- #
# URL normalization
# --------------------------------------------------------------------------- #
def normalize_urls(url: str) -> list[str]:
    """A bare channel URL -> [/videos, /shorts]. Everything else -> [url]."""
    u = url.strip()
    lower = u.lower()
    # Already a tab, playlist, video, or short: use as-is.
    if any(t in lower for t in TAB_SUFFIXES) or "list=" in lower \
            or "watch?" in lower or "/shorts/" in lower or "youtu.be/" in lower:
        return [u]
    m = CHANNEL_ROOT_RE.match(u)
    if m:
        base = f"https://www.youtube.com/{m.group(1)}"
        return [f"{base}/videos", f"{base}/shorts"]
    return [u]


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #
def ytdlp_list(url: str, limit: int | None, cookies: str | None) -> list[dict]:
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--no-warnings", "--ignore-errors"]
    if limit:
        cmd += ["--playlist-end", str(limit)]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if not out.stdout.strip():
        raise RuntimeError(out.stderr.strip()[-400:] or "yt-dlp listing returned nothing")
    data = json.loads(out.stdout)
    entries = data.get("entries")
    if entries is None:  # single video
        entries = [data]
    items: list[dict] = []
    for e in entries:
        if not e:
            continue
        # Nested entries (e.g. channel -> tab -> playlist) can appear; flatten.
        if e.get("entries"):
            for sub in e["entries"]:
                if sub and sub.get("id"):
                    items.append(_entry(sub))
            continue
        if e.get("id"):
            items.append(_entry(e))
    return items


def _entry(e: dict) -> dict:
    vid = str(e.get("id") or "")
    return {
        "id": vid,
        "url": e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
        "title": (e.get("title") or "").strip(),
        "timestamp": e.get("timestamp"),  # usually null in flat mode
    }


def list_videos(url: str, limit: int | None, cookies: str | None) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for u in normalize_urls(url):
        print(f"  listing: {u}")
        try:
            for it in ytdlp_list(u, limit, cookies):
                if it["id"] and it["id"] not in seen:
                    seen.add(it["id"])
                    merged.append(it)
        except Exception as e:  # noqa: BLE001
            print(f"    (skipped: {str(e)[:160]})", file=sys.stderr)
        if limit and len(merged) >= limit:
            return merged[:limit]
    return merged


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def ytdlp_download(
    url: str, tmp_base: Path, max_height: int, cookies: str | None, archive: Path | None
) -> tuple[Path | None, int | None, str | None, str]:
    """Download one video. Returns (file_or_None, timestamp, upload_date, status).

    file is None when the item was skipped via the download archive.
    """
    fmt = (
        f"bv*[height<={max_height}][vcodec^=avc1]+ba[acodec^=mp4a]/"
        f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"
    )
    cmd = [
        "yt-dlp", url,
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", f"{tmp_base}.%(ext)s",
        "--write-info-json",
        "--no-progress", "--no-warnings", "--no-playlist",
    ]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    if archive:
        cmd += ["--download-archive", str(archive)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    info_path = tmp_base.with_suffix(".info.json")
    ts = upload_date = None
    if info_path.exists():
        info = json.loads(info_path.read_text())
        ts = info.get("timestamp")
        upload_date = info.get("upload_date")
        info_path.unlink(missing_ok=True)

    files = sorted(tmp_base.parent.glob(tmp_base.name + ".*"))
    media = [f for f in files if not f.name.endswith(".info.json") and f.suffix != ".json"]
    if media:
        return media[0], ts, upload_date, "ok"
    if archive and "has already been recorded in the archive" in (out.stdout + out.stderr):
        return None, ts, upload_date, "skipped (archive)"
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-400:] or "yt-dlp download failed")
    return None, ts, upload_date, "skipped (archive)"


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #
def local_filename(ts: int | None, upload_date: str | None, tz: ZoneInfo, vid: str) -> str:
    if ts:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz)
        return dt.strftime("%Y-%m-%d_%H-%M-%S")
    if upload_date and re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}_00-00-00"
    return f"unknown_{vid}"


def iso_date(ts: int | None, upload_date: str | None, tz: ZoneInfo) -> str | None:
    if ts:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz).isoformat()
    if upload_date and re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return None


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
    ap = argparse.ArgumentParser(description="Download public YouTube videos with datetime names")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="YouTube channel, playlist, video, or short URL")
    src.add_argument("--listing-json", type=Path, help="Pre-fetched yt-dlp --flat-playlist -J output")
    ap.add_argument("--output-dir", type=Path, required=True, help="Folder for .mp4 files")
    ap.add_argument("--max-height", type=int, default=720, help="Max video height (default 720)")
    ap.add_argument("--timezone", default="America/Santiago", help="IANA tz for filenames")
    ap.add_argument("--max", type=int, default=None, help="Max videos to download")
    ap.add_argument("--cookies-from-browser", default=None,
                    help="Browser to pull cookies from for age/bot-gated public videos (e.g. chrome)")
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--delay-ms", type=int, default=800, help="Delay between videos")
    ap.add_argument("--no-archive", action="store_true", help="Disable resume archive")
    args = ap.parse_args()

    tz = ZoneInfo(args.timezone)
    cookies = args.cookies_from_browser

    # 1) Build the listing.
    if args.listing_json:
        raw = json.loads(args.listing_json.read_text())
        entries = raw.get("entries", raw) if isinstance(raw, dict) else raw
        if isinstance(raw, dict) and "entries" not in raw:
            entries = [raw]
        seen: set[str] = set()
        videos = []
        for e in entries:
            if e and e.get("id") and e["id"] not in seen:
                seen.add(e["id"])
                videos.append(_entry(e))
    else:
        print(f"Listing videos for: {args.url.strip()}")
        videos = list_videos(args.url.strip(), args.max, cookies)

    if args.max:
        videos = videos[: args.max]
    if not videos:
        print("No videos found.")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (args.output_dir / "videos_manifest.json")
    archive = None if args.no_archive else (args.output_dir / "download-archive.txt")
    print(f"Found {len(videos)} video(s). max_height={args.max_height}. Downloading to {args.output_dir}")

    # 2) Download each, capture exact timestamp.
    manifest: list[dict] = []
    tmp_by_id: dict[str, Path] = {}
    for i, item in enumerate(videos):
        vid = item["id"] or f"idx{i}"
        tmp_base = args.output_dir / f".tmp_{vid}"
        try:
            f, ts, upload_date, status = ytdlp_download(
                item["url"], tmp_base, args.max_height, cookies, archive
            )
        except Exception as e:  # noqa: BLE001
            print(f"  - {vid}: FAILED ({str(e)[:160]})", file=sys.stderr)
            manifest.append({"id": vid, "url": item["url"], "error": str(e)[:300]})
            continue
        ts = ts or item.get("timestamp")
        if f is None:
            print(f"  - {vid}: {status}")
            manifest.append({"id": vid, "url": item["url"], "status": status})
            continue
        tmp_by_id[vid] = f
        manifest.append(
            {
                "id": vid,
                "url": item["url"],
                "title": (item.get("title") or "")[:160],
                "timestamp": ts,
                "uploadDate": iso_date(ts, upload_date, tz),
                "height": args.max_height,
                "local": local_filename(ts, upload_date, tz, vid),
            }
        )
        print(f"  - {vid}: ok ({f.stat().st_size} bytes)")
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
    skipped = [m for m in manifest if m.get("status", "").startswith("skipped")]
    print(f"\nDone. {len(ok)} downloaded, {len(skipped)} skipped, {len(failed)} failed -> {args.output_dir}")
    print(f"Manifest: {manifest_path}")
    for item in sorted(ok, key=lambda x: x["local"], reverse=True):
        print(f"  {item['file']}")
    return 0 if (ok or skipped) else 1


if __name__ == "__main__":
    raise SystemExit(main())
