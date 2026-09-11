#!/usr/bin/env python3
"""Shared helpers for the video-remix skill.

video-remix analyzes the *visual + narrative + audio MOLD* of a reference video
(a reel / short / talking-head clip) and regenerates NEW content that reuses that
exact mold — format/ratio, per-scene layout, character positions + gaze, palette
and color combinations, elements, action types, captions, brand watermark/logo
placement + timing, transitions, the intro->development->close arc, and the
music + voice-vs-music ducking — producing a premium new reel with the repo's
existing avatar / location / voice / music / compose skills.

This module centralizes everything the stages share:
  - Credential reuse (Gemini key from asset-generator; Replicate from siblings).
  - A robust Gemini vision -> JSON wrapper (image list + instruction).
  - ffprobe geometry + aspect->format snapping (reel / post / landscape).
  - Dominant-color extraction + semantic palette (Pillow), like pdf-remix.
  - A temporal-stability watermark/logo detector (numpy + Pillow, degrades to []).
  - A music-bed + voice-vs-music ducking measurement from the per-scene audio.
  - A sibling-skill subprocess bridge (inherit stdio, or capture last JSON line).

Sibling-skill / sibling-config resolution mirrors the rest of avatar-skills:
prefer the project-local repo copy, then the user-level ``~/.cursor/skills``
install (so the skill works both from the repo and after ``npx skills add ...``).

Stdlib-only except for optional google-genai / Pillow / numpy used by callers
(all degrade gracefully when missing).
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path
from typing import Any, Optional

HOME = Path.home()
SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"            # this skill's own (optional) config
USER_SKILLS = HOME / ".cursor" / "skills"

PY = sys.executable or "python3"


# --------------------------------------------------------------------------- #
# Sibling-skill resolution (repo-local first, then the global install)
# --------------------------------------------------------------------------- #
def _skills_root() -> Path:
    """The skills root that holds our siblings (video-scene-analysis, avatar-*)."""
    local = SKILL_DIR.parent
    if (local / "video-scene-analysis" / "scripts" / "analyze_video.py").exists():
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


# Sibling entrypoints we orchestrate (resolved lazily by callers via skill_path).
ANALYZE_VIDEO = skill_path("video-scene-analysis/scripts/analyze_video.py")
INVENT_AVATAR = skill_path("avatar-invent/scripts/invent_avatar.py")
CREATE_LOCATION = skill_path("avatar-location/scripts/create_location.py")
CLONE_VOICE = skill_path("voice-clone/scripts/clone_voice.py")
GENERATE_ANGLES = skill_path("avatar-camera-angles/scripts/generate_angles.py")
COMPOSE_REEL = skill_path("avatar-reel-composer/scripts/compose_reel.py")
ASSEMBLE_NARRATION = skill_path("avatar-reel-composer/scripts/assemble_narration.py")

# Text+vision model used to read frames. Override with env if needed.
VISION_MODEL = os.environ.get("VIDEO_REMIX_VISION_MODEL", "gemini-flash-latest")


# --------------------------------------------------------------------------- #
# Credentials (reuse — never store new secrets in the repo)
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _sibling_configs(sibling: str) -> list[Path]:
    out: list[Path] = []
    for root in (SKILLS_ROOT, USER_SKILLS):
        p = root / sibling / "config.json"
        if p not in out:
            out.append(p)
    return out


def _discover(env_keys: list[str], cfg_keys: list[str], siblings: list[str]) -> Optional[str]:
    """env var -> this skill's own config.json -> each sibling skill's config.json."""
    for ev in env_keys:
        v = os.environ.get(ev)
        if v:
            return v
    own = _read_json(CONFIG_FILE)
    for ck in cfg_keys:
        if own.get(ck):
            return own[ck]
    for sib in siblings:
        for path in _sibling_configs(sib):
            cfg = _read_json(path)
            for ck in cfg_keys:
                if cfg.get(ck):
                    return cfg[ck]
    return None


def gemini_key() -> Optional[str]:
    """Resolve the Gemini API key (env -> own config -> asset-generator config)."""
    return _discover(["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                     ["gemini_api_key", "GEMINI_API_KEY"], ["asset-generator"])


def replicate_token() -> Optional[str]:
    """Resolve the Replicate token (env -> own config -> sibling skill configs)."""
    return _discover(["REPLICATE_API_TOKEN"],
                     ["replicate_api_token", "REPLICATE_API_TOKEN"],
                     ["voice-clone", "bg-music-hq", "avatar-reel-composer",
                      "gpt-image-2", "avatar-invent"])


def genai_client():
    """Return a configured google-genai client, or None if unavailable."""
    key = gemini_key()
    if not key:
        print("Warning: no Gemini key found (set GEMINI_API_KEY or configure "
              "asset-generator). Vision analysis will be skipped.", file=sys.stderr)
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:  # noqa: BLE001
        print(f"Warning: google-genai unavailable ({e}). "
              "Run: pip3 install google-genai", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Gemini vision -> JSON
# --------------------------------------------------------------------------- #
def _coerce_json(text: str) -> Optional[Any]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except Exception:  # noqa: BLE001
                return None
    return None


def vision_json(client, instruction: str, images: list[Path],
                extra: Optional[str] = None) -> Optional[Any]:
    """Send instruction + images to the vision model and parse a JSON reply.

    Returns the parsed object (dict/list) or None on any failure.
    """
    if client is None:
        return None
    try:
        from PIL import Image as PILImage
    except Exception:  # noqa: BLE001
        return None
    contents: list = [instruction]
    if extra:
        contents.append(extra)
    n = 0
    for p in images:
        try:
            contents.append(PILImage.open(str(p)))
            n += 1
        except Exception:  # noqa: BLE001
            continue
    if n == 0:
        return None
    try:
        resp = client.models.generate_content(model=VISION_MODEL, contents=contents)
        return _coerce_json(resp.text or "")
    except Exception as e:  # noqa: BLE001
        print(f"  ! vision error: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# ffprobe geometry + aspect -> format snapping
# --------------------------------------------------------------------------- #
def _parse_rate(rate: str | None) -> Optional[float]:
    if not rate:
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return round(float(num) / den_f, 3) if den_f else None
        return round(float(rate), 3)
    except Exception:  # noqa: BLE001
        return None


# Reference aspect ratios for the three composer formats.
_FORMAT_ASPECTS = {"reel": 9 / 16, "post": 1.0, "landscape": 16 / 9}


def snap_format(width: int, height: int) -> str:
    """Snap a WxH to the nearest composer format: reel (9:16) / post (1:1) / landscape (16:9)."""
    if not width or not height:
        return "reel"
    aspect = width / height
    return min(_FORMAT_ASPECTS, key=lambda k: abs(aspect - _FORMAT_ASPECTS[k]))


def _reduce_ratio(w: int, h: int) -> str:
    from math import gcd
    if not w or not h:
        return "?"
    g = gcd(w, h) or 1
    return f"{w // g}:{h // g}"


def video_geometry(video_path: str | Path) -> dict:
    """ffprobe -> width/height/fps/duration + reduced aspect + snapped format."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_streams", "-show_format", str(video_path)]
    width = height = 0
    fps = duration = None
    has_audio = False
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
        for st in data.get("streams", []):
            if st.get("codec_type") == "video" and not width:
                width = int(st.get("width") or 0)
                height = int(st.get("height") or 0)
                fps = _parse_rate(st.get("avg_frame_rate") or st.get("r_frame_rate"))
            if st.get("codec_type") == "audio":
                has_audio = True
        dur = data.get("format", {}).get("duration")
        duration = round(float(dur), 3) if dur else None
    except Exception as e:  # noqa: BLE001
        print(f"  ! ffprobe failed: {e}", file=sys.stderr)
    fmt = snap_format(width, height)
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "duration": duration,
        "has_audio": has_audio,
        "aspect_ratio": _reduce_ratio(width, height),
        "orientation": "portrait" if height >= width else "landscape",
        "format": fmt,
    }


# --------------------------------------------------------------------------- #
# Color extraction (Pillow) — mirrors pdf-remix
# --------------------------------------------------------------------------- #
def dominant_colors(img_path: str | Path, k: int = 6) -> list[str]:
    """Return up to k dominant colors as #hex, ordered by frequency."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return []
    try:
        im = Image.open(str(img_path)).convert("RGB")
        im.thumbnail((200, 200))
        q = im.quantize(colors=max(k, 2), method=Image.Quantize.FASTOCTREE)
        pal = q.getpalette() or []
        counts = q.getcolors() or []
        counts.sort(reverse=True)
        out: list[str] = []
        for _, idx in counts[:k]:
            r, g, b = pal[idx * 3: idx * 3 + 3]
            out.append(f"#{r:02x}{g:02x}{b:02x}")
        return out
    except Exception:  # noqa: BLE001
        return []


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(h: str) -> float:
    r, g, b = hex_to_rgb(h)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def saturation(h: str) -> float:
    r, g, b = (v / 255.0 for v in hex_to_rgb(h))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return 0.0
    return (mx - mn) / mx


def pick_palette(colors: list[str]) -> dict:
    """Assign semantic palette slots from a set of dominant colors."""
    if not colors:
        return {"ink": "#111114", "paper": "#ececec", "accent": "#c81414",
                "accent_dark": "#8b1a1a", "on_dark": "#ffffff", "muted": "#6b6b6b"}
    by_lum = sorted(colors, key=luminance)
    ink = by_lum[0]
    paper = by_lum[-1]
    candidates = [c for c in colors if 0.08 < luminance(c) < 0.92 and saturation(c) > 0.35]
    accent = max(candidates, key=saturation) if candidates else "#c81414"
    r, g, b = hex_to_rgb(accent)
    accent_dark = f"#{int(r * 0.6):02x}{int(g * 0.6):02x}{int(b * 0.6):02x}"
    grays = [c for c in colors if saturation(c) < 0.2 and 0.25 < luminance(c) < 0.75]
    muted = grays[0] if grays else "#6b6b6b"
    return {"ink": ink, "paper": paper, "accent": accent,
            "accent_dark": accent_dark, "on_dark": "#ffffff", "muted": muted}


# --------------------------------------------------------------------------- #
# Watermark / logo detection (temporal stability across frames)
# --------------------------------------------------------------------------- #
def _corner_of(cx: float, cy: float) -> str:
    v = "top" if cy < 0.34 else ("bottom" if cy > 0.66 else "center")
    h = "left" if cx < 0.34 else ("right" if cx > 0.66 else "center")
    if v == "center" and h == "center":
        return "center"
    return f"{v}_{h}"


def detect_watermark(frame_paths: list[str | Path], *, grid=(8, 6)) -> list[dict]:
    """Heuristic watermark/logo detector.

    A watermark stays put (low temporal variance) while having real structure
    (edges) even across hard cuts where the rest of the frame changes. We stack
    the scene frames, grade a grid of cells by ``edge_density / (1 + temporal_std)``
    and keep the high-scoring cells that sit in the border band (not dead-center),
    then merge adjacent winners into candidate boxes. Gemini confirms/describes.

    Returns a list of candidates: ``{bbox_norm:[x,y,w,h], corner, score}`` sorted
    by score. Degrades to ``[]`` when numpy/Pillow are missing or on any error.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # noqa: BLE001
        return []
    paths = [p for p in frame_paths if Path(p).exists()]
    if len(paths) < 3:
        return []
    W, H = 256, 256
    try:
        stack = []
        for p in paths[:24]:
            im = Image.open(str(p)).convert("L").resize((W, H))
            stack.append(np.asarray(im, dtype=np.float32) / 255.0)
        arr = np.stack(stack, axis=0)                     # (N, H, W)
    except Exception:  # noqa: BLE001
        return []
    tstd = arr.std(axis=0)                                 # per-pixel temporal std
    mean_img = arr.mean(axis=0)
    # Cheap edge density via gradient magnitude of the mean image.
    gy, gx = np.gradient(mean_img)
    edges = np.hypot(gx, gy)
    gcols, grows = grid
    cell_w, cell_h = W // gcols, H // grows
    cands: list[dict] = []
    for r in range(grows):
        for c in range(gcols):
            y0, x0 = r * cell_h, c * cell_w
            cell_std = float(tstd[y0:y0 + cell_h, x0:x0 + cell_w].mean())
            cell_edge = float(edges[y0:y0 + cell_h, x0:x0 + cell_w].mean())
            cx = (c + 0.5) / gcols
            cy = (r + 0.5) / grows
            border = (cx < 0.28 or cx > 0.72 or cy < 0.22 or cy > 0.78)
            if not border:
                continue
            score = cell_edge / (1.0 + 12.0 * cell_std)
            cands.append({"r": r, "c": c, "cx": cx, "cy": cy,
                          "edge": cell_edge, "tstd": cell_std, "score": score})
    if not cands:
        return []
    scores = sorted(x["score"] for x in cands)
    thr = scores[int(len(scores) * 0.85)] if len(scores) > 4 else scores[-1]
    winners = [x for x in cands if x["score"] >= thr and x["edge"] > 0.02]
    if not winners:
        return []
    # Merge winners by corner region into bounding boxes.
    by_corner: dict[str, list[dict]] = {}
    for w in winners:
        by_corner.setdefault(_corner_of(w["cx"], w["cy"]), []).append(w)
    out: list[dict] = []
    for corner, cells in by_corner.items():
        xs = [w["c"] for w in cells]
        ys = [w["r"] for w in cells]
        x = min(xs) / gcols
        y = min(ys) / grows
        ww = (max(xs) - min(xs) + 1) / gcols
        hh = (max(ys) - min(ys) + 1) / grows
        out.append({
            "corner": corner,
            "bbox_norm": [round(x, 3), round(y, 3), round(ww, 3), round(hh, 3)],
            "score": round(float(statistics.mean(w["score"] for w in cells)), 4),
        })
    out.sort(key=lambda d: d["score"], reverse=True)
    return out[:3]


# --------------------------------------------------------------------------- #
# Music-bed + voice-vs-music ducking measurement (from per-scene audio)
# --------------------------------------------------------------------------- #
_MUSIC_PROFILES = {"speech_with_music", "speech_mixed", "music_only", "ambient"}
_MUSIC_UNDER_SPEECH = {"speech_with_music", "speech_mixed"}


def measure_music(scenes: list[dict]) -> dict:
    """Estimate the reference's music + ducking style from the audio analysis.

    HEURISTIC (mixed audio is not source-separated): we read each scene's
    ``audio`` block (audio_profile + has_music_bed + levels) produced by
    video-scene-analysis and derive:
      - present     : any scene carries a music bed / music profile
      - coverage    : fraction of scenes with music present
      - under_speech: fraction of scenes where music co-occurs with speech
      - base_volume : a conservative bed level (0.06-0.16) for the remix, scaled
                      from the median non-speech RMS of the music scenes
      - structure   : "auto" (there is a voice to duck under) or "flat"
      - depth       : rough duck depth = 1 - speech_rms_music/non_speech_rms_music
    """
    if not scenes:
        return {"present": False, "coverage": 0.0, "under_speech": 0.0,
                "base_volume": 0.12, "structure": "flat", "depth": 0.0,
                "notes": "no scenes"}
    n = len(scenes)
    music_scenes, under = [], 0
    for s in scenes:
        a = s.get("audio") or {}
        prof = a.get("audio_profile")
        is_music = bool(a.get("has_music_bed")) or (prof in _MUSIC_PROFILES and prof != "ambient")
        if is_music:
            music_scenes.append(s)
        if prof in _MUSIC_UNDER_SPEECH:
            under += 1
    present = len(music_scenes) > 0
    coverage = round(len(music_scenes) / n, 3)
    under_speech = round(under / n, 3)
    ns_levels, sp_levels = [], []
    for s in music_scenes:
        lv = (s.get("audio") or {}).get("levels") or {}
        if lv.get("non_speech_rms"):
            ns_levels.append(float(lv["non_speech_rms"]))
        if lv.get("speech_rms"):
            sp_levels.append(float(lv["speech_rms"]))
    med_ns = statistics.median(ns_levels) if ns_levels else 0.0
    med_sp = statistics.median(sp_levels) if sp_levels else 0.0
    # Map measured non-speech (music-dominant) RMS to a conservative bed level.
    base_volume = round(min(0.16, max(0.06, med_ns * 1.4)) if med_ns else 0.12, 3)
    depth = 0.0
    if med_ns and med_sp and med_ns > 0:
        # Rough duck-depth proxy: how far the bed must sit under the voice. When
        # the voice is much louder than the ambient/music bed (ratio >> 1), a
        # deeper duck reads natural; when they're comparable, little/no ducking.
        ratio = med_sp / (med_ns + 1e-6)
        depth = round(max(0.0, min(0.85, 1.0 - 1.0 / max(1.0, ratio))), 3)
    structure = "auto" if (present and under_speech >= 0.25) else "flat"
    notes = ("music present under the voice -> low ducked bed with an auto envelope"
             if structure == "auto"
             else ("music present, mostly in non-speech beats" if present
                   else "no continuous music bed detected"))
    return {"present": present, "coverage": coverage, "under_speech": under_speech,
            "base_volume": base_volume, "structure": structure, "depth": depth,
            "notes": notes}


# --------------------------------------------------------------------------- #
# Transition SFX measurement (sounds AT the cuts) — mechanical
# --------------------------------------------------------------------------- #
def measure_transition_sfx(scenes: list[dict], *, boundary_window: float = 0.6,
                           present_coverage: float = 0.30, min_hits: int = 2) -> dict:
    """Measure whether the reference dresses its CUTS with transition SFX.

    A transition sound (whoosh / sting) sits right AT a scene boundary. We inspect
    each scene's mechanical audio (``has_sfx`` + ``sfx_events`` with absolute
    ``start``/``end``/``strength`` from video-scene-analysis) and count boundaries
    whose INCOMING scene carries an SFX event within ``boundary_window`` s of its
    start (or a trailing one on the OUTGOING scene). Returns present/coverage/kind/
    level so the remix enables inter-cut SFX only when the original actually uses
    them (instead of hardcoding them on every reel).
    """
    if not scenes or len(scenes) < 2:
        return {"present": False, "coverage": 0.0, "kind": "none", "level": 0.0,
                "count": 0, "notes": "no cuts to dress"}
    n_boundaries = len(scenes) - 1
    hits, levels = 0, []
    for i in range(1, len(scenes)):
        cur, prev = scenes[i], scenes[i - 1]
        a = cur.get("audio") or {}
        pa = prev.get("audio") or {}
        cstart = float(cur.get("start") or 0.0)
        pend = float(prev.get("end") or cstart)
        near = False
        for ev in (a.get("sfx_events") or []):
            est = float(ev.get("start") or ev.get("t") or 0.0)
            if abs(est - cstart) <= boundary_window:
                near = True
                levels.append(float(ev.get("strength") or 0.0))
                break
        if not near:
            for ev in (pa.get("sfx_events") or []):
                eend = float(ev.get("end") or ev.get("start") or 0.0)
                if abs(eend - pend) <= boundary_window:
                    near = True
                    levels.append(float(ev.get("strength") or 0.0))
                    break
        if near:
            hits += 1
    coverage = round(hits / n_boundaries, 3) if n_boundaries else 0.0
    med_lv = round(statistics.median(levels), 4) if levels else 0.0
    present = coverage >= present_coverage and hits >= min_hits
    notes = (f"~{hits}/{n_boundaries} cuts carry a boundary SFX"
             if hits else "cuts are clean (no boundary SFX detected)")
    return {"present": present, "coverage": coverage,
            "kind": "whoosh" if present else "none",
            "level": med_lv, "count": hits, "notes": notes}


# --------------------------------------------------------------------------- #
# Caption STYLE derivation (enums + ES/EN prose -> renderer-ready structure)
# --------------------------------------------------------------------------- #
# Multiword phrases first so "gris claro" wins over "gris".
_COLOR_PHRASES = [
    ("gris claro", "#e4e6e9"), ("gris clara", "#e4e6e9"),
    ("light gray", "#e4e6e9"), ("light grey", "#e4e6e9"),
    ("gris oscuro", "#3a3c40"), ("dark gray", "#3a3c40"), ("dark grey", "#3a3c40"),
    ("negro", "#141416"), ("negra", "#141416"), ("black", "#141416"),
    ("blanco", "#ffffff"), ("blanca", "#ffffff"), ("white", "#ffffff"),
    ("amarillo", "#ffd400"), ("amarilla", "#ffd400"), ("yellow", "#ffd400"),
    ("rojo", "#e5342b"), ("roja", "#e5342b"), ("red", "#e5342b"),
    ("verde", "#2ec26b"), ("green", "#2ec26b"),
    ("azul", "#2f6bff"), ("blue", "#2f6bff"),
    ("gris", "#8a8d91"), ("gray", "#8a8d91"), ("grey", "#8a8d91"),
]


def _first_color(text: str):
    t = (text or "").lower()
    best, besti = None, len(t) + 1
    for word, hexv in _COLOR_PHRASES:
        i = t.find(word)
        if 0 <= i < besti:
            besti, best = i, hexv
    return best


def _fg_bg_from_color(text: str):
    """Split a caption color phrase like 'negro sobre pastilla gris claro' into
    (foreground_ink_hex, background_hex)."""
    t = (text or "").lower()
    parts = re.split(r"\bsobre\b|\bon\b|\bcon fondo\b|\ben caja\b|\ben pastilla\b|\ben barra\b",
                     t, maxsplit=1)
    fg = _first_color(parts[0]) if parts else None
    bg = _first_color(parts[1]) if len(parts) > 1 else None
    return fg, bg


_CAPTION_BOX_WORDS = ("caja", "pastilla", "barra", "banda", "bar", "box", "pill",
                      "band", "rectáng", "rectang", "cápsula", "capsula", "chip",
                      "tarjeta", "card", "backing")
_CAPTION_ROUND_WORDS = ("redonde", "rounded", "pill", "cápsula", "capsula")
_CAPTION_SANS_WORDS = ("sans", "geométr", "geometr", "grotesk", "grotesque",
                       "helvetica", "inter", "neue", "roboto", "arial", "futura")
_CAPTION_NOEMPH_WORDS = ("sin énfasis", "sin enfasis", "no emphasis", "plano",
                         "uniforme", "sin resalt", "no highlight", "flat")

_CAPTION_Y_BY_POSITION = {"top": 0.14, "middle": 0.5, "center": 0.5,
                          "lower_third": 0.85, "bottom": 0.9}


def caption_emphasis_flag(caps: dict) -> bool:
    """True when the mold highlights key words (default), False when it uses a flat
    uniform caption block (e.g. 'Sin énfasis tipográfico')."""
    blob = " ".join(str((caps or {}).get(k) or "")
                    for k in ("emphasis", "style_notes")).lower()
    if any(w in blob for w in _CAPTION_NOEMPH_WORDS):
        return False
    return True


def derive_caption_style(caps: dict) -> dict:
    """Map a blueprint ``captions`` block (enums + ES/EN prose) to a STRUCTURED,
    renderer-ready style. Any structured fields already present in ``caps['style']``
    win. Safe when ``caps`` is empty (returns renderer defaults == today's look).
    """
    caps = caps or {}
    existing = dict(caps.get("style") or {})
    pos = (caps.get("position") or "").lower()
    y_default = _CAPTION_Y_BY_POSITION.get(pos, 0.85)
    blob = " ".join(str(caps.get(k) or "")
                    for k in ("color", "style_notes", "emphasis")).lower()

    # Font class (None -> caller keeps its current serif default).
    if "serif" in blob and "sans" not in blob:
        font_class = "serif"
    elif any(w in blob for w in _CAPTION_SANS_WORDS):
        font_class = "sans"
    else:
        font_class = None

    fg, bg_hex = _fg_bg_from_color(caps.get("color") or "")

    bg = dict(existing.get("background") or {})
    if not bg.get("kind"):
        if any(w in blob for w in _CAPTION_BOX_WORDS):
            bg["kind"] = "pill" if any(w in blob for w in _CAPTION_ROUND_WORDS) else "box"
        else:
            bg["kind"] = "none"
    if bg.get("kind") not in (None, "none"):
        if not bg.get("color_hex"):
            bg["color_hex"] = bg_hex or _first_color(caps.get("style_notes") or "") or "#e4e6e9"
        bg.setdefault("opacity", 0.92)
        bg.setdefault("radius_frac", 0.34 if bg["kind"] == "pill" else 0.12)

    has_box = bg.get("kind") not in (None, "none")
    text_color = existing.get("text_color_hex") or fg or ("#141416" if has_box else "#ffffff")

    return {
        "font_class": existing.get("font_class") or font_class,
        "text_color_hex": text_color,
        "y_frac": existing.get("y_frac", y_default),
        "align": existing.get("align") or "center",
        "background": bg,
    }


# --------------------------------------------------------------------------- #
# Environment / lighting / location aggregation (mold-level look)
# --------------------------------------------------------------------------- #
_WARDROBE_WORDS = ("blusa", "camisa", "camiseta", "polera", "chaqueta", "saco",
                   "traje", "vestido", "suéter", "sueter", "sweater", "turtleneck",
                   "cuello alto", "hoodie", "t-shirt", "tshirt", "shirt", "jacket",
                   "blazer", "dress", "abrigo", "corbata", "collar", "aretes",
                   "pendientes", "gafas", "lentes", "sombrero", "gorra", "bufanda",
                   "prenda", "outfit", "ropa", "top", "cardigan")

# On-screen graphics (burned-in captions / lower-thirds / watermarks) that vision
# reports as "elements" but are NOT physical set props — they must NOT be baked
# into a generated location still (captions are added later in finishing).
_UI_OVERLAY_WORDS = ("subtítulo", "subtitulo", "subtitle", "caption", "rótulo",
                     "rotulo", "lower third", "lower-third", "tercio inferior",
                     "texto en pantalla", "overlay", "marca de agua", "watermark")


_ENV_STOPWORDS = frozenset(
    "de del la el los las un una uno unos unas y o con sin sobre para por en al "
    "the a an of and or with without on for in to sin".split())


def _sig(text: str) -> frozenset:
    """A keyword signature (significant lowercased words) for near-dup detection."""
    words = re.findall(r"[a-záéíóúñ0-9]+", (text or "").lower())
    return frozenset(w for w in words if len(w) > 3 and w not in _ENV_STOPWORDS)


def _dedupe_similar(items: list[str], *, threshold: float = 0.6) -> list[str]:
    """Collapse near-duplicate phrases by Jaccard overlap of their signatures."""
    out: list[str] = []
    sigs: list[frozenset] = []
    for it in items:
        s = _sig(it)
        dup = False
        for prev in sigs:
            union = s | prev
            if union and len(s & prev) / len(union) >= threshold:
                dup = True
                break
        if not dup:
            out.append(it)
            sigs.append(s)
    return out


def aggregate_environment(scenes: list[dict], design_system: dict | None = None) -> dict:
    """Aggregate per-scene backgrounds + elements + the design system into ONE
    mold-level look: background, lighting, wardrobe, the key set elements to carry
    over, and any distinct alternate looks. A deterministic fallback the remix can
    use to build a matching avatar-location even without vision synthesis.
    """
    from collections import Counter
    design_system = design_system or {}
    bg_descs: list[str] = []
    elements: list[str] = []
    wardrobe: list[str] = []
    types: Counter = Counter()
    off_type_descs: list[str] = []
    for s in scenes or []:
        b = s.get("background") or {}
        t = (b.get("type") or "").strip()
        if t:
            types[t] += 1
        el = (b.get("elements") or "").strip()
        if el and el.lower() not in [x.lower() for x in bg_descs]:
            bg_descs.append(el)
        for e in (s.get("elements") or []):
            e = (e or "").strip()
            if not e:
                continue
            low = e.lower()
            if any(w in low for w in _UI_OVERLAY_WORDS):
                continue  # burned-in caption/watermark graphic, not a set prop
            bucket = wardrobe if any(w in low for w in _WARDROBE_WORDS) else elements
            if e not in bucket:
                bucket.append(e)
    bg_type = types.most_common(1)[0][0] if types else "unknown"
    # An alternate look is a scene whose background TYPE differs from the dominant
    # one (e.g. plain studio vs a real set) — NOT mere adjective variation of the
    # same look. This keeps a single-look mold (all "black studio") from spawning
    # spurious per-scene locations.
    for s in scenes or []:
        b = s.get("background") or {}
        if (b.get("type") or "").strip() and (b.get("type") or "").strip() != bg_type:
            d = (b.get("elements") or "").strip()
            if d:
                off_type_descs.append(d)
    bg_unique = _dedupe_similar(bg_descs)
    distinct = _dedupe_similar(off_type_descs)
    return {
        "background": (bg_unique[0] if bg_unique else bg_type),
        "background_type": bg_type,
        "lighting": (design_system.get("visual_style") or "").strip(),
        "mood": (design_system.get("mood") or "").strip(),
        "wardrobe": "; ".join(_dedupe_similar(wardrobe)[:4]),
        "set_elements": _dedupe_similar(elements)[:6],
        "key_elements": _dedupe_similar(elements + wardrobe)[:8],
        "distinct_looks": distinct,
    }


# --------------------------------------------------------------------------- #
# Camera-move normalization (analysis vocabulary -> avatar-camera-angles catalog)
# --------------------------------------------------------------------------- #
CAMERA_MOVES = ("eye_level", "push_in", "pull_out", "low_angle", "high_angle",
                "three_quarter", "three_quarter_mirror", "profile", "dutch_tilt",
                "negative_space_left", "negative_space_right", "pip")
_MOVE_ALIASES = {
    "negative_space": "negative_space_left", "zoom_in": "push_in",
    "zoom_out": "pull_out", "low_angle_v2": "low_angle", "center": "eye_level",
    "centered": "eye_level", "medium": "eye_level", "medium_shot": "eye_level",
    "straight_on": "eye_level", "": "eye_level", None: "eye_level",
}


def normalize_move(m):
    """Map an analysis/beat move token to a valid avatar-camera-angles move."""
    if m in CAMERA_MOVES:
        return m
    return _MOVE_ALIASES.get(m, "eye_level")


def normalize_moves(moves, *, always=("eye_level",)) -> list[str]:
    """A de-duplicated, catalog-valid move list (always includes ``always``)."""
    out: list[str] = []
    for m in list(always) + list(moves or []):
        nm = normalize_move(m)
        if nm not in out:
            out.append(nm)
    return out


# --------------------------------------------------------------------------- #
# Text utilities
# --------------------------------------------------------------------------- #
def slugify(text: str, maxlen: int = 60, default: str = "video") -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:maxlen] or default


# --------------------------------------------------------------------------- #
# JSON IO
# --------------------------------------------------------------------------- #
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


def rel_to(path, base) -> str:
    """Path relative to base when possible, else absolute (keeps JSON portable)."""
    path = Path(path).resolve()
    base = Path(base).resolve()
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def resolve_path(raw, base) -> Path:
    p = Path(str(raw)).expanduser()
    return p if p.is_absolute() else (Path(base) / p).resolve()


# --------------------------------------------------------------------------- #
# Process / checkpoints / sibling-CLI bridge
# --------------------------------------------------------------------------- #
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
