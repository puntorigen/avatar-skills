# Avatar Camera Angles — Reference

Design notes and internals for the `avatar-camera-angles` skill. Start with
[SKILL.md](SKILL.md); read this when you want to understand or tune the prompt
recipe.

## The problem

Re-rendering "the same person from a different camera" is really a small
novel-view-synthesis task. gpt-image-2 (`openai/gpt-image-2`) is good at it
because it preserves a reference image's identity at high fidelity — but left to
its own devices it tends to:

1. **Widen / loosen the frame** (the dominant failure mode — it pulls back and
   adds headroom/torso even when you don't ask).
2. **Restyle** into a cleaner "portrait" that loses the candid phone-video look.
3. **Invent** the occluded parts of the room.

The prompt recipe is designed to counter (1) and (2). (3) is unavoidable and
actually harmless — minor background differences read as natural between cuts.

## Prompt anatomy (`scripts/_prompt.py`)

```
[HEADER]  "another real frame of the very same recording, a fraction of a
           second later, from a slightly different camera position. NOT a new
           scene / restyle / illustration."

[PRESERVE EXACTLY]
   - subject   (identity: age, skin, hair, eyewear, expression)
   - wardrobe  (garment, colors, details, crest/logo)
   - scene     (room + props + their frame positions)
   - light     (key direction, mood, color grade)
   - realistic-detail clause (skin texture, real reflections, no smoothing,
     no added text/logo/watermark)

[CHANGE ONLY THE CAMERA / FRAMING]
   {camera}    ← the one variable, from camera_moves.json

[FRAMING ANCHOR]
   {anchor}    ← default = "keep the tight chest-up frame, do not widen";
                 pull_out / negative_space_* override it

[FOOTER]  vertical, smartphone front-camera look (~26-28mm), subject sharp /
          background soft, indistinguishable from a real still.
```

`build_prompt(profile, move_key)` fills the template. The `subject/wardrobe/
scene/light` come from the **scene profile** (a JSON file or CLI flags); the
`camera` and optional `anchor` come from the **move catalog**.

## Scene profile

Four free-text fields. Accuracy here is what keeps identity/scene from drifting:

```json
{
  "subject":  "who they are + face/hair/eyewear/expression",
  "wardrobe": "exact garment, colors, distinguishing details",
  "scene":    "room + props + where they sit in the frame",
  "light":    "key direction, mood, color grade"
}
```

Write it by *looking at the reference frame*. Describe frame-relative positions
("diplomas in the upper-left, bookshelf on the right") so moves that reveal more
of one side stay coherent.

## Move catalog (`scripts/camera_moves.json`)

Each move has:

- `label` — human description.
- `validated` — `true` if verified to hold identity+scene on a real frame.
- `tags` — rough intent (safe / cinematic / captions / ...).
- `camera` — the camera-change instruction (the prompt's only variable).
- `anchor` *(optional)* — overrides `_default_anchor`. Used by `pull_out` (wants
  a wider frame) and `negative_space_*` (wants an off-center frame), which would
  otherwise be fought by the default "do not widen / do not add empty space".

Add a move by appending an entry — no code change needed.

### The `pip` move (special case)

`pip` is the only move framed for a **circular picture-in-picture badge** rather
than a full reel frame. It overrides the default anchor with a *tighter,
centered* one (the opposite of `pull_out`/`negative_space_*`), so the face fills
a square with even margin all around and a circle never clips it. Two rules when
using it:

- **Render at `1:1`** (`--move pip -ar 1:1`) — the square master *is* the PiP
  source, so skip `--crop916`.
- **Animate it locked with `p-video-avatar`.** For the PiP, always lip-sync with
  [`avatar-talking-video`](../avatar-talking-video/SKILL.md)
  (`prunaai/p-video-avatar`), **not** `seedance-2`. Keep the camera locked: a
  `--video-prompt` like *"The person is talking, head still, no camera
  movement"* (no push/pull/zoom/dolly). The base layer under the PiP carries the
  motion.

### Calibrated magnitudes

Validated, natural-looking amounts (push further only if you want it obvious):

- low angle: ~16° up, camera ~chest height
- high angle: ~14° down, camera just above eye line
- three-quarter: ~30° around
- profile: ~50° around (experimental — more drift)
- Dutch tilt: ~9° roll
- push-in: ~25 cm closer; pull-out: ~40 cm back

## Generation path (`scripts/generate_angles.py`)

1. Build the prompt per move, write it to `<slug>_<move>.prompt.txt`.
2. Shell out to `gpt-image-2/scripts/generate_image.py` with the prompt file,
   `--ref`(s), `-ar 2:3`, `-q high`, `-n count`, `-o <slug>_<move>.png`.
3. Parse the JSON that generate_image.py prints (`["files"]`).
4. Retry on failure up to `--retries` times — gpt-image-2 occasionally hits a
   transient Replicate **read-timeout**; a re-run almost always succeeds.
5. With `--crop916`, center-crop each master from 2:3 to 9:16 (trim the sides,
   native resolution, no upscaling) → `<slug>_<move>_916.png`.

We intentionally call the existing CLI rather than importing its internals, so
this skill stays decoupled from gpt-image-2's implementation.

## Why 2:3 master, not 9:16 directly

gpt-image-2 has no native 9:16; its 9:16 mode **pads** the canvas with a sampled
border color, which leaves a visible band on a non-uniform background (bookshelf
/ wall). 2:3 is the model's true vertical maximum (~1024×1536) with no padding,
so we render there and crop to 9:16 ourselves — cleaner and still native res.

## Handoff to video

Each still is a *start frame* for a per-shot talking clip. Animate with the
`seedance-2` skill (image-to-video + lip-sync/audio) or VEED Fabric, one clip
per angle, then stitch with cuts every 4–8s. Because every shot shares the same
reference identity, the cuts read as one continuous multi-cam recording.

The `pip` shot is the exception: animate it with **`avatar-talking-video`
(`p-video-avatar`)** — not seedance — on a **locked camera** (talking only, no
move), then feed it to `broll-web-capture --avatar` as the PiP overlay.

## Troubleshooting

- **Frame drifts wider than intended** → strengthen the `subject`/`scene`
  accuracy, keep the default anchor, or pick `push_in`.
- **Identity drift across many shots** → reuse the exact same `--ref` and scene
  profile for every move; add a second/third `--ref`.
- **Transient `httpx.ReadTimeout` from Replicate** → handled by `--retries`;
  bump it if your network is flaky.
- **9:16 crop cuts too much off the sides** → keep/deliver the 2:3 master, or
  use a `negative_space_*` move so the subject isn't centered.
- **Token errors** → fix in gpt-image-2 (`setup_key.py`); this skill reuses it.
