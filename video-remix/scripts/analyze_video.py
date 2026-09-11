#!/usr/bin/env python3
"""Analyze a reference video and extract a reusable visual+narrative+audio MOLD.

This is the "pdf-remix for video": it deconstructs a premium reel/short so we can
replicate its exact structure with brand-new content.

It fuses three signal sources (like analyze_pdf.py):
  1. Mechanical  — ffprobe geometry (WxH, fps, duration, aspect -> format) +
     video-scene-analysis (scene cuts, transcript + word timings, per-scene
     SFX/music detection, one representative frame per scene) + pixel-accurate
     per-scene / global palette (Pillow) + a temporal-stability watermark/logo
     detector + a music-bed & voice-vs-music ducking measurement.
  2. Vision (Gemini) — per-scene semantics: layout (split/pip/overlay + regions),
     on-screen people + which speaks + GAZE, camera angle/framing, action type,
     background (real/animated), scene elements, color combination, and any
     watermark / caption visible in the frame.
  3. Synthesis (Gemini) — a final pass over representative frames + the per-scene
     summary + the mechanical audio facts that names the global design system
     (palette semantics, color combinations, mood), the caption system, the
     brand/watermark system (where/how it appears + disappears), the music +
     ducking mood, the transition style, the number of distinct speakers/avatars
     needed, and the intro->development->close narrative arc.

Outputs (under --out-dir, default runs/<slug>/):
  frames/scene_XX.jpg      representative frames (reference)
  blueprint.json           machine-readable mold (design + rhythm + per-scene + arc + beats)
  blueprint.md             human-readable mold
  content_template.json    pre-filled skeleton to author NEW content onto the mold

Usage:
  python3 analyze_video.py "/path/to/reference.mp4" [--out-dir runs/mine] \
      [--language es] [--max-scenes N] [--no-vision]
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# analysis camera.angle slug -> avatar-camera-angles move (kept in sync with
# reel-restyle/scripts/_angle_map.py; inlined so video-remix stays self-contained).
ANGLE_TO_MOVE = {
    "eye_level": "eye_level", "low_angle": "low_angle", "low_angle_v2": "low_angle",
    "high_angle": "high_angle", "three_quarter": "three_quarter",
    "dutch_tilt": "dutch_tilt", "negative_space": "negative_space_left",
    "pull_out": "pull_out", "zoom_in": "push_in", "none": None,
}


def move_for_angle(angle):
    if angle is None:
        return "eye_level"
    return ANGLE_TO_MOVE.get(angle, "eye_level")


SCENE_INSTRUCTION = (
    "Eres director de arte y editor de video. Te muestro UN fotograma representativo de una escena "
    "de un reel / video corto de alta calidad. Analiza su composicion para poder REPLICAR el molde con "
    "contenido nuevo. Responde SOLO con JSON valido con esta forma exacta:\n"
    "{\n"
    '  "scene_kind": "talking_head|broll",\n'
    '  "layout": {"type":"fullscreen|split_horizontal|split_vertical|pip|overlay_graphics",'
    '"regions":[{"position":"top|bottom|left|right|inset|full","content":"broll|main_character|screen|graphics","description":"que se ve"}]},\n'
    '  "people_count": 0,\n'
    '  "speaker_present": true,\n'
    '  "speaker_position": "left|right|center|full|none",\n'
    '  "gaze": "to_lens|off_left|off_right|down|up|profile|none",\n'
    '  "camera": {"angle":"eye_level|low_angle|low_angle_v2|high_angle|three_quarter|dutch_tilt|negative_space|pull_out|zoom_in|none",'
    '"framing":"extreme_close_up|close_up|medium_close_up|medium_shot|medium_wide|wide_shot|unknown"},\n'
    '  "action_type": "talking|gesturing|demonstrating|walking|reacting|product_focus|scenery|screen_demo|none",\n'
    '  "broll_kind": "archival_known_person|archival_footage|stock_generic|screen_recording|graphics_animation|other|null",\n'
    '  "background": {"type":"real_set|animated|mixed|plain|virtual|unknown","elements":"que hay detras"},\n'
    '  "elements": ["objetos/props/texto notables en la escena"],\n'
    '  "color_combo": "combinacion de colores dominante de esta escena en 3-6 palabras",\n'
    '  "watermark": {"present": false, "position":"top_left|top_right|bottom_left|bottom_right|center|none", "description":"logo/handle/texto si lo hay"},\n'
    '  "captions": {"present": false, "position":"top|middle|lower_third|bottom", "casing":"upper|subtitle|sentence", "color":"ej blanco con borde", "style":"descripcion breve"},\n'
    '  "role_hint": "hook|intro|body|point|transition|cta|close"\n'
    "}\n"
    "Se preciso con scene_kind (talking_head = presentador hablando a camara; broll = inserto de apoyo). "
    "Responde en espanol en los campos de texto."
)

SYNTH_INSTRUCTION = (
    "Eres director de arte y estratega de contenido. A partir de estos fotogramas representativos de un "
    "reel/video y del resumen de todas sus escenas + datos mecanicos (formato, duracion, musica), define el "
    "MOLDE reutilizable. Responde SOLO con JSON valido:\n"
    "{\n"
    '  "design_system": {\n'
    '    "palette_semantics": {"ink":"uso","paper":"uso","accent":"uso (color de marca)","on_dark":"uso","muted":"uso"},\n'
    '    "color_combinations": ["combinaciones de color recurrentes por escena"],\n'
    '    "mood": "tono/estetica dominante en 2-5 palabras",\n'
    '    "visual_style": "descripcion del look (grano, iluminacion, saturacion, tipo de encuadre)"\n'
    "  },\n"
    '  "captions": {"present":true,"position":"lower_third|middle|top|bottom","casing":"subtitle|upper|sentence",'
    '"reveal":"word|phrase","words_per_caption":5,"color":"ej blanco con sombra","emphasis":"como se resaltan palabras clave","style_notes":"tipografia/estilo"},\n'
    '  "watermark": {"present":false,"kind":"logo|handle|text|none","position":"top_left|top_right|bottom_left|bottom_right|center|none",'
    '"appears":"throughout|after_intro|on_cta|intermittent","disappears":"never|before_cta|between_cuts","description":"que es y como aparece/desaparece"},\n'
    '  "audio": {"music_mood":"tono de la musica de fondo (o none)","voice_music_relation":"como conviven voz y musica (ducking, bed bajo, sin musica)"},\n'
    '  "transitions": {"style":"hard_cut|golden_flash|white_flash|dip_black|mixed|none","notes":"donde y como"},\n'
    '  "speakers": {"count":1,"roles":["host"],"notes":"cuantas personas distintas hablan y su papel"},\n'
    '  "narrative_arc": {"type":"tipo de video y estrategia","voice":"persona/tono de la narracion",'
    '"open":"como abre (intro/hook)","develop":"como desarrolla","close":"como cierra (cta/outro)",'
    '"beats":["secuencia de momentos narrativos de principio a fin"]},\n'
    '  "rhythm_notes": "ritmo de cortes y como sostiene la atencion",\n'
    '  "replication_notes": ["3-6 reglas clave para que el video nuevo iguale o supere al original"]\n'
    "}\n"
    "Responde en espanol."
)

ROLE_ORDER = ["hook", "intro", "body", "point", "transition", "cta", "close"]


def _load_mechanical(video: Path, out_dir: Path, language: str | None,
                     scene_mode: str) -> dict:
    """Run video-scene-analysis to get scenes + transcript + audio + frames."""
    mech_dir = out_dir / "_mech"
    mech_dir.mkdir(parents=True, exist_ok=True)
    stem = video.stem
    analysis_path = mech_dir / f"{stem}.analysis.json"
    if not analysis_path.exists():
        cmd = [C.PY, str(C.ANALYZE_VIDEO), str(video), "-o", str(mech_dir),
               "--scene-mode", scene_mode]
        if language:
            cmd += ["--language", language]
        rc = C.run_child(cmd, desc="video-scene-analysis: scenes + transcript + audio + frames")
        if rc != 0:
            C.stop("video-scene-analysis failed.", [
                "Ensure its deps + models are installed:",
                "  pip3 install -r " + str(C.skill_path("video-scene-analysis/scripts/requirements.txt")),
                "  bash " + str(C.skill_path("video-scene-analysis/scripts/setup_models.sh")),
            ], code=1)
    data = C.try_load_json(analysis_path)
    if not data:
        C.stop("Could not read the mechanical analysis.", [str(analysis_path)], code=1)
    return data


def _frame_path(mech_dir: Path, scene: dict) -> Path | None:
    rf = (scene.get("representative_frame") or {}).get("file")
    if not rf:
        return None
    p = Path(rf)
    return p if p.is_absolute() else (mech_dir / p)


def _cut_rhythm(median_dur: float) -> str:
    if median_dur <= 3.5:
        return "fast"
    if median_dur <= 6.0:
        return "medium"
    return "slow"


def _dur_weight(scene: dict, total: float) -> float:
    d = float(scene.get("duration") or 0)
    return round(d / total, 4) if total else round(1.0 / max(1, 1), 4)


def build_beats(scenes: list[dict], enriched: list[dict]) -> list[dict]:
    """Derive the per-scene beat list the remix consumes (like a reel_template)."""
    total = sum(float(s.get("duration") or 0) for s in scenes) or 1.0
    beats: list[dict] = []
    for i, (s, e) in enumerate(zip(scenes, enriched)):
        kind = e.get("scene_kind") or (
            "talking_head" if s.get("scene_type") == "main_character_solo" else "broll")
        angle = (e.get("camera") or {}).get("angle") or (s.get("camera") or {}).get("angle")
        zfp = (s.get("zoom_from_previous") or {}).get("type", "none")
        role = e.get("role_hint") or ("hook" if i == 0 else ("close" if i == len(scenes) - 1 else "body"))
        beat = {
            "index": i,
            "role": role,
            "type": kind,
            "speaker": "host" if kind == "talking_head" else None,
            "dur_weight": _dur_weight(s, total),
            "zoom_from_previous": zfp,
            "emphasis": bool(zfp == "zoom_in"),
            "gaze": e.get("gaze"),
            "audio_profile": (s.get("audio") or {}).get("audio_profile"),
            "has_music": bool((s.get("audio") or {}).get("has_music_bed")),
            "focus": (e.get("action_type") or "") + (
                (" - " + ", ".join(e.get("elements") or [])) if e.get("elements") else ""),
        }
        if kind == "talking_head":
            beat["camera_angle"] = angle
            beat["framing"] = (e.get("camera") or {}).get("framing")
            beat["move"] = move_for_angle(angle)
            beat["location_hint"] = ((e.get("background") or {}).get("elements") or "").strip()
        else:
            beat["broll_camera"] = {"zoom_in": "push_in", "zoom_out": "pull_out"}.get(zfp, "push_in")
            beat["broll_hint"] = (e.get("color_combo") or "") + " | " + ", ".join(e.get("elements") or [])
        beats.append(beat)
    return beats


def build_content_template(blueprint: dict) -> dict:
    """Editable skeleton to author NEW content onto the mold."""
    beats = blueprint.get("beats", [])
    speakers = blueprint.get("speakers", {}) or {}
    n_speakers = max(1, int(speakers.get("count") or 1))
    roles = speakers.get("roles") or (["host"] + [f"guest{i}" for i in range(1, n_speakers)])
    audio = blueprint.get("audio", {}) or {}
    caps = blueprint.get("captions", {}) or {}
    music = audio.get("music", {}) or {}
    tpl_beats = []
    for b in beats:
        entry = {
            "index": b["index"],
            "role": b.get("role"),
            "type": b.get("type"),
            "speaker": b.get("speaker"),
            "text": "",
        }
        if b.get("type") in ("broll",):
            entry["broll_description"] = ""
            entry["broll_action"] = ""
        if b.get("type") == "talking_head":
            entry["location_hint"] = b.get("location_hint", "")
        tpl_beats.append(entry)
    avatars = []
    for r in roles[:n_speakers]:
        avatars.append({
            "role": r,
            "use": None,                 # e.g. "avatares/nora" to reuse an existing avatar
            "invent": None,              # e.g. {"description": "...", "setting": "studio", "language": "es"}
            "voice_id": None,
        })
    return {
        "_comment": "Author NEW content onto the video mold. Fill `script` with the FULL verbatim "
                    "narration (its words are split across beats), set `avatars` (reuse existing "
                    "avatares/<name> via `use`, or `invent` a new one), author every B-roll beat, and "
                    "keep/tune `music`+`captions` (pre-filled from the mold). Concatenating every beat "
                    "`text` must equal `script` verbatim.",
        "meta": {
            "topic": "",
            "language": blueprint.get("transcript_language") or "es",
            "format": blueprint.get("geometry", {}).get("format", "reel"),
            "slug": "",
        },
        "brand": {"name": "", "handle": "", "logo_path": "", "palette_override": {}},
        "avatars": avatars,
        "music": {
            "enabled": bool(music.get("present", True)),
            "mood": "ambient",
            "prompt": "",               # TAILOR to the new topic + the mold's music_mood
            "structure": music.get("structure", "flat"),
            "volume": music.get("base_volume", 0.12),
        },
        "captions": {
            "reveal": caps.get("reveal", "word"),
            "max_words": int(caps.get("words_per_caption") or 6),
            "casing": caps.get("casing", "subtitle"),
            "style_from": "",           # optional subtitle_style.json path
        },
        "script": "",
        "beats": tpl_beats,
    }


def render_md(bp: dict) -> str:
    g = bp.get("geometry", {})
    ds = bp.get("design_system", {})
    pal = ds.get("palette", {})
    sem = ds.get("palette_semantics", {})
    rh = bp.get("rhythm", {})
    arc = bp.get("narrative_arc", {})
    caps = bp.get("captions", {})
    wm = bp.get("watermark", {})
    audio = bp.get("audio", {})
    music = audio.get("music", {})
    spk = bp.get("speakers", {})
    L = ["# Molde del video (blueprint para replicar)", ""]
    L.append(f"**Fuente:** `{Path(bp['source_video']).name}`  ·  {rh.get('total_scenes', '?')} escenas  ·  "
             f"{g.get('aspect_ratio', '?')} ({g.get('format', '?')})  ·  {g.get('duration', '?')}s  ·  {g.get('fps', '?')}fps")
    L.append("")
    L.append("## Sistema de diseño")
    L.append("")
    L.append("### Paleta")
    L.append("| Slot | Color | Uso |")
    L.append("| --- | --- | --- |")
    for slot in ("ink", "paper", "accent", "accent_dark", "on_dark", "muted"):
        if slot in pal:
            L.append(f"| {slot} | `{pal[slot]}` | {sem.get(slot, '')} |")
    L.append("")
    if ds.get("mood"):
        L.append(f"**Mood:** {ds['mood']}  ·  **Look:** {ds.get('visual_style', '')}")
        L.append("")
    if ds.get("color_combinations"):
        L.append("**Combinaciones de color:** " + "; ".join(ds["color_combinations"][:8]))
        L.append("")
    L.append("## Ritmo")
    L.append(f"- Escenas: {rh.get('total_scenes')} ({rh.get('talking_head')} talking-head, {rh.get('broll')} B-roll)")
    L.append(f"- Duración de escena (mediana): {rh.get('median_scene_dur')}s  ·  hook: {rh.get('hook_dur')}s  ·  ritmo: {rh.get('cut_rhythm')}")
    if rh.get("notes"):
        L.append(f"- {rh['notes']}")
    L.append("")
    L.append("## Captions")
    if caps.get("present"):
        L.append(f"- Posición: {caps.get('position')}  ·  casing: {caps.get('casing')}  ·  reveal: {caps.get('reveal')}  ·  ~{caps.get('words_per_caption')} palabras")
        L.append(f"- Color/estilo: {caps.get('color', '')} — {caps.get('style_notes', '')}")
        L.append(f"- Énfasis: {caps.get('emphasis', '')}")
    else:
        L.append("- Sin captions quemados detectados.")
    L.append("")
    L.append("## Marca / watermark")
    if wm.get("present"):
        L.append(f"- {wm.get('kind', 'logo')} en {wm.get('position')}  ·  aparece: {wm.get('appears')}  ·  desaparece: {wm.get('disappears')}")
        L.append(f"- {wm.get('description', '')}")
    else:
        L.append("- Sin watermark/logo persistente detectado.")
    L.append("")
    L.append("## Audio / música")
    L.append(f"- Música: {'sí' if music.get('present') else 'no'} "
             f"(cobertura {music.get('coverage')}, bajo voz {music.get('under_speech')})")
    L.append(f"- Ducking/estructura: {music.get('structure')} — {music.get('notes', '')}")
    L.append(f"- Mood musical: {audio.get('music_mood', '')}  ·  Voz vs música: {audio.get('voice_music_relation', '')}")
    L.append("")
    L.append("## Transiciones")
    tr = bp.get("transitions", {})
    L.append(f"- Estilo: {tr.get('style', '')} — {tr.get('notes', '')}")
    L.append("")
    L.append("## Presentadores / avatares necesarios")
    L.append(f"- {spk.get('count', 1)} — roles: {', '.join(spk.get('roles', ['host']))}")
    if spk.get("notes"):
        L.append(f"- {spk['notes']}")
    L.append("")
    L.append("## Arco narrativo")
    if arc.get("type"):
        L.append(f"**Tipo:** {arc['type']}  ·  **Voz:** {arc.get('voice', '')}")
    L.append(f"- **Abre:** {arc.get('open', '')}")
    L.append(f"- **Desarrolla:** {arc.get('develop', '')}")
    L.append(f"- **Cierra:** {arc.get('close', '')}")
    if arc.get("beats"):
        L.append("")
        L.append("**Beats:**")
        for i, b in enumerate(arc["beats"], 1):
            L.append(f"{i}. {b}")
    L.append("")
    if bp.get("replication_notes"):
        L.append("## Reglas para igualar o superar el original")
        notes = bp["replication_notes"]
        for nnote in ([notes] if isinstance(notes, str) else notes):
            L.append(f"- {nnote}")
        L.append("")
    L.append("## Mapa de escenas")
    L.append("| # | Tipo | Rol | Ángulo | Layout | Gaze | Dur (peso) | Foco |")
    L.append("| ---: | --- | --- | --- | --- | --- | --- | --- |")
    for b in bp.get("beats", []):
        L.append(f"| {b['index']} | {b.get('type')} | {b.get('role')} | "
                 f"{b.get('camera_angle') or '—'} | "
                 f"{(bp['scenes'][b['index']].get('layout') or {}).get('type', '—') if b['index'] < len(bp.get('scenes', [])) else '—'} | "
                 f"{b.get('gaze') or '—'} | {b.get('dur_weight')} | {b.get('focus', '')[:40]} |")
    L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract a reusable visual+narrative+audio mold from a video")
    ap.add_argument("video", help="Path to the reference video (mp4/mov/webm)")
    ap.add_argument("--out-dir", help="Output dir (default runs/<slug>)")
    ap.add_argument("--language", "-l", default=None, help="Transcription language (es, en, ...)")
    ap.add_argument("--scene-mode", default="auto", choices=["auto", "detect", "interval"])
    ap.add_argument("--max-scenes", type=int, default=40, help="Cap per-scene vision calls")
    ap.add_argument("--no-vision", action="store_true", help="Skip Gemini vision (mechanical only)")
    args = ap.parse_args()

    video = Path(args.video).expanduser()
    if not video.exists():
        print(f"Error: video not found: {video}", file=sys.stderr)
        sys.exit(1)

    slug = C.slugify(video.stem)
    out_dir = Path(args.out_dir) if args.out_dir else (C.SKILL_DIR / "runs" / slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    geom = C.video_geometry(video)
    print(f"Geometry: {geom['width']}x{geom['height']} ({geom['aspect_ratio']} -> {geom['format']}), "
          f"{geom['duration']}s @ {geom['fps']}fps", file=sys.stderr)

    mech = _load_mechanical(video, out_dir, args.language, args.scene_mode)
    mech_dir = out_dir / "_mech"
    scenes = mech.get("scenes", [])
    if not scenes:
        C.stop("No scenes detected in the reference.", [str(video)], code=1)

    # Copy representative frames into the run and gather palette per scene.
    scene_colors: list[str] = []
    frame_map: dict[int, Path] = {}
    for s in scenes:
        src = _frame_path(mech_dir, s)
        idx = s.get("index", 0)
        dest = frames_dir / f"scene_{idx:02d}.jpg"
        if src and src.exists():
            try:
                shutil.copyfile(src, dest)
                frame_map[idx] = dest
            except Exception:  # noqa: BLE001
                frame_map[idx] = src
        cols = C.dominant_colors(frame_map.get(idx, src) if (src and src.exists()) else "", k=5) if src else []
        s["dominant_colors"] = cols
        scene_colors += cols

    # Global palette.
    seen, uniq = set(), []
    for c in scene_colors:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    palette = C.pick_palette(uniq)

    # Watermark candidates (temporal stability).
    wm_cands = C.detect_watermark([frame_map.get(s.get("index", 0)) for s in scenes if s.get("index", 0) in frame_map])

    # Music / ducking measurement.
    music = C.measure_music(scenes)

    # Per-scene Gemini enrichment.
    client = None if args.no_vision else C.genai_client()
    enriched: list[dict] = []
    for i, s in enumerate(scenes):
        idx = s.get("index", i)
        e: dict = {}
        img = frame_map.get(idx)
        if client is not None and img and Path(img).exists() and i < args.max_scenes:
            print(f"  vision: scene {i + 1}/{len(scenes)}", file=sys.stderr)
            e = C.vision_json(client, SCENE_INSTRUCTION, [Path(img)]) or {}
        # Merge Gemini enrichment back into the scene object for the blueprint.
        s["layout"] = e.get("layout") or s.get("layout") or {"type": "fullscreen", "regions": []}
        s["camera"] = e.get("camera") or s.get("camera")
        s["gaze"] = e.get("gaze")
        s["elements"] = e.get("elements") or []
        s["color_combo"] = e.get("color_combo")
        s["scene_watermark"] = e.get("watermark")
        s["scene_captions"] = e.get("captions")
        s["background"] = e.get("background") or s.get("background")
        s["broll_kind"] = e.get("broll_kind") or s.get("broll_kind")
        s["action_type"] = e.get("action_type")
        enriched.append(e)

    # Rhythm.
    durs = [float(s.get("duration") or 0) for s in scenes]
    n_th = sum(1 for i, s in enumerate(scenes)
               if (enriched[i].get("scene_kind") or
                   ("talking_head" if s.get("scene_type") == "main_character_solo" else "broll")) == "talking_head")
    median_dur = round(statistics.median(durs), 2) if durs else 0.0
    rhythm = {
        "total_scenes": len(scenes),
        "talking_head": n_th,
        "broll": len(scenes) - n_th,
        "median_scene_dur": median_dur,
        "avg_scene_dur": round(statistics.mean(durs), 2) if durs else 0.0,
        "hook_dur": round(durs[0], 2) if durs else 0.0,
        "cut_rhythm": _cut_rhythm(median_dur),
        "notes": "",
    }

    # Beats for the remix.
    beats = build_beats(scenes, enriched)

    # Assemble a first-pass blueprint (mechanical), then synthesize the global mold.
    blueprint = {
        "source_video": str(video),
        "geometry": geom,
        "transcript_language": (mech.get("transcript") or {}).get("language"),
        "design_system": {
            "palette": palette,
            "palette_semantics": {},
            "color_combinations": [],
            "mood": "",
            "visual_style": "",
        },
        "rhythm": rhythm,
        "captions": {"present": any((e.get("captions") or {}).get("present") for e in enriched)},
        "watermark": {"present": bool(wm_cands) or any((e.get("watermark") or {}).get("present") for e in enriched),
                      "candidates": wm_cands},
        "audio": {"music": music, "music_mood": "", "voice_music_relation": ""},
        "transitions": {"style": "", "notes": ""},
        "speakers": {"count": 1, "roles": ["host"], "notes": ""},
        "narrative_arc": {},
        "replication_notes": [],
        "scenes": scenes,
        "beats": beats,
    }

    if client is not None:
        rep_idx = sorted(set([0, len(scenes) // 4, len(scenes) // 2,
                              3 * len(scenes) // 4, len(scenes) - 1]))
        rep_imgs = [frame_map[scenes[i]["index"]] for i in rep_idx
                    if i < len(scenes) and scenes[i].get("index") in frame_map]
        scene_summ = "\n".join(
            f"s{b['index']}: [{b['type']}/{b.get('role')}] dur_w={b['dur_weight']} "
            f"angle={b.get('camera_angle')} gaze={b.get('gaze')} "
            f"{(scenes[b['index']].get('transcript') or '')[:80]}"
            for b in beats)
        facts = (f"Formato: {geom['aspect_ratio']} ({geom['format']}), {geom['duration']}s, {geom['fps']}fps.\n"
                 f"Ritmo: {rhythm['total_scenes']} escenas, mediana {rhythm['median_scene_dur']}s, "
                 f"hook {rhythm['hook_dur']}s ({rhythm['cut_rhythm']}).\n"
                 f"Musica (medida): present={music['present']} coverage={music['coverage']} "
                 f"under_speech={music['under_speech']} structure={music['structure']}.\n"
                 f"Watermark (candidatos): {wm_cands}\n"
                 f"Escenas:\n{scene_summ}")
        synth = C.vision_json(client, SYNTH_INSTRUCTION, rep_imgs, extra=facts)
        if synth:
            ds = synth.get("design_system", {})
            blueprint["design_system"]["palette_semantics"] = ds.get("palette_semantics", {})
            blueprint["design_system"]["color_combinations"] = ds.get("color_combinations", [])
            blueprint["design_system"]["mood"] = ds.get("mood", "")
            blueprint["design_system"]["visual_style"] = ds.get("visual_style", "")
            caps = synth.get("captions", {})
            caps["present"] = caps.get("present", blueprint["captions"]["present"])
            blueprint["captions"] = caps
            wm = synth.get("watermark", {})
            wm["candidates"] = wm_cands
            blueprint["watermark"] = wm
            aud = synth.get("audio", {})
            blueprint["audio"]["music_mood"] = aud.get("music_mood", "")
            blueprint["audio"]["voice_music_relation"] = aud.get("voice_music_relation", "")
            blueprint["transitions"] = synth.get("transitions", blueprint["transitions"])
            spk = synth.get("speakers", {})
            if spk:
                blueprint["speakers"] = spk
            blueprint["narrative_arc"] = synth.get("narrative_arc", {})
            blueprint["rhythm"]["notes"] = synth.get("rhythm_notes", "")
            blueprint["replication_notes"] = synth.get("replication_notes", [])

    # Re-tag beat roles from the arc-informed pass would go here; keep the vision role_hint.
    (out_dir / "blueprint.json").write_text(
        json.dumps(blueprint, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "blueprint.md").write_text(render_md(blueprint), encoding="utf-8")

    content_tpl = build_content_template(blueprint)
    (out_dir / "content_template.json").write_text(
        json.dumps(content_tpl, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "out_dir": str(out_dir),
        "scenes": len(scenes),
        "used_vision": client is not None,
        "format": geom["format"],
        "aspect_ratio": geom["aspect_ratio"],
        "speakers": blueprint["speakers"].get("count", 1),
        "music": music["present"],
        "watermark": blueprint["watermark"].get("present", False),
        "artifacts": ["blueprint.json", "blueprint.md", "content_template.json",
                      f"frames/ ({len(frame_map)} imgs)"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
