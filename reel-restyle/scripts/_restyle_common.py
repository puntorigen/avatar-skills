#!/usr/bin/env python3
"""Shared helpers for the reel-restyle skill.

reel-restyle distills a script-agnostic "reel template" from a reference
avatar's analysis + measured style files, then applies that template to a NEW
avatar (a single picture + a voice sample + a script): it scaffolds the new
avatar's assets (camera-angle stills, cloned voice, talking profile, copied
caption/transition styles) and auto-drafts a composer-ready storyboard.

This module only holds path resolution + tiny JSON/subprocess helpers; the
heavy lifting lives in the sibling skills we delegate to (video-scene-analysis,
avatar-camera-angles, voice-clone, avatar-reel-composer). Sibling scripts are
resolved against the project-local skills root first (so a version-controlled
<repo>/.cursor/skills copy is self-contained), then the user-level install.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
USER_SKILLS = Path.home() / ".cursor/skills"


def _resolve_skills_root() -> Path:
    local = SKILL_DIR.parent  # the directory that holds this skill + its siblings
    if (local / "avatar-reel-composer/scripts/compose_reel.py").exists():
        return local
    return USER_SKILLS


SKILLS_ROOT = _resolve_skills_root()


def skill_script(rel: str) -> Path:
    """Resolve a sibling skill script, preferring the project-local skills root."""
    cand = SKILLS_ROOT / rel
    if cand.exists():
        return cand
    alt = USER_SKILLS / rel
    return alt if alt.exists() else cand


# Sibling entrypoints we orchestrate.
GENERATE_ANGLES = skill_script("avatar-camera-angles/scripts/generate_angles.py")
CLONE_VOICE = skill_script("voice-clone/scripts/clone_voice.py")
COMPOSE_REEL = skill_script("avatar-reel-composer/scripts/compose_reel.py")
ANALYZE_VIDEO = skill_script("video-scene-analysis/scripts/analyze_video.py")

PY = sys.executable or "python3"

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


# ---------------------------------------------------------------------------
# Output format -> talking-head angle frame conventions
# ---------------------------------------------------------------------------
# avatar-camera-angles writes each camera-move still as ``<slug>_<move><suffix>``.
# reel/post keep the vertical 9:16 crop (``_916`` via ``--crop916``); landscape
# (YouTube) uses the 16:9 crop (``_169`` via ``--crop169``). Both are produced by
# avatar-camera-angles/scripts/generate_angles.py.
FORMAT_ANGLE = {
    "reel":      ("_916", "--crop916"),
    "post":      ("_916", "--crop916"),
    "landscape": ("_169", "--crop169"),
}


def angle_suffix(fmt: str) -> str:
    """Frame-name suffix for a given output format (default: vertical ``_916``)."""
    return FORMAT_ANGLE.get(fmt, FORMAT_ANGLE["reel"])[0]


def angle_crop_flag(fmt: str) -> str:
    """generate_angles crop flag for a given output format (default: ``--crop916``)."""
    return FORMAT_ANGLE.get(fmt, FORMAT_ANGLE["reel"])[1]


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
# Paths
# ---------------------------------------------------------------------------
def rel_to(path, base) -> str:
    """Path relative to base when possible, else absolute (keeps JSON portable)."""
    path = Path(path).resolve()
    base = Path(base).resolve()
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def resolve_path(raw, base) -> Path:
    """Resolve a (possibly relative) path against base_dir."""
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (Path(base) / p).resolve()


def infer_avatar_dir(start) -> Path | None:
    """Nearest ancestor that is/contains a ``videos/`` dir (the avatar root)."""
    p = Path(start).expanduser().resolve()
    if p.is_file():
        p = p.parent
    for cand in [p, *p.parents]:
        if cand.name == "videos":
            return cand.parent
        if (cand / "videos").is_dir():
            return cand
    return None


def first_image(folder: Path) -> Path | None:
    if not Path(folder).is_dir():
        return None
    imgs = sorted(p for p in Path(folder).iterdir()
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


def run_child(cmd, *, desc=None) -> int:
    """Run a child process inheriting stdio; return its exit code."""
    cmd = [str(c) for c in cmd]
    if desc:
        print(f"\n  >>> {desc}", file=sys.stderr)
    print(f"      $ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd).returncode


def run_child_json(cmd, *, desc=None):
    """Run a child process, stream stderr, capture stdout, parse the last JSON.

    Returns (exit_code, parsed_json_or_None).
    """
    import threading

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
