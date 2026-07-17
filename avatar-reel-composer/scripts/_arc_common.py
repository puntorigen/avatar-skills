#!/usr/bin/env python3
"""Shared utilities for the avatar-reel-composer skill.

This skill orchestrates the sibling skills to turn a script + an existing avatar
into a finished reel (9:16 vertical, 1:1 square or 16:9 landscape/YouTube):
  voice-clone           -> continuous cloned-voice narration (one master track)
  faster-whisper        -> word-level alignment of that narration
  avatar-talking-video  -> lip-synced talking-head scenes (driven by audio chunks)
  broll-generator       -> silent B-roll scenes (voice-over)
  video-compose         -> Ken Burns / zoom motion + scale/pad + stitching primitives

NOTE on the module name: this file is intentionally named ``_arc_common`` (not
``_common``) so it never collides with video-compose's own ``_common`` module,
which we import by adding its scripts dir to ``sys.path`` (see
``get_video_pipeline``). Both modules can therefore coexist in one process.

Token discovery is shared with the other Replicate-based skills.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"

# --- Sibling skill scripts we delegate to -----------------------------------
# Resolve the skills root relative to THIS skill first, so a version-controlled,
# project-level copy (e.g. <repo>/.cursor/skills/) is self-contained and runs
# standalone; otherwise fall back to the user-level ~/.cursor/skills install.
USER_SKILLS = Path.home() / ".cursor/skills"


def _resolve_skills_root() -> Path:
    local = SKILL_DIR.parent  # directory that holds this skill + its siblings
    if (local / "voice-clone/scripts/generate_speech.py").exists():
        return local
    return USER_SKILLS


HOME_SKILLS = _resolve_skills_root()
VOICE_CLONE_SCRIPT = HOME_SKILLS / "voice-clone/scripts/generate_speech.py"
ELEVENLABS_TTS_SCRIPT = HOME_SKILLS / "voice-clone/scripts/elevenlabs_tts.py"
TALKING_VIDEO_SCRIPT = HOME_SKILLS / "avatar-talking-video/scripts/generate_video.py"
BROLL_SCRIPT = HOME_SKILLS / "broll-generator/scripts/generate_broll.py"
VIDEO_COMPOSE_SCRIPTS = HOME_SKILLS / "video-compose/scripts"

# Sibling skills that may hold the shared Replicate token. Check the resolved
# (possibly project-local) root first, then always fall back to the user-level
# install so a token-stripped published copy still finds a locally-set token.
_FALLBACK_SKILLS = (
    "voice-clone",
    "avatar-talking-video",
    "broll-generator",
    "gpt-image-2",
    "video-compose",
    "bg-music-hq",
    "sound-effects",
)
FALLBACK_CONFIGS = [
    root / skill / "config.json"
    for root in dict.fromkeys((HOME_SKILLS, USER_SKILLS))  # dedupe, preserve order
    for skill in _FALLBACK_SKILLS
]


# ---------------------------------------------------------------------------
# Config / token
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def get_replicate_token() -> str:
    """Resolve the Replicate API token: env -> local config -> sibling skills."""
    token = os.environ.get("REPLICATE_API_TOKEN")
    if token:
        return token

    token = load_config().get("replicate_api_token", "")
    if token:
        return token

    for path in FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                t = cfg.get("replicate_api_token", "")
                if t:
                    return t
            except (json.JSONDecodeError, OSError):
                continue

    print("Error: No Replicate API token found.", file=sys.stderr)
    print(f"  Run: python3 {SCRIPT_DIR}/setup_key.py YOUR_REPLICATE_API_TOKEN", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths / naming
# ---------------------------------------------------------------------------
def infer_avatar_dir(path) -> Path | None:
    """Find the avatar folder (nearest ancestor containing a ``videos/`` dir)."""
    p = Path(path).expanduser().resolve()
    if p.is_file():
        p = p.parent
    for cand in [p, *p.parents]:
        if (cand / "videos").is_dir():
            return cand
    return None


def slugify(text: str, maxlen: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:maxlen].strip("-") or "reel"


def next_reel_index(reels_dir: Path) -> int:
    nums = []
    if reels_dir.is_dir():
        for f in reels_dir.glob("[0-9][0-9][0-9]_*"):
            m = re.match(r"(\d+)_", f.name)
            if m:
                nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# FFmpeg / ffprobe (small local helpers so narrate.py needs no heavy imports)
# ---------------------------------------------------------------------------
def run_ffmpeg(args, *, description="", quiet=False) -> bool:
    cmd = ["ffmpeg", "-y"] + [str(a) for a in args]
    if description and not quiet:
        print(f"  FFmpeg: {description} ...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FFmpeg error (exit {result.returncode}):", file=sys.stderr)
        for line in (result.stderr or "").strip().split("\n")[-8:]:
            print(f"    {line}", file=sys.stderr)
        return False
    return True


def ffprobe_duration(path) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def slice_audio(src, start: float, end: float, out, *, reencode=True) -> bool:
    """Cut [start, end] from an audio file. Re-encodes by default (frame-accurate)."""
    dur = max(0.05, float(end) - float(start))
    args = ["-ss", f"{float(start):.3f}", "-i", str(src), "-t", f"{dur:.3f}"]
    if reencode:
        # aresample re-frames the decoded audio before libmp3lame: without it some
        # VBR-mp3 slices intermittently fail ("Error submitting audio frame to the
        # encoder: Invalid argument") and silently truncate the chunk, which then
        # desyncs that scene against the master narration.
        args += ["-af", "aresample=44100", "-c:a", "libmp3lame", "-q:a", "2", "-ar", "44100"]
    else:
        args += ["-c", "copy"]
    args += [str(out)]
    return run_ffmpeg(args, description=f"Slice audio [{start:.2f}-{end:.2f}]")


def concat_audio(parts, out, *, gap: float = 0.0) -> bool:
    """Concatenate mp3 parts with the concat demuxer (re-encode for safety).

    When ``gap`` > 0, a short silence of that many seconds is inserted *between*
    parts (not before the first or after the last). This keeps independently
    synthesized sentence takes from running together and gives the caption
    engine clean pauses at sentence boundaries.
    """
    import tempfile

    silence = None
    if gap and gap > 0:
        silence = Path(tempfile.mktemp(suffix="_gap.mp3"))
        if not run_ffmpeg(
            ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
             "-t", f"{float(gap):.3f}", "-c:a", "libmp3lame", "-q:a", "2", str(silence)],
            description=f"silence {gap:.2f}s", quiet=True,
        ):
            silence = None  # fall back to gapless concat rather than failing

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for i, p in enumerate(parts):
            if i > 0 and silence is not None:
                f.write(f"file '{silence.resolve()}'\n")
            f.write(f"file '{Path(p).resolve()}'\n")
        list_file = f.name
    ok = run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", list_file,
         "-c:a", "libmp3lame", "-q:a", "2", "-ar", "44100", str(out)],
        description=f"Concat {len(parts)} audio parts"
        + (f" (+{gap:.2f}s gaps)" if silence is not None else ""),
    )
    Path(list_file).unlink(missing_ok=True)
    if silence is not None:
        silence.unlink(missing_ok=True)
    return ok


# ---------------------------------------------------------------------------
# Subprocess orchestration for sibling CLIs
# ---------------------------------------------------------------------------
def parse_last_json(text: str):
    """Return the last JSON object printed on stdout (siblings print one)."""
    for line in reversed([ln for ln in (text or "").splitlines() if ln.strip()]):
        s = line.strip()
        if s.startswith("{"):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                continue
    # Fall back to the first "{...}" block (some scripts pretty-print).
    if text and "{" in text:
        try:
            return json.loads(text[text.index("{"):])
        except json.JSONDecodeError:
            return None
    return None


def run_cli_json(cmd, *, desc=None):
    """Run a sibling CLI, stream its stderr live, capture stdout, parse JSON.

    Returns the parsed JSON dict (or None). Raises RuntimeError on non-zero exit.
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
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {' '.join(cmd)}")
    return parse_last_json(out)


# ---------------------------------------------------------------------------
# video-compose pipeline (lazy import — heavy: moviepy/PIL/numpy)
# ---------------------------------------------------------------------------
def get_video_pipeline():
    """Import video-compose's _video_pipeline + _common modules.

    Adds video-compose/scripts to ``sys.path`` so ``_video_pipeline``'s internal
    ``from _common import ...`` resolves to *its* _common (this skill deliberately
    has no ``_common`` module of its own — see the module docstring).
    Returns ``(pipeline_module, common_module)``.
    """
    p = str(VIDEO_COMPOSE_SCRIPTS)
    if p not in sys.path:
        sys.path.insert(0, p)
    import _video_pipeline as vp  # noqa: E402
    import _common as vc  # noqa: E402  (video-compose's _common)
    return vp, vc


def ceil_int(x: float) -> int:
    return int(math.ceil(float(x) - 1e-6))
