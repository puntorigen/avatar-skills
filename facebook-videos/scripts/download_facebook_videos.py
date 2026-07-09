#!/usr/bin/env python3
"""
Download public Facebook videos with upload-datetime filenames.

Like YouTube, Facebook is a single-engine yt-dlp target: no browser mirror
(Instagram) and no third-party fallback API (TikTok) are used. It requires
`ffmpeg` to merge Facebook's separate video+audio (DASH) streams when present.

The big difference from YouTube is that Facebook is the most login-walled of
the four platforms: many otherwise-public videos return a login redirect to
anonymous tooling. The resilience path is `--cookies-from-browser` (pull your
own logged-in session cookies), NOT a second engine.

Accepts:
  - a watch link              facebook.com/watch/?v=ID
  - a video permalink         facebook.com/<page>/videos/ID/
  - a reel                    facebook.com/reel/ID
  - a share short link        fb.watch/xxxx/   (yt-dlp resolves it)
  - a Page's videos tab       facebook.com/<page>/videos   (a playlist)
  - or a pre-fetched listing JSON (yt-dlp --flat-playlist -J output)

To grab only the first video of a Page/videos listing, pass --max 1.

Each video is saved as YYYY-MM-DD_HH-MM-SS.mp4 in the chosen timezone, using
the exact upload `timestamp` (from each video's info.json). Videos with only
date precision fall back to YYYY-MM-DD_00-00-00.mp4; videos with no date at all
fall back to unknown_<id>.mp4.

Usage:
    python3 download_facebook_videos.py \\
        --url "https://www.facebook.com/watch/?v=10154325234224113" \\
        --output-dir out/facebook \\
        [--max-height 1080] \\
        [--timezone America/Santiago] \\
        [--max 1] \\
        [--cookies-from-browser chrome] \\
        [--manifest out/facebook/videos_manifest.json]

    # or from a pre-fetched listing:
    yt-dlp --flat-playlist -J "https://www.facebook.com/<page>/videos" > listing.json
    python3 download_facebook_videos.py --listing-json listing.json --output-dir out/facebook
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

# Numeric Facebook video id found in the common URL shapes.
VIDEO_ID_RE = re.compile(
    r"(?:[?&]v=|/videos/|/reel/|/watch/?\?v=)(\d{6,})",
    re.I,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def video_id_from_url(url: str) -> str | None:
    m = VIDEO_ID_RE.search(url or "")
    return m.group(1) if m else None


def _entry(e: dict) -> dict:
    vid = str(e.get("id") or "")
    url = e.get("url") or e.get("webpage_url") or ""
    if not vid:
        vid = video_id_from_url(url) or ""
    return {
        "id": vid,
        "url": url or (f"https://www.facebook.com/watch/?v={vid}" if vid else ""),
        "title": (e.get("title") or "").strip(),
        "timestamp": e.get("timestamp"),  # usually null in flat mode
    }


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
        if e.get("entries"):  # nested playlist -> flatten one level
            for sub in e["entries"]:
                if sub:
                    items.append(_entry(sub))
            continue
        items.append(_entry(e))
    return [it for it in items if it["id"] or it["url"]]


def list_videos(url: str, limit: int | None, cookies: str | None) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for it in ytdlp_list(url, limit, cookies):
        key = it["id"] or it["url"]
        if key and key not in seen:
            seen.add(key)
            merged.append(it)
        if limit and len(merged) >= limit:
            break
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
    # Facebook quirk: its best renditions are the progressive `hd`/`sd` formats,
    # whose height is reported as "unknown" — so a naive height filter skips them
    # and grabs a smaller DASH stream instead. Prefer `hd` by default (matches
    # yt-dlp's own pick); only lead with height-capped selectors when the caller
    # explicitly lowered --max-height below 1080.
    if max_height >= 1080:
        fmt = "hd/b/bv*+ba/sd"
    else:
        fmt = f"bv*[height<={max_height}]+ba/b[height<={max_height}]/hd/sd/b"
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
        raise RuntimeError(_explain(out.stderr) or "yt-dlp download failed")
    return None, ts, upload_date, "skipped (archive)"


def _explain(stderr: str) -> str:
    """Surface the most actionable line from a yt-dlp failure."""
    tail = stderr.strip()[-400:]
    low = tail.lower()
    if "log in" in low or "login" in low or "cookies" in low or "not available" in low:
        return (tail + "  -> retry with --cookies-from-browser chrome (or firefox/safari)")
    return tail


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
    ap = argparse.ArgumentParser(description="Download public Facebook videos with datetime names")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="Facebook watch/video/reel/fb.watch URL or a Page videos tab")
    src.add_argument("--listing-json", type=Path, help="Pre-fetched yt-dlp --flat-playlist -J output")
    ap.add_argument("--output-dir", type=Path, required=True, help="Folder for .mp4 files")
    ap.add_argument("--max-height", type=int, default=1080, help="Max video height (default 1080)")
    ap.add_argument("--timezone", default="America/Santiago", help="IANA tz for filenames")
    ap.add_argument("--max", type=int, default=None, help="Max videos to download (use 1 for first only)")
    ap.add_argument("--cookies-from-browser", default=None,
                    help="Browser to pull cookies from for login-walled public videos (e.g. chrome)")
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
            if not e:
                continue
            it = _entry(e)
            key = it["id"] or it["url"]
            if key and key not in seen:
                seen.add(key)
                videos.append(it)
    else:
        print(f"Listing videos for: {args.url.strip()}")
        videos = list_videos(args.url.strip(), args.max, cookies)

    if args.max:
        videos = videos[: args.max]
    if not videos:
        print("No videos found. If the content is login-walled, retry with --cookies-from-browser chrome.")
        return 1

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
            print(f"  - {vid}: FAILED ({str(e)[:200]})", file=sys.stderr)
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
