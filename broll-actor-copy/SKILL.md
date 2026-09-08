---
name: broll-actor-copy
description: >-
  Generate a B-roll clip where OUR avatar COPIES the motion of a driving video —
  same movement, gestures, expressions and lip movements — via ByteDance
  DreamActor M2.0 (bytedance/dreamactor-m2.0 on Replicate). Takes an avatar, a
  location/look (or its default) and a driving video, resolves the look's hero
  image, and transfers the video's performance onto it. Works with humans,
  cartoons and animals. The driving video must show exactly ONE animated
  character; multi-character sources are split into single-character segments
  and stitched. A human driver should match a human avatar's gender (else warn +
  ask: the face distorts) and the reference scene should include the objects the
  driver interacts with. Output keeps the reference image's resolution (9:16
  hero → 9:16 clip); the clip is muted and avatar-reel-composer re-lays
  narration. Use when the user wants the avatar to mimic a video's movement, a
  motion copy / performance transfer / actor copy / "copiar el movimiento del
  video" B-roll, or mentions dreamactor.
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
- **Human driver → same gender as the avatar (or warn + ask).** DreamActor also
  transfers the driver's facial gestures and the position of facial features. When
  both driver and avatar are human but of different genders, the avatar's face
  gets distorted / drifts off-identity. Before generating with a human driver,
  check its apparent gender against the avatar's: if they differ, **tell the user
  and ask (AskQuestion) whether to continue anyway or pick another driver**.
  A human driver animating an ANIMAL avatar is fine — the face-matching issue is
  human-to-human.
- **The reference scene must support the driver's interactions.** If the driving
  actor interacts with objects (a bench, a mat, a bar, a chair…), the reference
  image's location should contain a **similar interactable element** — not
  necessarily identical, just coherent with the avatar's scene — placed where the
  motion needs it. Otherwise DreamActor invents props mid-clip and the motion
  looks unnatural. Also frame the reference **half-body (mid-thigh up)** when the
  detail that matters is the face/torso: DreamActor plausibly fills in whatever
  is outside the reference frame, and a closer reference keeps the face sharp.
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

## If the driver's gender differs from the avatar's (human ↔ human)
DreamActor mirrors the driver's facial gestures and feature placement, so a
female driver on a male avatar (or vice versa) tends to **distort the face**.
Before generating with a human driver:

1. Compare the driver's apparent gender with the avatar's.
2. If they differ, **inform the user** of the face-distortion risk and **ask**
   (AskQuestion) whether to (a) use/pick a same-gender driving clip, or
   (b) continue anyway accepting possible facial drift.

This only applies human-to-human: driving an **animal** avatar with a human
video is fine and supported.

## Match the reference scene to the driver's interactions
Watch what the driving actor touches or leans on (bench, mat, bar, wall, chair…)
and make sure the reference image's location has a **coherent interactable
counterpart** in a workable position — the avatar's own version of it, not a copy
of the driver's scene. If the hero look lacks it, generate a scene-matched
reference (e.g. with `gpt-image-2` / `avatar-location`) instead of feeding a
mismatched hero: DreamActor will otherwise hallucinate props and the contact
points will look wrong. Prioritize detail where it matters — a **half-body
(mid-thigh up) reference** keeps face/torso sharp and lets the model infer legs
and clothing below the frame.

## Workflow

### 1 — Pick the driver + the look
Choose (or download) the driving video whose performance you want the avatar to
copy, and decide the avatar look. **Confirm the driver shows a single animated
character** (see the multi-character workflow above if not), **check the
driver/avatar gender match** (warn + ask if they differ), and **check the
reference scene supports the driver's object interactions** (see above). Preview
the resolved inputs with `--dry-run` (no spend): it prints the resolved hero,
prepared image/video sizes and the plan.

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
- **Face looks distorted / wrong gender vibes** → likely a human driver of a
  different gender than the avatar (DreamActor copies facial gesture/feature
  placement). Use a same-gender driving clip, or accept the drift knowingly.
- **Face mushy in full-body shots** → the face is too small in the reference;
  switch to a half-body (mid-thigh up) reference so face/torso carry the detail
  and let the model infer the rest.
- **Props appear/change mid-clip, unnatural contact** → the reference scene lacks
  the element the driver interacts with; regenerate the reference with a coherent
  interactable counterpart (bench/mat/bar…) in position.
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
