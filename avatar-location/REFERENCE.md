# avatar-location — reference

Internals, schemas and design notes for the `avatar-location` skill.

## Concept

`scene.json` already separates the avatar's **identity** (`subject` — the person) from
its **look** (`wardrobe` / `scene` / `light`). A *location* is just a new look on the
**same subject**: a bundled wardrobe + environment + light, with its own identity-anchored
hero still and camera angles. The avatar's voice, `talking_profile` and gestures are
untouched — only how it's dressed and where it sits change.

- **Default location = today's top-level** `scene.json` + `angles/`. Never modified; no
  migration. It is the implicit `"default"` look everywhere.
- New looks live under `locations/<loc>/` and are referenced by name from a reel storyboard.

## Folder layout (additive)
```
<avatar>/
  scene.json            # default look (unchanged)
  angles/               # default angles (unchanged)
  refs/<slug>_hero_master.png   # shared identity anchor (from avatar-invent / create_avatar)
  avatar.json           # gains a "locations" registry (additive)
  locations/
    <loc>/
      location.json     # record (below)
      scene.json        # subject copied from the avatar + NEW wardrobe/scene/light (+ assets[])
      assets/           # copies of asset refs (logo.png, prop.png, ...)
      refs/<slug>__<loc>_hero.png (+ _hero_master.png[, look_reference.*])
      angles/<slug>__<loc>_<move>_916.png
```
`<slug>` = `<avatar-folder-name>__<loc-slug>` (e.g. `nora__studio_night`).

## Stage machine (`create_location.py`)

Idempotent; each stage skips when its outputs already exist. Re-run to resume;
`--force-stage {hero,angles}` to redo one. `--status` prints the table and exits.

| stage | done when | does |
|---|---|---|
| `author` | location `scene.json` has non-empty subject/wardrobe/scene/light | copies `subject` from the avatar's `scene.json`; seeds wardrobe/scene/light from `--wardrobe/--scene/--light` > `--brief` > `--setting` (else the avatar's own look); copies `--asset` files into `assets/` and records `assets[]`; copies `--from-image` into `refs/`; writes a draft `location.json`; **stops once** for review (unless `--no-review`) |
| `hero` | a `refs/<slug>__<loc>_hero*.png` exists | `avatar-invent/generate_hero.py --anchor-identity --ref <avatar hero_master> [--ref <asset>…]` → identity-anchored master (2:3/3:2) + cropped hero |
| `angles` | every move has `angles/<slug>__<loc>_<move>_916.png` | `avatar-camera-angles/generate_angles.py --ref <location hero_master> [--ref <asset>…] --crop916` |
| `record` | `location.json` has a status and the avatar's `locations` registry lists it | writes the final `location.json` + merges into `avatar.json` `locations` |

### Identity anchoring
The avatar's `refs/<slug>_hero_master.png` (resolved via `avatar.json artifacts.hero_master`,
then conventional paths, then any clean ref/frame/angle) is passed to the hero generation as
`--ref` with `--anchor-identity`, so the **face/person stays identical** while the look
changes. The generated location hero (its master) is then the reference for the angles, so
the angle set reads as the same recording in the new look. Asset refs are forwarded to both
hero and angles so a logo/prop stays crisp across re-renders.

## `scene.json` (location)
```json
{
  "subject": "<copied from the avatar — do not change the person>",
  "wardrobe": "<the NEW outfit>",
  "scene": "<the NEW environment/background>",
  "light": "<the NEW lighting mood>",
  "assets": [
    {"file": "assets/logo-primary.png", "placement": "printed large and centered on the chest of the white t-shirt"}
  ]
}
```
`assets` is optional. `assets[].file` is relative to the location folder. The placement
strings are appended to the hero AND angle prompts (`build_hero_prompt` / `_prompt.build_prompt`).

## `location.json`
```json
{
  "avatar": "doki-monster", "location": "brand_tee", "name": "brand_tee",
  "brief": "...", "source": "brief|setting|flags|from-image",
  "status": "draft|partial|ready",
  "style": "soft3d", "aspect_ratio": "9:16", "generator": "gpt-image-2",
  "created_at": "...", "updated_at": "...",
  "scene": "scene.json",
  "look": {"wardrobe": "...", "scene": "...", "light": "..."},
  "assets": [{"file": "assets/logo-primary.png", "placement": "..."}],
  "look_reference": "refs/look_reference.png",
  "moves": ["push_in", "pull_out", "low_angle", "three_quarter", "negative_space_left"],
  "hero": "refs/<slug>__<loc>_hero.png",
  "hero_master": "refs/<slug>__<loc>_hero_master.png",
  "angles": ["angles/<slug>__<loc>_push_in_916.png", ...]
}
```

## `avatar.json` `locations` registry (additive)
```json
"locations": {
  "studio_night": {"name": "Studio Night", "dir": "locations/studio_night",
                   "status": "ready", "angles": 5, "assets": 0, "updated_at": "..."}
}
```
Merged in by `create_location.py` and **preserved** by `avatar-invent/invent_avatar.py`'s
`write_report` (so re-inventing/refreshing an avatar doesn't clobber its looks). The default
location is intentionally NOT listed here — it's implicit.

## Composer integration (`avatar-reel-composer`)
`compose_reel.py` resolves a talking-head angle by:
1. explicit scene `image` path (always wins); else
2. scene `angle` move name globbed under the **active location**'s
   `<avatar>/locations/<loc>/angles/**/*<angle>*_916.png`, where the active location =
   per-scene `location` > reel-level `location` > `"default"` (top-level `angles/`).
   If the location lacks that angle it falls back to the default look with a warning.
A `--dry-run` prints the resolved angle (and `@ <loc>`) per talking-head scene for a
no-spend confirmation. Voice, narration, guest and B-roll scenes are unaffected.

## Key discovery (`_common.py`)
`env var → avatar-location/config.json → sibling configs` (avatar-invent / gpt-image-2 /
asset-generator). Override with `setup_key.py`. Sibling scripts + the avatar-invent
`presets.json` are resolved preferring the project-local `.cursor/skills` copy, then the
user-level install.

## Gotchas
- **gpt-image-2 has no resolution knob** — `--quality high` is the native max; `low` is for
  scouting. Re-run `--force-stage angles -q high` for finals.
- **Reference limit:** keep refs to identity + 1–2 assets; too many references can make
  gpt-image-2 drop the identity. The skill warns past ~4 refs.
- **Identity/asset drift:** review the hero before generating angles (the author checkpoint
  is one pause; you can also `--force-stage hero` to re-roll). Re-roll a single angle by
  deleting its `*_916.png` and re-running.
- **16:9:** the angle catalog is tuned for vertical 9:16 crops; locations default to the
  avatar's aspect ratio.
- A location's `subject` must stay the avatar's — editing it would change the person and
  break identity consistency across reels.
