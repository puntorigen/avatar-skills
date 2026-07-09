# Cuento Reel — reference

Detailed schemas, the A/V-sync QA check, and troubleshooting. The plan and
storyboard schemas are owned by `avatar-reel-composer` — see its `SKILL.md`
(sections *Storyboard schema* and *Guest / cameo scenes*). This file only adds
the cuento-specific conventions and the lessons baked into the hard rules.

## Why the hard rules exist

### Boundaries pin to assemble offsets (frame-exact A/V)
`compute_boundaries` in `compose_reel.py` snaps cuts to whisper word timings,
which is only approximate. For a multi-segment narration that drift inflates the
narration-scene slots and runs the PICTURE ahead of the AUDIO (≈1s by mid-reel) —
the dialogue then looks out of lip-sync. Fix (already in the composer): when the
master narration came from `assemble_narration` with a **1:1 scene↔segment**
correspondence, it pins EVERY scene boundary to the exact recorded segment
offsets (`assemble_narration.out.json`). So:
- keep `storyboard.scenes` in the SAME order as `plan.segments`, one-to-one;
- use `gap: 0` so each scene's clip equals its audio segment exactly.

### gap = 0
With `gap>0` the audio slot of a guest = `audio_dur + gap`, but the lip-sync clip
is only `audio_dur` long → it falls short by `gap` and everything after drifts.
`compose_reel` prints a warning if it pins offsets while the plan used `gap>0`.

### motion = none (no Ken Burns)
A static frame with a push/zoom reads as fake. Animate the still into real motion
(seedance image-to-video) instead, and set `motion:"none"`. Never put `emphasis`
on a `guest` scene — emphasis bumps motion and would re-introduce a push-in.

### Lip-sync clip A/V (avoid cumulative drift)
A talking clip whose AUDIO stream is slightly longer than its VIDEO stream makes
the composer trim the video short → cumulative drift. If you hand-build clips,
re-mux so audio ≤ video:
```bash
ffmpeg -i in.mp4 -map 0:v:0 -map 0:a:0 -c:v copy -c:a aac -shortest out.mp4
```

## A/V-sync QA check (do this after compose)
Confirm a character cut lands where its line ends (not before/after):
```bash
# read the exact segment end from assemble (e.g. d_eus_5 end = 54.96)
# extract frames around it and compare picture vs the burned subtitle/audio
cd <libro>/<NN_slug>
for t in 54.6 54.8 55.0 55.2; do ffmpeg -y -ss $t -i final.mp4 -frames:v 1 _qa_$t.png -loglevel error; done
```
The frame just BEFORE the boundary should still show the speaking character on
their last word; the frame just AFTER should be the next scene. If the next scene
appears EARLY (while the subtitle is still on the previous line), the picture is
running ahead — re-check `gap:0` and the 1:1 scene/segment order.

Optional: detect big visual cuts and compare to expected boundaries:
```bash
ffmpeg -i final.mp4 -vf "select='gt(scene,0.4)',showinfo" -an -f null - 2>&1 \
  | grep -oE "pts_time:[0-9.]+"
```

## Dialogue clip paths (two options)
- **Own MiniMax voice** → plan `kind:"guest"` (composer auto-generates the clip
  to `<char>/generated-videos/guest_<slug>.mp4`).
- **Specific non-MiniMax voice** (youthful/child voices ElevenLabs blocks):
  `audio-theater` → line `.wav`; lip-sync with `avatar-talking-video --audio`
  onto the character face → clip `.mp4`. Reference that clip as plan
  `kind:"audio"` (`file` = .mp4) AND a storyboard `guest` scene (`broll_clip` =
  same .mp4). Re-mux audio≤video (above) if you see drift.

## Troubleshooting
- **`ip_detected` / blocked in seedance** with photoreal faces → push wording to
  "cinematic realism" (not a clone of a real person); keep invented side-characters
  stylized to match; re-run. Wide shots / silhouettes / body language pass more
  often than distressed child close-ups.
- **Mouth moving on a narration beat** (the character is silent under VO) → in the
  seedance prompt demand the mouth stays SHUT the entire time ("lips pressed
  gently together; never opens the mouth; no jaw/lip movement"); add a downward or
  away gaze so only eyes/head/hair move.
- **Narrator sounds flat** → set `voice.emotion` and drop sparse MiniMax
  interjections (`(sighs)`) / pauses `<#0.6#>` into the narrator text (ignored by
  captions/alignment).
- **Face drifts between clips** → anchor `refs/<char>_hero_master.png` and repeat
  the character DNA verbatim in every broll sheet.
- **higgsfield `Session expired` / out of credits** → `higgsfield auth login` /
  top up; the broll sheet is cached (pass `--sheet` to skip image gen).

## Copyright
Copyright protects expression, not ideas. For a copyrighted source, write 100%
original narration + dialogue inspired by the plot — never reproduce or closely
paraphrase the prose, structure or distinctive wording. Public-domain tales are
free, but modern translations may carry their own copyright; adapt in your own
words. Keep an internal rights note in the series pauta and treat published output
as needing a rights review.
