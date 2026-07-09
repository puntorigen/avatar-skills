#!/usr/bin/env python3
"""Shared helpers for the avatar-location skill.

avatar-location lets ONE avatar (same face, gestures, voice, behavior) appear in
different *looks* — a "location" is a bundled wardrobe + environment + light on
the same subject, with its own identity-anchored hero still and camera angles
(optionally incorporating asset refs like a logo on a shirt or a prop). It does
NOT re-design the person; it re-dresses/re-rooms them.

This module only holds: sibling-script + preset resolution, key discovery
(shared with the sibling skills), JSON IO, a couple of subprocess helpers and
small path utilities. The heavy lifting is delegated to the skills it reuses
(avatar-invent/generate_hero.py for the identity-anchored hero, and
avatar-camera-angles/generate_angles.py for the angles).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"
USER_SKILLS = Path.home() / ".cursor/skills"

PY = sys.executable or "python3"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


# ---------------------------------------------------------------------------
# Sibling-script / preset resolution: prefer the project-local .cursor/skills
# copy (where avatar-invent lives and is version-controlled), then the
# user-level install.
# ---------------------------------------------------------------------------
def _skills_root() -> Path:
    local = SKILL_DIR.parent
    if (local / "avatar-invent/scripts/generate_hero.py").exists():
        return local
    return USER_SKILLS


SKILLS_ROOT = _skills_root()


def skill_script(rel: str) -> Path:
    """Resolve a sibling skill script, preferring the project-local skills root."""
    for root in (SKILLS_ROOT, USER_SKILLS):
        cand = root / rel
        if cand.exists():
            return cand
    return SKILLS_ROOT / rel


GENERATE_HERO = skill_script("avatar-invent/scripts/generate_hero.py")
GENERATE_ANGLES = skill_script("avatar-camera-angles/scripts/generate_angles.py")
INVENT_PRESETS = skill_script("avatar-invent/prompts/presets.json")


# ---------------------------------------------------------------------------
# Config / API keys (shared with the sibling skills, discovered automatically).
# avatar-location itself only needs the keys the skills it calls need:
#   Replicate -> gpt-image-2 (hero + angles)
#   Gemini    -> asset-generator (only for --generator gemini)
# ---------------------------------------------------------------------------
_SIBLING_CONFIGS = [
    USER_SKILLS / "avatar-invent/config.json",
    USER_SKILLS / "gpt-image-2/config.json",
    USER_SKILLS / "asset-generator/config.json",
    USER_SKILLS / "avatar-video-reel/config.json",
    SKILLS_ROOT / "avatar-invent/config.json",
    SKILLS_ROOT / "gpt-image-2/config.json",
]


def load_config() -> dict:
    return try_load_json(CONFIG_FILE) or {}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _discover(env_keys, cfg_keys, *, required=False, label=""):
    for ev in env_keys:
        v = os.environ.get(ev)
        if v:
            return v
    own = load_config()
    for ck in cfg_keys:
        v = own.get(ck)
        if v:
            return v
    for path in _SIBLING_CONFIGS:
        cfg = try_load_json(path)
        if not isinstance(cfg, dict):
            continue
        for ck in cfg_keys:
            v = cfg.get(ck)
            if v:
                return v
    if required:
        print(f"Error: no {label} found.", file=sys.stderr)
        print(f"  Set it: python3 {SCRIPT_DIR / 'setup_key.py'} --help", file=sys.stderr)
        sys.exit(1)
    return None


def get_replicate_token(required=True):
    return _discover(["REPLICATE_API_TOKEN"],
                     ["replicate_api_token"], required=required, label="Replicate API token")


def get_gemini_api_key(required=False):
    return _discover(["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                     ["gemini_api_key"], required=required, label="Gemini API key")


# ---------------------------------------------------------------------------
# JSON IO
# ---------------------------------------------------------------------------
def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def try_load_json(path):
    try:
        return load_json(path)
    except (OSError, ValueError):
        return None


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Presets (reuse avatar-invent's settings / default light / default moves)
# ---------------------------------------------------------------------------
_FALLBACK_PRESETS = {
    "default_light": (
        "Soft key light from the left at about 45 degrees, a gentle soft rim / back light "
        "separating the subject from the background, soft ambient fill so the shadow side "
        "stays open and flattering, even natural exposure with no harsh hotspots."
    ),
    "default_moves": ["push_in", "pull_out", "low_angle", "three_quarter", "negative_space_left"],
    "settings": {},
}


def load_presets() -> dict:
    data = try_load_json(INVENT_PRESETS)
    if isinstance(data, dict):
        return data
    return dict(_FALLBACK_PRESETS)


# ---------------------------------------------------------------------------
# Paths / strings
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "location"


def rel_to(path, base) -> str:
    path = Path(path).resolve()
    base = Path(base).resolve()
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def first_image(folder) -> Path | None:
    folder = Path(folder)
    if not folder.is_dir():
        return None
    imgs = sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    return imgs[0] if imgs else None


# ---------------------------------------------------------------------------
# Process / checkpoints
# ---------------------------------------------------------------------------
def stop(headline: str, lines, code: int = 2):
    """Print an agent-checkpoint message and exit with ``code`` (2 by default)."""
    print(f"\n  ==> {headline}", file=sys.stderr)
    for ln in lines:
        print(f"      {ln}", file=sys.stderr)
    raise SystemExit(code)


def _parse_last_json(text: str):
    for line in reversed([ln for ln in (text or "").splitlines() if ln.strip()]):
        s = line.strip()
        if s.startswith("{"):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                continue
    if text and "{" in text:
        try:
            return json.loads(text[text.index("{"):])
        except json.JSONDecodeError:
            return None
    return None


def run_child_json(cmd, *, desc=None):
    """Run a child process, stream stderr, capture stdout, parse the last JSON.

    Returns (exit_code, parsed_json_or_None).
    """
    cmd = [str(c) for c in cmd]
    if desc:
        print(f"\n  >>> {desc}", file=sys.stderr)
    print(f"      $ {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _pump():
        assert proc.stderr is not None
        for line in proc.stderr:
            sys.stderr.write(line)
        sys.stderr.flush()

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    out = proc.stdout.read() if proc.stdout else ""
    proc.wait()
    t.join(timeout=5)
    return proc.returncode, _parse_last_json(out)
