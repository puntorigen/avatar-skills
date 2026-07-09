---
name: cuento-reel
description: >-
  Produce a "cuento" (story) reel where each avatar is a CHARACTER in a narrated
  tale (Narnia-style), not a single presenter talking to camera. An unseen
  storyteller NARRATOR (voice-only, older "cuentacuentos"/grandfatherly cloned
  voice) carries the story in third person, while invented character avatars ACT:
  silent animated action beats (broll-story / seedance image-to-video) under the
  narrator's voice-over, and key lines delivered as real lip-synced p-video-avatar
  clips (avatar-talking-video) woven in as guest scenes. Orchestrates avatar-invent,
  broll-story, audio-theater, avatar-talking-video and avatar-reel-composer
  (assemble_narration + compose_reel). Use when the user wants a story/cuento reel,
  to "contar una historia / cuento" with characters and a narrator, to adapt a tale
  (fairy tale, public-domain classic, etc.) into a narrated multi-character reel, or
  to make another episode in a cuento series like narnia/.
---

# Cuento Reel (narrated multi-character story)

Films a **cuento**, not a marketing reel. A voice-only **Narrator**
(cuentacuentos) holds the thread in third person; **characters** are invented
avatars that ACT. Two visual building blocks:

- **Narration beats (no lip-sync)** → SILENT animated clips built with
  `broll-story` (ONE multi-panel storyboard sheet → seedance, muted), with the
  Narrator's voice-over on top. Never one-still-per-clip, never a centered
  talking-head.
- **Dialogue / action-with-speech beats** → REAL lip-synced clips of one
  character at a time (`avatar-talking-video` / p-video-avatar), woven in as
  `guest` scenes that keep their OWN voice. Use this whenever a shot needs
  ACTION **and** LIP-SYNC at the same time.

This is the generalized pipeline behind `narnia/` (see that folder + its
`serie-narnia.pauta.md` / `*.script.md` for a full worked example).

## Folder layout (a "cuento" project)
```
<serie>/
  serie-<x>.pauta.md                 # series bible (templates/serie.pauta.md)
  cast/                              # REUSABLE avatars, made ONCE per series
    narrador/                        # voice-only storyteller (older cuentacuentos)
      voice_brief.json  voices/...   # MiniMax voice_id (no face needed)
    <personaje>/                     # face + voice (avatar-invent)
      scene.json  refs/  angles/  voices/  talking_profile.json
  <libro>/<NN_slug>/                 # ONE episode = one reel
    <NN_slug>.script.md              # beat sheet (templates/episodio.script.md)
    dialog/script.json               # character dialogue (audio-theater)
    broll/anim/*.mp4                 # silent animated narration-beat clips
    plan.json                        # master-narration plan (assemble_narration)
    storyboard.json                  # scenes (compose_reel)
    narration.mp3  final.mp4         # outputs
```

## Hard rules (learned the hard way — do not break)
1. **NO Ken Burns, ever.** Every scene `motion: "none"`. Movement must be REAL
   (animate the still into video); never a static frame with a push/zoom, and
   never `emphasis` on a `guest` scene (it would re-introduce a push-in).
2. **`gap: 0` in the plan.** Guest (lip-sync) clips have no trailing pad; any
   `gap>0` makes each guest fall short and the picture drifts ahead of the audio.
   `compose_reel` now warns if it sees `gap>0` with guest scenes.
3. **1:1 scene ↔ plan-segment correspondence, same order.** The composer pins
   every scene boundary to `assemble_narration`'s exact offsets (frame-exact
   A/V). Keep `storyboard.scenes` in the SAME order as `plan.segments`.
4. **Narrator is voice-only and OLD.** A warm, grandfatherly cuentacuentos timbre
   (older than a generic narrator). Voice-only — it never needs a face on screen.
5. **Original text for copyrighted sources.** Copyright protects expression, not
   ideas. If the source tale is under copyright (e.g. Narnia), write 100% ORIGINAL
   narration + dialogue inspired by the plot; never reproduce or closely paraphrase
   the prose. Public-domain tales (Verne, Andersen, Grimm, Quiroga…) are free, but
   their modern TRANSLATIONS may not be — adapt in your own words. Note personal use.
6. **Animation tool by shot type — NON-NEGOTIABLE.**
   - **No lip-sync during the animation (interludios / b-roll)** → **`broll-story`**:
     author ONE multi-panel storyboard sheet and animate it in a SINGLE seedance
     pass (cheaper + more coherent). Do **NOT** animate a separate still per beat.
   - **Action + lip-sync at the same time** (a character moving/acting AND speaking
     on camera) → **`p-video-avatar`** (`avatar-talking-video`).
   That's the rule: silent motion = broll-story; speaking-on-camera = p-video-avatar.
7. **Series compile.** Join episodes with `ami/compile_series.py` (or the series'
   equivalent): video dips to/from black at each chapter, audio runs straight
   through (never fade the voice), a ≥0.5s black pause between chapters and ~1s of
   black at the end so it doesn't cut abruptly. The intro is silent; music starts
   on the first episode.

## Workflow

### A) Once per SERIES
1. **Write the bible.** Copy `templates/serie.pauta.md` → `<serie>/serie-<x>.pauta.md`:
   north star, visual DNA (style/era/palette), language, cast table, per-episode map.
2. **Create the Narrator voice** (voice-only). Copy
   `templates/narrador.voice_brief.json` → `<serie>/cast/narrador/voice_brief.json`
   (older cuentacuentos timbre), then design+clone it:
   ```bash
   python3 .cursor/skills/avatar-invent/scripts/design_voice.py \
       --avatar-dir <serie>/cast/narrador --name narrador \
       --voice-brief <serie>/cast/narrador/voice_brief.json
   # -> <serie>/cast/narrador/voices/narrador.json (voice_id)
   ```
3. **Create each CHARACTER avatar** (face + voice) with `avatar-invent` (pauses
   once for the casting review — make the SUBJECT a vivid, concrete face so it
   stays consistent across clips):
   ```bash
   python3 .cursor/skills/avatar-invent/scripts/invent_avatar.py <serie>/cast/<char> \
       --description "<vivid age/face/hair/wardrobe, era-accurate>" --setting <fit> --language es
   # review cast/<char>/scene.json + voice_brief.json, then re-run to generate.
   ```
   Anchor each character's `refs/<char>_hero_master.png` and repeat its DNA
   verbatim in every broll sheet so the face never drifts.

### B) Per EPISODE
4. **Write the beat sheet** — copy `templates/episodio.script.md`. Mark each beat
   **N** (narration), **D** (character dialogue), **VIS** (what we see). Then derive:
   - the running **Narrator script** (only the N lines, third person), and
   - the **dialogue list** (the D lines, per character).
5. **Generate dialogue lip-sync clips** (one character per clip). Two paths:
   - **Default (character's own MiniMax voice):** let `assemble_narration` do it —
     add a `kind:"guest"` segment (it calls `avatar-talking-video` and uses the clip).
   - **Specific non-MiniMax voice** (e.g. youthful/child voices that ElevenLabs
     blocks): synthesize the line with `audio-theater` (Gemini voices, see
     `dialog/script.json`), lip-sync it onto the face, then reference the clip:
     ```bash
     python3 .cursor/skills/avatar-talking-video/scripts/generate_video.py \
         --audio <line>.wav --avatar-dir <serie>/cast/<char> \
         --image <serie>/cast/<char>/refs/<char>_hero_master.png --out-name <dlg_id>
     ```
     Use the clip as a `kind:"audio"` plan segment (`file` = the .mp4) AND a
     storyboard `guest` scene (`broll_clip` = that .mp4).
6. **Generate narration-beat visuals** (SILENT, real motion) — always
   **`broll-story`** (see Hard Rule 6): one multi-panel storyboard sheet per beat
   (or per contiguous group of beats) → animate in a single seedance pass, muted.
   Do NOT animate one still per beat. Save to `<libro>/<NN_slug>/broll/story/*.mp4`
   (or `broll/anim/`). All will be `motion:"none"` scenes. Only use
   `p-video-avatar` here if the shot also needs on-camera lip-sync.
7. **Assemble the master narration** (interleave narrator + dialogue). Copy
   `templates/plan.example.json` → `plan.json` (`gap:0`, segments in story order:
   `tts` = narrator, `audio`/`guest` = dialogue clips), then:
   ```bash
   python3 .cursor/skills/avatar-reel-composer/scripts/assemble_narration.py \
       <libro>/<NN_slug>/plan.json --base-dir .
   # -> narration.mp3 + narration.align.json + assemble_narration.out.json
   ```
8. **Write the storyboard** — copy `templates/storyboard.example.json`. One scene
   per plan segment, SAME order: `guest` for dialogue clips, `broll`
   (`broll_source:"existing"`, `broll_clip`) for narration beats; EVERY scene
   `motion:"none"`; a `finish` block (subtitles + cinematic music, `max_words` ~6).
   The `script` = the full running narrator text. Then compose (reuses the
   pre-built narration when `--out-dir` points at the episode folder):
   ```bash
   python3 .cursor/skills/avatar-reel-composer/scripts/compose_reel.py \
       <libro>/<NN_slug>/storyboard.json --base-dir . \
       --out-dir <libro>/<NN_slug> --finish
   ```
9. **QA lip-sync.** Confirm each character cut lands where its line ends (extract
   frames at the boundary and compare to the subtitle/audio). See
   [REFERENCE.md](REFERENCE.md) for the exact A/V-sync check.

## Templates
- `templates/serie.pauta.md` — series bible.
- `templates/episodio.script.md` — beat sheet (N / D / VIS).
- `templates/narrador.voice_brief.json` — older cuentacuentos narrator voice.
- `templates/dialog.script.json` — audio-theater dialogue (character voices).
- `templates/plan.example.json` — master-narration plan (`gap:0`, interleaved).
- `templates/storyboard.example.json` — scenes (motion none, guest+broll, finish).

## Additional resources
- Schemas (plan/storyboard/scene), troubleshooting, A/V-sync check: [REFERENCE.md](REFERENCE.md)
- Orchestrated skills: `avatar-invent`, `broll-story`, `audio-theater`,
  `avatar-talking-video`, `avatar-reel-composer` (assemble_narration + compose_reel).
- Worked example: the `narnia/` folder and its `serie-narnia.pauta.md`.
