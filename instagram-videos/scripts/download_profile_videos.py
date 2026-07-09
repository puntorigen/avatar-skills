#!/usr/bin/env python3
"""
Download public Instagram profile videos via Picnob metadata.

Reads a picnob_posts.json (from browser scrape), downloads only videos,
fetches exact uploadDate from each post page, and saves as YYYY-MM-DD_HH-MM-SS.mp4.

Usage:
    python3 download_profile_videos.py \\
        --posts-json posts-raw/meta/picnob_posts.json \\
        --output-dir lolo/videos \\
        [--timezone America/Santiago] \\
        [--manifest output/videos_manifest.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
PICNOB_POST = "https://www.picnob.com/post/{pId}/"


def is_video(post: dict) -> bool:
    url = post.get("downloadUrl") or ""
    return bool(post.get("isVideo")) or ".mp4" in url.lower()


def fetch_upload_date(p_id: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        PICNOB_POST.format(pId=p_id),
        headers={"User-Agent": UA, "Referer": "https://www.picnob.com/"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", "ignore")
    m = re.search(r'"uploadDate"\s*:\s*"([^"]+)"', html)
    if not m:
        raise ValueError(f"uploadDate not found for pId {p_id}")
    return m.group(1)


def download_file(url: str, dest: Path, timeout: int = 60) -> tuple[Path, str]:
    if dest.exists() and dest.stat().st_size > 0:
        return dest, "skipped"
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://www.picnob.com/"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest, f"ok ({len(data)} bytes)"


def local_filename(upload_date: str, tz: ZoneInfo) -> str:
    dt = datetime.fromisoformat(upload_date).astimezone(tz)
    return dt.strftime("%Y-%m-%d_%H-%M-%S")


def dedupe_names(items: list[dict]) -> None:
    seen: dict[str, int] = {}
    for item in items:
        base = item["local"]
        n = seen.get(base, 0) + 1
        seen[base] = n
        item["file"] = f"{base}.mp4" if n == 1 else f"{base}_{n}.mp4"


def main() -> int:
    ap = argparse.ArgumentParser(description="Download Instagram profile videos with datetime names")
    ap.add_argument("--posts-json", type=Path, required=True, help="Picnob scrape JSON array")
    ap.add_argument("--output-dir", type=Path, required=True, help="Folder for .mp4 files")
    ap.add_argument(
        "--timezone",
        default="America/Santiago",
        help="IANA timezone for filenames (default: America/Santiago)",
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifest JSON path (default: <output-dir>/videos_manifest.json)",
    )
    ap.add_argument("--workers", type=int, default=3, help="Parallel downloads")
    ap.add_argument("--delay-ms", type=int, default=600, help="Delay between download starts")
    args = ap.parse_args()

    tz = ZoneInfo(args.timezone)
    posts = json.loads(args.posts_json.read_text())
    if not isinstance(posts, list):
        print("ERROR: posts-json must be a JSON array", file=sys.stderr)
        return 1

    videos = [p for p in posts if p.get("downloadUrl") and is_video(p)]
    if not videos:
        print("No videos found in posts JSON.")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (args.output_dir / "videos_manifest.json")

    print(f"Fetching upload dates for {len(videos)} videos...")
    manifest: list[dict] = []
    for i, post in enumerate(videos):
        p_id = post["pId"]
        try:
            upload_date = fetch_upload_date(p_id)
        except (urllib.error.URLError, ValueError) as e:
            print(f"  WARN {p_id}: {e}", file=sys.stderr)
            upload_date = None
        local = local_filename(upload_date, tz) if upload_date else f"unknown_{p_id}"
        manifest.append(
            {
                "pId": p_id,
                "uploadDate": upload_date,
                "local": local,
                "caption": (post.get("caption") or "")[:120],
                "time": post.get("time"),
                "picnobHref": post.get("picnobHref"),
                "downloadUrl": post.get("downloadUrl"),
            }
        )
        if i < len(videos) - 1:
            time.sleep(0.4)

    dedupe_names(manifest)

    print(f"Downloading to {args.output_dir} ...")
    tmp_by_pid: dict[str, Path] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {}
        for item in manifest:
            tmp = args.output_dir / f".tmp_{item['pId']}.mp4"
            futures[ex.submit(download_file, item["downloadUrl"], tmp)] = item
            time.sleep(args.delay_ms / 1000.0)
        for fut in as_completed(futures):
            item = futures[fut]
            dest, status = fut.result()
            tmp_by_pid[item["pId"]] = dest
            print(f"  - {item['pId']}: {status}")

    print("Renaming files...")
    for item in manifest:
        src = tmp_by_pid[item["pId"]]
        dst = args.output_dir / item["file"]
        if dst.exists() and dst.resolve() != src.resolve():
            dst.unlink()
        src.rename(dst)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\nDone. {len(manifest)} videos -> {args.output_dir}")
    print(f"Manifest: {manifest_path}")
    for item in sorted(manifest, key=lambda x: x["local"], reverse=True):
        print(f"  {item['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
