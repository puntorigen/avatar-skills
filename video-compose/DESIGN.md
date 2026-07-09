# video-compose — Design Spec v0.1

## One-liner
A Cursor skill that turns *(folder of clips + images) + (interactive treatment) + (chosen music)* into a Premiere/VEED-quality composite reel — using a Python+FFmpeg renderer with Remotion title overlays and beat-synced cuts.

## Locked decisions

| Area | Decision |
|---|---|
| Skill name | `video-compose` |
| Tech stack | **Hybrid** — Python+FFmpeg for cuts/transitions/Ken Burns/audio, Remotion only for animated title overlays composited via FFmpeg |
| Voiceover | **None** — script is a structural shot list, music is the only audio |
| Asset analysis | **Medium** — ffprobe + PySceneDetect + per-scene quality scoring (blur, motion, brightness) + Gemini Vision keyframe descriptions |
| Title engine | **Remotion** — 6 props-driven styles, rendered as transparent WebM and composited via FFmpeg |
| Music | **Interactive** — agent proposes 3 moods, user picks, generated via `bg-music-hq` |
| Beat-sync | **v1 feature** — librosa BPM/beats, EDL snaps cut points to beats within tolerance |
| Interaction | **Always interactive** — agent asks questions, drafts shot list, user approves before any rendering. Single approval gate after preview render. |
| Captions | Off by default (cinematic feel; no VO anyway) |
| Treatment input | Brief expansion via interactive Q&A — agent always drafts a shot list with the user before any render |
| Refactor scope | Copy Ken Burns + xfade functions from `avatar-video-reel/scripts/stitch_video.py` into `_video_pipeline.py` (no shared module v1) |
| Remotion location | Inside the skill at `~/.cursor/skills/video-compose/remotion/` (set up once, globally available) |
| Preview format | Low-res 480p MP4 (~15s render), no titles, basic concat |

## The 7-stage pipeline

| Stage | Script | Inputs | Outputs | Interaction |
|---|---|---|---|---|
| 1. Treatment | `treatment.py` | brief / Q&A | `treatment.yaml` (shot list) | Interactive — agent drafts, user approves |
| 2. Asset analysis | `analyze_assets.py` | source folder | `assets.json` | Automated (cached by path+mtime) |
| 3. Music selection | `pick_music.py` | treatment | `bgm.mp3` + `bgm_meta.json` (BPM, beats) | Interactive — user picks 1 of 3 mood options |
| 4. EDL generation | `generate_edl.py` | treatment + assets + bgm_meta | `timeline.json` | Automated (LLM call) |
| 5. Preview | `preview.py` | timeline.json | `preview.mp4` (480p, no titles) | Approval gate |
| 6. Title rendering | `render_titles.py` | timeline.json | `titles/t-NNN.webm` (transparent) | Automated (Remotion, parallel) |
| 7. Final render | `render_final.py` | timeline.json + titles + bgm | `final.mp4` | Automated |

## Data contracts

### `treatment.yaml`
```yaml
goal: "Adoption journey reel for my dog Luna"
tone: "emotional, uplifting, warm"
language: es
format: reel  # reel | post | landscape
target_duration: 30
shots:
  - duration: 4
    description: "Open on Luna's first night — small, unsure moments"
    title: { text: "Día 1", style: "lower_third" }
  - duration: 5
    description: "Bond-building — petting, naps, learning her name"
    title: null
  # ...
```

### `assets.json`
```json
{
  "videos": {
    "videos/clip-001.mp4": {
      "duration": 12.4,
      "fps": 30,
      "resolution": [1920, 1080],
      "scenes": [
        {
          "in": 0.0, "out": 3.2,
          "blur_score": 0.78, "motion_score": 0.34, "brightness": 0.62,
          "dominant_color": "#7a4f2c",
          "description": "Golden retriever puppy lying on a striped blanket, looking up shyly"
        }
      ]
    }
  },
  "images": {
    "images/luna-portrait.jpg": {
      "resolution": [3024, 4032],
      "dominant_color": "#a07a4f",
      "description": "Close-up portrait of golden retriever, soft natural light, intimate"
    }
  },
  "_cache": { "version": 1, "entries": { "<path>": "<sha256-of-mtime+size>" } }
}
```

### `timeline.json` (the EDL)
```json
{
  "version": 1,
  "format": "reel",
  "fps": 30,
  "width": 1080,
  "height": 1920,
  "total_duration": 30.0,
  "tracks": {
    "video": [
      {
        "id": "v1",
        "in_at": 0.00, "out_at": 4.10,
        "source": "videos/clip-001.mp4",
        "src_in": 0.0, "src_out": 3.2,
        "ken_burns": null,
        "transition_in": null
      },
      {
        "id": "v3",
        "in_at": 9.20, "out_at": 13.40,
        "source": "images/luna-portrait.jpg",
        "ken_burns": "push_in",
        "transition_in": { "type": "xfade", "kind": "fade", "dur": 0.3 }
      }
    ],
    "music": {
      "source": "bgm.mp3",
      "volume": 0.7,
      "fade_in_ms": 500,
      "fade_out_ms": 2000,
      "bpm": 92,
      "beat_times": [0.65, 1.30, 1.95, 2.60],
      "structure": [{ "tag": "Intro", "start": 0 }, { "tag": "Build Up", "start": 12 }]
    },
    "titles": [
      {
        "id": "t1",
        "in_at": 0.5, "out_at": 3.0,
        "text": "Día 1",
        "style": "lower_third",
        "props": { "subtitle": null }
      }
    ],
    "captions": null
  },
  "metadata": {
    "beat_snapped": true,
    "treatment_hash": "a3f8...",
    "assets_hash": "9c12..."
  }
}
```

## Beat-sync algorithm

```
1. Compute target boundaries from treatment.shots[].duration → t0=0, t1=4, t2=9, t3=15, ...
2. From bgm_meta.beat_times, find beats[] within ±tolerance (default 0.25s) of each boundary
3. Snap each boundary to the nearest beat if one exists in tolerance
4. Adjust adjacent shot durations to absorb the snap delta (preserve total_duration ±5%)
5. Record beat_snapped: true in timeline.metadata
```

For high-energy moods (`pet-playful`, `pet-trendy`, `pet-epic`), use tighter tolerance and prefer snapping.
For slower moods (`pet-heartfelt`, `pet-lullaby`), relax tolerance — snapping every shot would feel jittery.

## Title styles (Remotion)

| Style | Description | Typical duration |
|---|---|---|
| `lower_third` | Slides in from left, primary text + optional subtitle | 2.5s |
| `kinetic_burst` | Word-by-word springs, dramatic, scale + rotate accents | 2.0s |
| `fullscreen` | Large centered text, subtle scale-in, stays bold | 2.0s |
| `tag_line` | Bottom-center, slow fade, light weight, elegant | 3.0s |
| `badge` | Small pill in top-right, brand-card style | full segment |
| `ticker` | Horizontal scroll, e.g. for stats / dates / facts | 3.0s |

## File structure

```
~/.cursor/skills/video-compose/
├── DESIGN.md                   # this file
├── SKILL.md
├── REFERENCE.md
├── config.json                 # Replicate token, Gemini key (auto-imports from siblings)
├── scripts/
│   ├── _common.py
│   ├── _video_pipeline.py      # Ken Burns + xfade (copied from avatar-video-reel)
│   ├── analyze_assets.py
│   ├── treatment.py
│   ├── pick_music.py
│   ├── generate_edl.py
│   ├── preview.py
│   ├── render_titles.py
│   ├── render_final.py
│   ├── compose.py              # one-stop CLI
│   ├── setup_key.py
│   └── requirements.txt
└── remotion/
    ├── package.json
    ├── tsconfig.json
    ├── remotion.config.ts
    └── src/
        ├── Root.tsx
        ├── TitleOverlay.tsx
        └── styles/
            ├── LowerThird.tsx
            ├── KineticBurst.tsx
            ├── Fullscreen.tsx
            ├── TagLine.tsx
            ├── Badge.tsx
            └── Ticker.tsx
```

## Always-interactive flow

1. User invokes the skill with a folder of source media
2. Agent runs `analyze_assets.py` (cached, ~30-90s first time)
3. Agent shows summary; asks for goal, tone, target duration, format, language
4. Agent drafts `treatment.yaml`, presents for review
5. User iterates the shot list until approved
6. Agent proposes 3 music moods matched to tone; user picks one
7. Agent generates BGM via `bg-music-hq`; runs librosa for BPM + beats
8. Agent generates `timeline.json` via `generate_edl.py` (LLM matches shots → asset scenes → cuts → beat-snapped boundaries)
9. Agent renders preview.mp4 (480p, no titles, ~15s)
10. **Approval gate**: user approves / edits timeline.json / asks for re-roll
11. Agent renders titles (Remotion, parallel per title) → `titles/t-NNN.webm`
12. Agent renders final via `render_final.py` (FFmpeg) → `final.mp4`

## Implementation order (TODO ladder)

1. Skeleton: skill folder, SKILL.md stub, requirements.txt, config.json, setup_key.py, _common.py
2. `_video_pipeline.py`: copy Ken Burns + xfade from `stitch_video.py`. Smoke test
3. `analyze_assets.py`: ffprobe + PySceneDetect + Gemini Vision per scene + cache
4. `treatment.py`: brief → shot list LLM call. Interactive
5. `pick_music.py`: wraps `bg-music-hq` + librosa BPM/beats extraction
6. `generate_edl.py`: creative LLM call with beat-snap
7. `preview.py`: fast 480p concat preview
8. `remotion/`: scaffold + 6 title styles
9. `render_titles.py`: drives Remotion CLI per title (parallel)
10. `render_final.py`: orchestrator — cuts, Ken Burns, xfades, title overlays, music
11. `compose.py`: one-stop CLI
12. `SKILL.md`: full documentation

## Open risks

- **Gemini Vision rate limits** during asset analysis — mitigate with parallel calls (5-8 concurrent), retry-with-backoff, persistent cache
- **Beat-snap can produce shots <1s** — add `min_shot_duration: 1.0` constraint in EDL generator
- **Remotion render speed**: ~5-15s per title at reel resolution. With 5-8 titles: ~1-2min serial, ~30s parallel (3 workers)
- **PySceneDetect false positives on shaky handheld** — may need adaptive content detector instead of threshold
- **No-VO means longer total durations feel sparse** — bias EDL to ~25-45s reels; warn if user requests >60s without explicit shots
