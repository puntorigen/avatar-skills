---
name: avatar-location
description: >-
  Create a new LOCATION (a look) for an existing avatar — keep its IDENTITY
  (face, gestures, cloned voice, talking_profile) but vary the LOOK: wardrobe +
  environment + light, optionally incorporating asset references (a logo on a
  shirt/jacket, a prop in the scene). Generates an identity-anchored hero still +
  camera angles under <avatar>/locations/<loc>/, selectable later per reel and
  per scene by avatar-reel-composer, so one avatar can appear in many looks
  without re-making it. The avatar's DEFAULT location is just what exists today
  (top-level scene.json + angles/) and is untouched. Use when the user wants to
  "dress" an avatar differently, put it in another setting/room, give it a
  wardrobe/scene variant, add a branded outfit (logo on the shirt) or a prop,
  create reel looks, or asks for avatar locations / outfits / wardrobes /
  environments / "otro ambiente" / "otra ropa" for an avatar.
---

# avatar-location

Give one avatar multiple **looks**. A *location* = **wardrobe + environment + light**
bundled together, on the **same subject** (identity). It reuses the avatar's existing
identity (face, gestures, cloned **voice**, `talking_profile`) and only re-dresses /
re-rooms it, producing a new identity-anchored hero + camera angles. Reels then pick a
look per-reel and/or per-scene via avatar-reel-composer's `location` field.

> The avatar's **default location is what exists today** — the top-level `scene.json` +
> `angles/`. It is never modified; locations are purely additive under `locations/<loc>/`.

## When to use
- "Dress the avatar differently" / "put them in another room/setting" / "otra ropa, otro ambiente".
- A **branded** outfit (stamp a logo on the shirt) or a **prop** in the scene → use `--asset`.
- Build several reel looks for the same person; cut between looks within a reel.

## Setup
Keys are inherited from sibling skills (Replicate for gpt-image-2; Gemini only for
`--generator gemini`). Check with `scripts/setup_key.py --show`. Install deps once:
`pip3 install -r scripts/requirements.txt`. Requires an **existing avatar** with a
`scene.json` (a `subject`) and an identity anchor (`refs/<slug>_hero_master.png`, as
produced by `avatar-invent` or `create_avatar.py`).

## Workflow (idempotent stage machine — mirrors avatar-invent)
`scripts/create_location.py <avatar-dir> <loc-name>` runs: **author → hero → angles →
record**, resuming where it left off. It pauses **once** after `author` for a review
checkpoint before any paid generation (skip with `--no-review`).

```bash
# 1) Author + review: seed the LOOK (subject is copied from the avatar; you edit
#    wardrobe/scene/light). Stops for review before spending.
python3 ~/.cursor/skills/avatar-location/scripts/create_location.py nora studio_night \
    --setting studio \
    --brief "evening content studio, moody teal key light, black turtleneck"
#    ...edit nora/locations/studio_night/scene.json (wardrobe/scene/light/assets), then:

# 2) Re-run to generate the identity-anchored hero + angles (PAID: ~1 hero + ~5 angles).
python3 ~/.cursor/skills/avatar-location/scripts/create_location.py nora studio_night

# Inspect looks (default + locations):
python3 ~/.cursor/skills/avatar-location/scripts/list_locations.py nora

# 3) Use it in a reel (avatar-reel-composer storyboard):
#    top-level   "location": "studio_night"          (reel default look)
#    or per scene "location": "studio_night"          (override one scene)
```

### Asset references (logo / prop)
Pass an image to stamp/place, with a placement instruction. Assets are copied into
`locations/<loc>/assets/`, recorded in the look's `scene.json` `assets[]`, and attached
as gpt-image-2 references to **both** the hero and the angles (so the logo/prop stays
crisp and consistent across angle re-renders):

```bash
python3 ~/.cursor/skills/avatar-location/scripts/create_location.py doki-monster brand_tee \
    --asset doki-monster/brand/logo-primary.png \
    --asset-placement "printed large and centered on the chest of the white t-shirt" \
    --setting studio --no-review
```
Repeat `--asset`/`--asset-placement` (paired by order) for multiple assets. Keep it to
~1–2 assets so gpt-image-2 doesn't drop the identity anchor.

## Seeding the look
The author stage fills `wardrobe`/`scene`/`light`, falling back to the avatar's own look
so every field is non-empty (a valid no-op even with `--no-review`). Sources, in order
of specificity: explicit `--wardrobe`/`--scene`/`--light` > `--brief` (free text, seeded
into the setting; refine at the checkpoint) > `--setting <keyword>` (reuses avatar-invent
presets: office/home/studio/street/outdoors/kitchen/cafe/gym/clinic). `--from-image PATH`
saves a look reference that's attached to the hero generation.

## Cheap validation (no spend)
- `generate_hero.py --print-prompt` / `generate_angles.py --print-prompt` show the prompts.
- Scout angles at `--quality low`, then re-run at `high` for finals (`--force-stage angles`).
- `compose_reel.py <storyboard with location> --dry-run` prints the resolved angle per
  talking-head scene (with `@ <loc>`), confirming the look before any generation.

## Key flags
`--name`, `--style` (default: avatar's), `-ar/--aspect-ratio`, `--generator`,
`--quality {low,medium,high,auto}`, `--moves a,b,c` (default: presets), `--no-review`,
`--force-stage {hero,angles}`, `--status`.

## Output (under `<avatar>/locations/<loc>/`)
```
location.json     # record: name, brief, source, status, style, look, assets, angles
scene.json        # subject (copied) + NEW wardrobe/scene/light (+ assets[])
assets/           # copies of the asset refs (logo.png, prop.png, ...)
refs/<slug>__<loc>_hero.png (+ _hero_master.png[, look_reference.*])
angles/<slug>__<loc>_<move>_916.png
```
Also merges a `locations` registry into `<avatar>/avatar.json` (additive; preserved when
`invent_avatar.py` is re-run). `<slug>` = `<avatar>__<loc>`.

See `REFERENCE.md` for the data model, stage details and gotchas.

## Reuses (does not duplicate)
- `avatar-invent/scripts/generate_hero.py` — `--anchor-identity --ref <hero_master> [--ref <asset>…]`.
- `avatar-camera-angles/scripts/generate_angles.py` — `--ref <location hero> [--ref <asset>…]`.
- `avatar-reel-composer` consumes a location via the storyboard `location` field.
