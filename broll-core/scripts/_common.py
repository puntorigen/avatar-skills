#!/usr/bin/env python3
"""Shared helpers for the broll-* skills (single source of truth).

Used by broll-web-capture, broll-terminal and broll-demo-avatar. Provides:
  * canonical reel geometry (ASPECTS) + fps that match avatar-reel-composer,
  * thin ffmpeg / ffprobe wrappers,
  * the numbered-clip + manifest.json conventions,
  * a font finder for PIL text overlays.

Consumers add this dir to sys.path (see broll_core_path() in each skill) and
`import _common as C`. Set `C.PREFIX` once at startup for nicer per-skill logs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Overridden by each skill's orchestrator (e.g. "broll-terminal") for log lines.
PREFIX = "broll"

# Canonical output frames (match avatar-reel-composer: 9:16 = 1080x1920).
ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
DEFAULT_FPS = 30


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    log(f"[{PREFIX}] ERROR: {msg}")
    raise SystemExit(1)


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        die(f"`{name}` not found on PATH. Install it (e.g. `brew install ffmpeg`).")


def run(cmd: list[str], desc: str = "", check: bool = True) -> subprocess.CompletedProcess:
    if desc:
        log(f"  $ {desc}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1200:]
        die(f"command failed (rc={proc.returncode}): {' '.join(cmd[:4])} ...\n{tail}")
    return proc


def ffprobe_dims(path: Path) -> tuple[int, int]:
    proc = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path),
    ], check=False)
    out = (proc.stdout or "").strip().splitlines()
    if not out:
        die(f"ffprobe could not read dimensions of {path}")
    w, h = out[0].split("x")[:2]
    return int(w), int(h)


def ffprobe_duration(path: Path) -> float:
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], check=False)
    try:
        return float((p.stdout or "0").strip())
    except ValueError:
        return 0.0


def aspect_dims(aspect: str) -> tuple[int, int]:
    if aspect not in ASPECTS:
        die(f"--aspect must be one of {', '.join(ASPECTS)} (got {aspect!r})")
    return ASPECTS[aspect]


def next_index(out_dir: Path) -> int:
    import re
    mx = 0
    for p in out_dir.glob("*.mp4"):
        m = re.match(r"(\d{3})_", p.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


def append_manifest(out_dir: Path, entry: dict) -> Path:
    manifest = out_dir / "manifest.json"
    clips = []
    if manifest.exists():
        try:
            clips = json.loads(manifest.read_text(encoding="utf-8")).get("clips", [])
        except Exception:
            clips = []
    clips.append(entry)
    manifest.write_text(
        json.dumps({"clips": clips}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def find_font(bold: bool = True) -> str | None:
    """Locate a usable .ttf for ffmpeg drawtext / PIL (avoid .ttc which drawtext rejects)."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None
