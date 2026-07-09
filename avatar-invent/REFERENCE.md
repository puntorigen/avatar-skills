# avatar-invent — reference

Internals, schemas and design notes for the `avatar-invent` skill.

## Why this skill exists

Two ways to get an avatar into this repo:

| | source | how |
|---|---|---|
| `avatar-reel-composer/create_avatar.py` | a **real** person's Instagram reels | download → analyze → frames → **clone** voice → profiles |
| **`avatar-invent`** | a **text description** (fictional) | author → **generate** still → angles → **design** voice → record |

Both end at the *same folder contract*, so everything downstream
(`avatar-camera-angles`, `avatar-talking-video`, `avatar-reel-composer`,
`reel-restyle`) works identically on an invented avatar.

Key inversion vs. a real avatar: a cloned avatar's `scene.json` is **observed**
from a real frame; here `scene.json` is **prescribed first** and the hero still
is generated *from* it. The same `scene.json` then drives every camera angle, so
it is the single source of truth that keeps identity + room consistent.

## Stage machine (`invent_avatar.py`)

Idempotent; each stage skips when its outputs already exist. Re-run to resume;
`--force-stage <name>` to redo one.

| stage | done when | does |
|---|---|---|
| `author` | `scene.json` + `talking_profile.json` + `voice_brief.json` valid | drafts the three files from the brief + topic defaults, then **stops once** for agent review (unless `--no-review`) |
| `hero` | a `refs/<slug>_hero*.png` exists | `generate_hero.py` → master (2:3/3:2) + cropped hero (9:16/16:9) |
| `angles` | every move has `angles/<slug>_<move>_916.png` (auto-skipped for 16:9) | `avatar-camera-angles/generate_angles.py` with the hero master as the identity ref |
| `voice` | `voices/index.json` has a `voice_id` | `design_voice.py` (ElevenLabs design → MiniMax clone) |
| `record` | `avatar.json` + `frames/manifest.json` exist | copies hero → `frames/frame_0001.png`, writes both records |

The `brief.json` is the merge of `BRIEF_DEFAULTS` + any existing `brief.json` +
CLI overrides, re-saved every run. `--status` writes the report and exits.

## Prompt assembly (`generate_hero.py` + `_common.build_hero_prompt`)

```
<style preamble>                       # photoreal | soft3d | anime | stylized_real | <custom text>

SUBJECT:   scene.json.subject
WARDROBE:  scene.json.wardrobe
SETTING:   scene.json.scene
LIGHTING:  scene.json.light  (falls back to presets.default_light)

FRAMING:   presets.framing.default + vertical/horizontal note
CAMERA:    presets.camera
EXPRESSION:presets.delivery
CONSTRAINTS: presets.constraints  + "Avoid: <style.negative_extra>."
```

- **gpt-image-2** (default): renders the master at the nearest native ratio
  (`2:3` vertical, `3:2` horizontal), then `_common.crop_to_ratio` center-crops
  to exact `9:16`/`16:9` (native resolution, no upscaling) — the same proven
  path as `avatar-camera-angles`. Identity fidelity is why it's the default: the
  hero master is reused as the `--ref` for every angle.
- **gemini** (`--generator gemini`): `asset-generator` renders native `9:16`/
  `16:9` up to 4K with `--raw-prompt` (our full prompt, no style wrapping); no
  crop. Angles still go through gpt-image-2 using the hero as the reference.

`generate_hero.py --print-prompt` prints the assembled prompt without spending.

### Reference images (`--ref`, `--anchor-identity`) — used by `avatar-location`

`generate_hero.py` accepts `--ref PATH` (repeatable), forwarded to gpt-image-2 as
`input_images`. With no refs the behavior is exactly as above (text-only — invented
avatars are unchanged). Refs serve two purposes:

- **Identity anchoring.** Pass the avatar's `refs/<slug>_hero_master.png` as a `--ref`
  plus `--anchor-identity` to keep the **exact same person** while only the wardrobe /
  setting / light change. `--anchor-identity` prepends an `IDENTITY (CRITICAL): keep the
  same person…` line to the prompt. This is how the **`avatar-location`** skill makes
  alternate looks of one avatar.
- **Asset refs.** A logo/prop can be incorporated: list it in the scene profile's
  optional `assets: [{file, placement}]` array (and attach the file as another `--ref`).
  `_common.build_hero_prompt` appends an `INCORPORATE THE ATTACHED REFERENCE ASSET(S)…`
  section with each placement. (`avatar-camera-angles/_prompt.py` does the same for the
  angle prompts, so the asset stays crisp across angle re-renders.)

Keep refs minimal (identity + 1–2 assets) to stay within gpt-image-2's reference limit;
review the hero before generating angles if identity/asset fidelity matters.

## Voice: ElevenLabs design → MiniMax clone (`design_voice.py`)

1. `POST https://api.elevenlabs.io/v1/text-to-voice/design`
   `{ model_id: "eleven_multilingual_ttv_v2", voice_description, text: <long sample text> }`
   → up to 3 previews (`generated_voice_id` + base64 mp3). Auth: `xi-api-key`.
   - `voice_description` is clamped to 20–1000 chars; preview `text` to 100–1000
     (shorter falls back to `auto_generate_text: true`).
2. All previews are saved to `voices/design_previews/`; preview `--preview-index`
   (default 0) becomes `voices/<name>_design_sample.mp3`. Because the sample text
   is long (~600 chars ≈ ~40s), the clip clears MiniMax's 10s minimum.
3. The sample is handed to `voice-clone/clone_voice.py` → `voices/<name>.json` +
   `voices/index.json` with a **MiniMax `voice_id`**, identical to every other
   avatar. Provenance is kept in `voices/<name>_design.json`.

Idempotent: skips entirely if a MiniMax `voice_id` is already registered (unless
`--force`); reuses an existing design sample if present. `--no-clone` stops after
designing the sample (useful to audition previews before spending the clone).

> Design rationale: ElevenLabs Voice Design is the *casting* (invent a voice from
> a description — impossible to clone something that was never recorded); MiniMax
> remains the *engine* the reel pipeline already speaks through. This keeps
> `voices/` and `narrate.py` unchanged. (Alternative, not used: store the
> ElevenLabs `voice_id` and add an ElevenLabs TTS backend to the composer.)

## `prompts/presets.json` schema

| key | purpose |
|---|---|
| `styles.<name>.preamble` / `.negative_extra` | render look + things to avoid; `photoreal` is the default. Unknown `--style` values are treated as a literal custom preamble. |
| `framing.default` / `vertical_note` / `horizontal_note` | the seated half-body, eyes-to-lens, caption-safe framing |
| `camera`, `delivery`, `constraints` | phone-camera look, mid-sentence expression, single-person/no-text rules |
| `default_light` | the soft key-from-left + soft backlight recipe (seeded into draft `scene.json.light`) |
| `default_moves` | camera moves the `angles` stage generates |
| `settings.<keyword>` | `--setting` → default `scene` + `wardrobe` |
| `default_setting` | fallback when `--setting` is unknown/omitted |
| `delivery_profile` | seed for `talking_profile.json` (video/negative/mannerisms) |
| `voice.default_suffix`, `voice.model_id`, `voice.preview_text[lang]`, `voice.sample_text[lang]` | voice-design defaults |

## Output records

`avatar.json` (top-level, mirrors `lolo/avatar.json` with `invented: true`):

```json
{
  "avatar": "nora", "name": "nora", "invented": true,
  "ready": true, "brief": { ... }, "style": "photoreal",
  "setting": "clinic", "aspect_ratio": "9:16", "generator": "gpt-image-2",
  "language": "es",
  "stages": { "author": "complete", "hero": "complete", "angles": "complete",
              "voice": "complete", "record": "complete" },
  "artifacts": {
    "hero": "refs/nora_hero.png", "hero_master": "refs/nora_hero_master.png",
    "scene": "scene.json", "talking_profile": "talking_profile.json",
    "voice_brief": "voice_brief.json",
    "angles": ["angles/nora_push_in_916.png", ...],
    "voices": ["R8_..."], "voice_design": "voices/nora_design.json",
    "frames_manifest": "frames/manifest.json"
  }
}
```

## Key discovery (`_common.py`)

`env var → avatar-invent/config.json → sibling configs`:
ElevenLabs (`ELEVENLABS_API_KEY` → `audio-theater`), Replicate
(`REPLICATE_API_TOKEN` → `gpt-image-2`/`voice-clone`/…), Gemini
(`GEMINI_API_KEY` → `asset-generator`). Override per skill with `setup_key.py`.

## Gotchas

- **gpt-image-2 has no resolution knob** — `--quality high` is the native max; the
  only post-step is the lossless center-crop. Use `--quality low` to scout, `high`
  for finals.
- **16:9** disables the `angles` stage by default (the angle catalog is tuned for
  vertical 9:16 crops). The hero still is the deliverable; pass `--angles` to
  force it anyway.
- **MiniMax clone needs a tunnel** (`cloudflared`/`ngrok`) to expose the sample,
  exactly like `voice-clone`; without one it falls back to a temporary public host.
- A too-short voice preview (<10s) is warned about — lengthen `voice_brief.sample_text`
  or pick another `--preview-index`.
