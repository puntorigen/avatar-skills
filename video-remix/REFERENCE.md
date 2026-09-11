# video-remix — reference

Full schemas (`blueprint.json`, `content.json`), the taxonomies, the beat →
storyboard mapping, the `remix.py` stage machine and troubleshooting.

---

## Pipeline data flow

```
reference.mp4
   │  analyze_video.py  (video-scene-analysis backbone + palette + watermark + ducking + Gemini vision)
   ▼
runs/<slug>/
   frames/scene_XX.jpg     rendered reference frames
   blueprint.json          the reusable MOLD (design + rhythm + per-scene + arc + beats)
   blueprint.md            human-readable mold
   content_template.json   editable skeleton (author NEW content here)
   _mech/                  raw video-scene-analysis output (cache)

content.json  (authored by you from the template)
   │  remix.py  →  avatars (avatar-invent) · locations (avatar-location) · voices (voice-clone)
   │              →  build_storyboard.py  →  <slug>.storyboard.json  (+ <slug>.narration_plan.json)
   ▼
<host-avatar>/reels/<slug>/final.mp4     (avatar-reel-composer compose --finish)
```

---

## blueprint.json (the mold)

```jsonc
{
  "source_video": "…/reference.mp4",
  "geometry": {"width":1080,"height":1920,"fps":30,"duration":24.0,
               "aspect_ratio":"9:16","orientation":"portrait","format":"reel"},   // format ∈ reel|post|landscape (snapped)
  "transcript_language": "es",
  "design_system": {
    "palette": {"ink","paper","accent","accent_dark","on_dark","muted"},          // #hex, pixel-derived
    "palette_semantics": {…},                                                      // Gemini: how each slot is used
    "color_combinations": ["combos recurrentes por escena"],                       // Gemini
    "mood": "…", "visual_style": "grano/luz/saturación/encuadre"                   // Gemini
  },
  "rhythm": {"total_scenes":N,"talking_head":n,"broll":n,
             "median_scene_dur":s,"avg_scene_dur":s,"hook_dur":s,
             "cut_rhythm":"fast|medium|slow","notes":"…"},
  "captions": {"present":bool,"position":"lower_third|middle|top|bottom",
               "casing":"subtitle|upper|sentence","reveal":"word|phrase",
               "words_per_caption":N,"color":"…","emphasis":"…","style_notes":"…",
               "style": {"font_class":"serif|sans|null","text_color_hex":"#rrggbb","y_frac":0.85,
                         "align":"center|left|right",
                         "background":{"kind":"none|pill|box","color_hex":"#rrggbb",
                                       "opacity":0.9,"radius_frac":0.3}}},  // renderer-ready (derive_caption_style)
  "environment": {"background":"el SET en una frase","background_type":"studio|room|outdoor|…",
                  "lighting":"key/fill/mood","mood":"…","wardrobe":"vestuario del presentador",
                  "set_elements":["props del set a conservar"],"key_elements":["…"],
                  "distinct_looks":["si hay >1 entorno"]},                   // aggregate_environment + vision
  "watermark": {"present":bool,"kind":"logo|handle|text|none",
                "position":"top_left|top_right|bottom_left|bottom_right|center|none",
                "appears":"throughout|after_intro|on_cta|intermittent",
                "disappears":"never|before_cta|between_cuts","description":"…",
                "candidates":[{"corner","bbox_norm":[x,y,w,h],"score"}]},           // heuristic bboxes
  "audio": {"music": {"present":bool,"coverage":0-1,"under_speech":0-1,
                      "base_volume":0.06-0.16,"structure":"flat|auto","depth":0-1,"notes":"…"},
            "music_mood":"…","voice_music_relation":"cómo conviven voz y música"},  // Gemini
  "transitions": {"style":"hard_cut|golden_flash|white_flash|dip_black|mixed|none","notes":"…",
                  "sfx": {"present":bool,"coverage":0-1,"kind":"whoosh|none","level":0-1,
                          "count":N,"notes":"…"}},                           // measure_transition_sfx (are CUTS dressed?)
  "speakers": {"count":N,"roles":["host","guest1",…],"notes":"…"},                  // Gemini
  "narrative_arc": {"type","voice","open","develop","close","beats":["…"]},          // intro→development→close
  "replication_notes": ["reglas para igualar/superar"],
  "scenes": [ /* the merged per-scene objects (mechanical + Gemini enrichment) */ ],
  "beats":  [ /* one per scene — the remix consumes these (see below) */ ]
}
```

### `beats[]` (drives the remix, like a reel_template)

| Field | Applies | Meaning |
|---|---|---|
| `index`, `role`, `type` | all | order; `hook`/`intro`/`body`/`point`/`transition`/`cta`/`close`; `talking_head`/`broll` |
| `speaker` | talking_head | which presenter (`host` default; a guest role for a second face) |
| `dur_weight` | all | scene duration / total — the proportional pacing guide for the script split |
| `zoom_from_previous` | all | `none`/`zoom_in`/`zoom_out`/`hard_cut` → composer Ken Burns motion |
| `emphasis` | all | key beat (tighter push-in) |
| `gaze` | talking_head | `to_lens`/`off_left`/`off_right`/`down`/`up`/`profile` — seeds the delivery |
| `camera_angle`, `framing`, `move` | talking_head | analysis angle + framing; `move` = mapped `avatar-camera-angles` still |
| `location_hint` | talking_head | the background elements (seeds a matching `avatar-location` look) |
| `broll_camera`, `broll_hint` | broll | suggested camera move; content hint (re-authored per topic) |
| `has_music`, `audio_profile`, `focus` | all | informational |

Camera-angle mapping (`_common.normalize_move` — analysis/beat token →
`avatar-camera-angles` move). Catalog: `eye_level`, `push_in`, `pull_out`,
`low_angle`, `high_angle`, `three_quarter`, `three_quarter_mirror`, `profile`,
`dutch_tilt`, `negative_space_left`, `negative_space_right`, `pip`. Aliases:
`zoom_in→push_in`, `zoom_out→pull_out`, `low_angle_v2→low_angle`,
`negative_space→negative_space_left`, `center/centered/medium/straight_on→eye_level`;
`none→(B-roll, no still)`; unknown/missing → `eye_level`. `normalize_moves()`
returns the de-duplicated, catalog-valid list the reel-location stage generates.

---

## content.json (what you author + what remix.py consumes)

```jsonc
{
  "meta": {"topic":"…","language":"es","format":"reel","slug":"…"},   // format overrides the mold's ratio
  "brand": {"name":"…","handle":"@…","logo_path":"/abs/logo.png","palette_override":{"accent":"#…"}},
  "avatars": [
    // ONE per mold speaker. Reuse OR invent (leave both null to be asked).
    {"role":"host",   "use":"avatares/nora", "voice_id":null},
    {"role":"guest1", "use":null,
     "invent":{"description":"…","setting":"studio","style":"photoreal","language":"es"},
     "voice_sample":null}
  ],
  "music": {"enabled":true,"mood":"inspiring","prompt":"TAILOR to topic+tone","structure":"auto","volume":0.1,"depth":0.0},
  "captions": {"reveal":"word","max_words":6,"casing":"subtitle","style_from":"",
               "emphasis":true,                      // optional; omit → inherit the mold's flat/highlight behavior
               "style_override": {}},                // optional structured overrides onto blueprint.captions.style
  // Reel-level LOOK: remix auto-builds ONE avatar-location matching blueprint.environment
  // (background + lighting + set elements) + the camera moves the beats use. auto=false → keep
  // the avatar's default look. name/brief/assets steer it; `name` is filled by the locations stage.
  "location": {"auto":true,"name":"","brief":"","assets":[]},
  "fx": {"enabled":null,"sfx":null,"sfx_volume":0.18},  // optional; null → measured from transitions.sfx (silent cuts stay silent)
  "script": "The FULL verbatim narration …",
  "beats": [
    {"index":0,"type":"talking_head","speaker":"host","text":"…","location_hint":""},
    {"index":1,"type":"broll","text":"…","broll_description":"…","broll_action":"…"},
    {"index":2,"type":"talking_head","speaker":"guest1","text":"…","location":"studio_night"}
  ]
}
```

- **Verbatim rule.** The concatenation of every beat `text` (single-spaced) must
  equal `script`. Fill per-beat `text` yourself, or leave them all empty and the
  remix splits `script` proportionally by `dur_weight` (then review).
- **Guests.** A beat whose `speaker` is a non-host avatar becomes a `guest` scene
  (its own face + voice), woven into one master narration by `assemble_narration.py`.
- **Locations.** Two layers: (1) a **reel-level look** — the remix auto-builds ONE
  `avatar-location` that matches the mold's `environment` (background + lighting +
  set elements, *not* wardrobe — the new avatar keeps its identity) and the camera
  moves the beats use, then sets it as the reel default. Steer with the top-level
  `location` block (`auto`/`name`/`brief`/`assets`); `auto:false` keeps the avatar's
  own room. (2) a **per-scene look** — set a beat `location` slug to override just
  that scene (built from `location_hint`/`location_brief`).
- **Captions.** `captions.style_override` merges onto the mold's derived
  `captions.style` (pill/box + font class + text/bg color + `y_frac` + align).
  `captions.emphasis` forces word-highlight on/off; omit to inherit the mold (a
  flat block → no per-word emphasis).
- **Transitions / SFX.** `fx` is optional — leave null to reproduce ONLY what the
  mold uses (`transitions.sfx`): silent hard cuts stay silent, whoosh-dressed cuts
  get an SFX. Override `enabled`/`sfx`/`sfx_volume` to force it.
- **Watermark.** Set `brand.logo_path` to reproduce the mold's watermark; stamp it
  onto an avatar look with `avatar-location --asset` (see that skill).

---

## Palette semantics

| Slot | Meaning |
|---|---|
| `ink` | darkest — text on light scenes, dark backgrounds |
| `paper` | lightest — light backgrounds |
| `accent` | brand color — emphasis, captions accent, CTA |
| `accent_dark` | darker accent |
| `on_dark` | text over dark footage (usually `#ffffff`) |
| `muted` | secondary / captions base |

`pick_palette()` derives these from the scene frames' dominant colors
(darkest=ink, lightest=paper, most-saturated mid-tone=accent). Override via
`brand.palette_override`.

---

## Music + ducking measurement (heuristic)

Mixed audio is not source-separated, so `measure_music()` reads each scene's
`audio` block (from video-scene-analysis) and derives:
- `present` — any scene carries a music bed / music profile.
- `coverage` — fraction of scenes with music.
- `under_speech` — fraction where music co-occurs with speech (`speech_with_music`/`speech_mixed`).
- `base_volume` — a conservative bed level (0.06–0.16) scaled from the median
  non-speech RMS of the music scenes → the finish pass `music_volume`.
- `structure` — `auto` (there is a voice to duck under → duck-under-hook / lift /
  resolve envelope) or `flat` (constant low bed). Maps to `finish.music_structure`.
- `depth` — a duck-depth proxy (0–1) from the speech-vs-bed RMS ratio (voice much
  louder than the bed → deeper duck; comparable → little/none). → `finish.music_depth`.

If no bed is detected, the remix sets `music.enabled=false` (`--no-music`).

---

## Caption STYLE derivation (`derive_caption_style` / `caption_emphasis_flag`)

The mold's caption prose/enums are mapped to a **renderer-ready** structure so the
finish pass reproduces the actual look, not just reveal/casing:
- `font_class` — `serif`/`sans` inferred from `style_notes`/`color` (else `null` →
  composer keeps its default serif).
- `background` — `{kind: none|pill|box, color_hex, opacity, radius_frac}` inferred
  from box/pill/bar wording (`caja`/`pastilla`/`barra`/`box`/`pill`/…).
- `text_color_hex` — the ink color parsed from `color` (e.g. `negro sobre pastilla
  gris claro` → ink `#141416`, bg `#e4e6e9`); defaults to dark-on-box / white-on-none.
- `y_frac`/`align` — from `position` (`lower_third`→0.85, `top`→0.14, `middle`→0.5).
- `caption_emphasis_flag()` returns `False` when the mold reads as a flat/uniform
  block (`sin énfasis`, `no highlight`) → the finish pass disables per-word highlight.

Structured vision fields (`captions.font_class`/`text_color_hex`/`background`/…) win;
the deterministic derivation fills every gap, so `--no-vision` still yields a style.

---

## Environment aggregation (`aggregate_environment`)

Builds ONE mold-level look from the per-scene backgrounds + elements + design
system (deterministic, so it works without vision):
- `background`/`background_type` — the dominant set described / typed across scenes.
- `lighting`/`mood` — from `design_system.visual_style`/`mood`.
- `wardrobe` vs `set_elements` — elements are split (a small wardrobe lexicon routes
  clothing to `wardrobe`, which is intentionally **not** copied into the location so
  the new avatar keeps its identity); burned-in caption/watermark graphics are filtered.
- `distinct_looks` — only scenes whose background *type* differs from the dominant one
  (near-dup phrases are collapsed by keyword-signature Jaccard), so a single-look mold
  doesn't spawn spurious per-scene locations.

`remix.py`'s locations stage feeds this to `avatar-location` (background + set +
lighting + the beats' camera moves) to build the reel's default look.

---

## Transition-SFX measurement (`measure_transition_sfx`)

Inspects each scene's mechanical `audio.sfx_events` and counts scene boundaries whose
incoming/outgoing scene carries an SFX within ~0.6 s of the cut. Reports
`present`/`coverage`/`kind`/`level`/`count` so the remix dresses cuts with a whoosh
**only when the reference actually does** — silent hard cuts stay silent
(`finish.fx.sfx=false`). Overridable via `content.fx`.

---

## Watermark / logo detection (heuristic)

`detect_watermark()` stacks the scene frames, grades a grid by
`edge_density / (1 + temporal_std)` in the border band, and reports candidate
corner boxes: a watermark stays put (low temporal variance) while having real
structure even across hard cuts. Gemini confirms/describes it in the synthesis
pass (`watermark.kind/position/appears/disappears/description`). Requires
numpy + Pillow; degrades to `[]`.

---

## remix.py stage machine

Idempotent; re-run to resume. Exit codes: **2** = an agent/user checkpoint is
blocking (act, then re-run), **0** = progressed (stops after the storyboard for
review unless `--compose`), other = error.

| Stage | Done when | Action |
|---|---|---|
| `avatars` | every `avatars[].use` resolves to a dir | reuse the path, or invent via `avatar-invent` (its own review = exit 2). If none specified → STOP: **ASK THE USER** invent-vs-reuse for N = speaker count |
| `voices` | each avatar has a `voice_id` | read `<avatar>/voices/index.json`; else clone from `avatars[].voice_sample` |
| `locations` | reel look + each beat `location` slug exist under `<avatar>/locations/` | build per-beat looks, then auto-derive ONE reel-level look from `blueprint.environment` (background + lighting + set elements + the beats' camera moves) via `avatar-location`; records `content.location.name` (its review = exit 2). `location.auto:false` or an empty environment → skipped |
| `storyboard` | `<slug>.storyboard.json` present | `build_storyboard.py` (+ `<slug>.narration_plan.json` for guests) |
| `compose` | `final.mp4` in `<host>/reels/<slug>/` | `compose_reel.py --finish` (guests: `assemble_narration.py` first, patch `broll_clip`, compose over the pre-built narration) |

Flags: `--compose`, `--finish`, `--dry-run`, `--format`, `--resolution`, `--fps`,
`--no-review`, `--regen-storyboard`, `--allow-todo`, `--status`, `--base-dir`,
`--content`, `--blueprint`.

---

## Storyboard contract (`build_storyboard.py`)

Output matches [avatar-reel-composer's storyboard.example.json](../avatar-reel-composer/examples/storyboard.example.json):
- `scenes[]` preserve the mold's beat count + talking-head/B-roll/guest sequence.
- Host talking-head scenes get `image` (explicit default look), `angle`-only (when a
  reel-level `location` is active → composer resolves the still inside that look), or
  `angle`+`location` (per-scene override); plus `zoom_from_previous`, `emphasis`.
- A reel-level `location` (from the locations stage) is emitted at the storyboard root.
- Guest scenes are `type:"guest"` with `broll_clip:null` + `_guest_*` hints;
  `remix.py` fills `broll_clip` from `assemble_narration.out.json` before composing.
- B-roll scenes get `broll_camera` and the authored `broll_description`/`broll_action`
  (or a `TODO` seeded from the beat hint).
- `finish` wires captions (`caption_reveal`/`casing`/`max_words`/`emphasis`/`style_from`
  and `caption_style` = the mold's pill/box + font class + colors + `y_frac`/align),
  music (`music_prompt`/`music_mood`/`music_volume`/`music_structure`/`music_depth`, or
  `music:false`) and a measured `fx` (`enabled`/`sfx`/`sfx_volume`/`transition_style` —
  silent hard cuts stay silent unless the mold or `content.fx` says otherwise).

**Verbatim guarantee:** the per-beat texts (agent-authored or proportional split)
are checked to concatenate to `script` exactly — the composer's hard rule.

---

## Troubleshooting

- **Vision analysis is empty / generic** — ensure the Gemini key resolves
  (`setup_key.py --show`; configure `asset-generator`). `--no-vision` still emits
  geometry + palette + rhythm + watermark/ducking (no semantics).
- **video-scene-analysis fails** — install its deps + models:
  `pip3 install -r video-scene-analysis/scripts/requirements.txt` and
  `bash video-scene-analysis/scripts/setup_models.sh`.
- **"CHOOSE AVATARS" checkpoint** — the mold needs N presenters; set each
  `avatars[].use` (reuse) or `invent` (new), then re-run. Ask the user first.
- **Angle stills missing warning** — expected before the avatars/locations stages
  generate them; `remix.py` handles it. For an existing avatar lacking a move,
  generate it with `avatar-camera-angles` (or `reel-restyle --format`).
- **Wrong ratio** — set `meta.format` or `remix.py --format {reel|post|landscape}`;
  it selects the `_916` vs `_169` angle crop automatically.
- **Music sings the prompt / too loud** — `finish` strips sung directions and keeps
  a low bed; tune `music.volume`/`music.structure`, or `music.enabled=false`.
- **Don't commit** `runs/` (research + media) or `avatares/` (generated avatars) —
  both are gitignored.
