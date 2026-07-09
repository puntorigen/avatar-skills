#!/usr/bin/env python3
"""
Shared primitives for the reel-discovery skill.

Defines the cross-platform `Reel` record, normalization/scoring helpers, a tiny
stdlib HTTP layer, a polite rate limiter, credential detection, and the
results.json / results.md writers. Every platform searcher (search_youtube.py,
search_tiktok.py, search_instagram.py) produces `Reel`s; discover.py merges,
ranks and writes them.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# When a platform hides view counts (often Instagram), approximate reach from
# likes so cross-platform ranking stays meaningful. Tunable; flagged per-record.
LIKES_TO_VIEWS_MULT = 25

VALID_PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")
VALID_SORTS = ("views", "engagement", "velocity", "recent")
VALID_MATCH_TYPES = ("topic", "business", "handle")


# --------------------------------------------------------------------------- #
# Record
# --------------------------------------------------------------------------- #
@dataclass
class Reel:
    platform: str
    video_id: str
    url: str
    author: str = ""
    title: str = ""
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    published_at: Optional[str] = None  # ISO-8601 UTC
    duration_s: Optional[float] = None
    thumbnail: Optional[str] = None
    media_url: Optional[str] = None  # direct downloadable URL when known (IG/tikwm)
    query: str = ""
    match_type: str = ""  # topic | business | handle
    source: str = ""      # provider that produced it (youtube-api, tikwm, apify, ...)
    # publishing metadata (how the video was published; understands strategy, not reach)
    description: Optional[str] = None        # full description / caption text
    tags: Optional[list[str]] = None         # creator-set keywords (YT snippet.tags)
    hashtags: Optional[list[str]] = None     # parsed from title + description/caption
    category: Optional[str] = None           # human-readable category name
    language: Optional[str] = None           # default audio/text language (BCP-47)
    metadata: Optional[dict[str, Any]] = None  # platform-specific publishing extras
    # derived (filled by compute_derived)
    views_estimated: bool = False
    engagement_rate: Optional[float] = None
    velocity: Optional[float] = None
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Reel":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
_COUNT_RE = re.compile(r"^([\d.,]+)\s*([kmb]?)$", re.I)
_SUFFIX = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def to_int(value: Any) -> Optional[int]:
    """Best-effort parse of a count that may be an int, '1,234', '1.2M', etc."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "")
    if s.isdigit():
        return int(s)
    m = _COUNT_RE.match(s)
    if not m:
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else None
    num, suffix = m.group(1), m.group(2).lower()
    try:
        return int(float(num) * _SUFFIX.get(suffix, 1))
    except ValueError:
        return None


_ISO_DUR_RE = re.compile(
    r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", re.I
)


def parse_iso8601_duration(s: Optional[str]) -> Optional[float]:
    """YouTube contentDetails.duration ('PT1M30S') -> seconds."""
    if not s:
        return None
    m = _ISO_DUR_RE.fullmatch(s.strip())
    if not m:
        return None
    days, hours, mins, secs = (int(g) if g else 0 for g in m.groups())
    return days * 86400 + hours * 3600 + mins * 60 + secs


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(ts: Any) -> Optional[str]:
    """Normalize a unix timestamp / YYYYMMDD / ISO string to ISO-8601 UTC."""
    if ts is None or ts == "":
        return None
    if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit() and len(ts) >= 9):
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    s = str(ts).strip()
    if re.fullmatch(r"\d{8}", s):  # yt-dlp upload_date
        try:
            return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def days_since(published_at: Optional[str]) -> Optional[float]:
    if not published_at:
        return None
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now_utc() - dt
    return max(delta.total_seconds() / 86400.0, 0.0)


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").strip().lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return (s or "query")[:max_len].strip("-")


_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


def extract_hashtags(*texts: Optional[str]) -> list[str]:
    """Pull #hashtags out of any title/description/caption text, order-preserving
    and case-insensitively de-duplicated (keeps the first-seen casing)."""
    out: list[str] = []
    seen: set[str] = set()
    for t in texts:
        if not t:
            continue
        for m in _HASHTAG_RE.finditer(t):
            tag = m.group(1)
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                out.append(tag)
    return out


def backfill_publishing_meta(reels: list[Reel]) -> list[Reel]:
    """Safety net for platforms whose caption lives in `title` (TikTok/Instagram)
    or come from providers (Apify) that don't pre-parse it: fill `hashtags` from
    the title/description and stamp `hashtag_count`/`description_length` into
    `metadata`. Only fills what's missing, so explicit per-source metadata wins."""
    for r in reels:
        if r.hashtags is None:
            r.hashtags = extract_hashtags(r.title, r.description) or None
        meta = dict(r.metadata) if r.metadata else {}
        if "hashtag_count" not in meta and r.hashtags is not None:
            meta["hashtag_count"] = len(r.hashtags)
        if "description_length" not in meta:
            text = r.description or r.title or ""
            if text:
                meta["description_length"] = len(text)
        r.metadata = meta or None
    return reels


# --------------------------------------------------------------------------- #
# Scoring + ranking
# --------------------------------------------------------------------------- #
def effective_views(reel: Reel) -> int:
    if reel.views is not None:
        return reel.views
    if reel.likes is not None:
        return reel.likes * LIKES_TO_VIEWS_MULT
    return 0


def compute_derived(reel: Reel) -> None:
    if reel.views is None and reel.likes is not None:
        reel.views_estimated = True
    ev = effective_views(reel)
    interactions = sum(v for v in (reel.likes, reel.comments, reel.shares) if v)
    reel.engagement_rate = round(interactions / ev, 5) if ev else None
    days = days_since(reel.published_at)
    reel.velocity = round(ev / max(days, 0.5), 2) if days is not None else float(ev)


def _score(reel: Reel, sort: str) -> float:
    if sort == "engagement":
        return reel.engagement_rate or 0.0
    if sort == "velocity":
        return reel.velocity or 0.0
    if sort == "recent":
        days = days_since(reel.published_at)
        return -days if days is not None else -1e9  # unknown dates sink last
    return float(effective_views(reel))  # "views" (default)


def dedupe(reels: Iterable[Reel]) -> list[Reel]:
    seen: dict[tuple[str, str], Reel] = {}
    for r in reels:
        key = (r.platform, r.video_id or r.url)
        if key not in seen:
            seen[key] = r
    return list(seen.values())


def rank(
    reels: list[Reel],
    *,
    sort: str = "views",
    limit: Optional[int] = None,
    per_platform: Optional[int] = None,
    min_views: Optional[int] = None,
    since_days: Optional[int] = None,
    max_duration: Optional[float] = None,
) -> list[Reel]:
    """Filter, score and order reels. Unknown dates pass `since` (can't disprove)."""
    for r in reels:
        compute_derived(r)

    def keep(r: Reel) -> bool:
        if min_views is not None and effective_views(r) < min_views:
            return False
        if max_duration is not None and r.duration_s is not None and r.duration_s > max_duration:
            return False
        if since_days is not None:
            d = days_since(r.published_at)
            if d is not None and d > since_days:
                return False
        return True

    kept = [r for r in reels if keep(r)]
    for r in kept:
        r.score = round(_score(r, sort), 5)
    kept.sort(key=lambda r: r.score, reverse=True)

    if per_platform:
        counts: dict[str, int] = {}
        capped: list[Reel] = []
        for r in kept:
            c = counts.get(r.platform, 0)
            if c < per_platform:
                capped.append(r)
                counts[r.platform] = c + 1
        kept = capped

    return kept[:limit] if limit else kept


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_json(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout: int = 30,
    data: Optional[bytes] = None,
    method: Optional[str] = None,
) -> Any:
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    return json.loads(raw) if raw else None


def http_text(url: str, *, headers: Optional[dict[str, str]] = None, timeout: int = 30) -> str:
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def qs(params: dict[str, Any]) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})


class RateLimiter:
    """Spread calls so a host is hit no faster than `per_sec`."""

    def __init__(self, per_sec: float = 1.0) -> None:
        self.min_interval = 1.0 / per_sec if per_sec > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
# Optional git-ignored config file (see .cursor/skills/.gitignore). Lives next to
# the skill (parent of this scripts/ dir). Env vars take precedence over it.
CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


def _load_config() -> dict[str, Any]:
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _cfg(cfg: dict[str, Any], *keys: str) -> Optional[str]:
    for k in keys:
        v = cfg.get(k)
        if v:
            return str(v)
    return None


def detect_credentials() -> dict[str, Optional[str]]:
    cfg = _load_config()
    return {
        "yt_api_key": (
            os.environ.get("YT_API_KEY")
            or os.environ.get("YOUTUBE_API_KEY")
            or _cfg(cfg, "YT_API_KEY", "YOUTUBE_API_KEY", "yt_api_key", "youtube_api_key")
        ),
        "apify_token": (
            os.environ.get("APIFY_TOKEN")
            or os.environ.get("APIFY_API_TOKEN")
            or _cfg(cfg, "APIFY_TOKEN", "APIFY_API_TOKEN", "apify_token", "apify_api_token")
        ),
    }


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
def _fmt_int(n: Optional[int]) -> str:
    return f"{n:,}" if isinstance(n, int) else "-"


def write_outputs(reels: list[Reel], out_dir: Path, meta: dict[str, Any]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [{"rank": i + 1, **r.to_dict()} for i, r in enumerate(reels)]
    payload = {"meta": meta, "count": len(results), "results": results}
    json_path = out_dir / "results.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    md_path = out_dir / "results.md"
    md_path.write_text(render_markdown(reels, meta))
    return json_path, md_path


def render_markdown(reels: list[Reel], meta: dict[str, Any]) -> str:
    q = meta.get("query", "")
    lines = [
        f"# Reel discovery: {q}",
        "",
        f"- Match type: `{meta.get('match_type')}`",
        f"- Platforms: {', '.join(meta.get('platforms', []))}",
        f"- Sort: `{meta.get('sort')}`  |  Results: {len(reels)}",
        f"- Generated: {meta.get('generated_at')}",
    ]
    notes = meta.get("notes") or []
    if notes:
        lines.append("")
        lines.append("## Notes")
        lines += [f"- {n}" for n in notes]
    lines += [
        "",
        "## Ranked results",
        "",
        "| # | Platform | Views | Likes | Comments | Eng. | Age (d) | Author | Title | URL |",
        "|--:|---|--:|--:|--:|--:|--:|---|---|---|",
    ]
    for i, r in enumerate(reels):
        views = _fmt_int(r.views) + ("*" if r.views_estimated else "")
        eng = f"{r.engagement_rate:.1%}" if r.engagement_rate is not None else "-"
        age = f"{days_since(r.published_at):.0f}" if days_since(r.published_at) is not None else "-"
        title = (r.title or "").replace("|", "\\|").replace("\n", " ")[:60]
        author = (r.author or "").replace("|", "\\|")[:24]
        lines.append(
            f"| {i + 1} | {r.platform} | {views} | {_fmt_int(r.likes)} | "
            f"{_fmt_int(r.comments)} | {eng} | {age} | {author} | {title} | {r.url} |"
        )
    if any(r.views_estimated for r in reels):
        lines += ["", "_\\* views estimated from likes (platform hid the view count)._"]
    lines += render_publishing_section(reels)
    lines.append("")
    return "\n".join(lines)


def _has_publishing_meta(r: Reel) -> bool:
    return bool(r.hashtags or r.tags or r.description or r.category or r.metadata)


_PLATFORM_LABEL = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
}


def _md_cell(text: Optional[str], n: int) -> str:
    s = (text or "").replace("|", "\\|").replace("\n", " ").strip()
    return s[:n] or "-"


def _int_cell(v: Any) -> str:
    return f"{v:,}" if isinstance(v, int) else "-"


def _hashtag_cell(r: Reel, n: int = 4) -> str:
    return ", ".join("#" + h for h in (r.hashtags or [])[:n]) or "-"


def _fmt_counter(counter: Any, top: Optional[int] = None, prefix: str = "") -> str:
    items = counter.most_common(top) if top else counter.most_common()
    return ", ".join(f"{prefix}{k} ({c})" for k, c in items)


def render_publishing_section(reels: list[Reel]) -> list[str]:
    """Surface 'how were these published?' signals (hashtags, tags, category,
    language, captions, sounds, channel size...) for the records that carry them,
    grouped per platform so platform-specific stats never get mixed. Returns
    markdown lines; empty when no record has publishing metadata."""
    pub = [r for r in reels if _has_publishing_meta(r)]
    if not pub:
        return []
    ranks = {id(r): i + 1 for i, r in enumerate(reels)}
    lines = [
        "",
        "## Cómo están publicados (publishing metadata)",
        "",
        "How the ranked videos are packaged - hashtags, sounds, categories, "
        "languages, captions and channel size - grouped by platform.",
    ]
    by_platform: dict[str, list[Reel]] = {}
    for r in pub:
        by_platform.setdefault(r.platform, []).append(r)
    order = [p for p in VALID_PLATFORMS if p in by_platform]
    order += [p for p in by_platform if p not in VALID_PLATFORMS]
    for platform in order:
        lines += _publishing_block(platform, by_platform[platform], ranks)
    return lines


def _publishing_block(platform: str, group: list[Reel], ranks: dict[int, int]) -> list[str]:
    from collections import Counter
    import statistics

    def meta_vals(key: str) -> list[Any]:
        return [
            (r.metadata or {}).get(key) for r in group if (r.metadata or {}).get(key) is not None
        ]

    n = len(group)
    lines = ["", f"### {_PLATFORM_LABEL.get(platform, platform)} ({n})", ""]

    cat = Counter(r.category for r in group if r.category)
    lang = Counter(r.language for r in group if r.language)
    defn = Counter(meta_vals("definition"))
    region = Counter(meta_vals("region"))
    ptype = Counter(meta_vals("product_type"))
    music = Counter(meta_vals("music_title"))
    hashtags = Counter(h.lower() for r in group for h in (r.hashtags or []))
    tags = Counter(t.lower() for r in group for t in (r.tags or []))
    caption_flags = meta_vals("caption")
    made_for_kids = meta_vals("made_for_kids")
    desc_lens = [v for v in meta_vals("description_length") if v]
    subs = [v for v in meta_vals("subscribers") if isinstance(v, int)]

    if cat:
        lines.append("- Categories: " + _fmt_counter(cat))
    if lang:
        lines.append("- Languages: " + _fmt_counter(lang))
    if defn:
        lines.append("- Definition: " + _fmt_counter(defn))
    if region:
        lines.append("- Regions: " + _fmt_counter(region, 8))
    if ptype:
        lines.append("- Post types: " + _fmt_counter(ptype))
    if caption_flags:
        lines.append(f"- Captions (CC): {sum(1 for x in caption_flags if x)}/{len(caption_flags)}")
    if made_for_kids:
        lines.append(
            f"- Made-for-kids: {sum(1 for x in made_for_kids if x)}/{len(made_for_kids)}"
        )
    if desc_lens:
        lines.append(
            f"- Caption length (chars): median {int(statistics.median(desc_lens))}, "
            f"max {max(desc_lens)}"
        )
    if subs:
        lines.append(
            f"- Channel subscribers: median {int(statistics.median(subs)):,}, "
            f"range {min(subs):,}–{max(subs):,}"
        )
    if music:
        lines += ["", "**Top sounds:** " + _fmt_counter(music, 8)]
    if hashtags:
        lines += ["", "**Top hashtags:** " + _fmt_counter(hashtags, 12, prefix="#")]
    if tags:
        lines += ["", "**Top tags:** " + _fmt_counter(tags, 15)]

    lines += _publishing_table(platform, group, ranks)
    return lines


def _publishing_table(platform: str, group: list[Reel], ranks: dict[int, int]) -> list[str]:
    rows = sorted(group, key=lambda r: ranks.get(id(r), 1 << 30))

    def n_tags(r: Reel) -> str:
        md = r.metadata or {}
        v = md.get("tags_count")
        if v is None:
            v = md.get("hashtag_count")
        if v is None:
            v = len(r.tags or []) or len(r.hashtags or [])
        return str(v)

    if platform == "youtube":
        head = "| # | Title | Category | Lang | CC | #Tags | Hashtags | Subs |"
        sep = "|--:|---|---|---|:--:|--:|---|--:|"

        def row(r: Reel) -> str:
            md = r.metadata or {}
            return (
                f"| {ranks.get(id(r))} | {_md_cell(r.title, 44)} | {r.category or '-'} | "
                f"{r.language or '-'} | {'yes' if md.get('caption') else '-'} | {n_tags(r)} | "
                f"{_hashtag_cell(r)} | {_int_cell(md.get('subscribers'))} |"
            )
    elif platform == "tiktok":
        head = "| # | Caption | Sound | Region | #Tags | Hashtags | Saves |"
        sep = "|--:|---|---|---|--:|---|--:|"

        def row(r: Reel) -> str:
            md = r.metadata or {}
            return (
                f"| {ranks.get(id(r))} | {_md_cell(r.title, 40)} | "
                f"{_md_cell(md.get('music_title'), 22)} | {md.get('region') or '-'} | "
                f"{n_tags(r)} | {_hashtag_cell(r)} | {_int_cell(md.get('saves'))} |"
            )
    elif platform == "instagram":
        head = "| # | Caption | Type | #Tags | Hashtags |"
        sep = "|--:|---|---|--:|---|"

        def row(r: Reel) -> str:
            md = r.metadata or {}
            return (
                f"| {ranks.get(id(r))} | {_md_cell(r.title, 44)} | "
                f"{md.get('product_type') or '-'} | {n_tags(r)} | {_hashtag_cell(r)} |"
            )
    else:
        head = "| # | Title | #Tags | Hashtags |"
        sep = "|--:|---|--:|---|"

        def row(r: Reel) -> str:
            return f"| {ranks.get(id(r))} | {_md_cell(r.title, 44)} | {n_tags(r)} | {_hashtag_cell(r)} |"

    return ["", head, sep] + [row(r) for r in rows]
