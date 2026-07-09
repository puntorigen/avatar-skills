---
name: bg-music
description: Generate background music tracks for social media posts, presentations, reels, and app content using ElevenLabs Music on Replicate. Supports emotional mood presets (uplifting, calm, dramatic, playful, etc.), configurable duration (up to 5 minutes), multiple output formats (MP3/WAV), and fade-in/fade-out. Use when the user asks to generate, create, or produce background music, BGM, backing tracks, mood music, or any musical audio content for posts, reels, presentations, or videos.
---

# Background Music Generator

Generate production-ready background music for social media posts, presentations, reels, and in-app content using ElevenLabs Music on Replicate.

## Setup

Install dependencies (one-time):

```bash
pip3 install -r ~/.cursor/skills/bg-music/scripts/requirements.txt
```

Set your Replicate API token (skipped if already configured by another skill):

```bash
python3 ~/.cursor/skills/bg-music/scripts/setup_key.py YOUR_REPLICATE_API_TOKEN
```

## Quick Reference

### Generate background music

```bash
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "gentle piano melody for a pet care post" \
  --mood calm --duration 30 --output bgm_calm.mp3
```

### Prompt enhancement (default)

The script auto-enhances your description into an optimal prompt for ElevenLabs Music. Use `--raw-prompt` to skip:

```bash
# Enhanced (default)
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "upbeat happy vibe" -m uplifting -d 30 -o happy.mp3

# Raw: use your prompt verbatim
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "Lo-fi hip hop beat, warm vinyl texture, 85 BPM, C major" \
  --raw-prompt -d 45 -o lofi.mp3
```

### Generate variations

```bash
# Same mood, different results
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "warm acoustic background" \
  -m heartfelt -d 30 -n 3 -o acoustic.mp3
# Generates: acoustic_1.mp3, acoustic_2.mp3, acoustic_3.mp3
```

### Choose output format

```bash
# High-quality MP3
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "epic cinematic track" \
  -m epic -d 30 -f mp3_high_quality -o epic.mp3

# CD-quality WAV
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "ambient meditation pad" \
  -m calm -d 60 -f wav_cd_quality -o ambient.wav
```

## generate_bgm.py Options

| Option | Short | Description |
|--------|-------|-------------|
| `--mood MOOD` | `-m` | Emotional mood preset (see below) |
| `--duration SECS` | `-d` | Duration in seconds (5-300, default: 30) |
| `--output PATH` | `-o` | Output file path (default: auto-named) |
| `--variations N` | `-n` | Number of variations to generate (1-5) |
| `--output-format FMT` | `-f` | Audio format (default: mp3_standard) |
| `--raw-prompt` | | Use prompt as-is, skip enhancement |
| `--fade-in MS` | | Fade-in duration in ms (default: 500) |
| `--fade-out MS` | | Fade-out duration in ms (default: 1500) |
| `--no-fade` | | Disable fade-in/fade-out |
| `--bpm INT` | | Suggest BPM in the prompt (optional, mood has defaults) |
| `--key KEY` | | Suggest musical key (e.g. "C major", "A minor") |
| `--list-moods` | | Show all available mood presets |

### Output Formats

| Format | Quality | Best For |
|--------|---------|----------|
| `mp3_standard` | 128kbps MP3 | Social media, general use (default) |
| `mp3_high_quality` | 192kbps MP3 | Higher quality, still compact |
| `wav_16khz` | 16kHz WAV | Voice-focused content |
| `wav_22khz` | 22kHz WAV | Medium quality WAV |
| `wav_24khz` | 24kHz WAV | Good quality WAV |
| `wav_cd_quality` | 44.1kHz WAV | Uncompressed CD quality |

## Mood Presets

| Mood | Best For | Default Dur. | Character |
|------|----------|-------------|-----------|
| `uplifting` | Success stories, achievements, celebrations | 30s | Bright, optimistic, major key |
| `calm` | Wellness tips, mindful moments, care routines | 30s | Gentle, ambient, soothing |
| `playful` | Fun pet content, games, lighthearted posts | 20s | Bouncy, cheerful, quirky |
| `heartfelt` | Adoption stories, bonds, emotional moments | 30s | Warm, acoustic, intimate |
| `dramatic` | Transformations, reveals, before/after | 20s | Building tension, cinematic |
| `confident` | Tips, expertise, professional advice | 25s | Steady, assured, modern |
| `nostalgic` | Memories, throwbacks, reflection | 30s | Warm, vintage, soft |
| `energetic` | Fitness, active pets, outdoor adventures | 25s | Driving, uptempo, powerful |
| `mysterious` | Teasers, coming soon, curiosity hooks | 20s | Suspenseful, textural, dark |
| `inspiring` | Milestones, growth, motivational content | 30s | Soaring, orchestral, hopeful |
| `cozy` | Home life, comfort, seasonal content | 30s | Lo-fi, warm, intimate |
| `epic` | Big announcements, launches, hero moments | 25s | Cinematic, powerful, layered |
| `tender` | Gentle care, lullabies, quiet moments | 30s | Delicate, piano, strings |
| `corporate` | Presentations, pitch decks, demos | 30s | Clean, modern, understated |
| `generic` | General purpose (default) | 30s | Neutral, versatile |

Moods are defined in `scripts/moods.json` and can be customized.

## Common Workflows

### Background music for social media posts

```bash
# Happy pet content
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "cheerful background for a dog playing at the park" \
  -m playful -d 20 -o assets/bgm/dog_park.mp3

# Heartfelt adoption story
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "emotional piano for pet adoption story" \
  -m heartfelt -d 30 -o assets/bgm/adoption_story.mp3
```

### Presentation backing track

```bash
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "clean modern background for tech presentation" \
  -m corporate -d 60 --fade-out 3000 -o assets/bgm/presentation.mp3
```

### Reel / short-form video music

```bash
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "trendy upbeat track for instagram reel" \
  -m energetic -d 15 --bpm 120 -o assets/bgm/reel_beat.mp3
```

### Long-form content (up to 5 minutes)

```bash
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "ambient background for a meditation session" \
  -m calm -d 300 -f wav_cd_quality -o assets/bgm/meditation.wav
```

### Try different styles for the same concept

```bash
# Generate 3 variations, pick your favourite
python3 ~/.cursor/skills/bg-music/scripts/generate_bgm.py "warm acoustic guitar background" \
  -m heartfelt -d 30 -n 3 -o assets/bgm/acoustic.mp3
```

## Fade-In / Fade-Out

Background music tracks benefit from smooth fades. By default:
- **Fade-in**: 500ms gentle ramp
- **Fade-out**: 1500ms smooth tail

Use `--fade-in` and `--fade-out` to customize (in ms), or `--no-fade` to disable.

Fades are applied via ffmpeg after generation -- the model generates the full track, then fades are applied as post-processing.

## Model

Uses **ElevenLabs Music** (`elevenlabs/music`) on Replicate -- studio-grade music generation with:

- Text-to-music from natural language prompts
- Instrumental-only mode (enabled by default for background music)
- Up to 5 minutes of audio per generation
- Multiple output formats (MP3 and WAV at various quality levels)
- Commercial use license

Pricing: ~$8.30 per 1000 seconds of output audio (~120 seconds for $1).

## Prompt Enhancement

Enhancement adds musical descriptors to improve results:

1. Injects mood-specific style keywords (tempo, instruments, tonality)
2. Adds production quality descriptors (mixed, mastered, professional)
3. Suggests BPM range when appropriate
4. Adds "background music" / "instrumental" framing
5. Keeps your core description intact

## Configuration

Config at `~/.cursor/skills/bg-music/config.json`:

```json
{
  "replicate_api_token": "YOUR_TOKEN",
  "default_mood": "generic",
  "default_duration": 30,
  "default_output_format": "mp3_standard"
}
```

Falls back to tokens from `sound-effects`, `avatar-video-reel`, or `brand-asset-studio` skills.
