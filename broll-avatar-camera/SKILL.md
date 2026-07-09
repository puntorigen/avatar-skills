---
name: broll-avatar-camera
description: >-
  Generate a short B-roll clip of OUR OWN avatar DOING something on camera — an
  ACTION shot that COMPLEMENTS the narration (movement matters more than words),
  not a centered talking head. Built on the SAME model as our talking-heads
  (prunaai/p-video-avatar) so the avatar's face/wardrobe/room stay consistent.
  Pipeline: build ONE action start frame with the gpt-image-2 skill (locking
  wardrobe/room/light from the scene profile), then animate it with
  p-video-avatar driven by the beat's narration audio, with the action in
  video_prompt and exclusions in negative_prompt; the clip is muted and the
  master narration is re-laid by avatar-reel-composer. For a face-free beat or a
  precise object move with exact start+end poses, use seedance-2 instead. Use
  when the user wants the avatar SEEN doing an activity in-scene (reaching,
  tending, building, holding an object) under a narration line, or mentions
  broll-avatar-camera, p-video-avatar action shots, video_prompt/negative_prompt,
  or an action insert of the real avatar.
disable-model-invocation: true
---

# B-roll Avatar Camera (the avatar SEEN doing something)

The **realistic action** counterpart of the broll skills, starring **our own avatar**:

- `broll-story` → an **illustrated** 6-panel storyboard animated by seedance-2 (great
  for invented side-characters / stylized vignettes).
- `broll-generator` → presenter-free synthetic B-roll; `broll-finder` → real footage.
- **`broll-avatar-camera` → OUR avatar, photoreal, DOING something** — a single realistic
  action start frame (built like a camera angle) animated by **`prunaai/p-video-avatar`**,
  the **same model as our talking-heads**, driven by the beat's narration audio.

**Why `p-video-avatar` (the same model as the talking-heads, not plain `p-video`):** it keeps
the avatar's face/wardrobe/room **identical** to the talking-head beats, and it's
**audio-driven** — feed it the beat's narration slice and the avatar **lip-syncs** to it (when
the mouth is visible) while the clip **length matches the beat**. The action itself is directed
by the **`video_prompt`** param ("takes a book from a shelf while talking") and **`negative_prompt`**
keeps unwanted stuff out. The clip is **muted on disk**; `avatar-reel-composer` re-lays the
single master narration over it (so no double audio — the lip-sync visuals stay in sync because
the same slice drove them).

## When to use

The reel needs a beat where the avatar is **seen DOING** something in their own world while a
narration line plays — to **complement the words with action**, where the **movement matters more
than the speech** (the centered talking-head beats already carry the spoken delivery). Think:
**taking a book off a shelf**, **walking** through the garden, **tending the plants**, **building
a sandcastle**, lighting a candle, writing numbers, holding/handling an object — shot from
**varied angles**. It's the "show, don't tell" insert between talking-head beats, the photoreal
cousin of `broll-story` but starring the real avatar.

- **Face/mouth visible** in the action shot → the avatar **lip-syncs** the beat as a bonus (looks
  like them saying that line while doing the thing). This is the sweet spot for this skill.
- **Face-free** (true first-person POV of the hands, back-to-camera) **or a precise object move**
  with an exact start AND end pose → a talking-avatar model has no face to anchor; use
  **seedance-2 with start+end frames** instead (see REFERENCE.md).

## Prerequisites

- **gpt-image-2** ready (shared Replicate token) — builds the action start frame.
- **Replicate token** (shared, auto-discovered) for `prunaai/p-video-avatar`.
- **The beat's narration audio slice** (e.g. `antiguo/reels/NNN_slug/scenes/chunk_sN.mp3`, or a
  cut from `narration.mp3`) — this DRIVES the clip (lip-sync + length).
- **ffmpeg** on PATH — mutes the clip.
- `pip3 install -r scripts/requirements.txt` (replicate, pillow).
- A **scene profile** for the avatar (the same `subject`/`wardrobe`/`scene`/`light` JSON used by
  `avatar-camera-angles`; e.g. `antiguo/scene.json`) and an avatar reference image
  (`antiguo/refs/antiguo_hero.png`).

## Pipeline

```
scene profile + avatar ref + an ACTION description
  │
1 build_frame.py  → gpt-image-2 → ONE action start frame (2:3 master + 9:16 crop)
  │
2 make_broll_camera.py → prunaai/p-video-avatar
  │   inputs: image (start frame) + audio (beat slice) + video_prompt (action) + negative_prompt
  │   → download → mute (-an) → <avatar>/broll/camera/<NNN>_<slug>.mp4 + manifest.json
  │
3 hand off to avatar-reel-composer as a broll scene (broll_source: existing)
```

## Hard rules (project)

- **SHORT, positive ACTION in `--video-prompt`.** This is the model's "how the person behaves
  while speaking" — put the **action** here, one short clause, positive: `"takes a book from a
  shelf and looks at it while talking"`. Drop scene dressing/qualifiers and **never** write
  "hold still / static / no camera movement" — negative/static instructions confuse it. Name what
  the avatar DOES; lip-sync is automatic from the audio.
- **Drive with the beat's narration audio.** Pass `--audio` = the exact narration slice for this
  beat. It lip-syncs the avatar (if the mouth is visible) and **sets the clip length** to the
  beat, so the clip matches its slot. (`--voice-script` exists only as a generic built-in-TTS
  fallback for quick motion scouting — it is **not** the avatar's cloned voice.)
- **Muted output.** The clip is muted on disk; `avatar-reel-composer` re-lays the master
  narration. The same slice drove the lip-sync, so it stays in sync. (`--keep-audio` only for a
  standalone QA preview.)
- **Identity stays locked** because it's the same model as the talking-heads. Build the start
  frame from the avatar `--ref` + scene profile so the room/wardrobe match.
- **Prefer clear gross-motor actions.** Reaching, taking a book, walking, sweeping, planting read
  cleanly. `p-video-avatar` holds handled objects far better than plain `p-video` (a book stays
  coherent — cf. the old `006` page/​book flip), but still keep the action simple.
- **Face-free or precise object move → use seedance-2 start+end instead.** A talking-avatar model
  needs a face to anchor; for a true hands-only POV, a back-to-camera walk, or an exact
  start→end object move, generate a start and an end frame and interpolate with **seedance-2**
  (`--start-image` / `--end-image`). See REFERENCE.md.
- **No frozen frames / no Ken Burns.** The clip length follows the audio, so pass the exact beat
  slice and the clip matches its slot (the composer trims, never freezes). Project rule since Cap. 6.
- **Feed a 9:16 frame** for a 9:16 reel clip.

## Workflow

### 1 — Build the action start frame (the creative step)
Author the ACTION shot and render it with gpt-image-2 (locks wardrobe/room/light from the scene
profile, composes the action). For an action where the avatar lip-syncs, keep the **face/mouth
in frame** (`--face visible`); for an over-the-shoulder use `--face partial`:

```bash
python3 .cursor/skills/broll-avatar-camera/scripts/build_frame.py \
  --ref antiguo/refs/antiguo_hero.png \
  --scene-file antiguo/scene.json \
  --face visible \
  --action "three-quarter shot of the old mystic standing at his bookshelf, reaching up to \
pull a thick leather-bound tome from an upper shelf; upper body visible, indigo robe, candlelight" \
  --crop916 -o antiguo/broll/camera/_frames/ --slug antiguo_shelf_reach
```
Review the printed `reel_916` frame; re-roll (`--count`, or tweak `--action`) until it reads
right. Preview the prompt first with `--print-prompt`.

### 2 — Animate it, driven by the beat audio (the mechanical step)
Put the **action** in `--video-prompt` (short, positive) and the **beat slice** in `--audio`:
```bash
python3 .cursor/skills/broll-avatar-camera/scripts/make_broll_camera.py \
  --avatar-dir antiguo \
  --image antiguo/broll/camera/_frames/antiguo_shelf_reach_916.png \
  --audio antiguo/reels/NNN_slug/scenes/chunk_s4.mp3 \
  --action "takes a book from a shelf and looks at it while talking" \
  --slug antiguo-shelf-book
```
Writes `<avatar>/broll/camera/<NNN>_<slug>.mp4` (muted, length = the audio) + a manifest entry,
and prints a JSON summary. Useful flags: `--audio PATH` (the beat slice — lip-sync + length),
`--negative-prompt "…"` (override the action-broll preset) / `--use-profile-negative` (reuse the
avatar's `talking_profile.json`), `--strength-negative-prompt`, `--resolution 1080p`, `--seed`,
`--disable-prompt-upsampling` (verbatim action prompt), `--keep-audio` (QA preview),
`--voice-script "…"` (generic built-in TTS, scouting only).

### 3 — Hand off to avatar-reel-composer
Drop the clip into a storyboard `broll` scene; the composer lays the single master narration over
it (the same slice that drove the lip-sync → in sync):
```json
{ "id": "s4", "type": "broll", "broll_source": "existing",
  "broll_clip": "antiguo/broll/camera/001_antiguo-shelf-book.mp4",
  "motion": "none",
  "text": "the contiguous slice of the narration spoken over this beat" }
```

## Notes / troubleshooting
- **Action goes in `--video-prompt`, short + positive.** If the avatar *only talks* and doesn't
  act, name the gesture explicitly ("takes a book… ", "writes numbers…"). If it warps, shorten
  the prompt and drop scene dressing / any static-negative phrasing.
- **The audio is the driver.** Length follows the audio; pass the exact beat slice so the clip
  matches its slot. Lip-sync shows only where the mouth is visible — that's expected and fine for
  an action beat (the movement is the point).
- **Held objects** are much more coherent than with plain `p-video`, but a heavy object move is
  still safer as a **seedance-2 start+end** interpolation.
- **Face-free beats** (hands-only POV, back-to-camera): don't use this script (no face to anchor);
  use **seedance-2 start+end** (REFERENCE.md) or shoot the action with the face partially in frame.
- **Cost:** `p-video-avatar` is billed like the talking-heads (per second at 720p/1080p); the clip
  is as long as the beat audio.
- **Quick scout** without burning the cloned voice: `--voice-script "…"` uses the model's generic
  built-in TTS just to preview the motion, then re-run with the real `--audio` beat.

## Additional resources
- Action-shot prompt internals, p-video-avatar schema, seedance-2 start+end recipe, examples:
  [REFERENCE.md](REFERENCE.md)
- Frame builder reuses: `~/.cursor/skills/gpt-image-2` (image gen). Sibling: `avatar-talking-video`
  (centered talking-heads, same model) and `avatar-camera-angles` (talking-head re-frames).
  Consumer: `avatar-reel-composer` (`broll_source: existing`).
