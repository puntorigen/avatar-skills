---
name: caption-word-reveal
description: >-
  Word-by-word ("karaoke") burned-in captions for avatar reels: each word
  appears at the instant it's spoken, building up the SAME phrase unit in place
  (frozen layout, no reflow), and the phrase clears when the next one begins.
  Use when the user wants captions/subtitles where words form the sentence as the
  narration says them (word-by-word reveal, karaoke captions, "las palabras van
  apareciendo") on any reel produced by the avatar-reel-composer pipeline.
---

# Caption word-by-word reveal

Karaoke-style captions for reels: instead of a whole phrase popping in at once,
each aligned **word appears the moment it's spoken**, building the phrase up in
place; already-spoken words stay lit and the phrase **clears when the next
phrase starts** (same "replace" progression as the static captions).

This is already implemented in the **`avatar-reel-composer`** finishing pass
(`finish_reel.py`) — this skill is how to apply/tune it and the invariants to
keep. It is the **default** caption mode (`caption_reveal="word"`).

## When to use
- The user wants captions where the words form the sentence as they're spoken
  ("palabra por palabra formando la frase", karaoke captions, word reveal).
- Applying that look to a **new** reel, or **re-captioning** an already-finished
  reel without regenerating any video.

## Requirements
- A reel folder produced by `compose_reel.py` (has `video_track.mp4`,
  `narration.mp3`, `reel_manifest.json`).
- **Word-level timings** at `narration.align.json` (faster-whisper alignment) —
  the reveal is driven by each word's `start`. Without it, captions are skipped.

## How to apply

### A) New reel — set it in the storyboard `finish` block
```json
"finish": { "enabled": true, "subtitles": true, "caption_reveal": "word" }
```
Then compose normally; `caption_reveal` defaults to `"word"`, so a `finish`
block already gets the reveal unless you set `"phrase"`.

### B) Any existing reel — re-caption in place (no re-render of video)
```bash
python3 .cursor/skills/avatar-reel-composer/scripts/finish_reel.py <reel_dir> \
    --caption-reveal word --no-music
```
`--no-music` reuses the existing bed and only rebuilds the caption layer. Drop it
(or add `--music-prompt "…"`) to also (re)build music. Re-running is idempotent.
To revert to static phrase-replace captions use `--caption-reveal phrase`.

If a **polish pass** (golden-flash / SFX) was applied, re-run it afterward so the
effects sit on top of the freshly captioned video (see avatar-reel-composer
*Polish*). Tune text with the same knobs as static captions: `--max-words`,
`--no-emphasis`, `--casing`, `--fontsize`, `--y-frac`, `--regular-font`,
`--emph-font`.

## How it works (invariants — keep these when tuning)
The reveal reuses the SAME phrase units and setup/payoff styling as the static
captions; only the presentation differs. Four properties keep it from looking
janky — preserve them:

1. **Frozen layout, no reflow.** The wrap, font size and every word's `x/y` are
   computed ONCE from the FULL phrase, then frozen. Drawing the first *k* words
   reproduces the head of the finished line — words never recenter or jump as
   they arrive. (`_reveal_fit_fs` locks the size with the static fit rule;
   `_positioned_tokens` freezes positions.)
2. **Replace, not accumulate.** A phrase clears to blank only when the next
   phrase begins — the viewer never reads stale, not-yet/​already-spoken text
   stacked up.
3. **Frame-snapped timeline.** Every reveal-state boundary is rounded to the fps
   grid and durations accumulate in whole frames, so the reveal can't drift
   against the frame-locked picture (same anti-drift discipline as the video
   assembly). Long reels stay in sync to the end.
4. **One lossless alpha overlay.** All per-word states are baked into a SINGLE
   transparent `qtrle` (.mov) track via an `ffconcat` list and composited in one
   `overlay` pass — not ~hundreds of overlays. RLE + `argb` keeps the serif edges
   crisp. (`build_reveal_track` → `overlay_reveal_track`.)

Styling matches the static captions: serif (Georgia), `subtitle` casing
(lowercase, intentional ALL-CAPS + accents kept, no trailing dot), white with a
soft shadow/outline; the breath-group **payoff** is bold-italic.

## Verify
Extract a few frames spanning a phrase and confirm words accrue left→right
without the line shifting, and that the last words land in sync near the reel's
end (where drift would show first):
```bash
ffmpeg -y -ss <t> -i <reel_dir>/final.mp4 -frames:v 1 /tmp/rev_check.png
```

## Files (in the avatar-reel-composer skill)
- `scripts/finish_reel.py`
  - `_event_tokens` — per-word display strings + spoken start times + payoff split.
  - `_reveal_fit_fs` / `_positioned_tokens` — lock font size + freeze full-phrase word positions.
  - `render_reveal_state` — render one state (first *k* words lit).
  - `build_reveal_track` — bake all states into one frame-snapped transparent qtrle track.
  - `overlay_reveal_track` — composite the track over the base video in one pass.
  - `finish(..., caption_reveal="word"|"phrase")` / CLI `--caption-reveal` (default `word`).
- `scripts/compose_reel.py` — passes `finish.caption_reveal` through to `finish()`.

See the [avatar-reel-composer](../avatar-reel-composer/SKILL.md) skill for the
full finishing pass (caption phrasing, emphasis, music, polish).
