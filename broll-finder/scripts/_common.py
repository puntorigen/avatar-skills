#!/usr/bin/env python3
"""Shared utilities for the broll-finder skill.

broll-finder is the *found-footage* counterpart of broll-generator: instead of
GENERATING synthetic B-roll with an AI model, it FINDS real public YouTube
footage about a topic/person, downloads only the relevant segments, and
normalizes them into the same clean 9:16 / silent / manifest-backed format that
the avatar-reel-composer consumes as B-roll inserts.

This module holds everything the focused scripts share:
  * credential resolution (YouTube Data API key — optional, free)
  * a minimal YouTube search (Data API v3 + yt-dlp ytsearch fallback) modeled on
    the reel-discovery skill, with a Creative-Commons license filter
  * timecoded transcript fetching (youtube-transcript-api + yt-dlp VTT fallback)
  * yt-dlp section download (downloads ONLY a [start,end] window of a video)
  * ffmpeg helpers: cut + crop/pad/blur to 9:16, strip audio, probe, frame grab
  * slug / manifest / index helpers (manifest is broll/-compatible)

No paid APIs and no Replicate token are needed: YouTube search + download are
free. A YouTube Data API key only makes search faster / exact and enables the
Creative-Commons filter (otherwise we fall back to yt-dlp ytsearch).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from shutil import which
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"

API = "https://www.googleapis.com/youtube/v3"

# reel-discovery may already hold a YouTube Data API key; reuse it if present.
FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/reel-discovery/config.json",
    SKILL_DIR.parent / "reel-discovery/config.json",
]


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def detect_yt_api_key() -> Optional[str]:
    """env YT_API_KEY -> local config.json -> reel-discovery config.json."""
    key = os.environ.get("YT_API_KEY") or os.environ.get("YOUTUBE_API_KEY")
    if key:
        return key
    key = load_config().get("yt_api_key", "")
    if key:
        return key
    for path in FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                k = cfg.get("yt_api_key", "")
                if k:
                    return k
            except (json.JSONDecodeError, OSError):
                continue
    return None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _qs(params: dict) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return urllib.parse.urlencode(clean)


def http_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "broll-finder/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _parse_iso8601_duration(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return None
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


# --------------------------------------------------------------------------- #
# YouTube search (Data API v3, with a yt-dlp ytsearch fallback)
# --------------------------------------------------------------------------- #
def _order_for(sort: str) -> str:
    if sort in ("views", "velocity"):
        return "viewCount"
    if sort == "recent":
        return "date"
    return "relevance"


def _api_search_ids(api_key: str, *, q: str, order: str, region: Optional[str],
                    lang: Optional[str], video_license: str,
                    published_after: Optional[str], max_results: int) -> list[str]:
    url = f"{API}/search?" + _qs({
        "key": api_key, "part": "snippet", "type": "video", "q": q,
        "order": order, "regionCode": region, "relevanceLanguage": lang,
        "videoLicense": video_license, "publishedAfter": published_after,
        "maxResults": min(max_results, 50),
    })
    data = http_json(url) or {}
    return [it["id"]["videoId"] for it in data.get("items", [])
            if it.get("id", {}).get("videoId")]


def _api_hydrate(api_key: str, ids: list[str], query: str) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        url = f"{API}/videos?" + _qs({
            "key": api_key, "id": ",".join(batch),
            "part": "snippet,statistics,contentDetails,status",
        })
        data = http_json(url) or {}
        for it in data.get("items", []):
            snip = it.get("snippet", {})
            stats = it.get("statistics", {})
            status = it.get("status", {})
            vid = it.get("id", "")
            out.append({
                "video_id": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": snip.get("title", ""),
                "channel": snip.get("channelTitle", ""),
                "published_at": snip.get("publishedAt"),
                "duration_s": _parse_iso8601_duration(
                    it.get("contentDetails", {}).get("duration")),
                "views": int(stats["viewCount"]) if stats.get("viewCount") else None,
                "likes": int(stats["likeCount"]) if stats.get("likeCount") else None,
                "license": status.get("license", "youtube"),  # youtube | creativeCommon
                "query": query,
                "source": "youtube-api",
            })
    return out


def _ytsearch_fallback(query: str, limit: int, creative_commons: bool,
                       notes: list[str]) -> list[dict]:
    n = min(max(limit * 2, 10), 30)
    q = f"{query}, creativecommons" if creative_commons else query
    cmd = ["yt-dlp", f"ytsearch{n}:{q}", "-J", "--no-warnings"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if out.returncode != 0 or not out.stdout.strip():
        notes.append("yt-dlp ytsearch failed: " + (out.stderr.strip()[-200:] or "?"))
        return []
    data = json.loads(out.stdout)
    rows: list[dict] = []
    for e in data.get("entries", []):
        if not e:
            continue
        vid = str(e.get("id") or "")
        lic = e.get("license") or ""
        is_cc = "creative commons" in lic.lower()
        if creative_commons and not is_cc:
            continue
        rows.append({
            "video_id": vid,
            "url": e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
            "title": (e.get("title") or "").strip(),
            "channel": e.get("channel") or e.get("uploader") or "",
            "published_at": e.get("upload_date"),
            "duration_s": e.get("duration"),
            "views": e.get("view_count"),
            "likes": e.get("like_count"),
            "license": "creativeCommon" if is_cc else (lic or "youtube"),
            "query": query,
            "source": "yt-dlp",
        })
    return rows


def youtube_search(query: str, *, limit: int = 12, sort: str = "relevance",
                   region: Optional[str] = None, lang: Optional[str] = None,
                   since_days: Optional[int] = None, max_duration: Optional[int] = None,
                   creative_commons: bool = False, api_key: Optional[str] = None,
                   notes: Optional[list[str]] = None) -> list[dict]:
    """Search YouTube for candidate videos. Returns a list of plain dicts.

    Uses the Data API v3 when a key is available (exact counts + a real
    Creative-Commons filter), otherwise falls back to `yt-dlp ytsearch`.
    """
    notes = notes if notes is not None else []
    api_key = api_key or detect_yt_api_key()
    video_license = "creativeCommon" if creative_commons else "any"

    if not api_key:
        notes.append("No YT_API_KEY -> slower yt-dlp ytsearch fallback "
                     "(Creative-Commons filtering is best-effort).")
        return _ytsearch_fallback(query, limit, creative_commons, notes)[:limit]

    try:
        published_after = None
        if since_days:
            from datetime import datetime, timedelta, timezone
            published_after = (datetime.now(timezone.utc) - timedelta(days=since_days)
                               ).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids = _api_search_ids(
            api_key, q=query, order=_order_for(sort), region=region, lang=lang,
            video_license=video_license, published_after=published_after,
            max_results=min(limit * 2, 50))
        ids = list(dict.fromkeys(ids))
        rows = _api_hydrate(api_key, ids, query) if ids else []
        if max_duration:
            rows = [r for r in rows if not r.get("duration_s") or r["duration_s"] <= max_duration]
        # The API videoLicense filter already constrains CC; keep the field for the manifest.
        return rows[:limit]
    except Exception as e:  # noqa: BLE001 - degrade to yt-dlp
        notes.append(f"Data API failed ({str(e)[:120]}); trying yt-dlp ytsearch.")
        return _ytsearch_fallback(query, limit, creative_commons, notes)[:limit]


# --------------------------------------------------------------------------- #
# Transcripts (timecoded)
# --------------------------------------------------------------------------- #
def extract_video_id(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    return None


def _transcript_via_api(video_id: str, languages: list[str]) -> Optional[list[dict]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            data = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        else:  # youtube-transcript-api >= 1.0
            data = YouTubeTranscriptApi().fetch(video_id, languages=languages).to_raw_data()
        cues = [{"start": round(float(c["start"]), 2),
                 "dur": round(float(c.get("duration", 0)), 2),
                 "text": c["text"].strip()}
                for c in data if c.get("text", "").strip()]
        return cues or None
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[transcript] youtube-transcript-api failed: {e}\n")
        return None


def _vtt_ts_to_sec(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s


def _transcript_via_ytdlp(url: str, languages: list[str],
                          cookies_browser: Optional[str]) -> Optional[list[dict]]:
    import glob
    import tempfile
    tmp = tempfile.mkdtemp(prefix="bf_vtt_")
    cmd = ["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
           "--sub-format", "vtt", "--sub-langs", ",".join(languages),
           "-o", os.path.join(tmp, "sub"), url]
    if cookies_browser:
        cmd[1:1] = ["--cookies-from-browser", cookies_browser]
    res = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(res.stderr[-800:])
    vtts = sorted(glob.glob(os.path.join(tmp, "*.vtt")))
    if not vtts:
        return None
    chosen = None
    for lang in languages:
        for v in vtts:
            if f".{lang}." in os.path.basename(v) or f".{lang}-" in os.path.basename(v):
                chosen = v
                break
        if chosen:
            break
    return _parse_vtt(chosen or vtts[0])


def _parse_vtt(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    cues: list[dict] = []
    cur_start: Optional[float] = None
    cur_end: Optional[float] = None
    buf: list[str] = []
    last_text = None

    def flush():
        nonlocal buf, cur_start, cur_end, last_text
        if cur_start is not None and buf:
            text = re.sub(r"\s+", " ", " ".join(buf)).strip()
            if text and text != last_text:
                cues.append({"start": round(cur_start, 2),
                             "dur": round((cur_end or cur_start) - cur_start, 2),
                             "text": text})
                last_text = text
        buf = []

    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            flush()
            m = re.match(r"([\d:.,]+)\s*-->\s*([\d:.,]+)", line)
            if m:
                cur_start, cur_end = _vtt_ts_to_sec(m.group(1)), _vtt_ts_to_sec(m.group(2))
            continue
        if re.fullmatch(r"\d+", line):
            continue
        clean = re.sub(r"<[^>]+>", "", line).replace("&nbsp;", " ").strip()
        if clean:
            buf.append(clean)
    flush()
    return cues


def fetch_timed_transcript(url_or_id: str, languages: list[str],
                           cookies_browser: Optional[str] = None) -> Optional[list[dict]]:
    """Return [{start, dur, text}, ...] (seconds), or None if unavailable."""
    vid = extract_video_id(url_or_id) or url_or_id
    url = url_or_id if url_or_id.startswith("http") else f"https://www.youtube.com/watch?v={vid}"
    cues = _transcript_via_api(vid, languages)
    if cues:
        return cues
    sys.stderr.write("[transcript] falling back to yt-dlp subtitles\n")
    return _transcript_via_ytdlp(url, languages, cookies_browser)


def fmt_ts(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# --------------------------------------------------------------------------- #
# yt-dlp download
# --------------------------------------------------------------------------- #
def ytdlp_info(url: str, cookies_browser: Optional[str] = None) -> dict:
    cmd = ["yt-dlp", "-J", "--no-warnings", "--skip-download", url]
    if cookies_browser:
        cmd[1:1] = ["--cookies-from-browser", cookies_browser]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0 or not res.stdout.strip():
        return {}
    try:
        e = json.loads(res.stdout)
    except json.JSONDecodeError:
        return {}
    lic = e.get("license") or ""
    return {
        "video_id": e.get("id"),
        "title": (e.get("title") or "").strip(),
        "channel": e.get("channel") or e.get("uploader") or "",
        "channel_url": e.get("channel_url") or e.get("uploader_url"),
        "duration_s": e.get("duration"),
        "license": ("creativeCommon" if "creative commons" in lic.lower()
                    else (lic or "youtube")),
        "width": e.get("width"),
        "height": e.get("height"),
    }


def download_section(url: str, start: float, end: float, dst_base: Path, *,
                     max_height: int = 720, cookies_browser: Optional[str] = None) -> Optional[Path]:
    """Download ONLY the [start,end] window of a YouTube video to dst_base.mp4.

    Uses yt-dlp --download-sections with --force-keyframes-at-cuts so the saved
    file is exactly the requested window (re-encoded at the cut points). Returns
    the saved mp4 path or None on failure.
    """
    dst_base = Path(dst_base)
    dst_base.parent.mkdir(parents=True, exist_ok=True)
    section = f"*{float(start):.2f}-{float(end):.2f}"
    out_tmpl = str(dst_base.with_suffix("")) + ".%(ext)s"
    fmt = (f"bestvideo[height<={max_height}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
           f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best")
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist",
           "--download-sections", section, "--force-keyframes-at-cuts",
           "-f", fmt, "--merge-output-format", "mp4",
           "-o", out_tmpl, url]
    if cookies_browser:
        cmd[1:1] = ["--cookies-from-browser", cookies_browser]
    print(f"  yt-dlp section {section} <= {max_height}p ...", file=sys.stderr)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  yt-dlp failed:\n{res.stderr[-700:]}", file=sys.stderr)
        return None
    cand = dst_base.with_suffix(".mp4")
    if cand.exists():
        return cand
    for f in dst_base.parent.glob(dst_base.stem + ".*"):
        if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov"):
            return f
    return None


# --------------------------------------------------------------------------- #
# ffmpeg / ffprobe
# --------------------------------------------------------------------------- #
def has(binary: str) -> bool:
    return which(binary) is not None


def probe_video(path) -> dict:
    if not has("ffprobe"):
        return {}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format", {})
        fps = None
        rate = stream.get("r_frame_rate", "")
        if rate and "/" in rate:
            n, d = rate.split("/")
            fps = round(float(n) / float(d), 2) if float(d) else None
        return {
            "duration": round(float(fmt["duration"]), 2) if fmt.get("duration") else None,
            "width": stream.get("width"),
            "height": stream.get("height"),
            "fps": fps,
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
        return {}


def _fit_filter(W: int, H: int, fit: str) -> str:
    """Video filter to make the source exactly WxH for the chosen fit mode.

    DEFAULT (and the rule for 16:9 -> 9:16): ``crop`` = center crop-to-fill. The
    source is scaled UP until it fully covers the WxH frame (preserving aspect),
    then center-cropped to exactly WxH. The result fills the ENTIRE 9:16 frame —
    there is NEVER any letterbox/pillarbox padding of a downscaled copy.

    ``pad`` (black bars) and ``blur`` (blurred backfill) are opt-in alternatives
    only for shots where cropping would cut out essential content.
    """
    if fit == "pad":
        return (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    if fit == "blur":
        return (f"split[bg][fg];"
                f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"gblur=sigma=24[bgb];"
                f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    # crop-to-fill (default): scale up to cover WxH, then crop the centre.
    # No padding of a scaled-down version — the crop covers the whole 9:16 frame.
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:(in_w-{W})/2:(in_h-{H})/2,setsar=1")


def cut_and_normalize(src, dst, *, start: float, end: float, W: int = 1080, H: int = 1920,
                      fps: int = 30, fit: str = "crop", strip_audio: bool = True) -> Optional[Path]:
    """Cut [start,end] of src and render an exact WxH clip (audio stripped)."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not has("ffmpeg"):
        print("  ffmpeg not found - cannot normalize.", file=sys.stderr)
        return None
    dur = max(0.1, float(end) - float(start))
    vf = _fit_filter(W, H, fit)
    cmd = ["ffmpeg", "-y", "-ss", f"{float(start):.3f}", "-i", str(src),
           "-t", f"{dur:.3f}", "-vf", vf, "-r", str(fps),
           "-c:v", "libx264", "-crf", "20", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    cmd += ["-an"] if strip_audio else ["-c:a", "aac", "-b:a", "160k"]
    cmd.append(str(dst))
    print(f"  ffmpeg cut {start:.2f}-{end:.2f}s -> {W}x{H} ({fit}) {dst.name}", file=sys.stderr)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  ffmpeg failed:\n{res.stderr[-700:]}", file=sys.stderr)
        return None
    return dst


def extract_frame(src, t: float, dst) -> Optional[Path]:
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not has("ffmpeg"):
        return None
    res = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{float(t):.3f}", "-i", str(src),
         "-frames:v", "1", "-q:v", "3", str(dst)],
        capture_output=True, text=True)
    return dst if res.returncode == 0 and dst.exists() else None


# --------------------------------------------------------------------------- #
# Naming / manifest
# --------------------------------------------------------------------------- #
def slugify(text: str, maxlen: int = 48) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:maxlen].strip("-") or "clip"


def next_index(items: list, gen_dir) -> int:
    nums = []
    for it in items:
        m = re.match(r"(\d+)_", str(it.get("file", "")))
        if m:
            nums.append(int(m.group(1)))
    for f in Path(gen_dir).glob("[0-9][0-9][0-9]_*"):
        m = re.match(r"(\d+)_", f.name)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def load_manifest(manifest_path) -> dict:
    manifest_path = Path(manifest_path)
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
                return loaded
        except json.JSONDecodeError:
            pass
    return {"items": []}


def write_manifest(manifest_path, manifest: dict) -> None:
    Path(manifest_path).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def infer_avatar_dir(path) -> Optional[Path]:
    p = Path(path).expanduser().resolve()
    if p.is_file():
        p = p.parent
    for cand in [p, *p.parents]:
        if (cand / "videos").is_dir():
            return cand
    return None


# --------------------------------------------------------------------------- #
# Rights / licensing
# --------------------------------------------------------------------------- #
def license_summary(value: Optional[str]) -> dict:
    """Normalize a license value into {license, reusable, note}."""
    v = (value or "").lower()
    if "creativecommon" in v or "creative commons" in v:
        return {
            "license": "creativeCommon",
            "reusable": True,
            "note": ("Creative Commons (YouTube CC-BY). Reuse generally allowed WITH "
                     "attribution to the original channel; verify per-video and credit the source."),
        }
    return {
        "license": value or "youtube_standard",
        "reusable": False,
        "note": ("Standard YouTube license — NOT cleared for republishing. Treat this clip "
                 "as REFERENCE / research only. Using it in a published reel may infringe "
                 "copyright unless it qualifies as fair use or you obtain permission."),
    }
