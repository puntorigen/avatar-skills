---
name: broll-actor-copy
description: >-
  Generate a B-roll clip where OUR avatar COPIES the motion of a driving video —
  same movement, gestures, expressions and lip movements, but performed by the
  avatar — via ByteDance DreamActor M2.0 (bytedance/dreamactor-m2.0 on Replicate).
  Takes an avatar, a location/look (or its default) and a driving video, resolves
  the look's identity-anchored hero image, and transfers the video's performance
  onto it. DreamActor is universal (humans, cartoons, animals) and needs no pose
  estimation. The driving video must show exactly ONE animated character (person
  or animal); multi-character sources are split into single-character segments and
  stitched. Output keeps the reference image's resolution (9:16 hero →
  9:16 clip); the clip is muted and avatar-reel-composer re-lays narration. Use
  when the user wants the avatar to mimic a reference video's movement, a motion
  copy / performance transfer / actor copy / "copiar el movimiento del video"
  B-roll, or mentions dreamactor / DreamActor M2.0.
disable-model-invocation: true
---

# B-roll Actor Copy (the avatar copies a video's motion)

The **motion-transfer** member of the broll family. Where `broll-avatar-camera`
animates ONE start frame with a text action prompt and `broll-story` animates an
illustrated storyboard, **`broll-actor-copy` copies a real driving video's whole
performance onto our avatar** — the avatar re-does the exact movement, gestures,
expressions and lip movements of the video, keeping its own identity + look.

It is a thin **orchestrator** over one Replicate model:
**`bytedance/dreamactor-m2.0`** — image (the avatar's look hero) + driving video
→ a video of the avatar performing the video's motion.

> **Why DreamActor M2.0:** it learns motion from raw video pixels instead of
> extracting a human skeleton, so it animates realistic humans, stylized
> drawings, cartoons and animals alike — ideal for our varied avatars. It keeps
> the reference identity while accurately copying the motion, and the **output
> resolution equals the reference image's resolution**.

## Inputs (gather what's missing)
| Input | Used for |
|---|---|
| **Avatar** | a bare name (e.g. `nora` → `avatares/nora/`) or a path — its hero image is the appearance source |
| **Location / look** | which look to wear: `default` (top-level `scene.json`+`refs/`) or a name under `<avatar>/locations/<loc>/` (default: `default`) |
| **Driving video** | the MOTION source — its movement/expressions/lips are copied onto the avatar. **Must show exactly ONE animated character** (person or animal) in scene |

The look resolves to the identity-anchored hero automatically:
- default → `<avatar>/refs/<slug>_hero.png`
- a location → `<avatar>/locations/<loc>/refs/<slug>__<loc>_hero.png`

Override the appearance entirely with `--image PATH` (its resolution then sets
the output resolution).

## Prerequisites
- **Replicate token** (shared, auto-discovered) — for `bytedance/dreamactor-m2.0`.
  Set/refresh: `python3 scripts/setup_key.py YOUR_REPLICATE_API_TOKEN`.
- `pip3 install -r scripts/requirements.txt` (replicate, pillow).
- **ffmpeg / ffprobe** on PATH — trims/scales the driving video and mutes the clip.
- An **existing avatar** with a hero (as produced by `avatar-invent` / `avatar-location`).

## Pipeline
```
avatar look -> hero image  +  driving video
  │
1 resolve the look's hero (or --image); fit it to 480x480..1920x1080, <=4.7MB (only if needed)
  │  fit/trim the driving video to <=30s within a 2048x1440 box (only if needed)
  │
2 make_actor_copy.py -> bytedance/dreamactor-m2.0
  │   inputs: image (avatar hero) + video (driver) + cut_first_second
  │   -> download -> mute (-an) -> <avatar>/broll/actor-copy/<NNN>_<slug>.mp4 + manifest.json
  │
3 hand off to avatar-reel-composer as a broll scene (broll_source: existing)
```

## Hard rules
- **One character in the driving video.** DreamActor copies a SINGLE subject, so
  the driving video must show **exactly one animated character** (a person OR an
  animal) visible in scene. Our reference hero is one avatar → match it with a
  one-character driver. See the multi-character workflow below.
- **The reference image sets the output resolution.** Feed a **9:16 hero** for a
  9:16 reel clip, or a **16:9 hero** for a 16:9 YouTube clip. When it falls back
  to a camera angle, pass `--aspect 16:9` to prefer the avatar's `_169.png`
  angle. Keep the subject clear and framed like the shot you want.
- **Driving video ≤ 30s.** Longer input is auto-trimmed to the first 30s; pick a
  segment with `--trim-start` / `--trim-duration` (or `--segments`).
- **Muted output.** The clip is muted on disk; `avatar-reel-composer` re-lays the
  single master narration. `--keep-audio` only for a standalone QA preview.
- **The motion comes from the VIDEO, not a text prompt.** There is no
  `video_prompt`; choose a driving clip that already performs the movement you want.

## If the driving video has more than one character
DreamActor can only copy ONE subject. Before generating, **verify the driving
video shows a single animated character** (visually, or with the
`video-scene-analysis` skill). If it shows more than one:

1. **Tell the user** the driving video must have only one animated character to
   copy (this is a model limitation, not a preference).
2. **Ask the user** (use the AskQuestion tool) whether to:
   - **(a)** provide/pick a different clip that already has a single character, or
   - **(b)** split the video into time **segments where only one character
     appears**, process each, and **stitch** them into one clip via `--segments`.

For **(b)**, pass the single-character ranges to `--segments` (seconds or
`M:SS`/`H:MM:SS`); each range is animated separately with the same avatar hero and
the muted results are concatenated into one clip:
```bash
python3 broll-actor-copy/scripts/make_actor_copy.py nora \
  --video downloads/interview.mp4 --segments "0-8,15-22,0:40-0:52" \
  --slug nora-copies-host
```
Each segment must be ≤ 30s and contain a single character; the stitched output is
always muted (VO is re-laid later).

## Workflow

### 1 — Pick the driver + the look
Choose (or download) the driving video whose performance you want the avatar to
copy, and decide the avatar look. **Confirm the driver shows a single animated
character** (see the multi-character workflow above if not). Preview the resolved
inputs with `--dry-run` (no spend): it prints the resolved hero, prepared
image/video sizes and the plan.

### 2 — Generate
```bash
python3 broll-actor-copy/scripts/make_actor_copy.py nora \
  --video downloads/dance_take.mp4 \
  --slug nora-copies-dance
```
Writes `<avatar>/broll/actor-copy/<NNN>_<slug>.mp4` (muted, resolution = the hero)
plus a manifest entry, and prints a JSON summary. Useful flags:
- `--location <loc>` — use a specific look (else `default`).
- `--image PATH` — explicit appearance image (skips look resolution).
- `--segments "a-b,c-d"` — single-character time ranges to process + stitch (for
  multi-character sources). Mutually exclusive with `--trim-*`.
- `--trim-start S` / `--trim-duration S` — use a single segment of a long driver.
- `--keep-first-second` — keep the model's 1s lead-in (default: cut it).
- `--keep-audio` — keep the generated audio (default: mute).
- `--model-version HASH` — pin a specific Replicate version.
- `--dry-run` — resolve/prepare inputs and print the plan without calling the model.

### 3 — Hand off to avatar-reel-composer
Drop the clip into a storyboard `broll` scene; the composer lays the master
narration over it:
```json
{ "id": "s3", "type": "broll", "broll_source": "existing",
  "broll_clip": "avatares/nora/broll/actor-copy/001_nora-copies-dance.mp4",
  "motion": "none",
  "text": "the contiguous slice of the narration spoken over this beat" }
```

## Notes / troubleshooting
- **Identity drifts / off-look** → the reference hero controls the appearance;
  use a cleaner, front-ish hero (or a specific `--location`) and re-run.
- **Motion looks wrong / cropped** → the driver's framing matters; prefer a clean,
  well-lit driving clip with the same shot scale you want (portrait vs full-body
  both work — the model adapts).
- **Output wrong ratio** → it follows the reference image; crop the hero to 9:16
  first (or pass a 9:16 `--image`).
- **Input too big / too long** → handled automatically (image ≤4.7MB within
  1920x1080; video ≤30s within 2048x1440); pass `--no-fit-image` to send the
  image untouched.
- **Cost / time** — billed per run on Replicate (video generation takes a few
  minutes); check the model page for current pricing.

## Additional resources
- Model schema, resolution rules, look resolution details and examples: [REFERENCE.md](REFERENCE.md)
- Siblings: `broll-avatar-camera` (one frame + action prompt, p-video-avatar),
  `broll-story` (illustrated storyboard, seedance-2), `broll-generator` (synthetic),
  `broll-finder` (real footage). Looks come from `avatar-location`.
  Consumer: `avatar-reel-composer` (`broll_source: existing`).
