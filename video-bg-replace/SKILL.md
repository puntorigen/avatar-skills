---
name: video-bg-replace
description: Replace the background of a talking-head clip by matting the speaker (Robust Video Matting on Replicate) and compositing them over a NEW background — a generated/animated B-roll clip, a provided video, or a still image. The speaker layer gets a temporally-stable alpha matte, then ffmpeg lays it over the new background (alpha-mask + original RGB, or green-screen + chromakey), with optional edge feather, grounding drop-shadow and a unifying color grade, while preserving the speaker's original audio. Use when the user wants to swap/replace a video background, put an avatar over a different scene, place an animated video behind a person, key out / matte a talking head, or composite a presenter onto generated B-roll.
---

# Video BG Replace

Put a talking-head speaker on a **new background**. The speaker is matted with
**Robust Video Matting (RVM)** on Replicate — a recurrent net with temporal
memory, so the matte stays stable frame-to-frame instead of flickering like
per-image background removers — then composited over a new background
video/image with ffmpeg.

This is the compositing counterpart to `broll-generator`: that skill generates
a silent animated background, this skill marries the matted speaker to it.

## The key idea

Both "mask the speaker and drop them on a new bg" and "put an animated video
behind the front video" reduce to the **same layer stack**:

```
[ new background video/image ]   ← bottom layer
[ matted speaker (with alpha) ]   ← top layer
```

There's no way to see "behind" the front clip without transparency, so the
speaker **must be matted**. Talking-head clips from `avatar-talking-video` /
`p-video-avatar` / seedance are rendered full-frame with their own background,
so matting is always required (you can't skip it by generating on green).

## Setup

Shares the Replicate token with the other Replicate-based skills, so if any of
them is configured it's found automatically.

```bash
pip3 install -r .cursor/skills/video-bg-replace/scripts/requirements.txt
# Only if no sibling skill has a token yet:
python3 .cursor/skills/video-bg-replace/scripts/setup_key.py r8_YOUR_TOKEN
```

`ffmpeg`/`ffprobe` must be on PATH (libx264).

## Quick start

```bash
SCRIPTS=.cursor/skills/video-bg-replace/scripts

# Route A (recommended): alpha matte + original RGB, composited over a b-roll bg
python3 $SCRIPTS/replace_bg.py lolo/generated-videos/scene01.mp4 \
  --bg lolo/broll/003_calle-de-noche.mp4 --shadow --grade

# See the planned RVM call + ffmpeg command without spending anything
python3 $SCRIPTS/replace_bg.py scene01.mp4 --bg bg.mp4 --dry-run
```

Output: `<avatar>/generated-videos/bg-replaced/<speaker>__bg-<bg>.mp4` (when the
speaker lives under an avatar folder) plus a `manifest.json` entry. A JSON
summary is printed to stdout for an orchestrating skill.

## How it works

1. **Matte (RVM, Replicate)** — `arielreplicate/robust_video_matting` returns a
   **single** video per run; `output_type` selects what it renders:
   - `--matte alpha` → `output_type=alpha-mask` → grayscale matte (**default**)
   - `--matte green` → `output_type=green-screen` → speaker on green
2. **Composite (ffmpeg)**:
   - **Route A (alpha)** — `alphamerge` the *original* speaker RGB with the matte
     (true colors, no green spill), then `overlay` on the background.
   - **Route B (green)** — `chromakey` + `despill` the green clip, then `overlay`.
3. **Background prep** — the bg is cover-scaled + cropped to the target frame and
   **looped** (videos via `-stream_loop`, images via `-loop 1`) so a short clip
   covers the full speaker duration; output is trimmed to the speaker's length.
4. **Audio** — the speaker's **original** audio is preserved (the RVM output has
   none); in the green route the original clip is re-attached just for audio.
5. **Manifest** — every render is recorded (paths, route, model, dims, options).

## Route A vs Route B

| | Route A `alpha` (default) | Route B `green` |
|---|---|---|
| RVM `output_type` | `alpha-mask` | `green-screen` |
| Composite | alphamerge original RGB + matte | chromakey + despill |
| Edge/hair quality | best (no spill) | green spill possible |
| RVM runs | 1 | 1 |

Prefer **A**. Use **B** only if the alpha matte disappoints on a given clip.
If RVM edges aren't good enough at all, the same graph accepts a matte from a
higher-quality video matter (MatAnyone / BEN2) via `--reuse-matte`.

## Making the composite believable

The difference between "pasted on" and "shot there":

- `--feather 1.5` — soften the matte edge to kill the halo.
- `--shadow` — soft grounding drop-shadow under the subject (alpha route).
- `--grade` — subtle contrast/saturation + vignette over the **whole** composite
  so subject and background share a color temperature.
- **Motion match** — a locked-still subject over a moving bg reads as fake. Keep
  the bg motion subtle, or give the generated bg a gentle camera move (see
  `broll-generator --camera`).

## Iterating cheaply

RVM costs an API call per run, so once you have a matte, iterate the *composite*
for free:

```bash
# 1) Render once, keeping the matte
python3 $SCRIPTS/replace_bg.py scene01.mp4 --bg bgA.mp4 --keep-matte
#    -> writes ...scene01__bg-bgA.mp4 and ...scene01__bg-bgA.matte.mp4

# 2) Reuse the matte against other backgrounds / settings — no API spend
python3 $SCRIPTS/replace_bg.py scene01.mp4 --bg bgB.mp4 \
  --reuse-matte .../bg-replaced/scene01__bg-bgA.matte.mp4 --shadow --grade
```

## Key options

| Flag | Default | Notes |
|---|---|---|
| `--bg PATH` | (required) | Background video or image. |
| `--matte alpha\|green` | `alpha` | Matting route. |
| `--reuse-matte PATH` | – | Skip RVM; reuse an existing matte/green clip. |
| `--rvm-version V` | pinned | Override RVM version (`""` = latest). |
| `--keep-matte` | off | Keep the intermediate matte next to the output. |
| `--format reel\|post\|landscape` | match speaker | Output frame; or `--width/--height`. |
| `--fps N` | speaker fps | Output frame rate. |
| `--feather N` | `0` | Matte edge blur radius (px). |
| `--shadow` | off | Grounding drop-shadow (+ `--shadow-opacity/-dx/-dy/-blur`). |
| `--grade` | off | Unifying color grade + vignette. |
| `--chroma-color/-similarity/-blend`, `--no-despill` | – | Green-route key tuning. |
| `--no-audio` | off | Drop the speaker's audio. |
| `--avatar-dir / --out-dir / --out / --out-name` | – | Output location. |
| `--dry-run` | off | Print the RVM call + ffmpeg command; run nothing. |

## Fits the avatar pipeline

Use as a **leaf skill** the way `broll-generator` is: generate a background with
`broll-generator` (or seedance), render the talking head with
`avatar-talking-video`, then call `replace_bg.py` per talking-head scene. The
composited clip then flows through the normal `avatar-reel-composer` finishing
pass (captions, music, transitions). Mattes and composites are cached under the
avatar's `generated-videos/` like the rest of the generated media.

## Notes

- RVM output has **no audio** — Route A keeps the original RGB clip (audio
  intact); Route B re-attaches the original clip just for its audio track.
- Output defaults to the speaker's own resolution to keep the face crisp; the
  background conforms to it (cover-fit + crop).
- Matting is a long-running Replicate op (~seconds to a minute depending on clip
  length); the composite is local ffmpeg.
