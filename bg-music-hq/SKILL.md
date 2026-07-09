---
name: bg-music-hq
description: Generate high-quality background music and jingles using MiniMax Music 2.5 on Replicate. Supports structure tags, lyrics, 27 mood presets including pet-content moods (pet-playful, pet-heartfelt, pet-adventure, pet-chill, pet-regal, pet-goofy, pet-transformation, pet-daily, pet-epic, pet-lullaby, pet-trendy) plus presentation/podcast moods. Configurable sample rate/bitrate, WAV output for production, and fade-in/fade-out. Ideal for presentations, podcast jingles, keynote backing tracks, branded per-pet social media music, reel background tracks, and professional audio content. Use when the user asks to generate high-quality music, presentation music, podcast jingles, keynote tracks, pet-branded background music, reel music for pets, or any professional-grade musical audio content.
---

# Background Music HQ Generator

Generate production-grade background music for presentations, podcast jingles, keynotes, branded per-pet social media tracks, and professional content using **MiniMax Music 2.5** on Replicate.

This skill is the high-quality counterpart to `bg-music`. While `bg-music` uses Stable Audio 2.5 for quick, lightweight tracks (up to 90s), this skill uses MiniMax Music 2.5 which produces longer, richer, studio-quality tracks with proper song structure, style-aware mixing, and support for 100+ instruments.

It includes 11 pet-specific mood presets designed for social media content — from playful zoomie reels to heartfelt adoption stories to epic slow-mo showcases — making it ideal for pre-generating branded background music per pet.

## When to Use This vs bg-music

| Feature | bg-music (Stable Audio) | bg-music-hq (MiniMax Music 2.5) |
|---|---|---|
| Max duration | 90 seconds | ~5 minutes |
| Quality | Good for social media | Studio / broadcast quality |
| Structure control | None | 14 structure tags |
| Style-aware mixing | No | Yes (genre-adaptive) |
| Lyrics / Vocals | No | Yes (optional) |
| Instrument library | Limited | 100+ instruments |
| Speed | ~10s per track | 1-3 min per track |
| Best for | Quick social posts | Presentations, podcasts, branded pet music, reels |

## Setup

Install dependencies (one-time):

```bash
pip3 install -r ~/.cursor/skills/bg-music-hq/scripts/requirements.txt
```

Set your Replicate API token (skipped if already configured by another skill):

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/setup_key.py YOUR_REPLICATE_API_TOKEN
```

Or auto-import from an existing skill:

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/setup_key.py
```

## Quick Reference

### Generate presentation background music

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "clean modern background for tech startup pitch" \
  --mood presentation --output presentation_bgm.mp3
```

### Generate a podcast intro jingle

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "catchy upbeat podcast opener" \
  --mood podcast-intro --output podcast_intro.mp3
```

### Generate a keynote backing track

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "inspiring cinematic build for product launch keynote" \
  --mood keynote --output keynote_music.mp3
```

### Generate with custom lyrics and vocals

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  --lyrics lyrics.txt \
  --prompt "Indie folk, warm, acoustic guitar, male vocals" \
  --with-vocals --output song.mp3
```

### Generate high-quality WAV for production

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "orchestral background for documentary" \
  --mood cinematic --format wav --output documentary_score.wav
```

### Generate variations

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "smooth jazz for podcast bed" \
  --mood podcast-bed --variations 3 --output podcast_bed.mp3
# Generates: podcast_bed_1.mp3, podcast_bed_2.mp3, podcast_bed_3.mp3
```

## generate_bgm_hq.py Options

| Option | Short | Description |
|--------|-------|-------------|
| `--mood MOOD` | `-m` | Mood preset (see below) |
| `--lyrics PATH` | `-l` | Path to lyrics file with structure tags |
| `--lyrics-text TEXT` | `-L` | Inline lyrics string |
| `--prompt TEXT` | `-p` | Explicit style prompt (overrides description+mood) |
| `--output PATH` | `-o` | Output file path |
| `--duration SECS` | `-d` | Max duration — trims if model output is longer |
| `--variations N` | `-n` | Number of variations to generate (1-5) |
| `--sample-rate HZ` | | Sample rate: 16000, 24000, 32000, 44100 (default) |
| `--bitrate BPS` | | Bitrate: 32000, 64000, 128000, 256000 (default) |
| `--format FMT` | `-f` | Output format: mp3 (default), wav, pcm |
| `--raw-prompt` | | Use description as-is, skip mood enhancement |
| `--with-vocals` | | Allow vocals (requires lyrics with actual words) |
| `--fade-in MS` | | Fade-in duration in ms (default: 500) |
| `--fade-out MS` | | Fade-out duration in ms (default: 2000) |
| `--no-fade` | | Disable fade-in/fade-out |
| `--bpm INT` | | Suggest BPM in the prompt |
| `--key KEY` | | Suggest musical key (e.g. "C major") |
| `--list-moods` | | Show all available mood presets |

## Mood Presets

### Presentation & Podcast Moods

| Mood | Best For | Default Dur. | BPM | Character |
|------|----------|-------------|-----|-----------|
| `presentation` | Slide decks, pitch decks, keynotes | 60s | 90-110 | Clean, modern, understated |
| `podcast-intro` | Podcast episode openers | 15s | 100-120 | Punchy, catchy, bright |
| `podcast-outro` | Podcast episode endings | 15s | 85-100 | Warm, friendly, smooth |
| `podcast-bed` | Narration/interview underscore | 90s | 70-85 | Ambient, minimal, unobtrusive |
| `keynote` | Keynote openings, product reveals | 45s | 95-115 | Cinematic, building, inspiring |
| `pitch-deck` | Startup pitches, investor demos | 60s | 100-115 | Tech-forward, confident, sleek |
| `workshop` | Tutorials, workshops, educational | 60s | 85-100 | Friendly, approachable, light |

### Pet Content & Social Media Moods

| Mood | Best For | Default Dur. | BPM | Character |
|------|----------|-------------|-----|-----------|
| `pet-playful` | Zoomies, fetch, silly moments | 20s | 120-140 | Bouncy, quirky, cheerful |
| `pet-heartfelt` | Adoption stories, bonds, memorials | 30s | 70-90 | Warm, acoustic, emotional |
| `pet-adventure` | Hikes, beach days, road trips | 25s | 115-135 | Driving, sunny, adventurous |
| `pet-chill` | Napping, cuddles, lazy afternoons | 30s | 65-80 | Lo-fi, cozy, dreamy |
| `pet-regal` | Majestic pets, show cats, glamour | 25s | 80-100 | Elegant, sophisticated, classical |
| `pet-goofy` | Derpy moments, fails, meme clips | 15s | 125-150 | Comical, cartoon-like, quirky |
| `pet-transformation` | Grooming glow-ups, rescue reveals | 20s | 90-110 | Tension-build, impactful reveal |
| `pet-daily` | Day-in-the-life, routines, walks | 25s | 95-110 | Easygoing, warm, relatable |
| `pet-epic` | Slow-mo, obstacle courses, talent | 25s | 90-115 | Cinematic, heroic, triumphant |
| `pet-lullaby` | Sleeping pets, puppy bedtime | 30s | 50-65 | Music box, delicate, hushed |
| `pet-trendy` | TikTok/Reels viral content, trends | 20s | 110-130 | Hook-first, catchy, modern |

### General Moods

| Mood | Best For | Default Dur. | BPM | Character |
|------|----------|-------------|-----|-----------|
| `cinematic` | Trailers, dramatic reveals | 45s | 80-100 | Epic, orchestral, powerful |
| `ambient` | Focus, deep work, meditation | 120s | 60-75 | Atmospheric, ethereal, spacious |
| `uplifting` | Success stories, celebrations | 30s | 110-130 | Bright, optimistic, joyful |
| `dramatic` | Reveals, transformations | 30s | 85-105 | Suspenseful, impactful |
| `lofi` | Casual content, study vibes | 60s | 70-85 | Chill, vinyl warmth, relaxed |
| `inspiring` | Milestones, motivational | 45s | 85-105 | Soaring, hopeful, building |
| `news` | News segments, reports, updates | 30s | 95-110 | Broadcast, professional, urgent |
| `jazz` | Interviews, culture content | 60s | 80-100 | Smooth, sophisticated, warm |
| `generic` | All-purpose | 45s | 90-110 | Versatile, balanced, clean |

Moods are defined in `scripts/moods.json` and can be customized.

## Structure Tags

MiniMax Music 2.5 supports 14 structure tags for precise arrangement control. The mood presets include pre-built structure templates, but you can override them with `--lyrics` or `--lyrics-text`:

| Tag | Purpose |
|-----|---------|
| `[Intro]` | Song opening, mood setting |
| `[Verse]` | Story/narrative sections |
| `[Pre Chorus]` | Build-up before chorus |
| `[Chorus]` | Hook/memorable section |
| `[Hook]` | Catchy standalone phrase |
| `[Drop]` | Energy release (EDM) |
| `[Bridge]` | Contrast section |
| `[Solo]` | Instrumental spotlight |
| `[Inst]` | Instrumental section (no vocals) |
| `[Build Up]` | Intensity increase |
| `[Interlude]` | Instrumental breathing space |
| `[Break]` | Rhythmic pause |
| `[Transition]` | Section connector |
| `[Outro]` | Song ending |

For instrumental background music (the default), the script uses `[Inst]` tags with parenthetical instrument directions.

## Common Workflows

### Per-Pet Branded Music (Mascotify)

Pre-generate a branded music library for each pet, matching their personality to a mood:

```bash
# Playful golden retriever — bouncy, fun tracks for zoomie reels
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "bouncy cheerful background for a playful golden retriever puppy" \
  -m pet-playful -d 20 -n 2 -o assets/bgm/pets/max_playful.mp3

# Regal Persian cat — elegant, sophisticated ambiance
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "elegant classical-inspired background for a majestic Persian cat" \
  -m pet-regal -d 25 -o assets/bgm/pets/luna_regal.mp3

# Chill old bulldog — cozy lazy-afternoon vibes
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "warm cozy lo-fi background for a sleepy old bulldog" \
  -m pet-chill -d 30 -o assets/bgm/pets/bruno_chill.mp3

# Energetic border collie — adventure/outdoor tracks
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "driving adventurous background for an energetic border collie on hikes" \
  -m pet-adventure -d 25 -o assets/bgm/pets/rocky_adventure.mp3
```

### Pet Reel Music Library

Generate a complete set of tracks for different reel types:

```bash
# Goofy fail compilation
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "funny quirky background for pet fail compilation" \
  -m pet-goofy -d 15 -o assets/bgm/reels/goofy_fails.mp3

# Grooming transformation / rescue glow-up
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "dramatic build with uplifting reveal for pet grooming transformation" \
  -m pet-transformation -d 20 -o assets/bgm/reels/glow_up.mp3

# Heartfelt adoption story
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "emotional acoustic background for rescue dog adoption journey" \
  -m pet-heartfelt -d 30 -o assets/bgm/reels/adoption_story.mp3

# Trendy viral reel format
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "catchy modern beat for trending pet reel format" \
  -m pet-trendy -d 20 -o assets/bgm/reels/viral_trend.mp3

# Epic slow-mo showcase
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "epic cinematic track for slow-motion dog running on beach" \
  -m pet-epic -d 25 -o assets/bgm/reels/epic_slowmo.mp3

# Day-in-the-life montage
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "warm easygoing track for daily routine pet montage" \
  -m pet-daily -d 25 -o assets/bgm/reels/daily_life.mp3

# Sleeping puppy / bedtime content
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "ultra-soft lullaby for sleeping puppy ASMR content" \
  -m pet-lullaby -d 30 -o assets/bgm/reels/puppy_lullaby.mp3
```

### Presentation backing track

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "clean modern background for a SaaS product demo" \
  -m presentation -o assets/bgm/demo_presentation.mp3
```

### Podcast full set (intro + bed + outro)

```bash
# Intro jingle
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "energetic tech podcast opener" \
  -m podcast-intro -o assets/bgm/podcast_intro.mp3

# Interview bed
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "subtle background for interview conversation" \
  -m podcast-bed -o assets/bgm/podcast_bed.mp3

# Outro
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "warm friendly podcast closing" \
  -m podcast-outro -o assets/bgm/podcast_outro.mp3
```

### Keynote with cinematic build

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "epic cinematic build for startup launch event" \
  -m keynote --bpm 105 --key "D major" -o assets/bgm/launch_keynote.mp3
```

### Custom lyrics with structure

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  --lyrics-text "[Intro]
(Atmospheric synth opening)

[Inst]
(Full arrangement, driving modern beat, synth bass)

[Build Up]
(Rising intensity, layered synths)

[Inst]
(Peak energy, all instruments)

[Outro]
(Gentle fade, reverb tail)" \
  --prompt "Modern electronic, tech-forward, crisp production, 110 BPM" \
  -o assets/bgm/custom_track.mp3
```

### High-quality WAV for video production

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "orchestral score for documentary intro" \
  -m cinematic -f wav --sample-rate 44100 --bitrate 256000 \
  -o assets/bgm/documentary_score.wav
```

### Try different styles for the same concept

```bash
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "warm acoustic background for workshop" \
  -m workshop -n 3 -o assets/bgm/workshop.mp3
# Each variation is unique — the model produces different arrangements each time
```

## Fade-In / Fade-Out

Background music tracks benefit from smooth fades. By default:
- **Fade-in**: 500ms gentle ramp
- **Fade-out**: 2000ms smooth tail

Use `--fade-in` and `--fade-out` to customize (in ms), or `--no-fade` to disable.

Fades are applied via ffmpeg after generation.

## Duration Control

MiniMax Music 2.5 generates variable-length tracks (typically 2:30 to 4:30). Use `--duration` to trim the output to a maximum length:

```bash
# Trim to 30 seconds for a short jingle
python3 ~/.cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py \
  "upbeat podcast intro" -m podcast-intro -d 15 -o jingle.mp3
```

Trimming happens before fades are applied, so the fade-out is always clean.

## Model

Uses **MiniMax Music 2.5** (`minimax/music-2.5`) on Replicate.

| Feature | Detail |
|---------|--------|
| Max output | ~5 minutes per generation |
| Sample rates | 16000, 24000, 32000, 44100 Hz |
| Bitrates | 32, 64, 128, 256 kbps |
| Formats | MP3, WAV, PCM |
| Structure tags | 14 section types |
| Instrument library | 100+ instruments |
| Style-aware mixing | Genre-adaptive EQ and effects |
| Generation time | 1-3 minutes per track |

## Prompt Tips

The `prompt` field steers the overall sound. A good prompt follows this pattern:

```
[Genre], [Mood/Emotion], [Tempo], [Key instruments], [Production style]
```

Examples:
- `Corporate pop, clean, modern, 100 BPM, piano and subtle synths, wide soundstage`
- `Smooth jazz, sophisticated, relaxed 85 BPM, walking bass, brushed drums, piano`
- `Cinematic orchestral, inspiring, building, sweeping strings, brass, timpani`
- `Lo-fi hip-hop, chill, vinyl texture, warm midrange, 75 BPM`
- `Electronic, tech-forward, crisp transients, synth bass, 115 BPM`

## Configuration

Config at `~/.cursor/skills/bg-music-hq/config.json`:

```json
{
  "replicate_api_token": "YOUR_TOKEN",
  "default_mood": "presentation",
  "default_sample_rate": 44100,
  "default_bitrate": 256000,
  "default_format": "mp3"
}
```

Falls back to tokens from `bg-music`, `sound-effects`, `avatar-video-reel`, or `brand-asset-studio` skills.
