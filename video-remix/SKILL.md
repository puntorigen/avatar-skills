---
name: video-remix
description: Analyze the visual + narrative + audio MOLD of one or more reference videos (reels/shorts/talking-head clips) — format/ratio, per-scene layout, character position + gaze, palette and color combinations, on-screen elements, action types, caption type/style, brand watermark/logo placement and how it appears/disappears, transitions, the intro->development->close arc, background music and voice-vs-music ducking, and how many distinct presenters speak — then REGENERATE a brand-new reel on NEW content that reuses that exact mold at premium quality. The remix reuses the repo's existing skills to invent or reuse one or more avatars, build the locations the mold's scenes call for, clone/design voices, score music with the same ducking, and compose/caption/polish the final video in the mold's ratio. Frame analysis uses Gemini vision (asset-generator key). Use when the user wants to clone/replicate/copy the structure, ritmo, look, captions and music of a reference video/reel, turn a winning reel into a reusable template, or "make me a video like this one but about <topic>" with my avatars.
---

# video-remix — extract a video's mold, then remix it with new content

`reel-discovery` finds a winning video and `pdf-remix` clones a PDF's mold.
**video-remix does the same for a video**: it deconstructs a reference reel into a
reusable **mold** (visual system + per-scene layout + audio/caption/watermark
systems + narrative arc + how many presenters speak) and then rebuilds a new
reel — new topic, new narration, freshly generated avatars/locations/voices/music
— that follows the mold faithfully. It is a **generalized `reel-restyle`**: any
reference video (not just an avatar's own reels), a much richer mold, multiple
avatars, and it generates the avatars/locations/voices/music it needs.

**Two phases, one skill (mirrors `pdf-remix`):**

```
ANALYZE   reference.mp4 ─▶ blueprint.json + blueprint.md + content_template.json
REMIX     content.json  ─▶ avatars/locations/voices/music ─▶ storyboard ─▶ final.mp4
```

## When to use
- "Analyze this reel and make me a template I can reuse."
- "Make a video like this one but about <topic>, with my avatar(s)."
- "Copy the estructura / ritmo / captions / música of this reference for a new script."
- "Replicate this creator's reel format for my brand."

## Setup

```bash
pip3 install -r ~/.cursor/skills/video-remix/scripts/requirements.txt
```

The REMIX phase delegates to the sibling skills — install their requirements too
(usually already present): `video-scene-analysis` (+ `setup_models.sh`),
`avatar-invent`, `avatar-location`, `voice-clone`, `avatar-reel-composer`.

Credentials are **reused, not re-entered** (env var first, then a sibling config):
- **Gemini** (frame analysis) ← `asset-generator/config.json` (or `GEMINI_API_KEY`).
- **Replicate** (avatars/voice/music/compose) ← `voice-clone` / `bg-music-hq` / … (or `REPLICATE_API_TOKEN`).
- **ElevenLabs** (only when inventing a voice) ← `audio-theater/config.json`.

`python3 ~/.cursor/skills/video-remix/scripts/setup_key.py --show` prints what resolves.

## Workflow

```
- [ ] 1. ANALYZE   → analyze_video.py reference.mp4 → runs/<slug>/{blueprint.*, content_template.json, frames/}
- [ ] 2. REVIEW    → read blueprint.md; confirm format/ratio, rhythm, captions, watermark, music/ducking, arc, #speakers
- [ ] 3. AUTHOR    → cp content_template.json content.json; write the NEW script onto the beats,
                     set brand + avatars[] (reuse avatares/<name> or invent), author each B-roll beat
- [ ] 4. AVATARS   → remix.py runs/<slug>  → if avatars unspecified it STOPS and you ASK the user
                     (invent N new, or name which existing) — N = the mold's speaker count
- [ ] 5. STORYBOARD→ remix.py drafts the composer storyboard; review the split + B-roll + music prompt
- [ ] 6. COMPOSE   → remix.py runs/<slug> --compose --finish → final.mp4 (mold's ratio, captions, ducked music)
```

### 1. Analyze the reference

```bash
python3 ~/.cursor/skills/video-remix/scripts/analyze_video.py "/path/to/reference.mp4" \
    --out-dir ~/.cursor/skills/video-remix/runs/mine --language es
```

Runs `video-scene-analysis` for the mechanical backbone (scene cuts, transcript +
word timings, per-scene SFX/music detection, one representative frame per scene),
then adds pixel palette, a watermark/logo temporal-stability pass, a music +
voice-vs-music **ducking measurement**, and **Gemini vision** — per scene
(layout, gaze, elements, action, camera, color combo, watermark/caption in-frame)
and a global synthesis (palette semantics, caption system, watermark system,
music mood, transitions, #speakers, the intro→development→close arc). Produces:
- `blueprint.json` — the machine-readable mold (design + rhythm + per-scene + arc + `beats[]`).
- `blueprint.md` — the human-readable mold (share it / paste into a brief).
- `content_template.json` — the editable skeleton to author NEW content.
- `frames/scene_XX.jpg` — the reference frames.

Analyze several references by running it per file and picking the mold you like
(or point the remix at the richest one).

### 2. Review the mold

Open `blueprint.md`. Confirm the **format/ratio**, the **rhythm** (median scene
length, hook length, cut cadence), the **caption system**, the **watermark
system** (where/how it appears + disappears), the **music + ducking**, the
**transition style**, the **number of presenters** and the **narrative arc**.
These are the rules the new reel must obey to match or beat the original.

### 3. Author the new content (the creative step)

Copy `content_template.json` → `content.json` and write the new reel *onto* the
mold. Keep its structure; adapt only the message. See [REFERENCE.md](REFERENCE.md)
for the full schema. Essentials:
- `meta`: `topic`, `language`, `format` (defaults to the mold's ratio; override to
  `reel`/`post`/`landscape`), `slug`.
- `brand`: `name`, `handle`, `logo_path`, optional `palette_override`.
- `avatars[]`: one per mold speaker. Either **reuse** an existing avatar
  (`"use": "avatares/nora"`) or **invent** one (`"invent": {"description": "...",
  "setting": "studio", "language": "es"}`). Set `speaker` on any beat spoken by a
  non-host avatar (guest). If you don't know which avatars to use, leave them null
  — the remix will stop and you ASK the user.
- `script`: the FULL verbatim narration. Its words are split across beats; the
  concatenation of every beat `text` MUST equal `script` (the composer's hard rule).
  You may fill per-beat `text` yourself, or leave them empty and let the remix
  split proportionally (then review).
- For each `broll` beat, author `broll_description` + `broll_action` for the NEW
  topic (replace any `TODO`). Optionally set a beat `location` slug for a scene
  that needs a different look — the remix builds it with `avatar-location`.
- `music` + `captions` come pre-filled from the mold; **tailor `music.prompt`** to
  the new topic/tone.

### 4-6. Remix (avatars → locations → voices → storyboard → compose)

```bash
# Stages up to the storyboard, then STOPS for review (and stops earlier if avatars
# aren't chosen or an invent/location step needs your creative checkpoint):
python3 ~/.cursor/skills/video-remix/scripts/remix.py runs/mine --base-dir .

# When ready, compose all the way to final.mp4:
python3 ~/.cursor/skills/video-remix/scripts/remix.py runs/mine --base-dir . --compose --finish
```

`remix.py` is an idempotent stage machine (exit **2** = an agent/user checkpoint
is blocking — act, then re-run; **0** = progressed / stopped for review):
1. **avatars** — reuse `avatares/<name>` or invent via `avatar-invent`. If none are
   specified, it STOPS: **ASK THE USER** whether to invent N new avatars or name N
   existing ones (N = the mold's speaker count), edit `content.json`, re-run.
2. **voices** — records each avatar's cloned `voice_id` (invented avatars already
   have one; else set `avatars[].voice_sample` to clone with `voice-clone`).
3. **locations** — reproduces the reference's LOOK. It auto-builds ONE
   `avatar-location` that matches the mold's `environment` (background + lighting +
   set elements, NOT wardrobe — the new avatar keeps its own identity) and
   generates exactly the camera moves the beats use, then sets it as the reel's
   default look. Steer/disable it with `content.location` (`auto`/`name`/`brief`/
   `assets`). Per-beat `location` slugs still build their own extra looks.
4. **storyboard** — `build_storyboard.py` → an `avatar-reel-composer` storyboard in
   the mold's ratio, with per-scene angles, motion/emphasis, captions, the music +
   ducking envelope and transitions (+ a narration plan for multi-speaker molds).
5. **compose** — `compose_reel.py --finish` → `final.mp4` (multi-speaker:
   `assemble_narration.py` first, then guest clips are patched in and composed
   over the pre-built master narration).

Use `--no-review` to skip the invent/location review checkpoints, `--dry-run` for
the composer's narrate+align only, `--format` to override the ratio,
`--regen-storyboard` to redraft, and `--status` for readiness.

## How the mold maps to the reel

- **format/ratio** → the storyboard `format` (`reel` 9:16 / `post` 1:1 /
  `landscape` 16:9) and which angle crop (`_916` vs `_169`) each talking-head uses.
- **rhythm** (`dur_weight` per beat) → the script split + pacing; scene durations
  fall out of the new narration's word alignment (structural, not beat-locked).
- **per-scene camera angle** → the avatar's matching camera-angle still;
  **`zoom_from_previous`** → Ken Burns motion; **emphasis** → a tighter push-in.
- **gaze** / **mannerisms** → the invented avatar's `talking_profile` delivery.
- **environment / lighting** (`blueprint.environment`) → the auto-built reel
  `avatar-location` (background + lighting + key set elements) so the new avatar
  performs in the reference's SET, not the avatar's default room.
- **caption system** → `finish.caption_style` reproduces the mold's structured
  look: font class (serif/**sans**), a pill/box background (`kind`/`color_hex`/
  `opacity`/`radius_frac`), text color, vertical position (`y_frac`) and alignment
  — plus reveal/casing/words-per-caption. Real figures like `98%` survive; flat
  molds render no per-word emphasis.
- **watermark system** → a brand logo `location`/overlay when `brand.logo_path` is
  set (stamped via `avatar-location --asset`); recorded in the mold for placement.
- **music + ducking** → `finish.music_*`: the mood/prompt and a `flat` or `auto`
  envelope; `auto` sidechain-ducks the bed under the voice at the measured depth.
- **transitions** → measured into `blueprint.transitions` (style + whether the
  CUTS carry SFX). The polish pass only adds a flash/SFX the original actually
  uses — silent hard cuts stay silent (`fx.enabled=false`).
- **#speakers** → how many avatars to resolve; extra presenters become `guest`
  scenes woven into one master narration.

## Anti-patterns
1. **Do not** copy the reference's *words* — copy its *structure*. The new reel
   must be genuinely new content adapted to the mold.
2. **Do not** change the mold's **ratio/pacing/ducking** — they are what make it
   feel like the original.
3. **Do not** skip the review step — the arc, caption style and music envelope are
   the payoff.
4. **Do not** silently pick avatars — if the user didn't say which, ASK (invent vs
   reuse) for the exact number the mold needs.
5. **Do not** leave `TODO` B-roll — author every insert for the new topic before composing.
6. **Do not** commit `runs/` or `avatares/` — they hold research + generated media (gitignored).

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/analyze_video.py` | Extract the mold → blueprint.json/.md + content_template.json + frames (mechanical + Gemini vision) |
| `scripts/build_storyboard.py` | blueprint + content.json → avatar-reel-composer storyboard (+ narration plan for guests) |
| `scripts/remix.py` | Orchestrator: avatars → voices → locations → storyboard → compose --finish (idempotent, checkpointed) |
| `scripts/setup_key.py` | Show/store the reused Gemini + Replicate credentials |
| `scripts/_common.py` | Credentials, Gemini vision→JSON, ffprobe geometry, palette, watermark detection, ducking measurement, sibling bridge |

## Additional resources
- Full schemas (blueprint, content), taxonomies and the stage machine: [REFERENCE.md](REFERENCE.md).
- The engine this orchestrates: [`avatar-reel-composer`](../avatar-reel-composer/SKILL.md),
  [`reel-restyle`](../reel-restyle/SKILL.md), [`avatar-invent`](../avatar-invent/SKILL.md),
  [`avatar-location`](../avatar-location/SKILL.md), [`voice-clone`](../voice-clone/SKILL.md),
  [`bg-music-hq`](../bg-music-hq/SKILL.md), [`video-scene-analysis`](../video-scene-analysis/SKILL.md).
- The PDF sibling with the same shape: [`pdf-remix`](../pdf-remix/SKILL.md).
