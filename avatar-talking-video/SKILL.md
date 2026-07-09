---
name: avatar-talking-video
description: >-
  Generate a talking-head avatar video from a line of text. Stage 1 synthesizes
  the text in the avatar's cloned voice via the voice-clone skill (reusing the
  avatar's trained voice, or training one from a source recording if it has
  none). Stage 2 feeds a camera-angle image (from avatar-camera-angles) plus the
  generated mp3 to prunaai/p-video-avatar on Replicate at 720p (or 1080p) and
  saves the lip-synced MP4 under <avatar>/generated-videos/ with a manifest.json.
  Use when the user wants a talking avatar / talking-head video, a lip-synced
  clip of an avatar saying some text, to animate a camera-angle still into a
  speaking video, or mentions "video del avatar hablando", "avatar que hable",
  "talking head", "lip sync", or p-video-avatar.
---

# Avatar Talking Video

Turn **text → a lip-synced talking-head video** of an avatar, in two stages:

1. **Voice (TTS).** Delegates to the [`voice-clone`](../voice-clone/SKILL.md)
   skill to speak the text in the avatar's cloned voice. It reuses the avatar's
   already-trained voice, or trains one from `--source` if the avatar has none.
2. **Video (lip-sync).** Sends a **camera-angle image** (`image`, from the
   [`avatar-camera-angles`](../avatar-camera-angles/SKILL.md) skill) plus the
   generated **mp3** (`audio`) to **`prunaai/p-video-avatar`** on Replicate. When
   `audio` is supplied it drives the speech directly (the model's own voice
   settings are ignored), so lip-sync follows the cloned voice exactly.

Output lands in `<avatar>/generated-videos/` with a `manifest.json` recording
the text, voice, image, audio, and video params.

## Requirements

- `pip3 install -r requirements.txt` (Replicate client). The `voice-clone` skill
  must be installed (its TTS does stage 1); install its requirements too.
- A Replicate API token, **shared** with the other Replicate skills (voice-clone,
  gpt-image-2, avatar-video-reel, …) and discovered automatically. To set/refresh:
  `python3 scripts/setup_key.py YOUR_REPLICATE_API_TOKEN`.

## Inputs you need

- **An avatar folder** (e.g. `lolo/`) — the one containing a `videos/` dir. It is
  auto-inferred from `--image`/`--audio`, or pass `--avatar-dir`.
- **A camera-angle image** — produce it first with `avatar-camera-angles`
  (a front-ish, clean portrait works best). Pass it with `--image`. If omitted,
  `<avatar>/frames/frame_0001.png` is used.
- **The text to say** (positional or `--text-file`). The avatar must have a
  trained voice, or pass `--source` so stage 1 trains one first.

## Usage

```bash
# Text -> cloned-voice audio -> talking-head video, from a camera angle
python3 scripts/generate_video.py "Hola, soy Lolo y te cuento algo." \
  --image lolo/angles/skill_test/lolo_push_in.png

# 1080p + happy delivery + a custom visual prompt
python3 scripts/generate_video.py "Big news today!" \
  --image lolo/angles/skill_test/lolo_push_in.png \
  --resolution 1080p --emotion happy \
  --video-prompt "The person is talking and smiling warmly."

# Reuse an existing mp3 (skip TTS) — just lip-sync it to the angle
python3 scripts/generate_video.py \
  --audio lolo/generated-audios/001_hola.mp3 \
  --image lolo/angles/skill_test/lolo_push_in.png

# Avatar has no voice yet: train it first from a clean voice clip
python3 scripts/generate_video.py "Hello there" \
  --image lolo/angles/skill_test/lolo_push_in.png \
  --source lolo/videos/2026-05-16_12-25-46_voice/voice_concat.mp3
```

## Key options

| Option | Default | Description |
|---|---|---|
| `text` / `--text-file` | — | What the avatar says (drives stage-1 TTS). |
| `--audio PATH` | — | Use this mp3/wav directly and **skip** TTS. |
| `--image PATH` | `<avatar>/frames/frame_0001.png` | Camera-angle / portrait image (`image` input). |
| `--avatar-dir` | auto | Avatar folder (else inferred from `--image`/`--audio`). |
| `--resolution` | `720p` | `720p` or `1080p` (1080p ≈ 2× the cost). |
| `--video-prompt` | `The person is talking.` | What the person is doing while speaking. |
| `--emotion` | `auto` | TTS delivery (forwarded to voice-clone). |
| `--language-boost` | `detect` | TTS language (auto-detected; forwarded). |
| `--voice-id` / `--name` / `--source` | — | Pick / train the voice (forwarded to voice-clone). |
| `--negative-prompt` | — | What to avoid (e.g. `subtitles, text, watermark`). |
| `--seed` | — | Reproducible generation. |
| `--disable-prompt-upsampling` | off | Use `--video-prompt` verbatim. |

## Output (in `<avatar>/generated-videos/`)

| File | What it is |
|------|------------|
| `<NNN>_<slug>.mp4` | The talking-head video (auto-numbered) |
| `manifest.json` | `items[]` mapping each video → `text`, `voice_id`, `image`, `audio`, `resolution`, `video_prompt`, and the rest of the params |

Stage 1 also leaves the generated audio in `<avatar>/generated-audios/` (the
voice-clone skill's own output). Report the video path, the `voice_id` used, and
the resolution when done.

## Notes

- **`audio` overrides voice settings.** Because we always pass `audio`, the
  model's `voice` / `voice_script` / `voice_language` inputs are intentionally
  unused — lip-sync follows the cloned-voice mp3.
- **Cost** is per second of output: 720p ≈ $0.025/s, 1080p ≈ $0.045/s.
- **Image quality matters.** A clean, front-ish angle preserves identity best;
  heavy angles or occlusion hurt lip-sync and likeness.
- **Per-shot reels:** generate several angles with `avatar-camera-angles`, run
  this skill once per angle with the same text/voice, then stitch the clips.

## Related skills

- [`voice-clone`](../voice-clone/SKILL.md) — stage-1 TTS / voice training.
- [`avatar-camera-angles`](../avatar-camera-angles/SKILL.md) — produce the `image` input.
- [`avatar-frames`](../avatar-frames/SKILL.md) — extract a clean reference frame.
