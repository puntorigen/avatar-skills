---
name: avatar-camera-angles
description: Generate realistic camera-angle variations of a talking-head avatar from a single reference frame, reusing the gpt-image-2 skill. Produces the SAME person, outfit, room and lighting seen from a different virtual camera position (push-in, pull-out, low/high angle, three-quarter, Dutch tilt, off-center negative space for captions) so a reel can "cut" the camera every 4-8s while the speaker keeps addressing the lens. Each still then drives a lip-synced clip (seedance-2 / VEED Fabric). Use when the user wants to create reel shots / camera cuts / multiple angles / perspectives for an avatar or talking-head video, simulate a multi-cam talking head, or vary the framing of a presenter while keeping identity and scene consistent.
---

# Avatar Camera Angles

Turn **one** still of a person talking to camera into a set of **realistic
camera-angle variations** of the *same* recording — same face, same outfit,
same room, same light, only the virtual camera moves. Built for vertical reels
where the shot cuts every 4–8 seconds while the speaker keeps talking to the
lens (the exact pattern seen in real talking-head reels).

This skill is a **thin wrapper around the `gpt-image-2` skill**. gpt-image-2
preserves a reference image's identity at high fidelity; this skill adds the
prompt engineering that turns that into a believable camera move instead of a
new portrait.

## Why it works (validated recipe)

Each prompt is assembled from three parts:

1. **Fixed identity/scene block** — locks the subject, wardrobe, background
   props, and lighting so the result reads as another frame of the same video.
2. **Camera slot** — the single thing that changes, from the move catalog.
3. **Framing anchor** — stops the model's main failure mode: drifting wider /
   looser than the source. Most moves keep a tight chest-up frame; `pull_out`
   and the `negative_space_*` moves override the anchor on purpose.

This was validated empirically against a real talking-head frame: identity and
the room stay consistent across moves while only the camera position changes.

## Setup

Generation runs through `gpt-image-2`, which owns the Replicate token (shared
across the Replicate skills — no separate key needed). This skill only needs
Pillow for the optional 9:16 crop:

```bash
pip3 install -r ~/.cursor/skills/avatar-camera-angles/scripts/requirements.txt
# gpt-image-2 must be installed too (usually already is):
pip3 install -r ~/.cursor/skills/gpt-image-2/scripts/requirements.txt
```

## Workflow

1. **Pick the reference frame.** A sharp, front-ish talking-head still of the
   avatar (e.g. an `avatar-frames` output). 1 ref is enough; up to 3 helps lock
   identity.
2. **Write the scene profile.** Look at the frame and describe four fields —
   `subject`, `wardrobe`, `scene`, `light` — in a small JSON file (see
   [examples/lolo_scene.json](examples/lolo_scene.json)). This is the most
   important step: the more accurate it is, the less the scene drifts. You can
   also pass the fields as `--subject/--wardrobe/--scene/--light`.
3. **Choose camera moves** from the catalog (`--list`).
4. **Generate** the masters (native 2:3), optionally with `--crop916` for the
   reel-ready 9:16 crop.
5. **Review & re-roll.** Use `--count N` or re-run a move to pick the best take.
6. **Animate each still** with lip-sync per shot (the **`seedance-2`** skill or
   VEED Fabric) and stitch the clips into the reel, cutting between angles every
   4–8s.

## Quick reference

```bash
# Inspect the catalog (no API call)
python3 ~/.cursor/skills/avatar-camera-angles/scripts/generate_angles.py --list

# Preview an assembled prompt without generating
python3 ~/.cursor/skills/avatar-camera-angles/scripts/generate_angles.py \
  --scene-file scene.json --move dutch_tilt --print-prompt

# Generate a few angles (masters in 2:3) + reel-ready 9:16 crops
python3 ~/.cursor/skills/avatar-camera-angles/scripts/generate_angles.py \
  --ref frame_0001.png --scene-file scene.json \
  --move push_in --move low_angle --move three_quarter --move negative_space_left \
  --crop916 -o out/ --slug lolo

# Generate only the empirically validated moves
python3 ~/.cursor/skills/avatar-camera-angles/scripts/generate_angles.py \
  --ref frame_0001.png --scene-file scene.json --validated-only --crop916 -o out/
```

Every run prints a JSON object to stdout with a `results` array (each item has
`master` and, with `--crop916`, `reel_916`). Per-move prompts are saved next to
the images as `<slug>_<move>.prompt.txt` for transparency.

## Camera-move catalog

| Move | Validated | Use it for |
|---|---|---|
| `push_in` | ✓ | Tighter close-up; emphasis / intimacy. The safest, cleanest cut. |
| `pull_out` | ✓ | Wider medium shot (waist + desk); a visual "breather" / establishing beat. |
| `low_angle` | ✓ | Subtle contrapicado; a touch more authority. |
| `high_angle` | ✓ | Soft picado; intimate, confessional. |
| `three_quarter` | ✓ | Camera to frame-right (subject's left); dynamic, cinematic. |
| `three_quarter_mirror` | – | Same, mirrored to the other side. |
| `profile` | – | Strong near-profile (~50°); experimental, can drift more. |
| `dutch_tilt` | ✓ | Canted horizon ~9°; editorial energy. |
| `negative_space_left` | ✓ | Subject on the right, clean empty space on the LEFT for captions. |
| `negative_space_right` | – | Subject on the left, clean empty space on the RIGHT for captions. |
| `pip` | – | **Centered, locked close-up for a circular picture-in-picture badge** (e.g. avatar over a `broll-web-capture` base). Tight, even margin all around, eye-level, no rotation — meant to be lip-synced with a **locked camera** (no push/zoom). |

"Validated" = verified to keep identity + scene consistent on a real frame.
The others are sound variations; preview/re-roll them as needed.

### The `pip` move (picture-in-picture badge)

When an avatar appears as a small circular badge over a base layer (a
`broll-web-capture` capture, a demo, a terminal), it should be a **dedicated
shot**, not a reused angle: a tight, perfectly **centered** face close-up with
even margin all around (so the circle never clips the face or hair), framed at
eye level with no rotation.

- **Generate it at `1:1`** so the circular crop wastes nothing:
  `--move pip -ar 1:1` (skip `--crop916` — the square master *is* the PiP source).
- **Keep it still when you animate it.** This still drives a lip-synced clip,
  but the PiP face must **stay put**. For the PiP, **always lip-sync with
  [`avatar-talking-video`](../avatar-talking-video/SKILL.md) (`p-video-avatar`),
  not `seedance-2`**, keeping the camera **locked**: pass a `--video-prompt`
  like *"The person is talking, head still, no camera movement"* (no push-in,
  pull-out, zoom or dolly) so only the face moves. The base layer carries the
  motion; the avatar is the steady credential anchor.
- Don't burn subtitles into the PiP clip — captions go on the **whole reel
  frame** (the reel composer's finish pass), not inside the circle.

## Aspect ratio: master 2:3, reel crop 9:16

gpt-image-2 renders natively only at `1:1 / 3:2 / 2:3`. This skill generates the
**master at `2:3`** (the cleanest vertical — no canvas padding, full native
resolution ~1024×1536). `--crop916` then **center-crops** the sides to a
`9:16` reel frame (~864×1536), keeping native resolution (no upscaling). Keep
the 2:3 masters as the archive; feed the 9:16 crops to the reel.

## Options

| Option | Default | Description |
|---|---|---|
| `--ref PATH` | — | Avatar reference frame (repeatable, 1–3). Required to generate. |
| `--scene-file` | — | JSON profile: `subject`, `wardrobe`, `scene`, `light`. |
| `--subject/--wardrobe/--scene/--light` | — | Per-field overrides (or use instead of a file). |
| `--move NAME` | — | Camera move (repeatable). |
| `--all` / `--validated-only` | — | Run the whole catalog / only validated moves. |
| `--crop916` | off | Also write a 9:16 center-crop per image. |
| `--output, -o` | `.` | Output directory. |
| `--slug` | `angle` | Output filename prefix. |
| `--aspect-ratio, -ar` | `2:3` | Master ratio passed to gpt-image-2. |
| `--quality, -q` | `high` | Fidelity (`low/medium/high/auto`). |
| `--count, -n` | `1` | Variations per move (1–10). |
| `--retries` | `2` | Retries per generation on transient Replicate timeouts. |
| `--list` / `--print-prompt` | — | Inspect catalog / preview prompts (no API call). |

## Tips

- **Consistency across a reel:** always use the *same* reference frame (and the
  same scene profile) for every shot, so the avatar doesn't drift between cuts.
- **Subtle beats subtle:** small camera moves (`push_in`, `low_angle`,
  `high_angle`) feel like real edits; big ones (`profile`, hard `three_quarter`)
  are punchier but drift more — preview before committing.
- **Captions:** generate `negative_space_*` shots for any segment that needs an
  on-screen headline; the empty side is left clean for text.
- **Background variation is fine:** the model reconstructs occluded props
  slightly differently per angle — that actually reads as natural across cuts.
- **Faster drafts:** use `--quality low` to scout framings, then re-run the
  keepers at `high`.

## Related skills

- [`gpt-image-2`](../gpt-image-2/SKILL.md) — the underlying image generator.
- [`avatar-frames`](../avatar-frames/SKILL.md) — extract clean reference frames.
- [`seedance-2`](../seedance-2/SKILL.md) — animate each still (lip-sync / motion).
- [`avatar-video-reel`](../avatar-video-reel/SKILL.md) — full reel pipeline.

See [REFERENCE.md](REFERENCE.md) for the prompt internals and design notes.
