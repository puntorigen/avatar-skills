# B-roll Actor Copy — reference

Schema, resolution rules, look resolution and examples for the
`bytedance/dreamactor-m2.0` motion-transfer path.

## bytedance/dreamactor-m2.0 — input schema (verified)

DreamActor M2.0 animates a character from ONE reference image by copying the
motion of a driving video. It learns motion from raw pixels (no human skeleton
extraction), so humans, cartoons, animals and stylized avatars all work.

| Input | Type | Default | Notes |
|---|---|---|---|
| `image` | string(file) | — | **required** — reference image of the subject (the avatar's look hero). JPEG/JPG/PNG, max **4.7 MB**, resolution **480×480 … 1920×1080**. **The output keeps this image's resolution.** |
| `video` | string(file) | — | **required** — driving/template video whose **motion, facial expressions and lip movements** are copied onto the subject. **Exactly ONE animated character** (person or animal) must be visible. MP4/MOV/WebM, **max 30 s**, resolution **200×200 … 2048×1440**. |
| `cut_first_second` | bool | `true` | Crop the first second of the output (removes the model's ~1 s lead-in transition). The script defaults to cutting it; `--keep-first-second` keeps it. |

**Output:** a single video URI. **No `seed`, no `resolution`, no prompt** — the
appearance is fully set by `image` and the motion fully by `video`.

## Single-subject rule (important)

DreamActor copies **one** subject. The driving video must show **exactly one
animated character** — a person OR an animal — visible in scene. Our reference is
a single-avatar hero, so it must be paired with a one-character driver.

If the source video has more than one character:
1. **Inform** the user that the driving video must have a single animated
   character to copy (model limitation).
2. **Ask** the user (AskQuestion) to either (a) supply a single-character clip, or
   (b) split into single-character time segments and stitch them.

For (b), pass the ranges to `--segments` (see below). To find where each character
is alone on screen, inspect the video visually or with the `video-scene-analysis`
skill.

## Segment → process → stitch (multi-character sources)

`--segments "start-end,start-end,…"` takes single-character time ranges (seconds,
`M:SS`, or `H:MM:SS`). Each range is:
- trimmed from the source with ffmpeg (respecting the 30 s cap),
- animated separately through DreamActor with the **same** avatar hero,
- saved as a muted intermediate under `_work/`,
then all intermediates are **concatenated** (ffmpeg concat filter, resolution is
identical because they share the hero) into one muted `<NNN>_<slug>.mp4`.

Rules: each range ≤ 30 s and must contain a single character; `--segments` is
mutually exclusive with `--trim-start`/`--trim-duration`; the stitched output is
always muted (`--keep-audio` is ignored in this mode). The manifest entry records
`mode: "segments"` and a per-segment list (`start`, `duration`, `source_url`, …).

### Auto-fit (make_actor_copy.py, only when needed)
- **Reference image**: converted/resized only if it violates a constraint —
  upscaled if the short side < 480, downscaled to fit the 1920×1080 envelope
  (either orientation), and re-encoded to JPEG if > 4.7 MB. A compliant hero is
  **passed through untouched**, so its resolution flows straight to the clip.
  `--no-fit-image` disables this.
- **Driving video**: trimmed to ≤ 30 s (or the `--trim-start`/`--trim-duration`
  segment) and downscaled into the 2048×1440 box only if larger; otherwise sent
  as-is.

## Look → hero image resolution

Mirrors `avatar-location`'s layout. The avatar folder `<avatar>` is a bare name
routed to `avatares/<name>` (or an explicit path); slug = the folder name:

| `--location` | Hero used (first that exists) |
|---|---|
| `default` (or omitted) | `refs/<slug>_hero.png` → `refs/<slug>_hero_master.png` → a `angles/*_916.png` → `frames/frame_0001.png` |
| `<loc>` | `locations/<loc>/refs/<slug>__<loc>_hero.png` → `…_hero_master.png` → `locations/<loc>/angles/*_916.png` |

`--image PATH` bypasses this entirely (use any image; its resolution sets the
output resolution). The default look = the avatar's top-level `scene.json` +
`refs/` and is never modified.

## Output & manifest

Clips land in `<avatar>/broll/actor-copy/`:

| File | What it is |
|---|---|
| `<NNN>_<slug>.mp4` | The muted motion-copied clip (auto-numbered) |
| `manifest.json` | `items[]` mapping each clip → `avatar`, `location`, `reference_image`, `driving_video`, `mode` (`single`/`segments`), `segments[]`, `trim_start`, `trim_duration`, `cut_first_second`, `width`/`height`, `duration_actual`, `source_url`, … |
| `_work/` | Prepared (fitted image / trimmed video) intermediates |

## Worked examples

A bare avatar name routes under `./avatares/<name>` (override with `AVATARES_ROOT`);
an explicit path is used as-is.

```bash
# Default look — copy a dance video onto the avatar (9:16 hero -> 9:16 clip)
python3 broll-actor-copy/scripts/make_actor_copy.py nora \
  --video downloads/dance_take.mp4 --slug nora-copies-dance

# A specific location/look
python3 broll-actor-copy/scripts/make_actor_copy.py nora \
  --location studio_night --video downloads/host_moves.mp4

# Use only an 8s segment starting at 12s of a long driver
python3 broll-actor-copy/scripts/make_actor_copy.py nora \
  --video downloads/long_take.mp4 --trim-start 12 --trim-duration 8

# Multi-character source -> single-character segments, processed + stitched
python3 broll-actor-copy/scripts/make_actor_copy.py nora \
  --video downloads/interview.mp4 --segments "0-8,15-22,0:40-0:52" --slug nora-copies-host

# Explicit reference image (skip look resolution), keep the generated audio for QA
python3 broll-actor-copy/scripts/make_actor_copy.py \
  --image avatares/nora/refs/nora_hero.png --video downloads/clip.mp4 --keep-audio

# Preview the plan without spending (prints resolved hero + prepared sizes)
python3 broll-actor-copy/scripts/make_actor_copy.py nora \
  --video downloads/clip.mp4 --dry-run
```

## Recipes / lessons

- **9:16 in, 9:16 out.** The output resolution equals the reference image's, so
  crop the hero to the reel ratio first (or pass a 9:16 `--image`).
- **The driver IS the direction.** There is no text motion prompt — pick a
  driving clip that already performs the movement/expression you want.
- **Clean inputs → clean output.** A clear reference subject and a clean,
  well-lit driving clip give the best identity + motion fidelity. Portrait and
  full-body both work; the model adapts scale.
- **One character only** in the driving video (see the single-subject rule
  above); for multi-character sources, segment + stitch with `--segments`.
- **Muted broll.** The clip is muted (ffmpeg `-an`); `avatar-reel-composer`
  re-lays the single master narration. Use `--keep-audio` only for a standalone
  lip-sync/motion QA preview.
- **When to use a sibling instead:** for an action described in words (no driving
  video) use `broll-avatar-camera` (start frame + `video_prompt`); for a stylized
  illustrated vignette use `broll-story` (seedance-2); for a precise start→end
  object move use seedance-2 start+end frames.
