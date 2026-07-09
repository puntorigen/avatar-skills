---
name: reel-restyle
description: Analyze ONE avatar's reels and re-apply their style to a DIFFERENT avatar. Distills a script-agnostic reel TEMPLATE from a reference avatar's existing video-scene-analysis (scene/beat sequence, talking-head vs B-roll pattern, per-beat camera angle, cut/zoom transitions, SFX placement, caption style and proportional pacing), then applies that template to a NEW avatar given only a picture + a voice sample + a script -- auto-scaffolding the new avatar's camera-angle stills, cloned voice, talking profile and copied caption/transition styles, and drafting a composer-ready storyboard. Use when the user wants to reuse one avatar's reel style/structure (e.g. "make a reel for this new person in lolo's style", "same camera angles, transitions, SFX and timing but a different face/voice/script", cross-avatar style transfer, reel templates).
---

# Reel Restyle (cross-avatar style transfer)

Take a reference avatar that has already been analyzed (e.g. `lolo`, with
`*.analysis.json` + `transition_style.json` + `subtitle_style.json`), capture
the *style and structure* of its reels as a reusable **template**, and re-apply
that template to a **brand-new avatar** supplied as just a **picture + voice
sample + script**.

The new reel reuses the reference's **scene/beat sequence, talking-head vs
B-roll pattern, per-beat camera angle, transitions, SFX placement, caption
style and proportional pacing** -- but with the new avatar's face, location,
cloned voice and a different script. Actual scene **durations** are not copied
(a different script has its own rhythm); they fall out of the new narration's
word alignment, exactly like `avatar-reel-composer`'s single-narration / hard-cut
pipeline.

This skill is an **orchestrator**: it delegates to
[`video-scene-analysis`](../video-scene-analysis/SKILL.md) (already produces the
analysis), [`avatar-camera-angles`](../avatar-camera-angles/SKILL.md),
[`voice-clone`](../voice-clone/SKILL.md) and
[`avatar-reel-composer`](../avatar-reel-composer/SKILL.md).

> **Output location.** `scaffold_avatar.py` creates a bare avatar name under
> `./avatares/<name>/` (so new avatars never clutter the project root); pass an
> explicit path to override, or set `AVATARES_ROOT`.

## Pipeline

```
extract_template.py   reference *.analysis.json (+ style files) -> reel_template.json
        |
apply_template.py  ───┐
        ├─ scaffold_avatar.py   picture + voice -> <new>/{scene.json, angles/, voices/,
        |                        talking_profile.json, transition_style.json, subtitle_style.json}
        |     [AGENT] write scene.json + talking_profile.json from the picture (vision)
        ├─ generate_storyboard.py   template + script -> <new>/<slug>.storyboard.json
        |     [AGENT] refine the text split + AUTHOR each B-roll for the new topic
        └─ avatar-reel-composer/compose_reel.py  --finish  -> final.mp4
```

Two steps need the agent (the orchestrator stops with precise instructions and
resumes on re-run, like `create_avatar.py`):

1. **Describe the new avatar** from its picture: write `scene.json`
   (`subject`/`wardrobe`/`scene`/`light`, per `avatar-camera-angles`) and
   `talking_profile.json` (`video_prompt` for the NEW person -- a different
   identity -- seeded with the template's `delivery_style_seed`).
2. **Refine the storyboard**: tune each `scene.text` split and replace every
   placeholder `TODO` B-roll `broll_description`/`broll_action` with content for
   the new topic.

## Quick start

```bash
# 0) Make sure the reference avatar is analyzed + enriched (run once, per the
#    video-scene-analysis SKILL / create_avatar.py). Then extract the template:
python3 .cursor/skills/reel-restyle/scripts/extract_template.py \
    lolo/videos/2026-06-08_15-02-03.analysis.json --avatar-dir lolo \
    -o lolo/reel_template.json

# 1) Apply it to a new avatar (scaffold + draft storyboard, stops for review):
python3 .cursor/skills/reel-restyle/scripts/apply_template.py mara \
    --template lolo/reel_template.json \
    --picture refs/mara.png --voice samples/mara.wav --script mara_script.txt

#    -> writes mara/scene.json + mara/talking_profile.json checkpoint instructions;
#       after you author those, re-run the same command to generate angles + clone
#       voice + draft mara/<slug>.storyboard.json.

# 2) Review the storyboard (text split + author the TODO B-roll), then compose:
python3 .cursor/skills/reel-restyle/scripts/apply_template.py mara \
    --template lolo/reel_template.json \
    --picture refs/mara.png --voice samples/mara.wav --script mara_script.txt \
    --compose --finish

# Inspect readiness at any time:
python3 .cursor/skills/reel-restyle/scripts/apply_template.py mara \
    --template lolo/reel_template.json --status
```

You can also run the steps individually (`extract_template.py`,
`scaffold_avatar.py`, `generate_storyboard.py`, then `compose_reel.py`).

## What transfers vs. what is authored fresh

| Transfers from the reference (template) | Authored fresh for the new reel |
|---|---|
| Beat count + talking-head/B-roll sequence | The script (verbatim narration) |
| Per-beat camera angle + framing -> new avatar's angle stills | The new avatar's identity (`scene.json`, `talking_profile.json`) |
| Per-beat motion / `zoom_from_previous` + emphasis | B-roll **content** (`broll_description`/`broll_action`) per beat |
| Transition style (`transition_style.json`) | Music prompt (mood transfers; tailor the prompt) |
| SFX placement + density | Exact scene durations (derived from the new narration) |
| Caption style (`subtitle_style.json`) + proportional pacing (`dur_weight`) | The semantic text split across beats (draft is proportional; refine it) |

## Requirements

The reference avatar must already be **analyzed and enriched** by
`video-scene-analysis` (talking-head scenes need `camera.angle`; the reel needs
an `avatar_profile`). Install the sibling skills' requirements (see
[scripts/requirements.txt](scripts/requirements.txt)). Generation costs apply
(gpt-image-2 for angles, MiniMax for voice/TTS, p-video for talking-head + B-roll).

See [REFERENCE.md](REFERENCE.md) for the `reel_template.json` schema, the camera
angle mapping table, the scaffold stage machine and the storyboard contract.
