# Avatar Ambient SFX — reference

Detailed cue schema, the Cap.6 worked example, and the level/positioning recipes.

## cues.json (the fields you actually use here)

This is an `audio-theater` file (full schema in `~/.cursor/skills/audio-theater/SKILL.md`).
For an ambient layer you only use `ambient` and `oneshot` cues (no `music`, no voice lines).

```json
{
  "_comment": "what worlds map to what windows + positioning notes",
  "cues": [
    {
      "id": "garden_birds",
      "type": "ambient",
      "description": "a calm garden in the morning: a few different small birds chirping softly and intermittently with natural gentle pauses",
      "prompt_influence": 0.3,
      "start": 0.0, "end": 12.6,
      "gain_db": -14, "fade_in": 2.5, "fade_out": 2.2,
      "spatial": {"pan": 0.0, "distance": 0.3}
    },
    {
      "id": "gull_1",
      "type": "oneshot",
      "description": "a single seagull calling as it glides across the open sky overhead",
      "prompt_influence": 0.4,
      "start": 14.4, "gen_seconds": 3, "gain_db": -9,
      "spatial": {"path": [{"t": 0, "pan": -0.85, "distance": 0.8},
                            {"t": 3, "pan": 0.55, "distance": 0.85}]}
    }
  ]
}
```

| Field | Cue types | Notes |
|---|---|---|
| `type` | — | `ambient` (looping bed) or `oneshot` (single hit at `start`) |
| `description` | both | Plain natural language, one source per cue. For repeated actions describe the **sequence** ("several footsteps…"), not one hit. |
| `prompt_influence` | both | 0–1 (ElevenLabs). Lower (~0.3) = more natural/varied; higher = follows prompt literally. |
| `start` / `end` | ambient | Window in seconds. Overlap ~0.5s into the next world for a soft cross. |
| `start` / `gen_seconds` | oneshot | Hit time + generated length (~2–3s). |
| `gain_db` | both | Level offset. Beds ~`-18..-11`; one-shots ~`-12..-8`. Balance per world (below). |
| `fade_in` / `fade_out` | ambient | Generous `fade_in` (~2.5s) avoids slamming in. |
| `spatial` | both | Beds: gentle `{pan}` balance + `{distance}` only (stay stereo/fixed). One-shots: `{pan,distance}` or movement `{path:[{t,pan,distance}…]}`. |

`pan` -1=left..+1=right (0=center); `distance` 0=close..1=far. **Pan follows what's on screen.**

## Overlay step (overlay_ambient.py)

Defaults encode the Cap.6/7 recipe:
- ambient gain `-4 dB`, ducked under `narration.mp3` via
  `sidechaincompress=threshold=0.04:ratio=3:attack=20:release=350`,
- **loudnorm MATCHES `final.mp4`'s own integrated loudness** (measured at runtime), so the only
  audible change is the ambient bed — our masters sit ~-21..-24 LUFS, NOT -16 (forcing -16 boosts
  the whole mix several dB; see lesson in SKILL.md),
- final audio fade auto-aligned to the last spoken word (`narration.align.json`) + 0.15s beat,
  so the bed fades out exactly with the fade-to-black,
- `-c:v copy` (video untouched).

```bash
python3 <skill>/scripts/overlay_ambient.py --reel-dir antiguo/reels/NNN_slug
# more subtle bed: --ambient-gain-db -7 ;  manual fade: --fade-start 49.55 --fade-dur 0.65
# force a fixed loudness target: --loudnorm I=-16:TP=-1.5:LRA=11 ;  inspect only: --dry-run
```

## Worked example — Cap.6 "El Libre" (3 worlds, 49.8s)

Journey: **garden** (0–11.9s) → **boat / open water** (11.9–32.3s) → **campfire** (32.3–end).
Final positions (after balancing by RMS and matching the frame):

| Cue | Type | Window | gain_db | pan | Reads as |
|---|---|---|---|---|---|
| `garden_birds` | ambient | 0–12.6 | -14 | 0.0 | a few soft birds, gentle pauses (regen'd for naturalness, fade_in 2.5s) |
| `bird_chirp_1` | oneshot | 2.2 | -14 | -0.45 | single chirp, left |
| `bird_chirp_2` | oneshot | 7.6 | -15 | +0.5 | different chirp, right |
| `sea_waves` | ambient | 11.4–32.9 | -5 | 0.0 | water lapping the hull, close & present |
| `sea_breeze` | ambient | 11.4–32.9 | -16 | +0.35 | airy breeze, right |
| `gull_1` | oneshot | 14.4 | -9 | path L→R | gull crosses overhead |
| `gull_2` | oneshot | 20.2 | -10 | path R→center | two gulls, far |
| `gull_3` | oneshot | 27.8 | -11 | -0.7 | lone gull, far left |
| `fire_crackle` | ambient | 31.9–49.7 | -11 | **-0.5** | fire is framed on the **left** |
| `night_crickets` | ambient | 32.0–49.7 | -15 | **+0.45** | crickets right |
| `night_wind` | ambient | 32.0–49.7 | -19 | **+0.45** | wind right |

The actual file lives at `antiguo/reels/008_leccion-de-vida-5-libre/ambient/cues.json` — copy it
as a starting template for the next reel and re-time/re-position the cues.

### QA numbers from Cap.6 (what "good" looks like)

- Pan verified with `astats` (left vs right RMS): gull_1 starts L (-37.6 vs -43.7 dB) and ends R
  (-43.4 vs -41.8); gull_2 enters strong on the R (-45.0 vs -34.0); fire window shows crickets
  left-of-center handled by the fire on the left + crickets/wind on the right.
- Narration still dominates: integrated loudness moved only **-21.5 → -21.3 LUFS** vs `final.mp4`.

## Failure modes seen (and the fix)

- **Bed inaudible** (garden birds at RMS -75 dB): the ElevenLabs render was too distant. Fix:
  regenerate with a closer/denser prompt and add 1–2 `oneshot` accents; then re-balance gain.
- **Bed sounds artificial** (nonstop trills): too dense. Fix: spaced/varied description + low
  `prompt_influence` (~0.3) + long `fade_in` (~2.5s).
- **One hot source crushes the rest** after `mix_spatial`'s global loudnorm (e.g. fire crackle):
  balance `gain_db` per world by measuring RMS; for transients (crackle) set by pan+level, not RMS.
- **Fade cuts the last word**: start the fade at `last_word_end + 0.15s` (overlay_ambient.py does
  this automatically from `narration.align.json`).
