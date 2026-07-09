---
name: avatar-invent
description: Invent a brand-new FICTIONAL avatar from a text description — no real person, photo or recording needed. Generates a front-facing, well-lit, seated half-body presenter still (photorealistic by default; soft3d/Pixar, anime or a custom style on request) in a room that fits the topic, derives camera-angle variations, and DESIGNS a matching voice with ElevenLabs Voice Design which is then cloned with MiniMax — all written into the same per-avatar folder structure (scene.json, talking_profile.json, refs/, angles/, voices/, avatar.json) that avatar-reel-composer and reel-restyle consume. Defaults follow UGC talking-head reel best practices (eyes to lens, soft key from the left + soft backlight, vertical 9:16). Use when the user wants to make up / invent / fabricate an avatar, character or presenter for a reel from just a description (e.g. "inventa un avatar de una psicóloga para un reel", "create a fictional presenter", "necesito un personaje para generar un reel"), rather than cloning an existing person.
---

# Avatar Invent

Fabricate a complete, reel-ready **fictional** avatar from a single text
description. Where `avatar-reel-composer`'s `create_avatar.py` *clones* a real
person from their Instagram reels, this skill **invents** one: it casts a face,
a room, a delivery style and a voice, and writes them into the exact same
per-avatar folder structure the rest of the pipeline already understands.

The result is a first-class avatar — drop it straight into
`avatar-reel-composer` / `reel-restyle` to produce reels.

> **Output location.** A bare avatar name is created under `./avatares/<name>/`
> (so generated avatars never clutter the project root); pass an explicit path
> (e.g. `path/to/nora`) to override, or set `AVATARES_ROOT`. `<avatar>/` below
> refers to that folder.

## What it produces

```
<avatar>/
  brief.json             # the inputs (description, setting, style, ...)
  scene.json             # subject / wardrobe / scene / light  (drives the still + angles)
  talking_profile.json   # p-video delivery prompt (calm presenter, eyes to lens)
  voice_brief.json       # ElevenLabs voice description + sample text
  refs/<slug>_hero.png   # the hero presenter still (+ _hero_master.png)
  angles/<slug>_<move>_916.png   # camera-angle cuts (push_in, pull_out, ...)
  frames/frame_0001.png + manifest.json   # hero exposed as a clean reference frame
  voices/<name>.json + index.json + <name>_design_sample.mp3   # MiniMax voice_id
  avatar.json            # the record (invented: true, stages, artifacts)
```

## Defaults (UGC talking-head reel best practices)

All baked into `prompts/presets.json` and overridable:

- **Photorealistic** render (use `--style soft3d` for Pixar-like, `--style anime`,
  or any custom style string).
- **Vertical 9:16**, eye-level, **looking straight into the lens**, leaning in slightly.
- **Seated, half-body** (waist/chest-up) medium shot, with clean negative space on
  one side for captions.
- **Soft, flattering light**: soft key from the left ~45°, a gentle rim/back light,
  open fill — no harsh shadows.
- **Phone-camera look**: ~35–50mm, shallow depth of field, natural color.
- **Room fits the topic** via `--setting` (office, home, studio, street, outdoors,
  kitchen, cafe, gym, clinic, …).
- Neutral **mid-sentence expression** (lips slightly parted) so the still animates
  well for lip-sync.

## Setup

Keys are auto-discovered from the sibling skills (usually nothing to set):

- **ElevenLabs** (voice design) ← `audio-theater/config.json`
- **Replicate** (hero still via gpt-image-2 + MiniMax clone) ← `gpt-image-2` / `voice-clone`
- **Gemini** (only for `--generator gemini`) ← `asset-generator/config.json`

```bash
pip3 install -r .cursor/skills/avatar-invent/scripts/requirements.txt
# sibling deps (usually already installed):
pip3 install -r .cursor/skills/voice-clone/requirements.txt
pip3 install -r ~/.cursor/skills/gpt-image-2/scripts/requirements.txt

python3 .cursor/skills/avatar-invent/scripts/setup_key.py --show   # verify keys
```

Cloning the designed voice with MiniMax needs **`cloudflared`** (preferred) or
**`ngrok`** on PATH, same as the `voice-clone` skill (`brew install cloudflared`).

## Workflow

The orchestrator runs an idempotent stage machine and **stops once** for an agent
review (the creative casting step) before any paid generation.

```bash
# 1) Invent: auto-drafts scene/profile/voice, then pauses for review.
python3 .cursor/skills/avatar-invent/scripts/invent_avatar.py nora \
    --description "Chilean woman, mid 30s, warm and reassuring, clinical psychologist" \
    --setting clinic --language es

#    -> review & refine nora/scene.json, talking_profile.json, voice_brief.json
#       (make the SUBJECT a vivid concrete face; tune wardrobe/room/voice).

# 2) Re-run to generate the hero still + angles + designed-and-cloned voice:
python3 .cursor/skills/avatar-invent/scripts/invent_avatar.py nora

# Inspect readiness any time (no API spend):
python3 .cursor/skills/avatar-invent/scripts/invent_avatar.py nora --status
```

Skip the pause with `--no-review` for a one-shot run. Re-run any stage with
`--force-stage hero` / `--force-stage voice` etc.

### The author checkpoint (why it matters)

The script seeds `scene.json` / `talking_profile.json` / `voice_brief.json` from
the brief + the topic's defaults, but the **`SUBJECT` field is just your raw
description**. Refine it into a concrete, vivid person (age, face, hair, skin,
expression) — gpt-image-2's identity fidelity is only as good as that text, and
the same `scene.json` is reused for every camera angle, so a precise subject is
what keeps the avatar from drifting between cuts.

## Common variations

```bash
# Pixar-style soft 3D character instead of photoreal
python3 .../invent_avatar.py leo --description "..." --setting home --style soft3d

# Horizontal 16:9 (angles auto-off; the hero still is the deliverable)
python3 .../invent_avatar.py max --description "..." --setting office -ar 16:9

# Use Gemini for the hero (native 9:16/16:9, up to 4K) instead of gpt-image-2
python3 .../invent_avatar.py mia --description "..." --generator gemini

# Custom camera moves
python3 .../invent_avatar.py mia --description "..." --moves push_in,low_angle,negative_space_left
```

## Single-stage scripts (also usable standalone)

```bash
# Just the hero still from a scene.json (preview the prompt with --print-prompt):
python3 .cursor/skills/avatar-invent/scripts/generate_hero.py \
    --scene-file nora/scene.json --style photoreal -ar 9:16 -o nora/refs/ --slug nora

# Just the voice (ElevenLabs design -> MiniMax clone):
python3 .cursor/skills/avatar-invent/scripts/design_voice.py \
    --avatar-dir nora --name nora --voice-brief nora/voice_brief.json
```

## After it's READY

Write a storyboard and compose, exactly like any other avatar:

```bash
python3 .cursor/skills/avatar-reel-composer/scripts/compose_reel.py \
    nora/reels/001_slug/storyboard.json --finish
```

## How the voice works (ElevenLabs → MiniMax bridge)

A fictional avatar has no recording to clone, so the voice is **designed** from
text: ElevenLabs Voice Design (`/v1/text-to-voice/design`) invents a voice from
`voice_brief.json`'s description and returns a long spoken sample. That clean
sample is then handed to the **`voice-clone`** skill (MiniMax), producing the
same `voices/<name>.json` + `index.json` (`voice_id`) every avatar uses — so
`avatar-reel-composer`'s `narrate.py` speaks the new voice with **no changes**.
The ElevenLabs provenance (description, preview ids) is kept in
`voices/<name>_design.json`.

See [REFERENCE.md](REFERENCE.md) for the stage machine, the prompt internals, the
presets schema and design notes.

## Related skills

- [`avatar-camera-angles`](../avatar-camera-angles/SKILL.md) — the angle generator this calls.
- [`voice-clone`](../voice-clone/SKILL.md) — the MiniMax clone step (+ TTS).
- [`avatar-talking-video`](../avatar-talking-video/SKILL.md) — animate a still into a talking clip.
- [`avatar-reel-composer`](../avatar-reel-composer/SKILL.md) — compose the finished reel.
- [`reel-restyle`](../reel-restyle/SKILL.md) — apply another avatar's reel style to this one.
