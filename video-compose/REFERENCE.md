# video-compose Reference

Detailed reference for schema, EDL contract, title style props, and CLI flags.

## Data contracts

### `treatment.yaml`

The structural script (replaces a voiceover; music is the only audio).

```yaml
goal: "Adoption journey reel for my dog Luna"
tone: "emotional, uplifting, warm"
language: es                # ISO 639-1
format: reel                # reel | post | landscape
target_duration: 30         # seconds
shots:
  - duration: 4             # 1.2 ≤ duration ≤ 8.0
    description: "Open on Luna's first night — small, unsure moments"
    title: { text: "Día 1", style: "lower_third" }
  - duration: 5
    description: "Bond-building — petting, naps, learning her name"
    title: null
  # ...
```

Constraints:
- `target_duration` must be > 0
- Each shot: `1.2 ≤ duration ≤ 8.0`
- Sum of `duration` across shots must equal `target_duration` ±10% (or ±2s)
- `title.style` must be one of: `lower_third`, `kinetic_burst`, `fullscreen`, `tag_line`, `badge`, `ticker`
- `title.text` and `title.style` are the only allowed keys inside `title`

### `assets.json`

```json
{
  "version": 1,
  "assets_root": "/abs/path/to/media",
  "videos": {
    "videos/clip-001.mp4": {
      "duration": 12.4,
      "fps": 30,
      "resolution": [1920, 1080],
      "scenes": [
        {
          "in": 0.0, "out": 3.2, "duration": 3.2,
          "blur_score": 0.78,    // 0..1, Laplacian variance / 800
          "motion_score": 0.34,  // 0..1, mean inter-frame diff / 30
          "brightness": 0.62,    // 0..1, mean grayscale / 255
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
  "_cache": {
    "version": 1,
    "entries": { "videos/clip-001.mp4": "1714536123-12345678" }
  }
}
```

The `_cache.entries` map keys (relative paths) to signatures (`mtime-size`). On re-runs, files with matching signatures are read from the previous JSON.

### `bgm_meta.json`

```json
{
  "bpm": 92.3,
  "beat_times": [0.65, 1.30, 1.95, 2.60, ...],
  "duration": 28.5,
  "structure": [
    { "tag": "Intro", "start": 0.0 },
    { "tag": "Build Up", "start": 9.5 },
    { "tag": "Outro", "start": 24.2 }
  ],
  "energy_curve": [0.18, 0.22, 0.31, ...],
  "mood": "pet-heartfelt",
  "source": "/abs/path/to/bgm.mp3"
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
        "in_at": 0.00, "out_at": 4.10, "duration": 4.10,
        "source": "videos/clip-001.mp4",
        "scene_index": 0,
        "src_in": 0.0, "src_out": 3.2,
        "ken_burns": "none",
        "transition_in": null
      },
      {
        "id": "v3",
        "in_at": 9.20, "out_at": 13.40, "duration": 4.20,
        "source": "images/luna-portrait.jpg",
        "scene_index": null,
        "src_in": 0.0, "src_out": 4.20,
        "ken_burns": "push_in",
        "transition_in": { "type": "xfade", "kind": "fade", "dur": 0.30 }
      }
    ],
    "music": {
      "source": "bgm.mp3",
      "volume": 0.7,
      "fade_in_ms": 500,
      "fade_out_ms": 2000,
      "bpm": 92,
      "beat_times": [0.65, 1.30, ...],
      "structure": [...]
    },
    "titles": [
      {
        "id": "t1",
        "shot_index": 0,
        "in_at": 0.50, "out_at": 3.00,
        "text": "Día 1",
        "style": "lower_third",
        "props": { }
      }
    ],
    "captions": null
  },
  "metadata": {
    "beat_snapped": true,
    "beat_snap_count": 4,
    "beat_snap_log": [{ "shot": 1, "from": 4.10, "to": 3.96 }],
    "treatment_hash": "a3f8...",
    "assets_hash": "9c12..."
  }
}
```

### Ken Burns presets

| Preset | Movement | Use |
|---|---|---|
| `none` | static | for video sources (already moving) |
| `zoom_center` | zoom in around center | safe default for portraits |
| `push_in` | zoom in + slight pan to center | intimate, dramatic |
| `push_out` | zoom out from center | reveals, openings |
| `drift_left` | pan right→left | wide scenes, movement direction |
| `drift_right` | pan left→right | wide scenes, movement direction |
| `drift_up` | pan down→up | uplifting, hopeful |
| `drift_down` | pan up→down | grounding, settling |

### Transition kinds (FFmpeg xfade)

`cut`, `fade`, `dissolve`, `slideleft`, `slideright`, `slideup`, `slidedown`, `circleopen`, `circleclose`, `wipeleft`, `wiperight`, `smoothleft`, `smoothright`, `smoothup`, `smoothdown`, `radial`

Duration: 0.0s for `cut`, 0.15-0.50s typical for others (defaults to 0.30s).

## Title style props

All Remotion title styles accept these common props (passed via `--props=` to `remotion render`):

| Prop | Type | Default | Notes |
|---|---|---|---|
| `text` | string | required | Primary text |
| `style` | TitleStyle | required | One of the 6 styles |
| `durMs` | number | required | Duration in milliseconds |
| `width` | number | required | Output width (e.g. 1080) |
| `height` | number | required | Output height (e.g. 1920) |
| `fps` | number | 30 | Frame rate |
| `accentColor` | string | `#FFD166` | Hex color for accent bars / pills / underlines |
| `textColor` | string | `#FFFFFF` | Primary text color |
| `fontFamily` | string | `Inter` | Loaded via Google Fonts |
| `subtitle` | string \| null | null | Optional secondary line (LowerThird, Fullscreen) |

Style-specific behavior:

- **lower_third**: Slides in from left over ~18 frames (spring), holds, slides out. Text on a dark blurred pill with accent bar to its left.
- **kinetic_burst**: Words spring in one-by-one (4-frame stagger). Mid-sequence word(s) get accent color. Slight rotation on entry. Scale-out on exit.
- **fullscreen**: Centered text with accent line above. Slow scale-in (1.08→1.0) with fade. Subtitle uses uppercase + letterspacing.
- **tag_line**: Bottom-center, low-emphasis, slow fade in/out. Thin font weight (300), heavy letter-spacing. Short underline accent above.
- **badge**: Top-right pill with accent-color dot + glow. Slides down on entry.
- **ticker**: Bottom strip with continuous horizontal scroll. Text repeated 5× separated by `•` for seamless loop.

## CLI flags

### `analyze_assets.py`

```
--assets PATH          source media folder (required)
-o, --output PATH      output assets.json (required)
--force                re-analyze, ignore cache
--no-vision            skip Gemini Vision descriptions (faster, no API)
--max-scenes N         max scenes per clip (default 12)
--vision-parallel N    parallel Vision API workers (default 6)
```

### `treatment.py draft`

```
--brief TEXT              creative brief / paragraph (required)
--assets PATH             path to assets.json (required)
--format FMT              reel | post | landscape (default reel)
--target-duration SECS    target reel duration (default 30)
--language CODE           ISO 639-1 code (default en)
--tone TEXT               tone description (default "warm, uplifting")
--max-shots N             cap shot count
-o, --output PATH         output treatment.yaml (required)
```

### `pick_music.py generate`

```
--treatment PATH       path to treatment.yaml (required)
--mood ID              mood preset id (required, e.g. pet-heartfelt)
--prompt TEXT          override the bg-music-hq prompt
-o, --output PATH      output bgm.mp3 (required)
--meta-output PATH     output bgm_meta.json
--force                re-generate even if output exists
```

### `generate_edl.py`

```
--treatment PATH        path to treatment.yaml (required)
--assets PATH           path to assets.json (required)
--music PATH            path to bgm.mp3 (required)
--music-meta PATH       path to bgm_meta.json (required)
--format FMT            reel | post | landscape (default reel)
--music-volume FLOAT    0.0..1.0 (default 0.7)
--music-fade-in-ms N    default 500
--music-fade-out-ms N   default 2000
--no-beat-snap          skip beat-snap pass
--beat-tolerance SECS   beat-snap tolerance (default 0.25)
--min-shot-duration S   min shot duration after snap (default 1.2)
-o, --output PATH       output timeline.json (required)
```

### `preview.py`

```
--timeline PATH       path to timeline.json (required)
--assets-root PATH    folder for resolving relative asset paths (default: timeline's dir)
--scale FLOAT         downscale factor (default 0.5)
--fps N               preview FPS (default 24)
--no-music            skip music
--no-labels           skip burned-in shot labels
--no-transitions      use plain concat instead of xfade
-o, --output PATH     output preview.mp4 (required)
```

### `render_titles.py`

```
--timeline PATH        path to timeline.json (required)
--titles-dir PATH      output directory for {title.id}.mov files (required)
--workers N            parallel render workers (default 3)
--accent-color HEX     default #FFD166
--text-color HEX       default #FFFFFF
--font NAME            default Inter
--force                re-render even if output exists
```

### `render_final.py`

```
--timeline PATH         path to timeline.json (required)
--titles-dir PATH       directory with title .mov files (optional — skipped if absent)
--assets-root PATH      folder for resolving relative asset paths
--no-music              skip music
--no-transitions        use plain concat
--motion-intensity X    subtle | medium | strong (default subtle)
--watermark PATH        optional PNG with alpha overlaid top-right
--watermark-scale F     watermark width as fraction of video width (default 0.18)
--watermark-opacity F   0.0..1.0 (default 0.7)
-o, --output PATH       output final.mp4 (required)
```

### `compose.py`

```
up-to-preview          run stages 1-5, stop at approval gate
finalize               run stages 6-7 after approval
full                   run all 7 stages without approval gate
stage NAME             run a single stage by name

Common args (all subcommands):
  --output-dir PATH     pipeline output dir (required)
  --assets-dir PATH     source media folder
  --brief TEXT          creative brief (for treatment stage)
  --format FMT          reel | post | landscape
  --target-duration N   seconds
  --language CODE       ISO 639-1
  --tone TEXT
  --max-shots N
  --mood ID             music mood id
  --user-music PATH     skip music generation, use this file
  --no-beat-snap
  --no-vision
  --motion-intensity X
  --force
```

## Why ProRes 4444 instead of WebM for titles

The skill uses Apple ProRes 4444 (`.mov`, `yuva444p10le`) for all transparent title overlays. This was a deliberate choice over WebM:

| Format | Render speed | Alpha reliability | File size |
|---|---|---|---|
| WebM VP8 + alpha | ~1 fps at 1080p | reliable but glacial | small |
| WebM VP9 + alpha | ~10 fps at 1080p | UNRELIABLE — Remotion sometimes silently drops alpha | smallest |
| ProRes 4444 | ~50+ fps at 1080p | rock-solid | larger (acceptable for 2-3s clips) |
| PNG sequence | very fast | rock-solid | huge |

ProRes 4444 strikes the best balance: render time stays low, alpha never gets dropped, and FFmpeg's `overlay` filter handles it natively. Title file sizes are typically 5-15 MB each — irrelevant since they're discarded after compositing.

## Common issues

### "Title overlay shows as black box, not transparent"

Cause: Title MOV was rendered with the wrong codec/pixel format. Verify:

```bash
ffprobe -v quiet -show_entries stream=codec_name,pix_fmt -of json titles/t1.mov
# Must show: codec_name="prores", pix_fmt="yuva444p..."
```

If `pix_fmt` is `yuv420p` (no alpha), re-render with the right flags. The `render_titles.py` script and `remotion.config.ts` both pin ProRes 4444; check that neither was overridden.

### "EDL generator returns invalid JSON"

The LLM occasionally produces extra commentary alongside JSON. The skill's `call_llm_json` helper strips ` ```json` markdown wrappers and parses anyway. If you get a JSON error, re-run — the temperature is 0.45 so output varies.

### "Beat-snap made shots feel jittery"

Lower the tolerance (e.g. `--beat-tolerance 0.15`) so only very close beats trigger a snap. Or disable with `--no-beat-snap` for slow/heartfelt reels.

### "Treatment durations don't add up to target_duration"

The validator allows ±10% or ±2s drift (whichever is larger). If you see a warning, edit `treatment.yaml` directly and re-run `treatment.py validate`. The shot durations are the source of truth for the EDL — `target_duration` is a hint to the LLM at draft time.

### "Remotion render hangs at 'Bundling...' the first time"

This is a one-time bundle build. Subsequent renders are much faster. If the first render takes >2 minutes to start, check that `node_modules` is fully populated:

```bash
ls -la ~/.cursor/skills/video-compose/remotion/node_modules/@remotion
```

You should see `cli`, `bundler`, `renderer`, etc.
