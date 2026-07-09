---
name: avatar-ambient-sfx
description: Add a spatial ambient SFX layer to a finished avatar reel and deliver it as final-espacial.mp4, without overwriting final.mp4. Generates positioned ambient/foley beds + one-shots (birds, water, gulls, fire crackle, crickets, wind, etc.) with audio-theater (ElevenLabs Sound Effects), mixes them on a virtual stereo stage (pan + distance + movement) with mix_spatial.py, and overlays them ducked under the narration. Use when the user wants to "ambientar más" / add ambient or positional/spatial sound to a reel, or asks for sound design / atmosphere that follows different worlds/locations in a video. Builds on the audio-theater skill.
disable-model-invocation: true
---

# Avatar Ambient SFX (spatial sound design for reels)

Layer a **spatial ambient sound bed** over a finished reel so each "world"/location
(garden, water, fire, plaza…) gets its own positioned atmosphere, and deliver it as
**`final-espacial.mp4`**. The narration always stays on top; `final.mp4` is never touched.

This skill is a thin orchestration on top of **`audio-theater`** (which provides the SFX
generator and the spatial mixer) plus one overlay script in this skill.

## When to use

The reel is already finished (`final.mp4` with narration + music + captions + fade), and the
user wants to "ambientarlo más" / add ambient, positional, or spatial sound that follows the
different worlds in the video. Best when the reel is a **journey across distinct locations**.

## Prerequisites

- The finished reel folder must contain: `final.mp4`, `narration.mp3` (narration-only track,
  the sidechain key), and ideally `narration.align.json` (for the fade timing).
- `audio-theater` scripts available at `~/.cursor/skills/audio-theater/scripts` and an
  **ElevenLabs key** set (realistic foley). Verify: `python3 ~/.cursor/skills/audio-theater/scripts/setup_key.py --show`.
- `ffmpeg`/`ffprobe` on PATH.

## Workflow

```
SFX=~/.cursor/skills/audio-theater/scripts
THIS=<this-skill>/scripts          # overlay_ambient.py lives here
REEL=antiguo/reels/NNN_slug
AMB=$REEL/ambient
```

1. **Map the worlds to the timeline.** Read `reel_manifest.json` (scene `start`/`end`) and
   group scenes by location into time windows, e.g. garden `0–11.9s`, water `11.9–32.3s`,
   fire `32.3–end`. Note where the visible source sits in frame (left/right) — pan follows it.

2. **Author `$AMB/cues.json`** (you write it) + an empty `$AMB/lines.json`:
   ```json
   {"duration": <reel_seconds>, "lines": []}
   ```
   One `ambient` bed per world (with a ~0.5s pre-lap/overlap into the next for a soft cross),
   plus `oneshot` accents (a couple of bird chirps, gulls flying across, etc.). Give every cue
   a `spatial` block. **Describe CONCRETE, discrete sounds** (waves, birds, a clock tick, a candle
   pop, a page turn) — NOT abstract textures ("room tone", "airy shimmer", "hush", "starlight"),
   which ElevenLabs renders as broadband NOISE (see the "noise wash" lesson below). For intimate
   indoor scenes, prefer a few diegetic **one-shots in the speech gaps** over a continuous bed.
   See **[REFERENCE.md](REFERENCE.md)** for the cue schema, the Cap.6 worked
   example, and the positioning/level rules. (cues.json is an `audio-theater` file — full schema
   in `~/.cursor/skills/audio-theater/SKILL.md`.)

3. **Generate the SFX** (ElevenLabs, realistic foley):
   ```bash
   python3 $SFX/generate_sfx.py --cues $AMB/cues.json --out $AMB --backend elevenlabs
   ```
   Files land in `$AMB/sfx/`; durations are written back into `cues.json`.

4. **Spatial mix → `ambient_spatial.mp3`** (no dialogue/music in this project, so no ducking
   here — ducking under narration happens in the overlay step):
   ```bash
   python3 $SFX/mix_spatial.py --out $AMB --output-name ambient_spatial.mp3 --no-duck
   # intimate / quiet indoor beds: add --target-i -28 (default -16 over-amplifies near-noise beds)
   ```
   ⚠ `mix_spatial` loudnorms the whole bed to `--target-i` (default **-16 LUFS**, sized for loud
   outdoor foley). For quiet intimate ambiences pass **`--target-i -28`..`-30`** so it doesn't boost
   near-silent beds +30 dB and surface their hiss (see the "noise wash" lesson below).

5. **Overlay onto the reel, ducked under narration → `final-espacial.mp4`:**
   ```bash
   python3 $THIS/overlay_ambient.py --reel-dir $REEL
   ```
   Auto-discovers `final.mp4`, `ambient/ambient_spatial.mp3`, `narration.mp3`,
   `narration.align.json`. Copies the video, mixes the ambient ducked under the narration
   (sidechaincompress), **loudnorm's to MATCH `final.mp4`'s own loudness** (so the only audible
   change is the bed — our masters sit ~-21..-24 LUFS, not -16), and fades the audio out to match
   the fade-to-black. Tune presence with `--ambient-gain-db` (default `-4`; lower = subtler);
   force a fixed target with `--loudnorm I=-16:TP=-1.5:LRA=11` only if you really want it.
   - **Bed cleanup is ON by default** (`highpass 35Hz + lowpass 12kHz + afftdn nr=10`): tames the
     ElevenLabs broadband hiss that quiet/abstract beds carry (these ambiences have nothing above
     ~12kHz). Disable for rich loud outdoor foley with `--no-clean`; tune with `--clean-lowpass` /
     `--clean-nr`. The overlay also prints a **`[bed-QA]` warning** if the bed looks like a
     broadband-noise wash (>8kHz within ~3dB of full) — heed it and re-author the content.

6. **QA (objective, not just by ear):** confirm the panning and that narration still dominates.
   ```bash
   # Per-channel RMS in a window (left vs right) — pan should match the frame:
   ffmpeg -loglevel info -i $AMB/ambient_spatial.mp3 -af "atrim=START:END,astats" -f null - 2>&1 | grep -iE "Channel|RMS level"
   # Integrated loudness should barely move vs final.mp4 (ambient is subordinate):
   ffmpeg -i $REEL/final-espacial.mp4 -af loudnorm=print_format=summary -f null - 2>&1 | grep -i "Input Integrated"
   ```
   ⚠ `astats` needs `-loglevel info` (it's silenced by `-loglevel error`).

## Positioning rules (pan follows the frame)

- `pan` ∈ [-1,+1] (L..R, 0=center), `distance` ∈ [0,1] (0=close..1=far).
- **Position SFX where the source is on screen.** If the fire is framed on the left, crackle
  pans **left**; put crickets/wind **right**. Water/waves usually center & close.
- **Ambient beds stay stereo & fixed** — they only honor a gentle `{pan}` balance and `{distance}`.
  **One-shots move** — give a flying gull a `path` (e.g. L→R) so it crosses the stage.
- Use **soft overlaps** (~0.5s) between adjacent world beds with `fade_in`/`fade_out` so worlds
  cross-fade instead of cutting.

## Level & naturalness lessons (hard-won)

- **⚠ THE "NOISE WASH" TRAP — concrete foley vs abstract textures (Cap.8/9/10 regression).** Caps 6/7
  (008/009) sounded great because their worlds are **loud, concrete OUTDOOR foley** (sea waves, birds,
  fire crackle, gulls) — structured sounds ElevenLabs renders cleanly. Caps 8/9/10 (010/011/012) moved
  to **intimate/abstract INDOOR ambiences** ("candlelit room tone", "airy shimmer", "hush", "glassy
  starlight tone") → ElevenLabs renders those as **very quiet, low-level BROADBAND NOISE** (−41..−61 dB,
  no structure). The pipeline then **amplifies the hiss**: `mix_spatial` loudnorms the bed toward −16
  LUFS (built for loud foley) → +25..+45 dB on near-noise beds, and any hot per-cue `gain_db` (e.g. +10)
  compounds it. Result = a uniform broadband **hiss wash** = the "ruido raro / molesto". Verified by
  spectrogram: 008 shows distinct events + a dark high-freq floor; 012 is a solid red wash from DC to the
  16.5kHz MP3 brick-wall. **Post-processing (denoise/lowpass/lower level) only makes it quieter, not
  pleasant — the content IS noise.** Fixes, in order of importance:
  1. **Author CONCRETE, discrete diegetic sounds, not abstract textures.** A candlelit study reads as a
     few **clock ticks**, occasional **candle/wax pops**, a **page turn**, a wooden **desk creak**, a
     single distant **wind gust** — placed as `oneshot`s in the speech gaps. Avoid continuous "room
     tone / shimmer / hush / starlight" beds (those = noise). If a world has no honest continuous sound,
     **use only one-shots and no bed.**
  2. **QA every bed's spectrogram** (`ffmpeg -i sfx/X.mp3 -lavfi showspectrumpic=s=900x320:legend=1 X.png`):
     it must show **structured events + a dark floor above the content**. A uniform fill up to 16kHz =
     reject/regenerate. The overlay's `[bed-QA]` line is a cheap heuristic for the same thing.
  3. **Don't over-amplify.** For intimate beds, mix with a **lower target** (`mix_spatial.py --target-i
     -28` .. `-30`) so quiet beds aren't boosted +30 dB, and keep `--ambient-gain-db` low (−6..−9). The
     overlay's default **lowpass 12kHz + light denoise** removes the brick-wall hiss; it is a safety net,
     not a substitute for concrete content.
- **Narration ALWAYS wins.** Key the duck off `narration.mp3` (not the full mix) so the bed dips
  only under the voice and stays present in the gaps. After overlay, the integrated LUFS should
  move only ~+0.2–1 LU vs `final.mp4`.
- **Match the source loudness — don't force -16.** The series masters sit ~-21..-24 LUFS (Cap.7
  `final.mp4` = -24.4). The overlay used to hard-code `loudnorm I=-16`, which boosted the WHOLE mix
  (voice + music + ambient) ~+8 dB and made `final-espacial` sound much louder than `final.mp4` —
  a confounded A/B and a false "loudness jumped" QA reading. Fix (now the default): the overlay
  measures `final.mp4`'s integrated loudness and matches it, so the bed is the only change
  (Cap.7: -24.4 → -23.9..-24.3 LUFS, +0.5 LU). TikTok normalizes playback anyway.
- **Balance `gain_db` per world by measuring RMS, not by guessing.** `mix_spatial.py` runs a
  global `loudnorm`, so one hot source (e.g. fire crackle peaking at -1.7 dBFS) will crush the
  rest. Measure each world's RMS with `astats` and raise quiet worlds until each is audible.
- **Validate the SFX source.** ElevenLabs sometimes renders a bed too distant/quiet — the first
  garden-birds render came back at RMS **-75 dB** (inaudible). Regenerate with a closer/denser
  prompt and/or add 1–2 `oneshot` accents.
- **NEVER prompt beds as "almost silent" / "very faint".** ElevenLabs takes it literally and renders
  the bed at **-73..-83 dB** (dead). For an *intimate* room (candlelit study), describe **present,
  up-close** detail ("up-close candle flames fluttering with a faint wax crackle, a warm room tone,
  a distant tiny clock tick") — let `gain_db`/`distance` set the *level*, the prompt sets the
  *content*. Cap.9: "almost silent" beds → inaudible; rewritten present → -38..-58 dB.
- **Continuous narration crushes the bed (the "I hear no ambient" trap).** If the reel is wall-to-wall
  voice (check `narration.align.json` for gaps), the overlay's sidechain duck suppresses the WHOLE
  layer almost the entire time. Two fixes, used together: (1) **soften the duck** so the bed breathes
  under the voice — `--duck "threshold=0.06:ratio=2:attack=15:release=400"` (the `-4`/default
  `ratio=3` is too aggressive for continuous VO); (2) **place diegetic one-shot accents IN the speech
  gaps** — Cap.9 had a single 0.64s gap (18.84–19.48s), so the coin-clink (the action beat's sound)
  was moved to `start:18.95` and rang out **+8 dB** in-clear instead of being masked at full speech.
- **QA the bed by A/B window, not just integrated LUFS.** Measure the same windows in `final.mp4` vs
  `final-espacial.mp4` (`-ss W -t D -af volumedetect`): a real gap should jump several dB; speech
  windows should barely move (voice still wins). Integrated LUFS hides an inaudible bed.
- **Transients lie.** A crackle has low RMS despite high peaks — don't chase its RMS; set it by
  pan + level by ear.
- **Naturalness > density.** A dense/continuous bed sounds fake (e.g. nonstop bird trills).
  Prefer a spaced/varied description ("a few different small birds… with natural gentle pauses"),
  low `prompt_influence` (~0.3), and a generous `fade_in` (~2.5s) so it doesn't slam in.
- **Don't overwrite `final.mp4`** — always deliver `final-espacial.mp4` (the spatial layer is an
  optional alternate, not the canonical master).

## Output

- `$AMB/cues.json`, `$AMB/sfx/*.mp3`, `$AMB/ambient_spatial.mp3` (the spatial layer).
- `$REEL/final-espacial.mp4` (video copied from `final.mp4`, audio = original + ambient bed).

## Additional resources

- Cue schema, the full Cap.6 worked example, and detailed positioning/level recipes:
  [REFERENCE.md](REFERENCE.md)
- SFX/mix internals (cues.json fields, mix_spatial flags): `~/.cursor/skills/audio-theater/SKILL.md`
