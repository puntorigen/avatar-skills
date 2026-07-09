---
name: audio-theater
description: Turn a dialogue, a story with dialogue, or a one-line idea into multi-character audio using Gemini TTS, with word-level timecoded transcription (WhisperX or local faster-whisper), realistic ambient/foley SFX (ElevenLabs or the sound-effects skill), and instrumental score/music (MiniMax Music 2.6). Optional stereo spatialization (pan + distance + movement) and an ffmpeg mix with sidechain ducking (music ducks under voices+SFX). Three modes - theater (dramatized radio play), lipsync (clean per-line clips <=15s plus a manifest for the seedance-2 skill), and podcast (two hosts with intro/bed/outro music). With music it delivers three tracks (full mix, music-only, and a no-music stem for animated storyboards) plus a timecoded transcript and per-line voice + SFX/music files. Use for an audio drama, audio theater / audioteatro / radioteatro, a dramatized dialogue, a score for a story/podcast/storyboard, voiceover for lipsync, a TTS conversation, or a podcast episode from a script or idea.
---

# Audio Theater

Generate multi-character audio (radio drama, lipsync voice reference, or podcast) from a script or idea. The engine is the same in all modes: **one clean Gemini TTS clip per line**, one voice per character. Those clean per-line clips are exactly what you need to mix a radio play, feed lipsync in `seedance-2`, or assemble a podcast.

## Setup

Install dependencies (one-time):

```bash
pip3 install -r ~/.cursor/skills/audio-theater/scripts/requirements.txt
```

Keys are **reused from sibling skills** - you usually do not need to set anything:
- Gemini API key from the `asset-generator` skill (`gemini_api_key`).
- Replicate API token from the `sound-effects` skill (`replicate_api_token`, with the usual fallbacks).
- **(recommended for realistic SFX)** ElevenLabs API key (`elevenlabs_api_key`) — get a free key at https://elevenlabs.io and set it with `setup_key.py --elevenlabs KEY`. When present, the SFX backend defaults to ElevenLabs (much more realistic foley/ambience than Stable Audio). Without it, SFX fall back to the `sound-effects` skill (Stable Audio).

Import/verify them once:

```bash
python3 ~/.cursor/skills/audio-theater/scripts/setup_key.py            # auto-import from sibling skills
python3 ~/.cursor/skills/audio-theater/scripts/setup_key.py --show     # show what is configured
```

`ffmpeg` and `ffprobe` must be on PATH (`brew install ffmpeg`).

## Modes

| Mode | Output | Use it for |
|------|--------|-----------|
| `theater` (default) | `final.mp3` (dialogue + SFX + music, ducked) + stems when there's music + `transcript.md` | Dramatized radio play / audio drama |
| `lipsync` | clean `lines/*.wav` clips `<=15s` + `lipsync.json` | Audio reference for `seedance-2` lip-sync over a storyboard |
| `podcast` | `final.mp3` (2 hosts + intro/bed/outro music) + stems + show-notes `transcript.md` | Podcast episodes (e.g. mascotify) |

> **Music & stems.** Add `music` cues for a score (story/podcast underscore) or scene music. When music is present the mixers emit three tracks: `final.mp3` (everything), `final.music.mp3` (music only), and `final.nomusic.mp3` (dialogue + SFX, no music — the track to feed `seedance-2` for animated storyboards, then overlay the music back). See "Three deliverables" below.

> **Fitting a fixed duration (reels / ads).** When the audio must land at a target length (e.g. a 15s reel), **budget the script to that length at the voices' natural pace — use fewer, shorter lines.** Do *not* lean on time-stretching the speech: the Gemini voices read deliberately, so heavy `atempo` (>~1.1×) sounds rushed and *raises* cognitive load — the opposite of what an ad/explainer needs. Rough budget: **~2 spoken words per second** (this already accounts for the model's slow pace + inter-line pauses), so a 15s clip ≈ 25-30 words total. The model also pads each clip with leading/trailing/inter-sentence silence; **trim that dead air first** (it buys real seconds without changing perceived pace), and only then apply a *gentle* atempo (≤1.1×) if you're still slightly over. If it's still too long, **cut a line — never crank the speed.** Details + the trim/scale filters: REFERENCE.md → "Pacing & fixed-duration targets".

## Workflow

The skill is a set of small scripts. Run only the steps the mode needs. Outputs always go to a project folder `audio-theater/<slug>/` (pass `--out`).

```
SCRIPTS=~/.cursor/skills/audio-theater/scripts
OUT=audio-theater/la-tormenta        # project-relative output folder
```

### 1. Get a script (`script.json`)

You have a dialogue/story already, or just an idea. Either way the pipeline runs on a `script.json` (schema below).

- **From an idea or rough draft** -> let Gemini write it:

```bash
python3 $SCRIPTS/write_script.py \
  --idea "Dos marineros discuten mientras se acerca una tormenta" \
  --mode theater --language es --out $OUT
# podcast: two hosts + intro/outro
python3 $SCRIPTS/write_script.py \
  --idea "Episodio sobre por que los gatos amasan" \
  --mode podcast --language es --hosts "Lucas,Mia" --out $OUT
```

- **From an existing dialogue** -> pass a `.txt` (lines like `Marco: La tormenta se acerca.`); it is parsed and voices are auto-assigned:

```bash
python3 $SCRIPTS/write_script.py --script-file dialogo.txt --mode theater --language es --out $OUT
```

Either way it writes `$OUT/script.json` + a human-readable `$OUT/story.md`. **Review/edit `script.json`** (voices, tags, pauses) before generating audio.

### 2. Generate the voices (`lines/*.wav`, `dialogue.wav`, `lines.json`)

One clean clip per line, concatenated into `dialogue.wav` with exact timing in `lines.json`:

```bash
python3 $SCRIPTS/generate_voices.py --script $OUT/script.json --out $OUT
# Exactly 2 speakers and you want a single natural conversation take:
python3 $SCRIPTS/generate_voices.py --script $OUT/script.json --out $OUT --two-speaker
```

It warns if any clip exceeds `--max-clip-seconds` (15, the seedance limit). Keep lines short for lipsync.

### 3a. (lipsync mode) Export the seedance manifest

```bash
python3 $SCRIPTS/export_lipsync.py --out $OUT
```

Writes `$OUT/lipsync.json` (per clip: speaker, voice, exact transcript, duration, `ok` for `<=15s`, suggested `panel`). Then hand off to `seedance-2` (see "Lipsync handoff" below). In lipsync mode you can stop here - the clean clips are the deliverable.

### 3b. (theater/podcast) Transcribe with word timecodes (`words.json`)

```bash
python3 $SCRIPTS/transcribe.py --audio $OUT/dialogue.wav --script $OUT/script.json \
  --backend auto --out $OUT
```

`--backend`: `replicate` (WhisperX, default for `auto` when a token exists), `local` (faster-whisper), or `auto` (replicate then local fallback).

### 4. (theater/podcast) Author the SFX/music sheet (`cues.json`)

**You (the agent) write `$OUT/cues.json`** by reading `script.json` + `words.json` and placing sound where it makes sense (use word timecodes to anchor one-shots). Cue `type` is `ambient`, `oneshot`, or `music`. Schema below.

### 5. (theater/podcast) Generate the cued sounds (`sfx/*.mp3`)

```bash
python3 $SCRIPTS/generate_sfx.py --cues $OUT/cues.json --out $OUT
# force a backend:  --backend elevenlabs | sound-effects   (default: auto)
```

`ambient`/`oneshot` SFX use the `--backend` (default `auto`):
- **`elevenlabs`** (auto-selected when an ElevenLabs key is set) — ElevenLabs Sound Effects (`eleven_text_to_sound_v2`). Best realism for foley/ambience; ambient cues are rendered as native seamless loops (`loop=true`). Send a plain natural-language `description` (no keyword soup); tune realism with optional cue field `prompt_influence` (0-1, default 0.4).
- **`sound-effects`** — Stable Audio 2.5 via the `sound-effects` skill (synthesis; fine for abstract/UI, weaker on realistic foley). Uses the cue `category`.

`music` cues are always **instrumental** (no sung vocals). Pick the backend with `--music-backend` (default `auto` → `hq`):
- **`hq`** — MiniMax **Music 2.6** with `is_instrumental=true` (via `audio_music.py`). The model ignores lyrics and never sings; the `prompt` (built from `description` + `mood`) drives the whole track. Best for scores, beds, scene music.
- **`fast`** — the `bg-music` skill (quicker, lighter instrumental tracks).

> We intentionally do **not** use `bg-music-hq` for theater music: it targets MiniMax `music-2.5`, which has no instrumental flag and routes structure directions through the `lyrics` field — so `music-2.5` *sings them literally* ("soft piano joins…"). `audio_music.py` reads `bg-music-hq`'s mood library read-only to build the style prompt, but does not modify that skill.

A per-cue `music_backend` overrides the run default. Pass the cue `mood` (e.g. `pet-lullaby`, `cinematic`, `podcast-bed`); `audio_music.py --list-moods` shows the library. The model returns a full-length track (no looping needed); if it's shorter than the window the mixer loops it.

```bash
python3 $SCRIPTS/generate_sfx.py --cues $OUT/cues.json --out $OUT --music-backend hq
```

Files land in `$OUT/sfx/` and durations are written back into `cues.json`.

### 6. (theater/podcast) Mix (`final.mp3` + stems)

```bash
python3 $SCRIPTS/mix.py --dialogue $OUT/dialogue.wav --cues $OUT/cues.json --out $OUT
```

One-shots are placed at their timecode; ambient beds are looped/trimmed to `[start,end]` with fades and **sidechain ducking** keyed off the dialogue. **Music behaves like a background score:** it sits well below the dialogue and **gently lowers under the whole *content* (voices and SFX)** — but the ducking is smooth/broadcast-style (slow release, shallow ratio) so it **never pumps up and down between words** and **never gets louder than the voices**. Keep music base levels low (`-24..-20`) and SFX peaks under the dialogue. Everything is summed and loudness-normalized to `final.mp3`.

**Stems (`--stems`, default `auto`).** When the project has `music` cues, the mixer also emits two extra MP3s next to `final.mp3` (this is the standard music deliverable — see "Three deliverables" below):
- `final.nomusic.mp3` — dialogue + SFX, **no music** (the track to feed `seedance-2` for animated storyboards).
- `final.music.mp3` — the **music only** (ducked + faded exactly as it sits in the full mix).

All three share one linear normalization gain, so `final = nomusic + music` exactly (you can overlay the music back after the video render). `--stems always` forces it even without music; `--stems off` writes only `final.mp3`.

### 6b. (theater, optional) Spatial stereo mix (`final.mp3`)

For an immersive radio-drama feel, `mix_spatial.py` places **each voice line and each one-shot SFX on a virtual stereo stage** (left/right + near/far + movement) instead of the flat center mix of `mix.py`:

```bash
python3 $SCRIPTS/mix_spatial.py --out $OUT --output-name final.mp3
# headphone-friendlier hard pans:  --crossfeed
# wider voices:  --voice-pan-limit 0.6     stronger distance:  --max-atten-db -14
# keep SFX full level under narration:  --no-duck-sfx
```

It reads per-line clips from `lines.json`, character seats + per-line moves from `script.json`, and per-cue positions from `cues.json` (all the new `spatial`/`stage` fields below are **optional and backward compatible**). With no positions authored it still seats non-narration speakers at gentle alternating L/R offsets for a natural stereo image. Ambient SFX **beds stay stereo** (optional balance/distance) and keep their ducking; voices and one-shots are panned/moved.

`mix_spatial.py` emits the same **stems** as `mix.py` (`final.nomusic.mp3` + `final.music.mp3` when there are music cues; `--stems` controls it), and music sits under the content bus with the same smooth, shallow ducking as the flat mixer (no pumping, never above the voices).

**Music: fixed score by default; subtle entrances when diegetic.** Background / narrator-style score music must be **FIXED** (no movement) — by default a `music` cue is a still wide stereo bed, which is what you want for "part of the story" underscore. For diegetic *scene* music (a music box on the table, a radio across the room) give it `spatial` with a **single, gentle gesture** — never a zig-zag (on/off/on/off reads as broken):
- `{"scene": true, "enter": "left" | "right" | "front", "pan": …, "distance": …}` — glides in from that side/depth over a few seconds, then **holds** at its seat (pair with `fade_in`).
- `{"scene": true, "exit": "left" | "right" | "front"}` — holds, then glides out at the very end (pair with `fade_out`).
- `{"scene": true, "from": {…}, "to": {…}}` — one clean sweep across the window. A multi-point `path` is collapsed to first→last (no bouncing).

Scene music is collapsed to a positioned point source and still ducks under the content.

**Narration always wins.** The narrator sits closest (smallest distance) and one-shot SFX are kept *behind* the dialogue plane and **ducked under the narrator's voice** so a loud effect (a door, a gust) never buries the narration:
- `--sfx-min-distance` (default `0.12`): floor on how close any SFX may render, so the narrator (≈0.05) always reads as the closest source. Movement still works; SFX just can't come closer than this.
- one-shot SFX **duck under the narration** voice (keyed off the narrator, not the whole dialogue, so SFX stay punchy during character lines and gaps). `--sfx-duck-db` (default `-6`) sets how much they dip; `--no-duck-sfx` disables it; `--no-duck` disables all ducking. If there's no narrator, SFX duck under all voices instead.
- For an audio-theater feel, **move things boldly** — wide pans and big distance changes read far better than subtle ones. A sound that *recedes* (distance increasing) or a voice that *approaches* (distance decreasing) is the clearest cue; see the `historia-breve` demo (Lila walks in from far-left to center, the owl flies across L→R *and away*, the gust sweeps past and recedes).

**Theater only.** The lipsync feed (`split_tracks.py` → `seedance-2`) must stay centered/mono-safe for the video model, so it keeps using the flat `mix.py`. Use `mix_spatial.py` for the standalone listening deliverable, not for lipsync audio.

### 6c. Three deliverables when there's music (story, podcast, storyboard)

Whenever a project has `music` cues, both mixers deliver three tracks in one pass (the music stem is ducked + faded exactly as in the full mix, and the three share one gain so they recombine):

| File | Contents | Use it for |
|------|----------|-----------|
| `final.mp3` | dialogue + SFX + **music**, fully mixed (spatial if you used `mix_spatial.py`) | the finished listen — story, podcast episode |
| `final.music.mp3` | **music only** | swap/level the score, reuse the track, overlay after a video render |
| `final.nomusic.mp3` | dialogue + SFX, **no music** | feed `seedance-2` for animated storyboards |

**Storyboard / seedance workflow.** Audio-driven video models get confused by music, so feed them the **no-music** track, then layer the music back over the rendered video:

```bash
# 1) render the storyboard with the music-free track as the audio reference
#    (use final.nomusic.mp3, trimmed to < the render duration; see "Lipsync handoff")
# 2) after the video is back, overlay the music stem on top:
ffmpeg -y -i reel.mp4 -i final.music.mp3 \
  -filter_complex "[0:a][1:a]amix=inputs=2:normalize=0:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -shortest reel_final.mp4
```

Because the music stem keeps the original timecodes (and the same ducking it had in the full mix), it lines up automatically and still dips under the dialogue. For projects that also split narration vs on-camera voice, combine this with `split_tracks.py` (below): feed `lipsync_mix.mp3` (which is already music-free when you mix the no-music track) and overlay both `narration.mp3` and `final.music.mp3` afterward.

### 7. Build the transcript (`transcript.md`)

```bash
python3 $SCRIPTS/build_transcript.py --out $OUT
```

Timecoded transcript with `[SFX: id]` placeholders (theater/lipsync) or speaker show-notes (podcast), plus a list of the SFX/music used.

## script.json schema

```json
{
  "title": "La tormenta",
  "language": "es",
  "language_code": "es-US",
  "mode": "theater",
  "characters": [
    {"name": "Marco", "voice": "Charon", "persona": "marinero veterano, voz grave y cansada", "stage": {"pan": -0.35, "distance": 0.18}},
    {"name": "Inés", "voice": "Aoede", "persona": "joven grumete, nerviosa", "stage": {"pan": 0.4}},
    {"name": "Narrador", "voice": "Sulafat", "role": "narration", "on_camera": false, "persona": "voz cálida que cuenta la historia"}
  ],
  "lines": [
    {"index": 0, "speaker": "Marco", "text": "La tormenta se acerca, muchacha.", "tags": ["serious", "tired"], "pause_after": 0.4},
    {"index": 1, "speaker": "Inés", "text": "[trembling] ¿Llegaremos a puerto?", "tags": ["panicked"], "pause_after": 0.2,
     "spatial": {"from": {"pan": 0.6, "distance": 0.6}, "to": {"pan": 0.2, "distance": 0.15}}}
  ]
}
```

- `language` / `language_code`: `language` is the 2-letter content language (`es`). `language_code` is the **BCP-47 accent/locale** Gemini TTS renders in — set it to control the accent: `es-US` (LATAM-neutral, the default for `es`), `es-ES` (Castilian), `pt-BR`, `en-US`, etc. The 30 voices are accent-flexible; the locale, not the voice, drives the accent. Resolution order: `--language-code` flag > script `language_code` > mapped default from `language` (`es`→`es-US`). Omit for auto-detect.
- `voice`: one of the 30 Gemini voices (see `scripts/voices.json`). Auto-assigned if omitted. Timbre only — pair with `language_code` for the accent (e.g. for neutral LATAM Spanish keep `language_code: "es-US"`).
- `tags`: optional inline delivery tags (e.g. `whispers`, `laughs`, `excited`). They are woven into the line as `[tag]` audio tags. You can also put tags directly inside `text`.
- `pause_after`: seconds of silence appended after the line in `dialogue.wav` (default 0.3).
- `role` / `on_camera`: optional. Mark a character as off-camera narration with `"role": "narration"` (also accepts `voiceover`/`vo`/`offscreen`) or `"on_camera": false`. Only used by `split_tracks.py` to separate the narrator's voice from the lip-synced characters (see "Narration vs on-camera" below). Default: on-camera.
- `stage` (character, spatial mix only): the character's default seat `{pan, distance}` — `pan` ∈ [-1,+1] (L..R, 0=center), `distance` ∈ [0,1] (0=close, 1=far). Used by `mix_spatial.py`; ignored by `mix.py`. Default: narration centered/intimate, others auto-seated L/R.
- `spatial` (line, spatial mix only): per-line override of the seat — static `{pan, distance}`, or movement `{from:{…}, to:{…}}` / `{path:[{t,pan,distance}, …]}` (`t` in seconds from the line start). Voice pan is clamped to `±--voice-pan-limit` (default 0.5) for intelligibility.

## cues.json schema

```json
{"cues": [
  {"id": "rain_bed", "type": "ambient", "description": "lluvia constante sobre cubierta de madera",
   "category": "nature", "start": 0.0, "end": 42.0, "gain_db": -18, "duck_db": -8, "fade_in": 1.5, "fade_out": 2.0},
  {"id": "door_slam", "type": "oneshot", "description": "portazo de madera pesada",
   "category": "foley", "start": 12.6, "gain_db": -4, "spatial": {"pan": 0.0, "distance": 0.1}},
  {"id": "owl", "type": "oneshot", "description": "un búho ululando mientras cruza el bosque",
   "start": 19.5, "gen_seconds": 3, "gain_db": -6,
   "spatial": {"path": [{"t": 0, "pan": -0.9, "distance": 0.85}, {"t": 3, "pan": 0.9, "distance": 0.85}]}},
  {"id": "story_score", "type": "music", "mood": "cinematic", "music_backend": "hq",
   "description": "soft mystical underscore, slow strings and distant music box, low and unobtrusive",
   "start": 0.0, "end": 120.0, "gain_db": -18, "duck_db": -14, "fade_in": 3.0, "fade_out": 4.0},
  {"id": "music_box", "type": "music", "mood": "pet-lullaby", "description": "tiny wind-up music box on a table",
   "start": 60.0, "end": 80.0, "gain_db": -12, "spatial": {"scene": true, "enter": "left", "pan": 0.5, "distance": 0.35}},
  {"id": "intro_music", "type": "music", "mood": "podcast-intro", "description": "cortina alegre de podcast de mascotas",
   "start": 0.0, "end": 8.0, "gain_db": -10, "duck_db": -12, "fade_out": 2.0}
]}
```

- `type`: `ambient` (looping bed, ducked under voice), `oneshot` (single hit at `start`), `music` (instrumental score/bed/jingle).
- `description`: natural-language prompt. With the `elevenlabs` backend, send it plain (the model handles natural language); name concrete sources/materials, one source per cue. **For repeated/continuous actions describe the full sequence, not a single hit** — e.g. "a sequence of several footsteps crunching on leaves", "several twigs snapping in succession" — and set a matching `gen_seconds` (~3-5s). Otherwise the model renders one isolated event (one step, one snap), which sounds thin.
- For a stylized / dramatized feel, push the description (e.g. "mystical eerie wind with an otherworldly hum" instead of plain realistic wind) and lower `prompt_influence` (~0.3) so the model adds character.
- `prompt_influence` (ambient/oneshot, `elevenlabs` only): 0-1, default 0.4. Lower = more natural variation / more stylized, higher = follows the prompt more strictly.
- `category` (ambient/oneshot, `sound-effects` backend only): `nature`, `ambient`, `foley`, `mechanical`, `transition`, `game`, `voice`, `generic`. Ignored by the `elevenlabs` backend.
- `mood` (music): a mood from the `bg-music-hq` library (read-only) used to steer the prompt — `podcast-intro`, `podcast-bed`, `podcast-outro`, `cinematic`, `ambient`, `pet-lullaby`, etc. (run `audio_music.py --list-moods` for the full list).
- `music_backend` (music only): `hq` (MiniMax **Music 2.6**, `is_instrumental=true` — default; never sings) or `fast` (`bg-music`, quicker). Overrides the run's `--music-backend`. Music is always instrumental.
- `gain_db`: level offset applied to the cue. **Dialogue is always on top** — SFX and music must sit under it. SFX should be present but **not louder than the voices**: one-shots usually `-12..-8` (peaky sources like a door/gust/snap lower, ~`-13..-11`; quiet textures can go higher), SFX beds `-18..-15`. **Music score** sits lowest — base `-24..-20`; it stays a soft bed and the gentle ducking only nudges it a few dB further down under content. `duck_db`: how much the cue dips while content plays — `-4..-8` for everything (music's duck is intentionally **shallow + smooth** so it doesn't pump; default music `-8`, capped to a gentle ratio with a long release). `start`/`end`/`fade_in`/`fade_out` in seconds. `gen_seconds` (oneshot) pins the generated length.
- `spatial` (spatial mix only, `mix_spatial.py`): position on the virtual stage. **One-shots** are panned/moved like voices — static `{pan, distance}`, or movement `{from, to}` / `{path:[{t,pan,distance}, …]}` (SFX pan clamped to `±--sfx-pan-limit`, default 0.95). **Ambient beds and score music stay stereo & FIXED**; they only honor an optional `{pan}` (gentle L/R balance, keeps width) and/or `{distance}` (level + low-pass). A **`music` cue becomes a positioned point source** (diegetic scene music) only when its `spatial` has `{"scene": true}`; then keep the motion **subtle and single-direction** — `enter`/`exit` (`"left"|"right"|"front"`) for a gentle glide in/out, or one `from`/`to` sweep. **Never zig-zag music.** Ignored by `mix.py`.

## Lipsync handoff to seedance-2

The clean per-line clips are the audio reference for `seedance-2` lip-sync. This skill produces the clips + `lipsync.json`; it does **not** generate the storyboard (use `gpt-image-2` / `seedance-2` for that). Per clip:

1. Upload the clip: Higgsfield `media_upload` -> PUT bytes -> `media_confirm` (`type: "audio"`). Seedance accepts audio **only via `medias[]`** and **requires at least one image/video reference**, with total duration **`<=15s`** (`export_lipsync.py` validates this with `ok`).
2. Build the prompt with the exact transcript:

```bash
python3 ~/.cursor/skills/seedance-2/scripts/prompt_tools.py reframe \
  "[Image1] the sailor speaks to camera" --images 1 --audios 1 \
  --audio-transcript "La tormenta se acerca, muchacha."
```

3. Call `generate_video` (model `seedance_2_0`) with the storyboard panel image (reference-image role) + the confirmed audio `media_id` (audio role). Map `lipsync.json[*].panel` to the storyboard panel.

> **Keep the audio strictly *under* the render duration.** Seedance fails/derails when the audio length equals (or exceeds) the requested video duration. For a 15s render, feed audio **≤ 14.9s** (trim with a tiny tail fade). The render comes back ~15s.

## Narration vs on-camera: split tracks for video lip-sync

When a single mixed track contains both an **off-camera narrator** and an **on-camera character that should lip-sync**, feeding the whole thing to an audio-driven video model is wrong: the model tries to make an on-screen character mouth the narrator's words. Split the project into two role-separated tracks and recombine in post:

```bash
python3 $SCRIPTS/split_tracks.py --out $OUT
# or override role detection:
python3 $SCRIPTS/split_tracks.py --out $OUT --narration "Narrador" --onscreen "Doki"
```

It reads `lines.json` + `cues.json` (and character `role`/`on_camera` from `script.json`) and writes:
- **`narration.mp3`** — only the narration/off-camera lines, on the original timeline (silence elsewhere).
- **`lipsync_mix.mp3`** — the on-camera voices **+ all SFX**, with the narration **muted**. This is the track to feed the video model: it lip-syncs only the on-camera character(s) and never the narrator.
- **`tracks.json`** — which speakers/lines went to which track + durations.

Then:
1. Trim `lipsync_mix.mp3` to **under** the render duration (≤14.9s for a 15s reel) and feed it to `seedance-2` as the audio reference (prompt: lip-sync the on-camera character only when its voice is present; mouths closed during silence/narration; **do not add captions** and keep panel text unchanged).
2. After the video renders, **merge `narration.mp3` back on top** of the rendered video's audio (it already carries the on-camera voice + SFX), e.g.:

```bash
ffmpeg -y -i reel.mp4 -i narration.mp3 \
  -filter_complex "[0:a][1:a]amix=inputs=2:normalize=0:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -shortest reel_final.mp4
```

Because `narration.mp3` keeps the original timecodes, it lines up with the visuals automatically.

## Notes & limits

- TTS model defaults to `gemini-3.1-flash-tts-preview`. Output is PCM 24kHz 16-bit mono, wrapped to WAV.
- Gemini multi-speaker is capped at **2 voices** and quality drifts past a few minutes - that is why the default is one clip per line. `--two-speaker` exists for exactly-two-speaker scenes/podcasts.
- The model occasionally returns text instead of audio (random ~500); `generate_voices.py` retries automatically.
- Keep lines short, especially for lipsync (one clip per shot, `<=15s`).
- **Hitting a fixed total length is a scripting job, not a speed job** — write fewer/shorter lines (~2 words/sec budget) and trim dead air; reserve `atempo` for a gentle (≤1.1×) final nudge. See "Fitting a fixed duration" above.

## Additional resources

- Voices, tags, WhisperX/cues/lipsync schemas, mix internals, podcast recipes, troubleshooting: [REFERENCE.md](REFERENCE.md)
