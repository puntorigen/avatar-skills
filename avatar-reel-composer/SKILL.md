---
name: avatar-reel-composer
description: Turn a script + an existing avatar into a finished reel — 9:16 vertical (TikTok/Reels) or 16:9 landscape (YouTube), set via the storyboard `format`. Narrates the script once in the avatar's cloned voice, cuts it per scene by word-level alignment, generates lip-synced talking-head scenes (avatar-talking-video) and silent B-roll scenes (broll-generator) as voice-over, applies Ken Burns / zoom motion, and assembles with hard cuts under one master narration. Can weave in a GUEST/cameo scene (a clip of a DIFFERENT avatar speaking in its own voice) that keeps its own audio. Supports per-reel and per-scene LOCATIONS (alternate avatar looks built by avatar-location). Can also onboard a brand-new avatar from a public Instagram profile via create_avatar.py (download, analysis, frames, voice cloning, style profiling). Use when the user wants to produce a full reel/short from a script for an avatar that already exists (videos/, voices/, angles/ and/or talking_profile.json), or to onboard a new avatar from an Instagram URL, in the style of that avatar's analyzed reels.
---

# Avatar Reel Composer

Orchestrates the sibling skills into one finished reel from a **script** + an
**existing avatar**, replicating the structure of the avatar's analyzed reels.
An optional **finishing pass** (`finish_reel.py`) adds burned-in word-timed
subtitles + a music bed under the voice — flat by default, or a **structured
volume envelope** (entrance / lift / settle / duck / resolve, anchored to scene
boundaries) that makes the soundtrack do editing work. SFX stingers and dissolves
are still deferred (see *Next phases*).

## When to use
- The user has an avatar folder (e.g. `lolo/`) that already contains `videos/`,
  a trained voice in `voices/`, camera-angle images in `angles/`, and ideally a
  `talking_profile.json` (all produced by the upstream skills below).
- They give you a **script** (what the avatar should say) and want a reel — 9:16
  vertical (TikTok/Reels) or 16:9 landscape (YouTube), set via the storyboard's
  `format` — where the avatar's voice narrates continuously while the video cuts
  between talking-head shots and complementary B-roll — exactly like the
  original reels analyzed by `video-scene-analysis`. For 16:9, use the avatar's
  `_169.png` angle crops (see `avatar-camera-angles --crop169`).

If the avatar does NOT exist yet, create it first from its public Instagram
profile with `create_avatar.py` (see *Stage 0: create an avatar from a public
Instagram URL*).

> **Output location.** `create_avatar.py` creates a bare avatar name under
> `./avatares/<name>/` (so avatars never clutter the project root); pass an
> explicit path to override, or set `AVATARES_ROOT`. Storyboards reference the
> avatar via its `avatar_dir` path (e.g. `avatares/lolo`), resolved against
> `--base-dir`.

## Prerequisites (existing avatar)
| Asset | Produced by | Used for |
|---|---|---|
| `videos/`, `<name>.analysis.json` | `video-scene-analysis` | structural template (pacing, camera, zoom, emotion) |
| `voices/*.json` (trained voice) | `voice-clone` | the cloned narration voice |
| `angles/**/<angle>_916.png` (or `_169.png` for 16:9) | `avatar-camera-angles` | talking-head scene framings |
| `talking_profile.json` | `video-scene-analysis` | reusable lip-sync prompt/personality |

A shared `replicate_api_token` (inherited from the sibling skills) is required.
Install deps once: `pip3 install -r requirements.txt`.

## Pipeline
```
script ─► narrate.py ─► narration.mp3 (cloned voice, ONE TTS call per sentence,
                     │                  joined with a small silence gap)
                     └► faster-whisper ─► narration.align.json (word timings)
storyboard.json (you write it, guided by <avatar>.analysis.json)
                     │
                     ▼
            compose_reel.py
   1. align scene.text → [start,end] in the narration (snap cuts to silence)
   2. slice narration.mp3 → scenes/chunk_<id>.mp3
   3. talking_head → avatar-talking-video --audio chunk   (lip-synced)
      broll        → broll-generator --duration ceil(chunk) (silent)
   4. normalize each clip: TRIM to exact chunk dur (never freeze-pad) + scale/crop to the format size (1080x1920 reel / 1920x1080 landscape) + Ken Burns/zoom
   5. concat with HARD CUTS (Σ durations == narration length)
   6. mux narration.mp3 back on as the single master track → final.mp4

(optional finishing pass) finish_reel.py
   7. captions: group words → self-contained PHRASE UNITS that REPLACE each other
      (no stale already-spoken text stacked under a new line). A unit shows a
      regular SETUP line + a BOLD-ITALIC PAYOFF line (the breath-ending / key
      words); emphasis falls only on a breath group's completion, mid-breath
      continuation units stay plain. Serif, white + soft shadow, lowercase
      ("subtitle") casing with intentional ALL-CAPS preserved and no trailing dot —
      matching the analyzed reels. Rendered as transparent PNGs (Pillow), burned
      in via video-compose's overlay_titles
   8. music: bg-music-hq instrumental bed under the voice. Default = a FIXED low
      volume (no ducking). Optional STRUCTURED envelope (--music-structure auto,
      a storyboard finish.music_plan, or --music-from-cutsheet) makes the bed do
      editing work: a hard-cut entrance, a lift/settle at an emotional shift, a
      duck under a key line, a resolve into the close — anchored to scene
      boundaries. TAILOR the prompt to the reel's tone
   9. re-mux → final.mp4 (video copy + voice + music, flat or enveloped)

(optional polish pass) polish_reel.py — applied OVER the finished video
  10. keep the pre-fx version as final-without-sfx.mp4
  11. golden-flash transitions at B-roll cuts (the originals' warm amber wash,
      rising+decaying over ~0.36s on the incoming scene — duration-preserving,
      so nothing desyncs) + short-soft SFX (airy whoosh leading each B-roll cut
      by ~0.35s, soft low boom under emphasis scenes), sparse (~1 per 15s) and
      very quiet (~18% of voice) like the analyzed reels → final.mp4
```
**Sync key:** every chunk is cut from the *same* narration and the scenes are
assembled with hard cuts (no xfade that would shorten the timeline), so re-laying
the full narration on top lands perfectly in sync.

Output per reel: `<avatar>/reels/<NNN>_<slug>/` containing `storyboard.json`,
`narration.mp3`, `narration.align.json`, `scenes/` (chunks + normalized clips),
`video_track.mp4`, `final.mp4`, `reel_manifest.json`. After the finishing pass,
also `captions/` (caption PNGs), `video_sub.mp4` (captioned, silent) and
`music.mp3` (the bed).

**Why PNG captions, not ASS/SRT?** This machine's ffmpeg is built without libass
(no `subtitles`/`ass` filter), so we render captions ourselves with Pillow and
composite them with the `overlay` filter — which also gives full styling control.

## How to run

1. **Write a `storyboard.json`** (see `examples/storyboard.example.json` and the
   schema below). Derive it from the avatar's `*.analysis.json` so the new reel
   *feels* like the originals.
2. **Compose:**
   ```bash
   # run from the folder your storyboard's relative paths are based on (repo root)
   python3 ~/.cursor/skills/avatar-reel-composer/scripts/compose_reel.py storyboard.json --language es
   ```
   Useful flags:
   - `--dry-run` — narrate + align + compute boundaries + slice the audio, then
     stop. **Always do this first** to verify scene timing cheaply (one TTS call,
     no video generation).
   - `--regen` — regenerate scene clips even if cached ones exist.
   - `--force-narrate` — rebuild `narration.mp3` (reuses unchanged per-sentence
     takes from `narration_parts/`; change a `voice` param to actually re-TTS).
   - `--reroll N [M …]` — force a fresh take of the given 1-based sentence
     index(es) when one segment is mispronounced; the rest are reused, and only
     the talking-heads whose audio changed are regenerated.
   - `--out-dir DIR` — write the reel to a specific folder (otherwise
     `<avatar>/reels/<NNN>_<slug>`).
   - `--base-dir DIR` — base for resolving relative paths (default: CWD).
   - `--whisper-model {tiny,base,small,medium}` — alignment model (default `small`).
3. **Finish (optional but recommended):** add the serif phrase-unit captions + a
   fixed-volume music bed. Either let `compose_reel.py` do it in one shot with
   `--finish` (or a storyboard `finish` block), or run it standalone on any reel:
   ```bash
   python3 ~/.cursor/skills/avatar-reel-composer/scripts/finish_reel.py <reel_dir> \
       --style-from <avatar>/subtitle_style.json \
       --music-prompt "…tailored to the reel's emotional tone…"
   ```
   Useful flags: `--no-music`, `--no-subtitles`, `--music-mood <preset>`
   (default `ambient`), `--music-prompt "…"` (**tailor to the tone**),
   `--music-volume 0.12` (FIXED bed level), `--music-vocals {wordless,none}`
   (default `wordless` soft oohs/aahs; `none` = instrumental), `--regen-music`, `--max-words 6`
   (max words per phrase unit), `--no-emphasis` (disable the bold-italic payoff),
   `--casing {subtitle,natural,lower,upper}`, `--fontsize`, `--y-frac`, `--regular-font`,
   `--emph-font`, `--style-from <profile.json>` (seed caption position/size/casing
   from the analyzed reels — see *Matching the analyzed caption style*).
   It's **idempotent** (reuses `music.mp3` unless `--regen-music`) and re-runnable,
   so you can iterate on caption style / music without regenerating any video.

4. **Profile the originals' transitions (once per avatar):** measure how the
   avatar's ORIGINAL reels visually dress their cuts — flash or not, where
   (B-roll entry/exit/talking-head cuts), how long, how strong, what hue
   (golden vs white vs dip-to-black):
   ```bash
   python3 ~/.cursor/skills/avatar-reel-composer/scripts/profile_transitions.py \
       <video1>.analysis.json <video2>.analysis.json …   # -> <avatar>/transition_style.json
   ```
   It samples low-res frames around every scene boundary of each
   `*.analysis.json` (video-scene-analysis output), measures brightness/warmth
   deviation vs the surrounding baseline, and aggregates **per boundary type**
   (e.g. the reference avatar flashes 100% of B-roll ENTRIES, 0% of exits) into
   `transition_style.json`: `style`, `flash_at`, `flash_dur`, `flash_gain`.
5. **Polish (optional):** scene-cut transition effects + short-soft SFX,
   applied OVER `final.mp4` (the pre-fx version is kept as
   `final-without-sfx.mp4`). Either via the storyboard `finish.fx` block (runs
   automatically after the finish pass) or standalone:
   ```bash
   python3 ~/.cursor/skills/avatar-reel-composer/scripts/polish_reel.py <reel_dir> \
       --guide <avatar>/videos/<original>_voice/voice.json
   ```
   The transition look comes from the avatar's own measured
   `transition_style.json` (auto-discovered at `<avatar>/transition_style.json`,
   or `--style-from path`); explicit flags win, built-in defaults (= the
   reference avatar's measurements) are the last resort. Useful flags:
   `--transition-style {golden_flash,white_flash,dip_black,punch,none}`,
   `--no-transitions`, `--no-sfx`, `--sfx-volume 0.18`, `--flash-dur`,
   `--flash-gain`, `--density N` (seconds per SFX event), `--guide voice.json`
   (a voice-isolate output of an ORIGINAL reel: its measured `sfx_intervals`
   set the density), `--regen-sfx`. It's idempotent: re-running re-polishes
   from the clean copy (effects never stack), and a fresh finish pass resets
   the clean source. SFX assets are cached avatar-wide in
   `<avatar>/reels/_sfx_cache/`.

`narrate.py` can also be run standalone (it's what stage 1 calls). Likewise
`finish_reel.py` and `polish_reel.py` run standalone on any reel folder
produced by `compose_reel.py`.

## Storyboard schema (you write this)
Top-level:
| Field | Meaning |
|---|---|
| `avatar_dir` | path to the avatar folder (abs or relative to `--base-dir`) |
| `slug` | short id for filenames / the reel folder |
| `reference_analysis` | the `*.analysis.json` you based pacing on (recorded in manifest) |
| `format` | `reel` (1080x1920), `post` (1080x1080) or `landscape` (1920x1080) |
| `resolution` | `720p` or `1080p` — generation resolution for both models |
| `fps` | final reel fps (default 30) |
| `voice` | `{name, voice_id, emotion, speed, language_boost, volume, pitch, sentence_gap, sentences_per_call}` (all optional; voice auto-resolves). `language_boost` defaults to **`None`** (no boost — keeps the cloned voice's own accent; boosting e.g. `Spanish` can drag a neutral/Chilean clone toward another regional accent like Argentinian voseo). `sentence_gap` = silence in seconds joining sentence takes (default `0.12`); `sentences_per_call` = sentences per TTS call (default `1` = one per sentence) |
| `script` | the FULL verbatim narration (optional — defaults to the scenes' text joined). MAY contain MiniMax expressive **interjections** — `(sighs)`, `(exhales)`, `(laughs softly)`, … — and manual pauses `<#0.5#>`; they're spoken by the TTS and ignored by alignment/captions (whisper doesn't transcribe them). `--list-interjections` in voice-clone lists the recognized set |
| `location` | OPTIONAL reel-default **look** for the avatar (a "location" = wardrobe + environment + light, created by the `avatar-location` skill). Talking-head angles then resolve from `<avatar>/locations/<location>/angles/` instead of the top-level `angles/`. Omit or set `"default"` for the avatar's base look (today's behavior). Per-scene `location` overrides this. |
| `scenes[]` | ordered scenes (below) |
| `finish` | optional finishing-pass config (see below); runs automatically when present |

Optional `finish` block (also overridable by `compose_reel.py --finish` flags):
| Field | Meaning |
|---|---|
| `enabled` | `true` to auto-run the finishing pass after assembly |
| `subtitles` | burn in word-timed captions (default `true`) |
| `music` | add a fixed-volume music bed (default `true`) |
| `music_mood` | `bg-music-hq` mood preset (default `ambient`; e.g. `cinematic`, `inspiring`, `dramatic`, `lofi`) |
| `music_prompt` | **tailor this** to the reel's emotional tone (read from the script + B-roll); light, instrumental, no drums |
| `music_volume` | BASE bed level under the voice, 0–1 (default `0.12`). With `music_structure`/`music_plan` this is the level the envelope moves around (still no sidechain ducking) |
| `music_vocals` | `wordless` (default — soft, non-distracting oohs/aahs) or `none` (instrumental). Stage directions are NEVER sung either way |
| `music_structure` | `flat` (default — constant bed) or `auto` (a tasteful volume envelope from the scene structure: duck under the hook, lift after it, resolve on the close) |
| `music_plan` | explicit soundtrack moves — `{"moves":[{"type":…,"at":…,"amount":…}]}` — the precise envelope (overrides `music_structure`). See *Structured music* below |
| `music_from_cutsheet` | path to a `rule-of-six-edit` `*.cutsheet.json`; its per-cut `sound` notes are mapped (best-effort) to music moves at their scene boundaries |
| `max_words` | max words per caption phrase unit (default `6`) |
| `emphasis` | highlight each breath group's payoff in bold-italic (default `true`) |
| `casing` | `subtitle` (default — lowercase like the analyzed reels: no sentence-initial capitals and no trailing dot, but intentional ALL-CAPS words like `REPE`/`NO` stay shouted and accents are kept), `natural` (preserve ASR/script casing), `lower`, or `upper` |
| `caption_reveal` | `word` (default — **karaoke reveal**: each word appears as it's spoken, building the phrase in place; already-spoken words stay lit, the phrase clears on the next unit) or `phrase` (the whole phrase unit pops in at once). See the [`caption-word-reveal`](../caption-word-reveal/SKILL.md) skill |
| `style_from` | path to a `subtitle_style.json` (from avatar-frames) to seed caption position/size/casing |
| `regular_font` / `emph_font` | override the serif / bold-italic caption fonts (TTF) |
| `fontsize` / `y_frac` | caption size (px) / vertical center as fraction of height (defaults: profile, else ~7.2% of the SHORTER side / `0.66` for 9:16, `0.85` lower-third for 16:9) |
| `fx` | OPTIONAL polish-pass block (see below) — runs after the finish pass, keeps `final-without-sfx.mp4` |

`finish.fx` block (stage 4, `polish_reel.py`):
| Field | Meaning |
|---|---|
| `enabled` | `true` to auto-run the polish pass after finishing |
| `transition_style` | OMIT to use the avatar's measured `transition_style.json` (recommended). Override: `golden_flash` (warm amber wash over the incoming scene), `white_flash`, `dip_black`, `punch` (small zoom pulse), `none` (bare hard cuts) |
| `style_from` | explicit path to a `transition_style.json` (default: auto-discover `<avatar>/transition_style.json` written by `profile_transitions.py`) |
| `sfx` | overlay short-soft SFX (default `true`): airy whoosh leading each B-roll cut by ~0.35s + soft low boom under `emphasis: true` scene starts |
| `sfx_volume` | SFX level under the voice (default `0.18` ≈ the originals' non-speech/speech RMS ratio) |
| `flash_dur` / `flash_gain` | flash length (s) / strength — OMIT to use the measured profile (fallback `0.36` / `1.0`) |
| `density` | seconds per SFX event (default: from `guide`, else `15` as measured) |
| `guide` | path to a voice-isolate `voice.json` of an ORIGINAL reel — its measured `sfx_intervals` set the density |
| `regen_sfx` | regenerate the cached SFX assets (`<avatar>/reels/_sfx_cache/`) |

**Hard rule:** the concatenation of every `scene.text` (joined with single
spaces) must equal `script` verbatim. The script is narrated as one take, then
cut per scene; if the texts don't tile the script the alignment falls back to a
rough proportional split.

Each scene:
| Field | Applies to | Meaning |
|---|---|---|
| `id` | all | unique id (e.g. `s1`); used for filenames |
| `type` | all | `talking_head`, `broll` or `guest` |
| `text` | all | the contiguous slice of the script spoken during this scene |
| `motion` | all | Ken Burns/zoom: `zoom_center`, `push_in`, `push_out`, `drift_{left,right,up,down}`, `none` |
| `emphasis` | all | `true` bumps motion intensity (subtle→medium); a marked zoom-in for key lines |
| `image` | talking_head | path to a `*_916.png` (9:16) or `*_169.png` (16:9) camera-angle image (preferred); an explicit path always wins over `angle`/`location` |
| `angle` | talking_head | alternative to `image`: a move name (e.g. `push_in`) globbed under the active location's `angles/`, preferring the crop that matches the reel `format` (`*_169.png` for landscape, else `*_916.png`, then any `*.png`). Falls back to the default look (with a warning) if the location lacks that angle |
| `location` | talking_head | OPTIONAL per-scene **look** override (a name from the `avatar-location` skill); overrides the reel-level `location`. `"default"`/unset = the avatar's base look |
| `video_prompt` / `negative_prompt` | talking_head | optional p-video-avatar overrides; omit to use `talking_profile.json` |
| `broll_description` | broll | the scene to generate (people/objects/environment, NO main presenter) |
| `broll_camera` | broll | `handheld`, `push_in`, `pull_out`, `pan_left`, `pan_right`, `orbit`, `static` |
| `broll_action` | broll | explicit continuous human performance (gestures, talking/not), avoids the "mannequin" look |
| `broll_source` | broll | `generate` (default — synthesize with broll-generator) or `existing` (use a real found-footage clip instead, e.g. from the `broll-finder` skill) |
| `broll_clip` | broll | path to a pre-made B-roll clip (abs / relative to `--base-dir` / the avatar folder); required when `broll_source: existing`. Silent clips shorter than the slot are looped to cover it, then trimmed |
| `broll_clip` | guest | path to the pre-made guest clip (with its OWN voice) built by `assemble_narration.py`; the scene is used as-is and the cut is pinned to its exact end (no pad, no loop) |

## Guest / cameo scenes — a DIFFERENT avatar inside the reel
A `guest` scene drops a clip of **another avatar speaking in their own voice**
into the host avatar's reel — e.g. a photorealistic human presenter opens the
hook ("…I'm not real") before a surprise cut to the host. It is the right tool
whenever a beat needs a different face/voice than the host. (It is **not** B-roll:
B-roll is silent and gets the host's voice-over laid on top; a guest clip *keeps
its own audio* and must NOT be narrated over.)

Because `compose_reel.py` muxes **one** master narration over the whole timeline,
the guest's voice has to be woven INTO that master track. `assemble_narration.py`
does this: it stitches a single `narration.mp3` + `narration.align.json` from an
ordered list of segments (guest clips + the host narration), so everything
downstream (boundaries, captions, music, flash) just works.

```bash
# 1) Build the master narration from heterogeneous segments (gap 0 → host picks up
#    the instant the guest stops). See the plan schema in assemble_narration.py.
python3 .cursor/skills/avatar-reel-composer/scripts/assemble_narration.py plan.json --base-dir .
#    → writes narration.mp3 + narration.align.json into out_dir, prints guest scene stubs.
# 2) Put the printed stub(s) into storyboard.json as `type: "guest"` scenes, set the
#    storyboard `script` = the full combined text, then compose normally (it REUSES
#    the pre-built narration when you point --out-dir at that folder):
python3 .cursor/skills/avatar-reel-composer/scripts/compose_reel.py storyboard.json --base-dir . --out-dir <reel_dir> --finish
```
Segment kinds in the plan: `guest` (generates a lip-synced clip of `avatar_dir`
via avatar-talking-video and uses its audio — matched to the clip's exact video
length with inaudible trailing silence), `audio` (an existing file, e.g. a host
`audio-theater` `dialogue.wav`), `tts` (host MiniMax voice via `narrate.py`).

**No freeze pad — the next clip starts immediately.** A guest scene is never
looped or frozen: the composer pins its boundary to the clip's real duration, so
the host cuts in the instant the guest stops talking. The guest segment in the
master narration is matched to that same duration, so there is zero downstream
drift. A guest cut is also treated as an INSERT boundary (like B-roll), so the
polish pass's golden-flash + whoosh naturally land on the reveal.

**Any position — hook, middle or end.** Guests are not limited to the opening
scene. When `assemble_narration.py` ran, it recorded each clip's exact
`[start, end]` in the master narration (`assemble_narration.out.json`); the
composer reads those and pins BOTH the in- and out-point of every guest scene, so
a mid-reel guest (host → **guest** → host) is just as frame-exact as a leading
one. To place a guest in the middle, supply the host narration as TWO segments
(before / after the guest) in the plan, with the guest segment between them, and
keep the storyboard scene order matching the plan order.

## Locations — one avatar, multiple looks
A **location** is a *look* for the avatar — wardrobe + environment + light bundled
together — built by the sibling **`avatar-location`** skill (`create_location.py`).
It keeps the avatar's identity (face, gestures, **voice**, `talking_profile`) and
only changes how it's dressed/roomed, with its own identity-anchored hero + camera
angles under `<avatar>/locations/<loc>/angles/`. The avatar's *default* look is just
the top-level `scene.json` + `angles/` (unchanged).

- Set a reel-wide look with the top-level `location: "<loc>"`, and/or per-scene
  `location` overrides — so a reel can cut between looks while the same person keeps
  talking (e.g. open in `studio_night`, then back to `default`).
- Only **talking-head** angle resolution is affected; the voice, narration, guest
  and B-roll scenes are untouched. An explicit scene `image` path still wins.
- A `--dry-run` prints the resolved angle (and `@ <loc>`) per talking-head scene, so
  you can confirm the avatar + look **before** any paid generation. If a location is
  missing an angle, the scene falls back to the default look with a warning.

```bash
# 1) Create the look (review checkpoint, then 1 hero + ~5 angles via gpt-image-2)
python3 .cursor/skills/avatar-location/scripts/create_location.py nora studio_night \
    --setting studio --brief "evening studio, moody teal key light, black turtleneck"
# ...refine nora/locations/studio_night/scene.json, then re-run to generate.
python3 .cursor/skills/avatar-location/scripts/list_locations.py nora
# 2) Reference it in the storyboard: top-level "location": "studio_night" and/or
#    per-scene "location"; then compose normally.
```

## Deriving the storyboard from `<avatar>.analysis.json`
Read the avatar's analysis and mirror its rhythm so the new reel matches.

### Pacing rules (do this first — it's what makes a reel engaging)
Short-form reels keep attention by **cutting often** and **never lingering**.
Reproduce the analyzed reel's rhythm, not just its talking-head:B-roll ratio:
- **Compute the target:** `target_scene_len ≈ median scene duration` of the
  reference analysis (typically **~4–6s**); `num_scenes ≈ narration_seconds /
  target_scene_len`. A 30s reel usually wants **~6–8 scenes**, not 3–4.
- **Open with a short hook:** the first scene should be **~2–3s** (match the
  reference's scene #0). Never open with a 5s+ talking-head — that's the #1 way
  to lose the viewer early.
- **No shot lingers:** keep every scene **≤ ~6s** (a slightly longer ~7–8s shot
  is OK only for an emotional B-roll outro). If a sentence is long, **split it
  across 2+ scenes** at commas/colons/semicolons and change the framing/zoom on
  each — the scene texts still must tile the script verbatim.
- **Vary consecutive talking-heads:** alternate angle + zoom (`eye_level`
  zoom_center → `push_in` zoom-in → `pull_out` zoom-out …) so back-to-back
  presenter shots read as distinct cuts, exactly like the original's repeated
  `hard_cut` + `zoom_in/zoom_out`.
- **Place B-roll deliberately:** put one insert right after the hook and one for
  the outro at minimum; sprinkle more to break up long talking-head stretches.
- `compose_reel.py` prints a **pacing report** (vs the reference median) before
  generating and warns on a long hook / over-long shots — adjust the storyboard
  until the warnings are gone.

### Field-by-field mapping
- **`scene_type`** → scene `type`: `main_character_solo` → `talking_head`;
  `supplementary_material` → `broll`.
- **`zoom_from_previous.type`** → motion. You can either set `motion` directly,
  or **copy the analysis value verbatim** into the scene's `zoom_from_previous`
  and the pipeline maps it for you: `zoom_in` → `push_in`, `zoom_out` →
  `push_out`, `hard_cut` → `none` (clean static reframe), `none` → `zoom_center`
  (subtle) for talking-head / `none` for B-roll. An explicit `motion` always
  wins. B-roll keeps `none` regardless (its camera move is baked in at
  generation, so don't double it).

### Camera-angle sequence (base the new reel on the analyzed one)
The talking-head shots are NOT free camera moves — they reuse a few
**pre-rendered angle crops** from `<avatar>/angles/*_916.png` (or `*_169.png` for
a 16:9 reel) plus digital zoom. So replicate the reference's *tendencies*, not a
1:1 angle-per-scene copy (the new reel has fewer scenes):
- `compose_reel.py` prints a **camera fingerprint** of the reference
  (talking-head angle + framing distribution, and the zoom-transition mix). Match it.
- **Base shot:** use the dominant angle/framing for most talking-heads (for the
  analyzed `lolo` reel that's `eye_level` / `medium_close_up` → the
  `lolo_eye_level_916.png` crop).
- **Emphasis:** for the lines the original tightens on (its `close_up` /
  `zoom_in` scenes), use a closer crop (`*_push_in_916.png`) with
  `emphasis: true`.
- **Variety:** alternate in the other available crops (`pull_out`,
  `negative_space_left`) so consecutive presenter shots read as real cuts,
  mirroring the reference's repeated `hard_cut` + `zoom_in/zoom_out`.
- **Zoom mix:** keep roughly the reference's ratio (here ≈ half `hard_cut`,
  balanced `zoom_in`/`zoom_out`) — copy the per-scene values into
  `zoom_from_previous` to reproduce it faithfully.
- **Widen the palette:** if the reference uses angles you don't have a crop for
  (e.g. `high_angle`), generate them first with the `avatar-camera-angles`
  skill, then reference the new `*_916.png` in the storyboard.
- **`camera.angle` / `camera.framing`** → pick the matching talking-head
  `image` from `angles/` (e.g. `eye_level`, a closer push-in for emphasis).
- **`summary.emotion`** → informs the `voice.emotion` and the mood of B-roll
  descriptions/actions.
- **`summary.focus` / `camera.description`** of B-roll scenes → inspiration for
  your `broll_description` (reinforce the spoken idea visually, WITHOUT the
  presenter). Always give people a `broll_action` so they aren't mannequins.
- **emphasis:** set `emphasis: true` on talking-head lines the original drives
  home with a tighter zoom.

## Motion mapping (replicates the analyzed pattern)
- `push_in` / `push_out` / `zoom_center` / `drift_*` / `none` come from
  `video-compose`'s `MOTION_DEFS` and are applied with `apply_camera_motion`.
- talking-head default (no `motion`): `zoom_center` subtle; `emphasis` → medium.
- B-roll default: `none` (its camera move is baked in at generation time).

## Reuse of video-compose
- `apply_camera_motion` — Ken Burns/zoom on each scene clip (this skill applies
  it to *video* clips, which `video-compose`'s own `render_final` does not).
- `FORMAT_PRESETS` (reel=1080x1920), `ffprobe_video`, `run_ffmpeg`.
- We do **not** use its `mix_music` or the xfade-with-silent-audio path: with a
  voice-over we keep the narration as the single master track and cut hard.

## Notes / defaults
- **Hard cuts only (v1):** xfade would shorten the timeline and desync the
  narration. Motion lives *inside* each scene (Ken Burns/zoom) — which is exactly
  the analyzed reels' pattern (mostly `hard_cut` + `zoom_in/out`). Short
  dissolves are a future improvement (need to compensate the audio overlap).
- **Idempotency:** `narration.mp3` + `narration.align.json` are reused if present
  (skip with nothing, or re-make with `--force-narrate`). Scene clips are cached
  in `<avatar>/generated-videos/` (talking-heads, keyed by scene + an audio
  fingerprint) and `<avatar>/broll/` (keyed by scene); regenerate with `--regen`.
  So you can iterate on assembly without paying for generation twice.
- **Music cache (don't regenerate a good bed):** the per-reel `music.mp3` is reused
  unless `--regen-music`. On top of that, the RAW generated track is cached
  **avatar-wide** in `<avatar>/reels/_bgm_cache/<key>.mp3`, keyed by
  `prompt + mood + vocals`. So a second attempt — or a new reel **version**
  (`-v2`, `-v3`) — with the same musical intent reuses the already-good track
  (just re-fit/looped to that reel's length) instead of paying MiniMax again.
  Change the prompt/mood/vocals to get (and cache) a fresh bed; `--regen-music`
  forces a new generation and refreshes the cache entry.
- **No freeze-pad; B-roll covers its slot:** clips are only ever TRIMMED to the
  scene duration, never frozen on a held last frame. Talking-heads run the
  chunk's exact (audio-driven) length; **B-roll is silent (nothing to sync to)**,
  is generated at `ceil(target)` ≥ slot, and a cached B-roll that no longer
  covers its slot (e.g. after re-narration lengthened the scene) is regenerated
  rather than stretched/frozen.
- **Per-sentence narration + cache:** `narrate.py` synthesizes **one MiniMax call
  per sentence** (decimal/abbreviation-aware split) and joins the takes with a
  small `sentence_gap` of silence. This avoids the audio-quality degradation
  speech-2.8-hd shows on long single takes (its own docs recommend short
  sentences), and the sentence-boundary gaps give the caption engine clean pauses
  to clear on. Each take is **cached in `<reel>/narration_parts/`** keyed by its
  text + voice params, so re-narrating only regenerates what changed. If one
  segment is mispronounced, **re-roll just that sentence** with
  `compose_reel.py <storyboard> --reroll N` (1-based index, from the list
  `narrate.py` prints) — the rest are reused, and only the talking-heads whose
  audio actually changed are regenerated (their cache is audio-fingerprinted).
  Group sentences with `voice.sentences_per_call` to trade a little prosody
  continuity for fewer API calls.
- **No language boost by default:** narration uses `language_boost="None"` so the
  **cloned voice keeps its own accent**. Boosting a language nudges pronunciation
  toward a "standard"/regional accent that can fight the clone (e.g. a neutral or
  Chilean voice drifting into Argentinian *voseo*). Set `voice.language_boost` to
  a locale only if you specifically need that pronunciation help.
- **Expressive delivery:** keep the narration from sounding flat by setting a
  fitting `voice.emotion` and, sparingly, dropping MiniMax interjections
  (`(sighs)`, `(exhales)`, `(laughs softly)`, …) or manual pauses `<#0.5#>` right
  into `script`. They render in the voice but are invisible to alignment/captions.
- **Captions: ASR timing + ASR styling, script spelling (forced alignment):**
  faster-whisper gives the *timing*; its word strings are phonetic, so it
  mis-hears acronyms (`REPE` → `rape`). `align()` aligns each ASR word to the
  `script` and fixes only what should be fixed, while keeping normal subtitle
  conventions:
  - **same word (ignoring case AND accents) ⇒ keep the ASR word verbatim** — its
    casing, accents and punctuation. `Sólo`/`sólo`/`solo` are "the same"; we never
    impose the script's sentence-capitalization or punctuation, and never strip
    whisper's accents (`cómo`, `relación` stay accented).
  - **intentional ALL-CAPS in the script (≥2 letters) ⇒ forced uppercase** in the
    caption, since caps denote intent (acronyms/emphasis: `NO`, `REPE`).
  - **genuinely different letters ⇒ adopt the script spelling**, rendered in the
    ASR word's own case style (so `rape` → `REPE`, but no mid-sentence capitals).
  Originals are kept under `asr_word` in `narration.align.json` for debugging.
- **Polish pass is duration-preserving and applied OVER the final video:** the
  fx layer (stage 4) never re-cuts segments. Real crossfades are forbidden —
  they overlap clips and shorten the timeline, desyncing the continuous
  narration + captions. The golden flash is a per-cut color envelope (stepped
  `eq` slices under timeline `enable`; `eq` does NOT re-evaluate `t`
  expressions per frame) and SFX are an additive audio overlay — neither adds
  or removes a single frame. The pre-fx video is always kept as
  `final-without-sfx.mp4`; re-polishing starts from that clean copy (effects
  never stack), and a fresh finish pass clears the fx marker so the new
  `final.mp4` becomes the clean source.
- **FX fingerprint is MEASURED per avatar, not assumed:**
  `profile_transitions.py` studies the avatar's own originals (frames sampled
  around every analyzed scene boundary) and writes `transition_style.json` —
  flash presence per boundary type, hue (golden/white), duration, strength.
  `polish_reel.py` auto-discovers it, so a new avatar whose originals use a
  white flash, a dip-to-black, or no transition at all gets THEIR look, not the
  reference's. E.g. the reference avatar measures: golden flash on **100% of
  B-roll entries, 0% of exits**, ~0.40s, gain ~1.0. SFX are sparse (~1 per
  15s), short (0.3–0.7s), very soft (~15–20% of voice RMS), placed either
  leading a B-roll cut by ~0.35s (whoosh) or under an emphasized phrase (soft
  low boom). `--guide` (a voice-isolate `voice.json` of an original)
  recomputes the density from its measured `sfx_intervals`.
- **Module naming:** the shared module is `_arc_common.py` (not `_common.py`) on
  purpose, so importing `video-compose`'s `_video_pipeline` (which does
  `from _common import …`) resolves to *its* `_common`, not ours.

## Stage 0: create an avatar from a public Instagram URL (`create_avatar.py`)
If the avatar doesn't exist yet, build it with the orchestrator before composing
reels. `create_avatar.py` runs the whole setup chain with **idempotent resume**,
skipping any stage whose outputs already exist and stopping with instructions at
the two steps that need you (the agent): the browser scrape and the vision
enrichment. Re-run after each to continue.

```
download    instagram-videos      -> <avatar>/videos/*.mp4
analyze     video-scene-analysis  -> <avatar>/videos/*.analysis.json (+ *_frames/)
[CHECKPOINT] AGENT vision enrichment of the analyses (avatar_profile.video_prompt)
frames      avatar-frames         -> <avatar>/frames/ + subtitle_style.json
voice       voice-isolate + voice-clone -> <avatar>/voices/
transitions profile_transitions.py -> <avatar>/transition_style.json
profile     export_talking_profile.py -> <avatar>/talking_profile.json
report      -> <avatar>/avatar.json + readiness table
```

Agent workflow:
1. **Scrape the profile** with the browser MCP per the `instagram-videos` SKILL
   (confirm the profile is public, scroll Picnob, collect every `.post_box`) and
   save the array to `posts-raw/meta/picnob_<handle>.json`.
2. **Run the orchestrator** (from the repo root, so `<avatar>/...` paths resolve):
   ```bash
   python3 .cursor/skills/avatar-reel-composer/scripts/create_avatar.py <avatar> \
     --handle <handle_or_url> [--language es] [--voice-video <name>]
   ```
   It downloads + analyzes, then **stops at the enrichment checkpoint**.
3. **Enrich each `*.analysis.json`** per the `video-scene-analysis` SKILL — view
   the `<stem>_frames/scene_XX.jpg` and fill camera/framing, focus/emotion,
   mannerisms and the reusable `avatar_profile.video_prompt`/`negative_prompt`.
4. **Re-run the same command.** It resumes: frames, voice, transitions, profile,
   then writes `avatar.json` and prints a readiness table. `--status` shows that
   table any time without running anything (zero API spend); `--force-stage NAME`
   re-runs one completed stage.

Camera-angle stills (`angles/*_916.png`, via `avatar-camera-angles`) are the one
piece this orchestrator does not generate — add them if you want fixed
talking-head framings; otherwise the talking-head scenes use the reference
frames. Then write the storyboard and run `compose_reel.py` as above.

## Finishing pass (implemented — `finish_reel.py`)
- **Burned-in subtitles — matched to the analyzed reels.** Word timings from
  `narration.align.json` are segmented into **self-contained phrase units** (breath
  groups, split at pauses/punctuation; a group longer than `max_words` (default 6)
  is subdivided **recursively & balanced** so EVERY unit is short — no oversized
  leftover chunk — and breaks land at proclitic-safe points so a line never ends on
  `que`/`en`/`a`/`el`…). Each unit **REPLACES** the previous one — captions are
  never rolled/accumulated, so the viewer never reads stale already-spoken text
  stacked under a new line (the `avatar-frames` profile confirms the originals'
  `progression: "replace"`, word-overlap ≈ 0.1).
  - **Meaningful emphasis.** A unit renders as a regular **setup** line + a
    **bold-italic PAYOFF** line — the breath-ending / key words that *complete* the
    thought (e.g. `de no poder` → ***soltar.***). Emphasis falls only on a breath
    group's **completion**; mid-breath continuation units stay plain (so the bold
    is reserved for what matters, like the originals). The setup/payoff split is
    balanced (comma-preferred, proclitic-safe). `--no-emphasis` / `emphasis:false`
    disables it.
  - **Always ~2 lines (like the originals).** Lines use a **balanced wrap** (a small
    DP that minimizes the widest line) so a caption never strands an orphan
    single-word line.
  - **Split, don't shrink.** If a caption wouldn't fit at the nominal font, it's
    split into **sequential full-size captions** (each shown for its own words) —
    `necesitas reprogramar` → `tus patrones / subconscientes.` — rather than crammed
    into a tiny block. Lower cognitive load, consistent big text. Splits keep both
    sides ≥2 words (no lone-word flash). The font only auto-fits as a last resort
    (gentle ~80% floor) for a residual 2-long-word overflow.
  - **Tracks speech / clears at pauses.** Each caption is time-bounded to its spoken
    words; when a long pause follows (sentence boundary, > ~0.4s from the
    word-level alignment) it clears shortly after the last word instead of lingering
    on screen with not-yet-spoken text.
  - **Style:** an elegant **serif** (Georgia), **lowercase "subtitle" casing**
    (no sentence-initial capitals, no trailing dot; intentional ALL-CAPS like
    `REPE`/`NO` kept, accents kept), **white with a
    soft drop shadow** (thin subtle outline, no heavy block outline). Rendered as
    transparent PNGs (Pillow) and composited with `video-compose`'s
    `overlay_titles`; windows are contiguous (no flicker).
- **Music bed (fixed or structured).** Reuses `bg-music-hq`'s prompt/structure
  builders but drives `minimax/music-2.5` with prediction **polling** (a slow
  render can't trip the HTTP read-timeout the way a blocking `replicate.run`
  long-poll does). Mixed under the voice with **no sidechain ducking**, and
  **looped (with a short crossfade) to cover the whole reel** so the bed never
  drops out partway through. By default it sits at a **constant low level**; with a
  music plan it follows a **volume envelope** (see *Structured music* below).
  *Always tailor `music_prompt` to the reel's emotional tone* (inferred from the
  script + the generated B-roll); the default is a sparse, intimate, drumless piano
  bed.
  - **Vocals — never the instructions.** `minimax/music-2.5` has no
    `is_instrumental` flag; it SINGS whatever is in its `lyrics` field, so passing
    a mood's raw structure template makes it literally sing the stage directions
    (e.g. *"(Simple piano, hopeful)"*). The finisher therefore **always strips the
    parenthetical directions** and keeps only the bracketed structure tags, then
    shapes the vocals with `--music-vocals` / `finish.music_vocals`:
    `wordless` (default) adds soft, airy **oohs/aahs** under the singable sections —
    a warm sung quality that doesn't compete with the spoken narration — while
    `none` is purely instrumental. Either way the model can't sing the prompt.

### Structured music — the soundtrack that does editing work
The bed can go beyond a flat wash and follow a **volume envelope** that carries
the reel emotionally — the audible half of the [`rule-of-six-edit`](../rule-of-six-edit/SKILL.md)
`sound` axis (a hard-cut entrance, a lift/settle at an emotional shift, a duck
under a key line, a resolve/handoff into the close). It automates the bed's
**presence/dynamics** (aligning a track's own intro/verse/chorus to a frame would
need a structured render — future work). Three ways to drive it, in priority:

1. **`--music-structure auto`** (or `finish.music_structure: "auto"`) — a tasteful,
   zero-config envelope from the scene structure: soft enter, a gentle **duck**
   under the hook so the opening voice punches, a small **lift** after the hook, a
   **resolve** over the final scene.
2. **`--music-plan plan.json`** (or an inline storyboard `finish.music_plan`) — the
   precise envelope. A list of **moves**, each anchored at a scene boundary
   (`"s3 -> s4"` → that cut), a scene id (`"s2"` → its start), or seconds:

   ```json
   { "moves": [
     { "type": "enter_hard", "at": "s1 -> s2" },
     { "type": "duck", "span": ["s2", "s2 -> s3"], "amount": 0.5 },
     { "type": "lift", "at": "s3 -> s4", "amount": 1.3 },
     { "type": "resolve", "at": "s5" }
   ] }
   ```

   Move `type`s: `enter`/`enter_hard` (entrance, soft vs beat-on-the-cut),
   `lift`/`settle` (sustained shift up/down, `amount` × current), `duck`
   (transient dip over `span`/`dur`), `accent` (transient bump), `resolve`
   (decrescendo to the end). `amount` is relative to the running level; the bed is
   capped at a safe absolute ceiling. The envelope is applied as an ffmpeg `volume`
   expression at mux time (entrance via `adelay`), so it's **recomputed for free**
   and never regenerates audio.
3. **`--music-from-cutsheet reel.cutsheet.json`** (or `finish.music_from_cutsheet`)
   — the literal bridge: reads a `rule-of-six-edit` cut sheet and maps each cut's
   `sound` note to a move at its `at` boundary (SPLIT edits carry on the voice, so
   they add no gain move). Best-effort keyword mapping (EN/ES); for exact control
   author a `music_plan`.

The resolved plan + keyframes + entrance land in `reel_manifest.json`
(`finish.music_mix = "automated:<source>"`, `music_plan`, `music_keyframes`).

### Matching the analyzed caption style (`subtitle_style.json`)
`avatar-frames` profiles the burned-in captions of the *original* reels and
writes `subtitle_style.json` (and a `subtitle_style` block in its `manifest.json`)
with the measured **y position, text size, line count, words-per-caption, color,
casing**, an approximate **progression** (replace vs accumulate) and a documented
**emphasis convention**. Pass it to the finisher with `--style-from` (or
`finish.style_from`) to reproduce the originals' placement/size. Caveats:
- **Font family, weight and italic emphasis are NOT auto-detected** (OCR can't read
  them). The profile records the *convention* observed on the originals — the
  breath-ending payoff set in bold-italic of the same serif — and the finisher
  reproduces it by emphasizing each breath group's completion (see above).
- **`progression`** ("replace") is what tells us captions don't accumulate; it's
  approximate (sparse OCR sampling), so treat it as a hint, not a measurement.
- **Casing is low-confidence** (OCR lowercases its output), so only `upper` is
  honored from the profile; otherwise the default `subtitle` casing is used
  (lowercase presentation, intentional ALL-CAPS preserved).

## Next phases (not yet built)
- **SFX between scenes:** short k-drama-style stingers via `sound-effects` at the
  scene boundaries (already known from the slicing step).
- **Dissolves:** short cross-dissolves instead of pure hard cuts (need to
  compensate the audio overlap so the master narration stays in sync).

## Files
- `scripts/create_avatar.py` — stage 0 orchestrator: builds a ready-to-compose avatar from a public Instagram profile (download → analyze → [agent enrich] → frames → voice → transitions → profile → `avatar.json`), idempotent resume, `--status` / `--force-stage`.
- `scripts/narrate.py` — stage 1 (TTS + faster-whisper alignment); importable + CLI.
- `scripts/compose_reel.py` — stage 2 core (align/slice/generate/normalize/assemble/mux); `--finish` to chain stage 3.
- `scripts/finish_reel.py` — stage 3 finishing pass (serif phrase-unit captions with payoff emphasis + a music bed, flat or a structured volume envelope via `--music-structure`/`--music-plan`/`--music-from-cutsheet`); importable + CLI.
- `scripts/polish_reel.py` — stage 4 polish pass (measured-style flash transitions at B-roll cuts + short-soft SFX, applied OVER final.mp4; keeps `final-without-sfx.mp4`); importable + CLI.
- `scripts/profile_transitions.py` — measures the ORIGINAL reels' transition style (flash per boundary type, hue, duration, strength) from `*.analysis.json` + the videos → `<avatar>/transition_style.json` consumed by polish.
- `scripts/_arc_common.py` — shared utils (token, paths, ffmpeg, sibling-CLI runner, video-compose import).
- `scripts/setup_key.py` — set/show the shared Replicate token.
- `examples/storyboard.example.json` — a 7-scene `lolo` storyboard (talking-head + B-roll) with a `finish` block.
