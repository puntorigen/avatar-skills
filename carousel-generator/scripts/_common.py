#!/usr/bin/env python3
"""Shared helpers for the carousel-generator skill.

Reuses the credentials of the sibling skills bundled in this repo instead of
storing new ones (env var first, then a git-ignored config.json):
  - Gemini API key  -> asset-generator (Gemini 3 Pro Image, renders every slide).
  - Apify token      -> reel-discovery (scrapes the competitor carousels).

Sibling-script / sibling-config resolution mirrors the rest of avatar-skills:
prefer the project-local repo copy, then the user-level `~/.cursor/skills`
install (so the skill works both when run from the repo and after
`npx skills add ...`).

Stdlib-only except for the optional google-genai / requests used by callers.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any, Optional

HOME = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"           # this skill's own (optional) config
USER_SKILLS = HOME / ".cursor" / "skills"


# --------------------------------------------------------------------------- #
# Sibling-skill resolution (repo-local first, then the global install)
# --------------------------------------------------------------------------- #
def _skills_root() -> Path:
    """The skills root that contains our siblings (asset-generator, reel-discovery).

    Prefer the repo copy (SKILL_DIR.parent) when the bundled asset-generator is
    present there; otherwise fall back to the user-level `~/.cursor/skills`.
    """
    local = SKILL_DIR.parent
    if (local / "asset-generator" / "scripts" / "generate_asset.py").exists():
        return local
    return USER_SKILLS


SKILLS_ROOT = _skills_root()


def skill_path(rel: str) -> Path:
    """Resolve a sibling path, preferring the project-local skills root."""
    for root in (SKILLS_ROOT, USER_SKILLS):
        cand = root / rel
        if cand.exists():
            return cand
    return SKILLS_ROOT / rel


# Apify actor + vision model knobs (override with env vars if needed).
APIFY_BASE = "https://api.apify.com/v2/acts"
DEFAULT_IG_ACTOR = os.environ.get("APIFY_IG_ACTOR", "apify~instagram-scraper")
DEFAULT_HASHTAG_ACTOR = os.environ.get("APIFY_HASHTAG_ACTOR", "apify~instagram-hashtag-scraper")
VISION_MODEL = os.environ.get("CAROUSEL_VISION_MODEL", "gemini-flash-latest")


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _sibling_configs(sibling: str) -> list[Path]:
    """Candidate config.json paths for a sibling skill across both roots."""
    seen: list[Path] = []
    for root in (SKILLS_ROOT, USER_SKILLS):
        p = root / sibling / "config.json"
        if p not in seen:
            seen.append(p)
    return seen


def _discover(env_keys: list[str], cfg_keys: list[str], sibling: str) -> Optional[str]:
    """env var -> this skill's own config.json -> the sibling skill's config.json."""
    for ev in env_keys:
        v = os.environ.get(ev)
        if v:
            return v
    own = _read_json(CONFIG_FILE)
    for ck in cfg_keys:
        if own.get(ck):
            return own[ck]
    for path in _sibling_configs(sibling):
        cfg = _read_json(path)
        for ck in cfg_keys:
            if cfg.get(ck):
                return cfg[ck]
    return None


def gemini_key() -> Optional[str]:
    """Resolve the Gemini API key (env -> own config -> asset-generator config)."""
    return _discover(["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                     ["gemini_api_key"], "asset-generator")


def apify_token() -> Optional[str]:
    """Resolve the Apify token (env -> own config -> reel-discovery config)."""
    return _discover(["APIFY_TOKEN"],
                     ["APIFY_TOKEN", "apify_token"], "reel-discovery")


# --------------------------------------------------------------------------- #
# Apify
# --------------------------------------------------------------------------- #
def run_apify_actor(actor: str, run_input: dict[str, Any], token: str,
                    timeout: int = 300) -> list[dict]:
    """POST to the sync run endpoint and return the dataset items list."""
    url = f"{APIFY_BASE}/{actor}/run-sync-get-dataset-items?token={token}"
    body = json.dumps(run_input).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "carousel-generator/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    data = json.loads(raw) if raw else []
    return data if isinstance(data, list) else data.get("items", [])


def first(d: dict, *keys: str) -> Any:
    """Defensive multi-key getter supporting dotted paths."""
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
# Text utilities
# --------------------------------------------------------------------------- #
_HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_\u00C0-\u017F]+)")


def extract_hashtags(text: str) -> list[str]:
    if not text:
        return []
    return [h.lower() for h in _HASHTAG_RE.findall(text)]


def strip_hashtags(text: str) -> str:
    if not text:
        return ""
    return _HASHTAG_RE.sub("", text).strip()


def slugify(text: str, maxlen: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:maxlen] or "carousel"


def download_file(url: str, dest: Path, timeout: int = 60) -> bool:
    """Download a URL to dest. Returns True on success."""
    if not url:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception:  # noqa: BLE001
        return False


def classify_post_type(item: dict) -> str:
    """Return 'carousel' | 'reel' | 'image' from an Apify IG item."""
    t = (first(item, "type", "productType", "__typename") or "").lower()
    if "sidecar" in t or "carousel" in t:
        return "carousel"
    if "video" in t or "reel" in t or "clips" in t:
        return "reel"
    # Fallbacks based on presence of child media.
    children = item.get("childPosts") or item.get("images")
    if isinstance(children, list) and len(children) > 1:
        return "carousel"
    if first(item, "videoUrl", "videoViewCount", "videoPlayCount", "videoDuration"):
        return "reel"
    return "image"


def child_image_urls(item: dict) -> list[str]:
    """Collect all slide image URLs from a carousel Apify item (defensive)."""
    urls: list[str] = []
    children = item.get("childPosts")
    if isinstance(children, list) and children:
        for c in children:
            u = first(c, "displayUrl", "imageUrl", "url")
            if u:
                urls.append(u)
    if not urls:
        imgs = item.get("images")
        if isinstance(imgs, list):
            urls.extend([u for u in imgs if isinstance(u, str)])
    if not urls:
        u = first(item, "displayUrl", "thumbnailUrl")
        if u:
            urls.append(u)
    # De-dup keep order.
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def engagement(item: dict) -> int:
    likes = first(item, "likesCount", "likeCount") or 0
    comments = first(item, "commentsCount", "commentCount") or 0
    try:
        return int(likes) + int(comments)
    except (TypeError, ValueError):
        return 0


# A niche Top-10 example (ruptures / grief) — a convenient default handle set.
ARNOLDO_TOP10 = [
    "sanandoatuex_", "alvaro.rupturas.de.pareja", "corazonroto_oficial", "leoquins",
    "eva_latapi", "manuelaazuluagaf", "doctoraflorez", "roberttbarret",
    "veroo.araque", "santiagodecastrobalaguer",
]
