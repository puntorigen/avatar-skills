---
name: video-scene-analysis
description: >-
  Analyze local video files (mp4, mov, webm) into scene sequences: scene-change
  detection, scene type (talking head vs B-roll), split-screen /
  screen-composition detection (B-roll band + presenter, picture-in-picture,
  graphic overlays), B-roll kind (archival footage of a recognizable/known
  person vs generic material, naming the people), presenter background (real
  set/location vs animated/cartoons/motion graphics), zoom in/out vs previous
  scene, faster-whisper transcription with timecodes, SFX/music-bed detection
  per scene, a representative frame per scene, and per-scene focus/emotion
  summaries. Outputs .analysis.json, .analysis.md, and a frames folder. Use when
  the user asks to analyze a video, detect scenes, camera angle, split-screen
  layouts, archival/known-person footage, animated vs real backgrounds,
  transcribe a local video, detect SFX or background music, build a shot list
  from footage, or understand reel/avatar video structure.
---

# Video Scene Analysis

Analyze a local video into a structured scene sequence: cuts, visual type, zoom transitions, transcript with timecodes, and per-scene focus/emotion.

## Setup (one-time)

```bash
pip3 install -r ~/.cursor/skills/video-scene-analysis/scripts/requirements.txt
bash ~/.cursor/skills/video-scene-analysis/scripts/setup_models.sh
```

Requires `ffmpeg` and `ffprobe` on PATH.

## Quick start

```bash
SCRIPTS=~/.cursor/skills/video-scene-analysis/scripts

python3 $SCRIPTS/analyze_video.py video.mp4 -o .
python3 $SCRIPTS/analyze_video.py lolo/videos/clip.mp4 -o ./analysis --language es
```

Outputs in `-o` directory (default: cwd):

- `{stem}.analysis.json` — machine-readable sequence
- `{stem}.analysis.md` — human-readable report
- `{stem}_frames/scene_XX.jpg` — one sharp representative frame per scene

## Agent workflow (mandatory)

The script handles **steps 1–4** (visual + audio + frames + a conservative split-screen `layout.hint`). **You** (the active session LLM) must complete **steps 5–10** (camera, composition, summaries, mannerisms, avatar profile) by viewing the frames before delivering results. Do **not** call Gemini or any external LLM API.

1. Confirm video path and output directory.
2. Run setup if models or deps are missing.
3. Run `analyze_video.py` → JSON with `"summary": null` and `"camera": null` per scene, plus `{stem}_frames/`.
4. **Read each `representative_frame` image** (use the Read tool on every `scene_XX.jpg`). Classify camera for each scene and write `scenes[].camera`:
   ```json
   {
     "angle": "eye_level | low_angle | low_angle_v2 | high_angle | three_quarter | dutch_tilt | negative_space | pull_out | zoom_in | none",
     "framing": "extreme_close_up | close_up | medium_close_up | medium_shot | medium_wide | wide_shot | unknown",
     "description": "Nota breve en español (encuadre vertical, selfie, etc.)"
   }
   ```
   **`angle` must be an English pipeline slug** (snake_case), aligned with avatar prompts in `lolo/angles/prompts/` when applicable. Use `eye_level` for baseline frontal talking head; `none` for B-roll that does not map to the pipeline. Cross-check `zoom_from_previous` (`zoom_in` / `zoom_out` → consider `zoom_in` / `pull_out` slugs on presenter shots).
5. **Composition (every scene — while you have the frame open).** From the same
   `scene_XX.jpg`, fill the agent-written composition fields. The script
   pre-fills `scenes[].layout.hint` (`fullscreen` / `possible_split_horizontal` /
   `possible_split_vertical`) as a conservative guess you must confirm or correct.
   - **`scenes[].layout`** — screen composition (see *Layout taxonomy*):
     ```json
     {
       "type": "fullscreen | split_horizontal | split_vertical | pip | overlay_graphics",
       "regions": [
         { "position": "top|bottom|left|right|inset", "content": "broll|main_character|screen|graphics",
           "description": "qué se ve en esa región" }
       ],
       "notes": "breve, en español"
     }
     ```
     **Always inspect for split scenes:** a single scene that shows **B-roll in
     one band (top or bottom) and the main character talking in the other** is
     `split_horizontal` (side-by-side is `split_vertical`; a small inset is `pip`).
     List one entry per region. For a normal single shot use `"fullscreen"` with
     empty `regions`.
   - **`scenes[].broll_kind`** (B-roll / supplementary scenes, AND any B-roll
     region of a split — see *B-roll kind taxonomy*). Distinguish **pre-recorded
     archival footage of a recognizable person** (`archival_known_person`) from
     generic complementary material (`stock_generic`). null for pure talking-head.
   - **`scenes[].known_people`** — array of recognizable real people shown in
     pre-recorded footage (names if you recognize them, else short descriptions
     like "older male chef, 2000s TV interview"). `[]`/null when none or unsure.
   - **`scenes[].background`** (presenter / talking-head scenes — see *Background
     taxonomy*): is the person's backdrop a **real set/location** or **animated**
     (drawings, cartoons, motion graphics)?
     ```json
     { "type": "real_set | animated | mixed | plain | virtual | unknown",
       "elements": "qué hay detrás (p.ej. 'dibujos animados de nubes', 'oficina real')",
       "notes": "opcional" }
     ```
     null for B-roll / non-presenter scenes.
6. Read the JSON metadata. For **every** scene, write `scenes[].summary` using:
   - `transcript`, `scene_type`, `layout`, `zoom_from_previous`, `visual`, `camera`, `audio`
7. **Facial mannerisms (talking-head only).** For each `main_character_solo`
   scene (including the presenter band of a split), while you have the frame
   open, write `scenes[].mannerisms`: a brief (one sentence) note of how the
   face/head moves — eyebrow activity, head nods/tilts, eye contact,
   mouth/expression, lean, gesture restraint. Leave `null` for B-roll /
   non-presenter scenes.
8. **Avatar profile (talking head).** Synthesize the talking-head mannerisms
   into a single reusable `avatar_profile` (top-level), consistent across the
   video, with:
   ```json
   {
     "mannerisms_summary": "1-2 sentence description of the recurring facial behavior",
     "video_prompt": "Concise p-video-avatar prompt describing how this person naturally speaks to camera (identity-consistent, present tense)",
     "negative_prompt": "very brief, comma-separated failure modes to avoid (e.g. exaggerated gestures, big toothy grin, looking away, jittery head movement, subtitles, watermark)"
   }
   ```
   Keep `video_prompt` short and behavior-focused; keep `negative_prompt`
   **brevísimo**. If the video has no talking-head scenes, leave `avatar_profile` null.
9. Optionally rewrite `overview` (1–2 sentences, Spanish) with the narrative arc.
10. Re-render markdown:
   ```bash
   python3 $SCRIPTS/render_report.py path/to/{stem}.analysis.json
   ```
11. Present the final `.analysis.md` to the user.

**Never skip steps 4–10.** Heuristic or API-based summaries/classification are intentionally not used.

### Export the talking profile (for avatar-talking-video)

Once `avatar_profile` is written, export it to the avatar folder so the
`avatar-talking-video` skill auto-loads it for every generated talking-head clip:

```bash
python3 $SCRIPTS/export_talking_profile.py path/to/{stem}.analysis.json
# → writes <avatar>/talking_profile.json (avatar dir auto-inferred; override with --avatar-dir)
```

Pass several analyses to pick the first with a profile; preview with `--dry-run`.

### Batch

Run the script for each video, then enrich each JSON before re-rendering:

```bash
SCRIPTS=~/.cursor/skills/video-scene-analysis/scripts
OUT=./analysis
mkdir -p "$OUT"
for f in lolo/videos/*.mp4; do
  python3 $SCRIPTS/analyze_video.py "$f" -o "$OUT" --language es
done
# → enrich each $OUT/*.analysis.json, then render_report.py on each
```

## Script options

| Option | Default | Description |
|--------|---------|-------------|
| `-o DIR` | cwd | Output directory |
| `--scene-mode` | `auto` | `auto`, `detect` (PySceneDetect), `interval` (fixed windows) |
| `--interval` | `6` | Target scene length (4/6/8) for interval/fallback |
| `--min-scene-duration` | `2.5` | Merge shorter scenes |
| `--language` | auto | Transcription language (`es`, `en`, …) |
| `--whisper-model` | `small` | `tiny` (fast), `small`, `medium`, `large-v3` |
| `--skip-transcription` | off | Visual-only analysis |
| `--skip-audio-events` | off | Skip SFX/music detection |
| `--skip-frames` | off | Skip representative frame extraction |

## Camera taxonomy (agent-written)

### `camera.angle` — English pipeline slug (primary)

| Slug | Meaning |
|------|---------|
| `eye_level` | Frontal baseline, cámara a altura de ojos |
| `low_angle` | Contrapicado leve (~16°) |
| `low_angle_v2` | Contrapicado pronunciado (variante v2) |
| `high_angle` | Picado |
| `three_quarter` | Tres cuartos (~30° horizontal) |
| `dutch_tilt` | Inclinación holandesa |
| `negative_space` | Sujeto desplazado, espacio libre para captions |
| `pull_out` | Alejamiento / plano más abierto |
| `zoom_in` | Acercamiento / plano más cerrado |
| `none` | B-roll u otro inserto sin slug de pipeline |

Prompts de referencia: `lolo/angles/prompts/{slug}.txt`

### `camera.framing` — shot size

| Slug | Meaning |
|------|---------|
| `extreme_close_up` | Ojos/boca, recorte muy cerrado |
| `close_up` | Cabeza y hombros |
| `medium_close_up` | Pecho arriba (talking head típico) |
| `medium_shot` | Cintura arriba |
| `medium_wide` | Rodillas arriba / americano |
| `wide_shot` | Cuerpo completo o entorno dominante |

## Layout taxonomy (`scene.layout.type` — agent-written)

A single scene can combine B-roll and the presenter. Capture that here (the
script only pre-fills `layout.hint`).

| Slug | Meaning |
|------|---------|
| `fullscreen` | Un solo plano ocupa todo el cuadro (lo más común) |
| `split_horizontal` | Pantalla dividida en bandas: B-roll arriba/abajo + personaje en la otra banda |
| `split_vertical` | Pantalla dividida lado a lado (izquierda/derecha) |
| `pip` | Picture-in-picture: un recuadro pequeño sobre el plano principal |
| `overlay_graphics` | Gráficos/animación superpuestos sobre el plano |

For splits/pip list one `regions[]` entry per band: `position`
(`top`/`bottom`/`left`/`right`/`inset`) + `content`
(`broll`/`main_character`/`screen`/`graphics`) + a short `description`.

## B-roll kind taxonomy (`scene.broll_kind` — agent-written)

For B-roll / supplementary scenes (and the B-roll region of a split), say **what
kind** of footage it is — pre-recorded archival of a known person vs generic.

| Slug | Meaning |
|------|---------|
| `archival_known_person` | Material pregrabado donde aparece una persona **reconocible/célebre** (ej. una entrevista de Anthony Bourdain) |
| `archival_footage` | Material pregrabado real (personas no célebres, noticias, found footage) |
| `stock_generic` | Stock / complementario genérico (objetos, paisajes, manos) |
| `screen_recording` | Captura de pantalla / demo |
| `graphics_animation` | Gráficos o animación (no footage real) |
| `other` | Otro |

Record any recognizable people in `scene.known_people` (array of names or short
descriptions). When a reel leans on `archival_known_person`/`archival_footage`,
sourcing it for a new reel is the job of the **`broll-finder`** skill (real
YouTube footage), not `broll-generator` (synthetic).

## Background taxonomy (`scene.background.type` — agent-written, presenter scenes)

Is the main character's backdrop a real place or animated?

| Slug | Meaning |
|------|---------|
| `real_set` | Escenografía o locación real |
| `animated` | Fondo animado: dibujos, cartoons, motion graphics detrás de la persona |
| `mixed` | Real con elementos animados encima |
| `plain` | Fondo plano / liso (pared lisa, color sólido) |
| `virtual` | Fondo virtual / croma |
| `unknown` | No determinable |

Put a short description of what's behind the person in `background.elements`.

## Audio profiles (per scene)

| `audio_profile` | Meaning |
|-----------------|---------|
| `speech_only` | Solo voz |
| `speech_with_sfx` | Voz + efectos puntuales |
| `speech_with_music` | Voz + música/ambiente continuo |
| `speech_mixed` | Voz + SFX + música |
| `sfx_only` | Solo efectos, sin voz |
| `music_only` | Solo música/ambiente |
| `ambient` / `silent` | Fondo bajo / sin audio relevante |

Heuristic: Whisper masks speech intervals; transients in non-speech audio → SFX; sustained energy → music bed. For mixes complejos, usar Demucs (`youtube-audio-toolkit`) como complemento.

## What the script detects vs what you write

| Step | Who | What |
|------|-----|------|
| Scene boundaries | Script | PySceneDetect + interval fallback |
| Scene type | Script | MediaPipe face + edge heuristics |
| Zoom vs previous | Script | Face area + ORB → `zoom_in`, `zoom_out`, `none`, `hard_cut` |
| Transcript | Script | ffmpeg + faster-whisper with word timestamps |
| SFX / music bed | Script | Energy + transients in non-speech windows |
| Representative frame | Script | Sharpest sample at 25/50/75% of scene → `{stem}_frames/` |
| Split-screen hint | Script | Seam + half-histogram heuristic → `layout.hint` (you confirm) |
| Camera angle + framing | **Agent (you)** | Vision on each `scene_XX.jpg` |
| Layout / split-screen | **Agent (you)** | `layout.type` + `regions` (B-roll band + presenter band, pip, overlays) |
| B-roll kind + known people | **Agent (you)** | `broll_kind` (archival-known-person vs generic) + `known_people` |
| Presenter background | **Agent (you)** | `background.type` (real set vs animated drawings) |
| Focus + emotion | **Agent (you)** | Per-scene narrative summary in Spanish |
| Facial mannerisms | **Agent (you)** | Per talking-head scene: how the face/head moves |
| Avatar profile | **Agent (you)** | Reusable `video_prompt` + `negative_prompt` → `talking_profile.json` |

## Scene types

| Key | Meaning |
|-----|---------|
| `main_character_solo` | Talking head / personaje principal |
| `supplementary_material` | B-roll, inserts |
| `multi_person` | Multiple faces |
| `screen_demo` | Screen capture / UI |
| `unknown` | Unclassified keyframe |

## Tips

- Reels with hard cuts: `--scene-mode detect` (default in `auto`).
- Uniform 6s windows: `--scene-mode interval --interval 6`.
- Quick smoke test on transcript only: `--whisper-model tiny`.
- Long videos (>3 min): `--whisper-model small`.

## Troubleshooting

- **Face model not found** → run `setup_models.sh`.
- **scenedetect / faster-whisper missing** → reinstall requirements.
- **No transcript** → check audio track; try `--language es`.
- **MD shows "_Pendiente_"** → you skipped agent enrichment (summary or camera).

## Reference

JSON schema: [REFERENCE.md](REFERENCE.md)
