---
name: broll-story
description: >-
  Generate a SILENT B-roll clip of an existing avatar (and optional invented
  side-characters) DOING a demonstrative activity — not a talking head, no
  lip-sync — for an avatar reel. Given a short script, the avatar's reference
  image and the reel ratio (9:16 or 16:9), it authors ONE 6-panel storyboard
  sheet with the gpt-image-2 skill and animates that single sheet into an 8s
  720p MUTED video with the seedance-2 skill. The avatar's voice is added later
  as voice-over by avatar-reel-composer (broll_source: existing), so these
  segments are intentionally silent and focus on what the avatar is DOING (POV,
  seen from behind, cooking, building, interacting with other characters), not on
  dialogue. Use when the user wants an avatar action/demonstration B-roll, a
  non-talking-head avatar scene, a "show don't tell" avatar sequence, or to
  animate the avatar doing an activity for a reel.
---

# B-roll Story (avatar doing an activity)

The **action / demonstration** counterpart of the broll skills. Where
`broll-generator` synthesizes presenter-free B-roll and `broll-finder` finds real
footage, **`broll-story` puts OUR avatar on screen DOING something** — a silent,
voice-over-ready clip where the focus is the *action*, not the dialogue (the
avatar may be speaking, but it's off-screen narration, so there is **no
lip-sync**). Think ALF grabbing the camcorder, or a full-body shot of the
presenter showing a place, taking calls and scheduling on screen, seen from
behind, cooking, building — optionally interacting with invented side-characters.

It is an **orchestrator** over two existing skills:
`gpt-image-2` (one storyboard sheet) → `seedance-2` (animate it) → muted clip.

## Inputs (gather what's missing)
| Input | Used for |
|---|---|
| **Short script** | the beat/idea of the activity (the avatar's VO, added later) |
| **Avatar reference image** | character DNA (`--avatar-ref`, 1–3 images) |
| **Ratio** | `9:16` (default) or `16:9` — sets the storyboard grid + the video ratio |

## Prerequisites
- **gpt-image-2** ready (shared Replicate token) — produces the sheet.
- **higgsfield CLI** installed + authenticated with credits (`higgsfield account status`) — runs seedance.
- **ffmpeg** on PATH — mutes the clip.

## Pipeline
```
short script + avatar ref + ratio
  │
1 AGENT authors the Phase-1 storyboard prompt (6 panels) following gpt-image-2's
  │      prompts/storyboard_framework.md — adapted to broll-story, NOT simplified
  │      -> <slug>.board.txt
  │
2 make_broll_story.py:
  │   gpt-image-2 generate_image.py  -> ONE 6-panel storyboard sheet (the ratio's grid)
  │   seedance-2  (baseline storyboard→movie prompt via prompt_tools.py, verbatim)
  │               -> 8s 720p video, same ratio
  │   ffmpeg -an  -> MUTED clip in <avatar>/broll/story/<NNN>_<slug>.mp4 + manifest.json
  │
3 hand off to avatar-reel-composer as a broll scene (broll_source: existing)
```

## Hard rules (do not break)
- **6 panels, ONE storyboard image.** A single composite sheet for the requested
  ratio (16:9 → 3 columns × 2 rows; 9:16 → 2 columns × 3 rows).
- **Follow the baseline prompts verbatim, do NOT simplify them.** Author the
  storyboard image prompt by following gpt-image-2's storyboard framework
  (`~/.cursor/skills/gpt-image-2/prompts/storyboard_framework.md`, sections
  A–H). The seedance animation prompt is the baseline
  storyboard→movie one-liner produced by `prompt_tools.py storyboard` — the
  script uses it as-is. *"no simplifiques los baseline prompts."*
- **Do not tie the panels to 8 seconds.** *"no necesitas especificar en la imagen
  del storyboard que los paneles deban calzar en 8 segundos, eso lo determina el
  skill automáticamente … preocúpate que la historia esté bien representada en la
  imagen y no de su duración especificada."* The storyboard may carry the
  framework's own timecodes (even 15s/30s); seedance compresses the whole board
  into the requested 8s. Representing the story well in the 6 panels matters;
  the storyboard's stated duration does not.
- **Silent output, no audio requests.** *"No le pidas a seedance-2 sonidos ni
  voces específicas porque el resultado estará muteado."* The clip is muted; the
  avatar's voice is laid on later as voice-over by `avatar-reel-composer`.
- **No lip-sync / no talking-head.** Seedance cannot lip-sync without an audio
  reference, and these segments are not about what is said — write panels around
  what the avatar is **DOING** (action, blocking, camera changes), not dialogue.

## Workflow

### 1 — Author the storyboard prompt (the creative step)
Follow gpt-image-2's storyboard framework (Phase 1, sections A–H), **not
simplified**, adapted to broll-story:
- **Subject:** the avatar performing ONE activity across 6 beats (setup → do the
  thing → a small turn/interaction → result). Drive every panel with **action**,
  not dialogue.
- **Character DNA:** describe the avatar from `--avatar-ref` and demand identical
  identity/wardrobe across all panels. Invented side-characters are welcome — give
  each a distinct, consistent description.
- **Shot variety (this is the point):** first-person / POV, over-the-shoulder,
  from behind, full-body wide showing the whole action, inserts/close-ups of what
  the hands do, camera changes between panels. Never a centered talking-head.
- **Grid for 6 panels:** `16:9` → 3×2; `9:16` → 2×3 (flip the grid for vertical,
  per the framework).
- Save the prompt to `<slug>.board.txt`. See [REFERENCE.md](REFERENCE.md) for a
  broll-story Phase-1 template and worked examples.

### 2 — Generate + animate + mute (the mechanical step)
```bash
python3 .cursor/skills/broll-story/scripts/make_broll_story.py \
  --prompt-file <slug>.board.txt \
  --avatar-ref <avatar>/refs/<hero>.png \
  --ratio 9:16 --slug <slug> --avatar-dir <avatar> \
  --script "the short VO line for this beat (manifest only)"
```
It writes `<avatar>/broll/story/<NNN>_<slug>.mp4` (muted) + a `manifest.json`
entry and prints a JSON summary. Useful flags: `--sheet PATH` (reuse an existing
sheet, skip image gen), `--resolution`, `--duration` (default 8), `--panels 1-3`
(animate a sub-range), `--keep-audio` (rare). QA the printed `sheet` before
trusting the clip; re-author the prompt and re-run if a panel is off.

### 3 — Hand off to avatar-reel-composer
Drop the clip into a storyboard `broll` scene; the composer lays the avatar's
single master narration over it in sync:
```json
{ "id": "s3", "type": "broll", "broll_source": "existing",
  "broll_clip": "doki-monster/broll/story/001_doki-show-office.mp4",
  "text": "the contiguous slice of the narration spoken over this beat" }
```

## Notes / troubleshooting
- **Story longer than one clip?** Seedance is ≤15s and best ≤8s. For a longer
  beat, make ONE sheet and animate it once at 8s; if a sequence truly needs more
  time, split the script into two broll-story calls (two sheets) rather than one
  long clip.
- **`ip_detected` / blocked** — a photoreal human face in the sheet can trip
  seedance. Keep invented side-characters stylized to match the avatar; re-run.
- **`Session expired` / out of credits** — `higgsfield auth login` / top up, then
  re-run (the sheet is cached in the work folder; pass `--sheet` to skip image gen).

## Additional resources
- broll-story Phase-1 template, per-ratio grids, examples: [REFERENCE.md](REFERENCE.md)
- gpt-image-2 storyboard framework (verbatim baseline): `~/.cursor/skills/gpt-image-2/prompts/storyboard_framework.md`
- seedance-2 storyboard→video framework + baseline one-liner: `~/.cursor/skills/seedance-2/prompts/storyboard_video_framework.md`
- Consumer: `avatar-reel-composer` (`broll_source: existing`). Siblings: `broll-generator` (synthetic, presenter-free), `broll-finder` (real footage).
