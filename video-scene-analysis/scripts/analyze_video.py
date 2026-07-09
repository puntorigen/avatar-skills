#!/usr/bin/env python3
"""Analyze a local video: scenes, types, zoom, transcript, per-scene summaries.

Outputs:
  <stem>.analysis.json  — structured sequence
  <stem>.analysis.md    — human-readable report

Usage:
    python3 scripts/analyze_video.py lolo/videos/clip.mp4
    python3 scripts/analyze_video.py lolo/videos/clip.mp4 -o ./out --interval 6
    python3 scripts/analyze_video.py lolo/videos/clip.mp4 --whisper-model tiny
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from _face import FaceAnalyzer, format_timestamp, get_video_info  # noqa: E402
from _audio_events import AUDIO_PROFILES, analyze_all_scenes  # noqa: E402
from _camera_vocabulary import (  # noqa: E402
    CAMERA_ANGLE_IDS,
    CAMERA_ANGLE_LABELS_ES,
    CAMERA_FRAMINGS,
)

SCENE_TYPES = {
    "main_character_solo": "Personaje principal solo (talking head)",
    "multi_person": "Varias personas en cámara",
    "supplementary_material": "Material complementario (B-roll, inserts)",
    "screen_demo": "Demo / captura de pantalla",
    "unknown": "Sin clasificar",
}

# Agent-written taxonomies (rendered in the report; see SKILL.md for guidance).
LAYOUT_TYPES = {
    "fullscreen": "Pantalla completa",
    "split_horizontal": "Pantalla dividida (horizontal: B-roll arriba/abajo + personaje)",
    "split_vertical": "Pantalla dividida (vertical: lado a lado)",
    "pip": "Picture-in-picture (recuadro)",
    "overlay_graphics": "Gráficos superpuestos sobre el plano",
}

BROLL_KINDS = {
    "archival_known_person": "Archivo / pregrabado con persona reconocible",
    "archival_footage": "Material pregrabado real (personas no célebres)",
    "stock_generic": "Stock / complementario genérico",
    "screen_recording": "Captura de pantalla / demo",
    "graphics_animation": "Gráficos / animación",
    "other": "Otro",
}

BACKGROUND_TYPES = {
    "real_set": "Escenografía / locación real",
    "animated": "Fondo animado (dibujos / cartoons / motion graphics)",
    "mixed": "Mixto (real + elementos animados)",
    "plain": "Fondo plano / liso",
    "virtual": "Fondo virtual / croma",
    "unknown": "Sin determinar",
}

KEYFRAME_QUALITY = 90


def to_json_safe(obj):
    if isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def ffprobe_video(video_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path),
    ]
    raw = subprocess.check_output(cmd, text=True)
    data = json.loads(raw)
    fmt = data.get("format", {})
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fps_raw = vstream.get("avg_frame_rate", "30/1")
    if "/" in str(fps_raw):
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    else:
        fps = float(fps_raw or 30)
    duration = float(fmt.get("duration") or 0)
    width = int(vstream.get("width") or 0)
    height = int(vstream.get("height") or 0)
    return {
        "duration": duration,
        "fps": fps,
        "width": width,
        "height": height,
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    }


def detect_scenes_pyscenedetect(
    video_path: Path,
    *,
    min_scene_len_frames: int = 15,
    adaptive_threshold: float = 3.0,
) -> list[tuple[float, float]]:
    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import AdaptiveDetector
    except ImportError as exc:
        raise RuntimeError(
            "scenedetect not installed. Run: pip3 install 'scenedetect[opencv]'"
        ) from exc

    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(
        AdaptiveDetector(
            adaptive_threshold=adaptive_threshold,
            min_scene_len=min_scene_len_frames,
        )
    )
    manager.detect_scenes(video=video, show_progress=False)
    scene_list = manager.get_scene_list()
    if not scene_list:
        info = ffprobe_video(video_path)
        return [(0.0, info["duration"])] if info["duration"] > 0 else []
    return [(float(s.seconds), float(e.seconds)) for s, e in scene_list]


def scenes_by_interval(duration: float, interval: float) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    scenes = []
    start = 0.0
    while start < duration - 0.05:
        end = min(duration, start + interval)
        if end - start >= 0.25:
            scenes.append((start, end))
        start = end
    return scenes


def merge_short_scenes(
    scenes: list[tuple[float, float]],
    *,
    min_duration: float,
) -> list[tuple[float, float]]:
    if not scenes:
        return scenes
    merged = [scenes[0]]
    for start, end in scenes[1:]:
        prev_s, prev_e = merged[-1]
        if (end - start) < min_duration:
            merged[-1] = (prev_s, end)
        else:
            merged.append((start, end))
    return merged


def read_frame(cap: cv2.VideoCapture, timestamp: float):
    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
    ok, frame = cap.read()
    return frame if ok else None


def pick_representative_frame(cap: cv2.VideoCapture, start: float, end: float):
    """Return sharpest frame among 25% / 50% / 75% of the scene window."""
    if end - start < 0.15:
        t = start + (end - start) / 2.0
        frame = read_frame(cap, t)
        return frame, t, 0.0

    candidates = []
    for frac in (0.25, 0.5, 0.75):
        t = start + (end - start) * frac
        frame = read_frame(cap, t)
        if frame is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        candidates.append((sharpness, t, frame))

    if not candidates:
        t = start + (end - start) / 2.0
        frame = read_frame(cap, t)
        return frame, t, 0.0

    sharpness, t, frame = max(candidates, key=lambda item: item[0])
    return frame, t, sharpness


def save_representative_frame(frame, frames_dir: Path, scene_index: int, timestamp: float) -> Path:
    frames_dir.mkdir(parents=True, exist_ok=True)
    filename = f"scene_{scene_index + 1:02d}.jpg"
    filepath = frames_dir / filename
    cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, KEYFRAME_QUALITY])
    return filepath


def format_camera_lines(scene: dict) -> list[str]:
    cam = scene.get("camera")
    if not cam:
        return ["- **Cámara:** _Pendiente: analizar frame representativo._"]
    angle_id = cam.get("angle") or "unknown"
    angle_label = CAMERA_ANGLE_LABELS_ES.get(angle_id, angle_id)
    framing_id = cam.get("framing", "unknown")
    framing_label = CAMERA_FRAMINGS.get(framing_id, framing_id)
    lines = [f"- **Cámara:** `{angle_id}` — {angle_label} · {framing_label}"]
    if cam.get("description"):
        lines.append(f"- **Notas cámara:** {cam['description']}")
    return lines


def format_composition_lines(scene: dict) -> list[str]:
    """Render the agent-written composition fields: layout (split-screen / pip),
    B-roll kind (archival-known-person vs generic), recognizable people, and the
    presenter's background (real set vs animated)."""
    out: list[str] = []

    layout = scene.get("layout") or {}
    ltype = layout.get("type")
    hint = layout.get("hint")
    if ltype and ltype != "fullscreen":
        line = f"- **Composición:** {LAYOUT_TYPES.get(ltype, ltype)}"
        regions = layout.get("regions") or []
        if regions:
            bits = "; ".join(
                f"{r.get('position', '?')}: {r.get('content', '?')}" for r in regions
            )
            line += f" — {bits}"
        out.append(line)
        if layout.get("notes"):
            out.append(f"- **Notas composición:** {layout['notes']}")
    elif not ltype and hint and hint != "fullscreen":
        out.append(
            f"- **Composición:** _Pendiente — el script sospecha `{hint}`; "
            "confirmar en el frame (¿B-roll + personaje en una misma escena?)._"
        )

    bk = scene.get("broll_kind")
    if bk:
        out.append(f"- **Tipo de B-roll:** {BROLL_KINDS.get(bk, bk)}")

    people = scene.get("known_people")
    if people:
        people_str = ", ".join(str(p) for p in people) if isinstance(people, list) else str(people)
        out.append(f"- **Personas reconocibles:** {people_str}")

    bg = scene.get("background")
    if isinstance(bg, dict) and (bg.get("type") or bg.get("elements")):
        line = f"- **Fondo:** {BACKGROUND_TYPES.get(bg.get('type'), bg.get('type') or 'n/d')}"
        if bg.get("elements"):
            line += f" — {bg['elements']}"
        out.append(line)
        if bg.get("notes"):
            out.append(f"- **Notas fondo:** {bg['notes']}")

    return out


def score_frame(frame) -> dict:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F).var()
    edges = cv2.Canny(gray, 80, 160)
    edge_ratio = float(edges.mean() / 255.0)
    brightness = float(gray.mean() / 255.0)
    return {
        "blur_score": round(min(1.0, lap / 800.0), 3),
        "edge_ratio": round(edge_ratio, 3),
        "brightness": round(brightness, 3),
    }


def classify_scene_type(
    *,
    face_count: int,
    faces: list[dict],
    edge_ratio: float,
    motion_score: float,
) -> str:
    primary_face = faces[0] if faces else None
    if face_count == 1 and primary_face and primary_face["area_ratio"] >= 0.05:
        return "main_character_solo"
    if face_count >= 2:
        return "multi_person"
    if edge_ratio >= 0.12 and face_count == 0:
        return "screen_demo"
    if face_count == 0:
        return "supplementary_material"
    if face_count == 1 and primary_face and primary_face["area_ratio"] < 0.05:
        return "supplementary_material"
    return "unknown"


def _hist_corr(a, b) -> float:
    ha = cv2.calcHist([a], [0], None, [64], [0, 256])
    hb = cv2.calcHist([b], [0], None, [64], [0, 256])
    return float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))


def detect_split_layout_hint(frame, faces: list[dict]) -> str:
    """Cheap, CONSERVATIVE hint for split-screen composition (e.g. B-roll stacked
    over the presenter, or side-by-side). The agent confirms and details the
    layout from the representative frame — this only flags an obvious seam so a
    split scene is never silently read as a normal full-screen talking head.

    Returns one of: ``fullscreen`` (default), ``possible_split_horizontal``,
    ``possible_split_vertical``. A split needs BOTH a strong straight seam near
    the middle AND clearly different content on each side (low half-to-half
    histogram correlation), so an ordinary background gradient won't trip it.
    """
    h, w = frame.shape[:2]
    if h < 16 or w < 16:
        return "fullscreen"
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # A real split has a HARD seam: one mid-frame line whose cross-line jump is
    # large in absolute terms (>~12 gray levels) AND much sharper than the rest
    # of the frame. The absolute floor avoids false positives on smooth
    # brightness gradients (where the row-to-row delta is tiny everywhere).
    SEAM_ABS, SEAM_REL = 12.0, 5.0

    top, bottom = gray[: h // 2, :], gray[h // 2:, :]
    if _hist_corr(top, bottom) < 0.5:
        rowdiff = np.abs(np.diff(gray.astype(np.int16), axis=0)).mean(axis=1)
        baseline = max(float(np.median(rowdiff)), 2.0)
        band = rowdiff[int(0.30 * h): int(0.70 * h)]
        peak = float(band.max()) if band.size else 0.0
        if peak > SEAM_ABS and peak / baseline > SEAM_REL:
            return "possible_split_horizontal"

    left, right = gray[:, : w // 2], gray[:, w // 2:]
    if _hist_corr(left, right) < 0.5:
        coldiff = np.abs(np.diff(gray.astype(np.int16), axis=1)).mean(axis=0)
        baseline = max(float(np.median(coldiff)), 2.0)
        cband = coldiff[int(0.30 * w): int(0.70 * w)]
        peak = float(cband.max()) if cband.size else 0.0
        if peak > SEAM_ABS and peak / baseline > SEAM_REL:
            return "possible_split_vertical"

    return "fullscreen"


def score_motion(cap: cv2.VideoCapture, start: float, end: float, samples: int = 4) -> float:
    if end - start < 0.4:
        return 0.0
    n = max(2, samples)
    times = [start + (end - start) * i / (n - 1) for i in range(n)]
    prev_gray = None
    diffs = []
    for t in times:
        frame = read_frame(cap, t)
        if frame is None:
            continue
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None:
            diffs.append(float(cv2.absdiff(gray, prev_gray).mean()))
        prev_gray = gray
    if not diffs:
        return 0.0
    return round(min(1.0, sum(diffs) / len(diffs) / 30.0), 3)


def estimate_zoom_orb(prev_gray, curr_gray) -> tuple[str, float | None]:
    orb = cv2.ORB_create(800)
    kp1, des1 = orb.detectAndCompute(prev_gray, None)
    kp2, des2 = orb.detectAndCompute(curr_gray, None)
    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        return "none", None

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    if len(matches) < 8:
        return "none", None

    matches = sorted(matches, key=lambda m: m.distance)[:80]
    pts1 = np.float32([kp1[m.queryIdx].pt for m in matches])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in matches])

    dist1 = np.linalg.norm(pts1 - pts1.mean(axis=0), axis=1).mean()
    dist2 = np.linalg.norm(pts2 - pts2.mean(axis=0), axis=1).mean()
    if dist1 < 1e-3:
        return "none", None

    scale = dist2 / dist1
    if scale > 1.10:
        return "zoom_in", round(scale, 3)
    if scale < 0.90:
        return "zoom_out", round(scale, 3)
    return "none", round(scale, 3)


def detect_zoom_transition(
    prev_frame,
    curr_frame,
    prev_faces: list[dict],
    curr_faces: list[dict],
) -> dict:
    if prev_frame is None or curr_frame is None:
        return {"type": "none", "confidence": 0.0, "scale": None}

    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)

    hist_corr = cv2.compareHist(
        cv2.calcHist([prev_gray], [0], None, [64], [0, 256]),
        cv2.calcHist([curr_gray], [0], None, [64], [0, 256]),
        cv2.HISTCMP_CORREL,
    )
    if hist_corr < 0.35:
        return {"type": "hard_cut", "confidence": round(1 - hist_corr, 3), "scale": None}

    if (
        len(prev_faces) == 1
        and len(curr_faces) == 1
        and prev_faces[0]["area_ratio"] > 0.03
        and curr_faces[0]["area_ratio"] > 0.03
    ):
        scale = curr_faces[0]["area_ratio"] / prev_faces[0]["area_ratio"]
        if scale > 1.12:
            return {"type": "zoom_in", "confidence": 0.75, "scale": round(scale, 3)}
        if scale < 0.88:
            return {"type": "zoom_out", "confidence": 0.75, "scale": round(scale, 3)}
        return {"type": "none", "confidence": 0.6, "scale": round(scale, 3)}

    zoom_type, scale = estimate_zoom_orb(prev_gray, curr_gray)
    conf = 0.55 if zoom_type != "none" else 0.4
    return {"type": zoom_type, "confidence": conf, "scale": scale}


def extract_audio_wav(video_path: Path, wav_path: Path) -> bool:
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(wav_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 0


def transcribe_local(
    audio_path: Path,
    *,
    language: str | None,
    model_size: str,
) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip3 install faster-whisper"
        ) from exc

    print(f"  Transcribiendo con faster-whisper ({model_size})...", file=sys.stderr)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    lang = (language or "").strip().lower()[:2] or None
    segments_iter, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        language=lang,
        vad_filter=True,
    )

    segments = []
    words = []
    for seg in segments_iter:
        seg_words = []
        for w in seg.words or []:
            ww = {"word": (w.word or "").strip(), "start": w.start, "end": w.end}
            if ww["word"]:
                seg_words.append(ww)
                words.append(ww)
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": (seg.text or "").strip(),
            "words": seg_words,
        })

    return {
        "language": getattr(info, "language", lang),
        "duration": round(getattr(info, "duration", 0) or 0, 3),
        "segments": segments,
        "words": words,
    }


def transcript_for_scene(segments: list[dict], start: float, end: float) -> str:
    parts = []
    for seg in segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        parts.append(seg["text"])
    return " ".join(parts).strip()


def format_summary_lines(scene: dict) -> tuple[str, str]:
    summary = scene.get("summary") or {}
    focus = summary.get("focus")
    emotion = summary.get("emotion")
    if not focus:
        focus = "_Pendiente: el agente debe completar el foco._"
    if not emotion:
        emotion = "_pendiente_"
    return focus, emotion


def render_markdown(data: dict) -> str:
    info = data["video_info"]
    lines = [
        f"# Análisis de video: {data['video_name']}",
        "",
        f"- **Archivo:** `{data['video_path']}`",
        f"- **Duración:** {format_timestamp(info['duration'])} ({info['duration']:.1f}s)",
        f"- **Resolución:** {info['width']}x{info['height']} @ {info['fps']:.1f} fps",
        f"- **Escenas detectadas:** {len(data['scenes'])}",
        f"- **Modo escenas:** {data['scene_detection']['mode']}",
        f"- **Generado:** {data['analyzed_at']}",
        "",
        "## Resumen",
        "",
        data.get("overview") or "_Sin resumen global._",
        "",
    ]

    profile = data.get("avatar_profile")
    if profile:
        lines.extend(["## Perfil del avatar (talking head)", ""])
        if profile.get("mannerisms_summary"):
            lines.append(f"- **Gestos / microexpresiones:** {profile['mannerisms_summary']}")
        if profile.get("video_prompt"):
            lines.append(f"- **video_prompt (p-video-avatar):** {profile['video_prompt']}")
        if profile.get("negative_prompt"):
            lines.append(f"- **negative_prompt:** {profile['negative_prompt']}")
        lines.append("")

    lines.extend(["## Escenas", ""])

    for scene in data["scenes"]:
        zoom = scene["zoom_from_previous"]
        zoom_label = zoom["type"]
        if zoom.get("scale") is not None:
            zoom_label += f" (scale≈{zoom['scale']})"
        focus, emotion = format_summary_lines(scene)
        audio = scene.get("audio") or {}
        audio_profile = audio.get("audio_profile", "unknown")
        audio_label = AUDIO_PROFILES.get(audio_profile, audio_profile)
        lines.extend([
            f"### Escena {scene['index'] + 1} — {format_timestamp(scene['start'])} → {format_timestamp(scene['end'])}",
            "",
            f"- **Tipo:** {SCENE_TYPES.get(scene['scene_type'], scene['scene_type'])}",
            f"- **Duración:** {scene['duration']:.1f}s",
            f"- **Zoom vs anterior:** {zoom_label}",
            f"- **Audio:** {audio_label}",
        ])
        if audio.get("has_sfx") and audio.get("sfx_event_count", 0) > 0:
            lines.append(f"- **SFX detectados:** {audio['sfx_event_count']} evento(s)")
        lines.extend(format_camera_lines(scene))
        lines.extend(format_composition_lines(scene))
        rf = scene.get("representative_frame") or {}
        if rf.get("file"):
            lines.append(f"- **Frame:** `{rf['file']}` @ `{rf.get('timestamp_fmt', '')}`")
        lines.extend([
            f"- **Foco:** {focus}",
            f"- **Emoción:** {emotion}",
        ])
        if scene.get("mannerisms"):
            lines.append(f"- **Gestos faciales:** {scene['mannerisms']}")
        lines.append("")
        if scene.get("transcript"):
            lines.extend([
                "**Transcripción:**",
                "",
                f"> {scene['transcript']}",
                "",
            ])
        else:
            lines.append("_Sin diálogo en este tramo._")
            lines.append("")

    if data.get("transcript", {}).get("segments"):
        lines.extend(["## Transcripción completa", ""])
        for seg in data["transcript"]["segments"]:
            lines.append(
                f"- `{format_timestamp(seg['start'])}` {seg['text']}"
            )
        lines.append("")

    return "\n".join(lines)


def build_overview(scenes: list[dict]) -> str:
    if not scenes:
        return "No se detectaron escenas."
    types = {}
    for s in scenes:
        types[s["scene_type"]] = types.get(s["scene_type"], 0) + 1
    type_bits = ", ".join(f"{SCENE_TYPES.get(k, k)}: {v}" for k, v in types.items())
    spoken = sum(1 for s in scenes if s.get("transcript"))
    sfx_scenes = sum(1 for s in scenes if (s.get("audio") or {}).get("has_sfx"))
    bits = (
        f"Secuencia de {len(scenes)} escenas ({spoken} con diálogo, {sfx_scenes} con SFX). "
        f"Distribución visual: {type_bits}."
    )
    # Agent-written composition signals (only surface once the agent has filled them).
    splits = sum(1 for s in scenes if (s.get("layout") or {}).get("type") in
                 ("split_horizontal", "split_vertical", "pip"))
    archival = sum(1 for s in scenes if s.get("broll_kind") in
                   ("archival_known_person", "archival_footage"))
    split_hints = sum(1 for s in scenes
                      if (s.get("layout") or {}).get("type") is None
                      and (s.get("layout") or {}).get("hint", "fullscreen") != "fullscreen")
    extra = []
    if splits:
        extra.append(f"{splits} con pantalla dividida/PiP")
    if archival:
        extra.append(f"{archival} con material pregrabado de archivo")
    if extra:
        bits += " Composición: " + ", ".join(extra) + "."
    elif split_hints:
        bits += f" ({split_hints} posible(s) split por confirmar)."
    return bits


def write_analysis_outputs(result: dict, output_dir: Path, stem: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.analysis.json"
    md_path = output_dir / f"{stem}.analysis.md"
    json_path.write_text(
        json.dumps(to_json_safe(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, md_path


def analyze_video(
    video_path: Path,
    *,
    output_dir: Path,
    scene_mode: str = "auto",
    interval: float = 6.0,
    min_scene_duration: float = 2.5,
    adaptive_threshold: float = 3.0,
    language: str | None = None,
    whisper_model: str = "small",
    skip_transcription: bool = False,
    skip_audio_events: bool = False,
    skip_frames: bool = False,
) -> dict:
    video_path = video_path.resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    stem = video_path.stem
    output_dir = output_dir.resolve()
    frames_dir = output_dir / f"{stem}_frames"

    info = ffprobe_video(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    cv_info = get_video_info(cap)

    fps = info["fps"] or cv_info["fps"] or 30.0
    min_scene_len_frames = max(8, int(round(interval * fps * 0.45)))

    if scene_mode == "interval":
        raw_scenes = scenes_by_interval(info["duration"], interval)
        mode_used = "interval"
    elif scene_mode == "detect":
        raw_scenes = detect_scenes_pyscenedetect(
            video_path,
            min_scene_len_frames=min_scene_len_frames,
            adaptive_threshold=adaptive_threshold,
        )
        mode_used = "detect"
    else:
        raw_scenes = detect_scenes_pyscenedetect(
            video_path,
            min_scene_len_frames=min_scene_len_frames,
            adaptive_threshold=adaptive_threshold,
        )
        mode_used = "detect"
        if len(raw_scenes) <= 1 and info["duration"] >= interval:
            raw_scenes = scenes_by_interval(info["duration"], interval)
            mode_used = "interval_fallback"

    raw_scenes = merge_short_scenes(raw_scenes, min_duration=min_scene_duration)

    face_analyzer = FaceAnalyzer()
    scenes_out = []
    prev_frame = None
    prev_faces: list[dict] = []

    try:
        for idx, (start, end) in enumerate(raw_scenes):
            frame, frame_ts, frame_sharpness = pick_representative_frame(cap, start, end)
            if frame is None:
                continue

            faces, face_count = face_analyzer.analyze(frame)
            metrics = score_frame(frame)
            motion = score_motion(cap, start, end)
            scene_type = classify_scene_type(
                face_count=face_count,
                faces=faces,
                edge_ratio=metrics["edge_ratio"],
                motion_score=motion,
            )
            zoom = detect_zoom_transition(prev_frame, frame, prev_faces, faces)

            scene_entry = {
                "index": idx,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "scene_type": scene_type,
                "zoom_from_previous": zoom if idx > 0 else {"type": "none", "confidence": 1.0, "scale": None},
                "visual": {
                    "face_count": face_count,
                    "faces": faces,
                    "motion_score": motion,
                    **metrics,
                },
                "camera": None,
                # Screen composition. `hint` is the script's conservative guess;
                # the agent sets `type` + `regions` from the representative frame.
                "layout": {
                    "type": None,
                    "regions": [],
                    "hint": detect_split_layout_hint(frame, faces),
                    "notes": None,
                },
            }

            if not skip_frames:
                frame_path = save_representative_frame(frame, frames_dir, idx, frame_ts)
                try:
                    frame_rel = str(frame_path.relative_to(output_dir))
                except ValueError:
                    frame_rel = str(frame_path)
                scene_entry["representative_frame"] = {
                    "file": frame_rel,
                    "timestamp": round(frame_ts, 3),
                    "timestamp_fmt": format_timestamp(frame_ts),
                    "sharpness": round(frame_sharpness, 2),
                }

            scenes_out.append(scene_entry)

            prev_frame = frame
            prev_faces = faces
    finally:
        face_analyzer.close()
        cap.release()

    transcript = {"language": None, "duration": 0, "segments": [], "words": []}
    if info.get("has_audio", True):
        with tempfile.TemporaryDirectory(prefix="video_analysis_") as tmp:
            wav_path = Path(tmp) / "audio.wav"
            if extract_audio_wav(video_path, wav_path):
                if not skip_transcription:
                    transcript = transcribe_local(
                        wav_path, language=language, model_size=whisper_model,
                    )
                if not skip_audio_events:
                    print("  Analizando capas de audio (voz / SFX / música)...", file=sys.stderr)
                    audio_analyses = analyze_all_scenes(
                        wav_path, scenes_out, transcript.get("words", []),
                    )
                    for scene, audio in zip(scenes_out, audio_analyses):
                        scene["audio"] = audio
            else:
                print("  Warning: no audio extracted; skipping transcription", file=sys.stderr)

    for scene in scenes_out:
        scene["transcript"] = transcript_for_scene(
            transcript["segments"], scene["start"], scene["end"],
        )
        scene["summary"] = None
        # Agent-written for talking-head scenes: how the face/head moves
        # (expressions, gestures). Stays null for B-roll / non-presenter shots.
        scene["mannerisms"] = None
        # Agent-written (vision). For B-roll / supplementary scenes: what KIND of
        # footage it is — distinguishes pre-recorded archival of a recognizable
        # person from generic complementary material. null for pure talking-head.
        scene["broll_kind"] = None
        # Agent-written: recognizable real people shown in pre-recorded footage
        # (names or short descriptions). null/[] when none or not recognizable.
        scene["known_people"] = None
        # Agent-written for presenter scenes: is the background a real set/location
        # or animated (drawings/cartoons/motion graphics)? null for B-roll.
        scene["background"] = None

    result = {
        "version": 1,
        "video_name": video_path.name,
        "video_path": str(video_path),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "frames_dir": str(frames_dir.relative_to(output_dir)) if not skip_frames and frames_dir.exists() else None,
        "video_info": {
            "duration": round(info["duration"], 3),
            "duration_fmt": format_timestamp(info["duration"]),
            "fps": round(fps, 3),
            "width": info["width"],
            "height": info["height"],
            "has_audio": info.get("has_audio", True),
        },
        "scene_detection": {
            "mode": mode_used,
            "interval_sec": interval,
            "min_scene_duration_sec": min_scene_duration,
            "adaptive_threshold": adaptive_threshold,
        },
        "transcript": transcript,
        # Agent-written: a reusable per-avatar talking profile synthesized from
        # the talking-head scenes' mannerisms. Exported to <avatar>/talking_profile.json
        # by export_talking_profile.py for the avatar-talking-video skill.
        "avatar_profile": None,
        "scenes": scenes_out,
    }
    result["overview"] = build_overview(scenes_out)

    json_path, md_path = write_analysis_outputs(result, output_dir, stem)

    print(f"\nWrote {json_path}", file=sys.stderr)
    print(f"Wrote {md_path}", file=sys.stderr)
    if not skip_frames and frames_dir.exists():
        n_frames = len(list(frames_dir.glob("scene_*.jpg")))
        print(f"Wrote {n_frames} frame(s) to {frames_dir}/", file=sys.stderr)
    print(json.dumps({
        "json": str(json_path),
        "markdown": str(md_path),
        "frames_dir": str(frames_dir) if not skip_frames and frames_dir.exists() else None,
        "scenes": len(scenes_out),
        "transcript_segments": len(transcript["segments"]),
    }, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description="Analyze a local video into scenes + transcript")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument(
        "-o", "--output-dir",
        default=str(Path.cwd()),
        help="Output directory for .analysis.json and .analysis.md (default: cwd)",
    )
    parser.add_argument(
        "--scene-mode",
        choices=["auto", "detect", "interval"],
        default="auto",
        help="Scene detection strategy (default: auto)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=6.0,
        help="Target scene length in seconds for interval/fallback modes (default: 6)",
    )
    parser.add_argument(
        "--min-scene-duration",
        type=float,
        default=2.5,
        help="Merge scenes shorter than this (default: 2.5s)",
    )
    parser.add_argument(
        "--adaptive-threshold",
        type=float,
        default=3.0,
        help="PySceneDetect AdaptiveDetector threshold (default: 3.0)",
    )
    parser.add_argument("--language", "-l", default=None, help="Transcription language (es, en, ...)")
    parser.add_argument(
        "--whisper-model",
        default="small",
        help="faster-whisper model size (default: small; use tiny for quick tests)",
    )
    parser.add_argument("--skip-transcription", action="store_true", help="Skip audio extraction/transcription")
    parser.add_argument("--skip-audio-events", action="store_true", help="Skip SFX/music detection per scene")
    parser.add_argument("--skip-frames", action="store_true", help="Skip representative frame extraction")
    args = parser.parse_args()

    analyze_video(
        Path(args.video),
        output_dir=Path(args.output_dir),
        scene_mode=args.scene_mode,
        interval=args.interval,
        min_scene_duration=args.min_scene_duration,
        adaptive_threshold=args.adaptive_threshold,
        language=args.language,
        whisper_model=args.whisper_model,
        skip_transcription=args.skip_transcription,
        skip_audio_events=args.skip_audio_events,
        skip_frames=args.skip_frames,
    )


if __name__ == "__main__":
    main()
