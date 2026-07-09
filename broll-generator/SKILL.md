---
name: broll-generator
description: Generate hyper-realistic complementary B-roll video clips (3-6s) from a scene description using Pruna p-video on Replicate, with NO main character — only people, objects and situations that reinforce an idea. Clips are vertical 9:16 at 720p by default and silent (clean for voice-over), so an avatar's narration can be laid on top in a composite reel. Use when the user wants to create B-roll, inserts, cutaways, complementary footage, or realistic supporting clips for a talking-head/avatar video or reel.
---

# B-roll Generator

Generate short, hyper-realistic **complementary B-roll** clips with **Pruna's `p-video`** model on Replicate. The clips show only the people / objects / environments you describe — the main presenter/avatar never appears — so they can play under an avatar voice-over in a final composite (like the inserts used in the original `lolo` reels).

This is the visual counterpart to the `avatar-talking-video` skill: that one renders the talking head, this one renders the cutaways that reinforce what's being said.

## Setup

Uses the same Replicate token as the other Replicate-based skills (`avatar-talking-video`, `voice-clone`, `gpt-image-2`, ...). If any of those is configured, this skill finds the token automatically.

```bash
pip3 install -r ~/.cursor/skills/broll-generator/scripts/requirements.txt
# Only if no sibling skill has a token yet:
python3 ~/.cursor/skills/broll-generator/scripts/setup_key.py YOUR_REPLICATE_API_TOKEN
```

`ffmpeg`/`ffprobe` are used to normalize to the exact length and strip audio (recommended, but the skill degrades gracefully without them).

## Quick start

```bash
python3 ~/.cursor/skills/broll-generator/scripts/generate_broll.py \
  "manos sosteniendo un smartphone en penumbra, revisando el Instagram de un ex de noche, primer plano, foco selectivo" \
  --duration 6 --camera push_in --avatar-dir /Users/.../virtual-avatar/lolo
```

Output: `<avatar>/broll/<NNN>_<slug>.mp4` plus a `manifest.json` entry. A JSON summary (saved path + metadata) is printed to stdout for use by an orchestrating skill.

## How it works

1. **Prompt wrapping** — your scene description is wrapped in a photoreal/cinematic style block, a **camera move** (`--camera`) plus a "whole frame stays in motion" clause, and an explicit "the presenter does NOT appear / no on-screen text" instruction (skip with `--raw-prompt`). This fights the **static/frozen-background look** that makes AI B-roll feel fake. `p-video` has no negative-prompt field, so these constraints live in the positive prompt.
2. **Generate** — `prunaai/p-video` renders text-to-video at the **exact** requested duration (1–20s), 720p/1080p. `save_audio` is off for clean B-roll.
3. **Normalize** — the clip is trimmed to the exact duration and audio stripped via ffmpeg (best-effort).
4. **Manifest** — every clip is recorded with its description, prompt, camera, model, dimensions and seed.

## Making B-roll look believable

The biggest realism win is **camera motion** — without it, `p-video` tends to animate only the subject over a static background. Always pick a `--camera`:

- `push_in` / `pull_out` — classic reel inserts; the whole frame travels.
- `pan_left` / `pan_right` — good for landscapes, windows, walking subjects.
- `orbit` — wraps around a subject (objects, a person at a table).
- `handheld` (default) — organic drift + micro-shake for documentary feel.
- `static` — only when you genuinely want a locked tripod (scene still kept alive).

Describe **subject + action + framing + lighting/mood**, one concrete situation per clip (Spanish works well). Avoid naming the presenter or any real person.

**Avoid the "mannequin" look (people who don't move/talk).** Text-to-video freezes people into stiff poses unless you give them explicit, continuous performance. For any clip with people interacting, pass `--action` with vivid verbs — gestures, who points/turns/steps, and (for conversations) that **their mouths move as they speak**:

```bash
python3 .../generate_broll.py \
  "una mujer y un hombre discutiendo en la sala de una casa, luz natural fría, plano medio" \
  --duration 6 --camera handheld \
  --action "ambos discuten hablando con vehemencia, las bocas se mueven al hablar; ella gesticula con las manos, señala y sacude la cabeza; él levanta las manos y se gira; intercambian miradas de enojo, postura tensa en movimiento constante"
```

## Key options

| Flag | Default | Notes |
|------|---------|-------|
| `--duration N` | `6` | Exact seconds (1–20; use **3** or **6** for inserts). |
| `--aspect-ratio` | `9:16` | `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`, `1:1`. |
| `--resolution` | `720p` | `720p` or `1080p`. |
| `--fps` | `24` | `24` or `48`. |
| `--camera` | `handheld` | `handheld`, `push_in`, `pull_out`, `pan_left`, `pan_right`, `orbit`, `static`. |
| `--action TEXT` | – | Explicit performance for people (gestures, talking, reactions). Fixes the "mannequin" look. |
| `--seed N` | – | Reproducible generations. |
| `--draft` | off | Fast, lower-quality preview for iterating on the prompt. |
| `--no-upsample` | off | Disable p-video prompt upsampling (honor the prompt verbatim). |
| `--keep-audio` | off | Keep generated audio (stripped by default for clean B-roll). |
| `--raw-prompt` | off | Use the description verbatim (no realism/camera wrapper). |
| `--avatar-dir PATH` | – | Save to `<avatar>/broll/`. |
| `--out-dir PATH` | `./broll` | Explicit output folder. |

## Typical workflow (reel composite)

1. Analyze a reference reel with `video-scene-analysis` to get the per-scene focus, emotion and B-roll descriptions.
2. For each B-roll scene, write a scene description + camera move and call this skill (match the scene's `--duration`).
3. Render the talking-head segments with `avatar-talking-video`.
4. A higher-level composite skill stitches talking-head + B-roll under the avatar voice-over.

## Notes

- `p-video` supports any 1–20s duration, so 3s and 6s are produced natively (no padding/retiming).
- Audio is stripped by default so clips are clean for the avatar voice-over; pass `--keep-audio` to keep it.
- Use `--draft` to iterate cheaply on a prompt, then re-run without it for the final clip.
- Generation is a long-running operation (~30s–2min per clip).
