---
name: sound-effects
description: Generate consistent sound effects and short audio assets for mobile/web apps using Stable Audio 2.5 on Replicate. Supports UI sounds, notifications, game SFX, ambient loops, transitions, and more. Automatically enhances prompts for professional-quality results. Use when the user asks to generate, create, or produce sound effects, audio assets, UI sounds, notification tones, or any short audio content for their app.
---

# Sound Effects Generator

Generate production-ready sound effects for mobile and web apps using Stable Audio 2.5 on Replicate.

## Setup

Install dependencies (one-time):

```bash
pip3 install -r ~/.cursor/skills/sound-effects/scripts/requirements.txt
```

Set your Replicate API token (one-time — skipped if already configured by another skill):

```bash
python3 ~/.cursor/skills/sound-effects/scripts/setup_key.py YOUR_REPLICATE_API_TOKEN
```

## Quick Reference

### Generate a sound effect

```bash
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "button click" \
  --category ui --duration 1 --output click.mp3
```

### Generate with enhanced prompt (default)

The script automatically enhances your description into an optimal prompt for the model. Use `--raw-prompt` to skip enhancement:

```bash
# Enhanced (default): "button click" becomes a detailed audio-engineering prompt
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "button click" -c ui -d 1 -o click.mp3

# Raw: use your prompt verbatim
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "soft digital click, clean, minimal, 44.1kHz" \
  --raw-prompt -d 1 -o click.mp3
```

### Batch generate multiple effects

```bash
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "success chime" \
  --category notification --duration 2 --variations 3 --output success.mp3
# Generates: success_1.mp3, success_2.mp3, success_3.mp3
```

## generate_sfx.py Options

| Option | Short | Description |
|--------|-------|-------------|
| `--category CAT` | `-c` | Sound category preset (see below) |
| `--duration SECS` | `-d` | Duration in seconds (1-90, default: 3) |
| `--output PATH` | `-o` | Output file path (default: auto-named) |
| `--variations N` | `-n` | Number of variations to generate (1-5) |
| `--seed INT` | | Random seed for reproducible results |
| `--steps INT` | | Diffusion steps (default: 8, higher = better but slower) |
| `--cfg-scale FLOAT` | | Guidance scale (default: 3.5, higher = stricter prompt adherence) |
| `--raw-prompt` | | Use prompt as-is, skip enhancement |
| `--trim` / `--no-trim` | | Auto-trim leading/trailing silence (default: on) |
| `--trim-threshold DB` | | Silence detection threshold in dB (default: -35) |
| `--fade-out MS` | | Fade-out applied after trim in ms (default: 20) |
| `--list-categories` | | Show all available categories |

## Sound Categories

| Category | Best For | Gen Duration | Prompt Style |
|----------|----------|-------------|--------------|
| `ui` | Clicks, toggles, swipes, taps | 3s | Clean, digital, minimal |
| `notification` | Alerts, badges, messages | 3s | Tonal, melodic, clear |
| `success` | Completions, achievements, confirmations | 3s | Positive, bright, resolved |
| `error` | Failures, warnings, invalid actions | 3s | Discordant, attention-grabbing |
| `transition` | Screen changes, modals, reveals | 3s | Swoosh, whoosh, smooth |
| `ambient` | Background loops, atmosphere | 20s | Textural, environmental |
| `game` | Power-ups, collectibles, impacts | 3s | Dynamic, punchy, satisfying |
| `voice` | Vocal textures, vocalizations | 3s | Human vocal elements |
| `nature` | Rain, wind, birds, water | 15s | Organic, environmental |
| `mechanical` | Motors, gears, machinery | 3s | Industrial, metallic |
| `musical` | Jingles, stingers, intros | 5s | Melodic, composed |
| `foley` | Footsteps, doors, objects | 3s | Realistic, physical |
| `generic` | General purpose (default) | 3s | Neutral, versatile |

Gen Duration is the minimum passed to the model (`-d` flag). Actual file duration will be shorter after auto-trim strips silence.

Categories are defined in `scripts/categories.json` and can be customized or extended.

## Common Workflows

### Generate a UI sound set for a mobile app

```bash
# Button tap (3s gen → auto-trimmed to ~150ms)
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "button tap" \
  -c ui -o sounds/tap.mp3

# Toggle switch
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "toggle switch on" \
  -c ui -o sounds/toggle_on.mp3

# Back swipe
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "swipe back gesture" \
  -c transition -o sounds/swipe_back.mp3
```

### Generate notification sounds

```bash
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "new message received" \
  -c notification -d 2 -o sounds/message.mp3

python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "task completed successfully" \
  -c success -d 2 -o sounds/complete.mp3

python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "error occurred" \
  -c error -d 1 -o sounds/error.mp3
```

### Generate ambient loops

```bash
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "calm office background" \
  -c ambient -d 30 -o sounds/office_ambient.mp3
```

### Reproducible results with seed

```bash
# Same seed = same output
python3 ~/.cursor/skills/sound-effects/scripts/generate_sfx.py "coin collect" \
  -c game -d 1 --seed 42 -o coin.mp3
```

## Silence Trimming

The model needs at least 3 seconds of generation time to follow prompts well, but many SFX (clicks, taps, pops) are 60-400ms of actual audio followed by silence. By default, `--trim` is enabled and automatically:

1. Detects where actual audio begins and ends using ffmpeg's `silencedetect` filter
2. Trims the file to just the active region (with 10ms padding)
3. Applies a subtle 20ms fade-out for clean tails
4. Overwrites the file in-place

This is especially important for UI micro-interactions where sub-200ms precision matters.

Use `--no-trim` to disable (useful for ambient loops or music that fills the full duration).

### Standalone trimming

The trim tool can also be used independently on any audio file:

```bash
# Trim a single file
python3 ~/.cursor/skills/sound-effects/scripts/trim_silence.py input.mp3 --output trimmed.mp3

# Trim in-place
python3 ~/.cursor/skills/sound-effects/scripts/trim_silence.py input.mp3 --in-place

# Tighter threshold for very quiet sounds
python3 ~/.cursor/skills/sound-effects/scripts/trim_silence.py input.mp3 --threshold -40 --in-place

# Add a longer fade-out
python3 ~/.cursor/skills/sound-effects/scripts/trim_silence.py input.mp3 --fade-out 50 -o smooth.mp3

# Batch process a folder
python3 ~/.cursor/skills/sound-effects/scripts/trim_silence.py sounds/*.mp3 --in-place
```

### trim_silence.py Options

| Option | Short | Description |
|--------|-------|-------------|
| `--output PATH` | `-o` | Output file or directory |
| `--threshold DB` | `-t` | Silence threshold in dB (default: -35, lower = more aggressive) |
| `--min-duration SECS` | | Min silence segment to detect (default: 0.05) |
| `--pad MS` | | Padding around active region in ms (default: 10) |
| `--fade-out MS` | | Fade-out duration in ms (default: 0) |
| `--in-place` | | Overwrite input files |

## Model

This skill uses **Stable Audio 2.5** (`stability-ai/stable-audio-2.5`) on Replicate. Key capabilities:

| Feature | Specification |
|---------|--------------|
| Min Duration | 1 second (3s recommended for quality) |
| Max Duration | 90 seconds |
| Output Format | MP3 |
| Sample Rate | 44.1 kHz |
| Diffusion Steps | Configurable (default 8) |
| CFG Scale | Configurable (default 3.5) |

## Prompt Enhancement

By default, the script enhances your natural-language description into an audio-engineering prompt optimized for Stable Audio 2.5. The enhancement:

1. Adds technical audio descriptors (clean, high-fidelity, 44.1kHz)
2. Injects category-specific style keywords (e.g., "digital, minimal, crisp" for UI sounds)
3. Adds appropriate mood and texture descriptors
4. Keeps the core intent of your description intact

Use `--raw-prompt` to bypass this and send your exact text to the model.

> Note: Stable Audio 2.5 is a *synthesis* model — great for clean UI/abstract/designed sounds, but real-world foley and nature ambiences can sound synthetic. For maximum realism, prefer a real-recording source (e.g. the audio-theater skill's ElevenLabs or Freesound backends).

## Configuration

Config stored at `~/.cursor/skills/sound-effects/config.json`:

```json
{
  "replicate_api_token": "YOUR_TOKEN",
  "default_category": "generic",
  "default_duration": 3,
  "default_steps": 8,
  "default_cfg_scale": 3.5
}
```

The skill also checks for an existing Replicate token in `~/.cursor/skills/avatar-video-reel/config.json` as a fallback, so you may not need to configure it again if you already use that skill.
