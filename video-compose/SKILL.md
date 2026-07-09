---
name: video-compose
description: Compose a polished video reel from a folder of source clips and images using a Python+FFmpeg pipeline with Remotion title overlays. The skill drafts an interactive treatment (shot list) with the user, analyzes available assets via ffprobe + PySceneDetect + Gemini Vision, generates branded background music via bg-music-hq, builds a beat-synced Edit Decision List (EDL), renders a low-res preview for approval, then renders animated titles via Remotion (ProRes 4444 with alpha) and the final composite via FFmpeg with Ken Burns motion, xfade transitions, and music mixing. Use when the user asks to compose, edit, assemble, or stitch a video reel from a folder of clips and photos, especially when they want titles, transitions, background music, or VEED.io / Adobe-Premiere-style auto-editing without a voiceover.
---

# Video Compose

Compose a polished video reel from a folder of source clips and images. Output: VEED.io / Adobe-Premiere-quality video assembled programmatically with an interactive treatment, beat-synced cuts, animated Remotion titles, branded background music from `bg-music-hq`, and FFmpeg-rendered transitions and Ken Burns motion.

## Pipeline at a glance

```
1. ANALYZE     analyze_assets.py        → assets.json
2. TREATMENT   treatment.py draft       → treatment.yaml          (interactive)
3. MUSIC       pick_music.py generate   → bgm.mp3 + bgm_meta      (interactive: pick mood)
4. EDL         generate_edl.py          → timeline.json           (LLM + beat-snap)
5. PREVIEW     preview.py               → preview.mp4 (480p)      (approval gate)
6. TITLES      render_titles.py         → titles/*.mov            (ProRes 4444 + alpha)
7. FINAL       render_final.py          → final.mp4               (FFmpeg orchestrator)
```

See [DESIGN.md](DESIGN.md) for the architectural spec and rationale.

## Setup

Install Python dependencies (one-time):

```bash
pip3 install -r ~/.cursor/skills/video-compose/scripts/requirements.txt
```

Install Node dependencies for Remotion (one-time):

```bash
cd ~/.cursor/skills/video-compose/remotion && npm install
```

Set up API keys (auto-imports from sibling skills if available):

```bash
python3 ~/.cursor/skills/video-compose/scripts/setup_key.py
# or explicitly:
python3 ~/.cursor/skills/video-compose/scripts/setup_key.py YOUR_REPLICATE_API_TOKEN
```

Required:
- **Replicate token** — for `bg-music-hq` (auto-imported from sibling skills)
- **Gemini API key** — for asset analysis + LLM (treatment, EDL)
- **FFmpeg** on PATH (with libx264 + libvpx + opus encoders)
- **Node.js 18+** (for Remotion)

## Workflow (always interactive)

The skill is designed for an LLM agent to orchestrate. The agent:

1. Runs `analyze_assets.py` to scan the user's media folder.
2. Asks the user for goal, tone, target duration, format, language.
3. Drafts a `treatment.yaml` shot list with `treatment.py draft` and presents it for review.
4. Iterates the shot list until the user approves.
5. Runs `pick_music.py suggest` to propose 3 mood options matched to the treatment.
6. Generates the chosen mood with `pick_music.py generate` (this also extracts BPM + beats via librosa).
7. Generates the EDL with `generate_edl.py` (LLM-driven asset matching + beat-snap).
8. Renders a 480p preview with `preview.py`.
9. **Approval gate** — shows the preview to the user. The user can:
   - approve → proceed to titles + final render
   - edit `timeline.json` directly (clean JSON)
   - re-roll specific shots
10. Renders titles with `render_titles.py` (Remotion → ProRes 4444 MOV with alpha).
11. Renders final composite with `render_final.py`.
12. Delivers `final.mp4` (and keeps all intermediate artifacts for re-rolls).

## Quick reference

### One-stop driver

```bash
# Run stages 1-5 (analyze..preview) — stops at the approval gate
python3 ~/.cursor/skills/video-compose/scripts/compose.py up-to-preview \
  --assets-dir ./media --output-dir ./reel-out \
  --brief "Adoption journey for my dog Luna" \
  --format reel --target-duration 30 \
  --language en --tone "emotional, uplifting, warm" \
  --mood pet-heartfelt

# After user approves → render titles + final
python3 ~/.cursor/skills/video-compose/scripts/compose.py finalize \
  --output-dir ./reel-out --assets-dir ./media

# Or run everything end-to-end without an approval gate
python3 ~/.cursor/skills/video-compose/scripts/compose.py full \
  --assets-dir ./media --output-dir ./reel-out \
  --brief "..." --format reel --target-duration 30 --mood pet-heartfelt
```

### Individual stages

```bash
SCRIPTS=~/.cursor/skills/video-compose/scripts

# 1. Analyze a folder of media
python3 $SCRIPTS/analyze_assets.py --assets ./media -o assets.json

# 2. Draft a treatment from a brief
python3 $SCRIPTS/treatment.py draft \
  --brief "..." --assets assets.json \
  --format reel --target-duration 30 \
  --language en --tone "warm, uplifting" -o treatment.yaml

# Print / validate
python3 $SCRIPTS/treatment.py print treatment.yaml
python3 $SCRIPTS/treatment.py validate treatment.yaml

# 3. Pick a mood + generate music + extract BPM/beats
python3 $SCRIPTS/pick_music.py suggest --treatment treatment.yaml
python3 $SCRIPTS/pick_music.py generate \
  --treatment treatment.yaml --mood pet-heartfelt \
  -o bgm.mp3 --meta-output bgm_meta.json

# Or: analyze a user-provided track
python3 $SCRIPTS/pick_music.py analyze --input my_song.mp3 -o my_song.meta.json

# 4. Generate the EDL (matches shots → assets, beat-snaps cuts)
python3 $SCRIPTS/generate_edl.py \
  --treatment treatment.yaml --assets assets.json \
  --music bgm.mp3 --music-meta bgm_meta.json \
  -o timeline.json

# 5. Render a fast preview (480p, no titles)
python3 $SCRIPTS/preview.py --timeline timeline.json -o preview.mp4

# 6. Render titles via Remotion (ProRes 4444 + alpha, parallel)
python3 $SCRIPTS/render_titles.py \
  --timeline timeline.json --titles-dir ./titles --workers 3

# 7. Render the final composite
python3 $SCRIPTS/render_final.py \
  --timeline timeline.json --titles-dir ./titles -o final.mp4
```

## Output structure

When using `compose.py`, the output directory will contain:

```
reel-out/
├── assets.json          # cached per-file analysis (mtime-keyed)
├── treatment.yaml       # the shot list (the structural script)
├── bgm.mp3              # background music track
├── bgm_meta.json        # BPM, beat_times, structure tags
├── timeline.json        # the EDL — the contract between stages
├── preview.mp4          # low-res approval-gate render
├── titles/
│   ├── t1.mov           # ProRes 4444 with alpha (LowerThird, etc.)
│   ├── t2.mov
│   └── ...
└── final.mp4            # the final composite
```

## Title styles (Remotion)

| Style | Use | Default duration |
|---|---|---|
| `lower_third`   | Slides in from left, primary text + optional subtitle (intros, names) | 2.5s |
| `kinetic_burst` | Word-by-word springs, dramatic, scale + rotate (energy, big reveals) | 2.0s |
| `fullscreen`   | Large centered text, subtle scale-in, stays bold (hero statements) | 2.0s |
| `tag_line`     | Bottom-center, slow fade, light weight, elegant (closing taglines) | 3.0s |
| `badge`        | Small pill in top-right, brand-card style (chapter labels, dates) | full segment |
| `ticker`       | Horizontal scroll for stats / facts / dates | 3.0s |

To preview a single title interactively:

```bash
cd ~/.cursor/skills/video-compose/remotion
npm run start  # opens Remotion Studio
```

## Format presets

| Format | Resolution | Aspect | Use |
|---|---|---|---|
| `reel`      | 1080×1920 | 9:16 | Instagram Reels, TikTok, YouTube Shorts |
| `post`      | 1080×1080 | 1:1  | Instagram Posts, Facebook |
| `landscape` | 1920×1080 | 16:9 | YouTube, LinkedIn |

## Music moods

Run `python3 pick_music.py suggest --treatment treatment.yaml` to get 3 ranked mood suggestions. The full list of supported moods (delegated to `bg-music-hq`):

`pet-heartfelt`, `pet-daily`, `pet-playful`, `pet-adventure`, `pet-epic`, `pet-chill`, `pet-trendy`, `pet-transformation`, `pet-lullaby`, `pet-regal`, `pet-goofy`, `cinematic`, `uplifting`, `lofi`

The skill will analyze the chosen track with `librosa` to extract BPM, beat times, and structure tags. The EDL generator uses these to snap shot boundaries to musical beats (within ±0.25s tolerance by default).

## Beat-sync algorithm

In stage 4 (EDL), after the LLM picks asset matches:

1. Compute target shot boundaries from the treatment (cumulative sums of shot durations).
2. For each boundary, find the nearest beat from `bgm_meta.beat_times` within `--beat-tolerance` (default 0.25s).
3. If a beat is in tolerance and the snap doesn't violate `min_shot_duration` (default 1.2s), snap the boundary.
4. Adjust adjacent shot durations to absorb the delta.
5. Re-center sub-clip windows for video segments to keep durations consistent.

Disable with `--no-beat-snap`. Increase tolerance for tighter sync: `--beat-tolerance 0.4`.

## Re-rolls and edits

The `timeline.json` is the canonical EDL — clean JSON. Edit it directly to:

- swap a video source for a shot
- adjust src_in / src_out
- change Ken Burns presets
- change transition kind/duration
- reposition titles
- tweak music volume / fade timings

Then re-run from `preview.py` or `render_final.py` — the rest of the pipeline reads from `timeline.json`.

To re-roll just the LLM matching step (e.g. "shot 3 picked the wrong clip"):

```bash
python3 generate_edl.py \
  --treatment treatment.yaml --assets assets.json \
  --music bgm.mp3 --music-meta bgm_meta.json \
  -o timeline.json
```

The treatment + assets + music are cached, so this only re-runs the LLM call.

## Performance

| Stage | Typical time | Notes |
|---|---|---|
| analyze   | 30-90s first run, instant on cache hit | Gemini Vision is the bottleneck (parallel ×6) |
| treatment | 5-15s | One LLM call |
| music     | 60-180s | bg-music-hq via Replicate |
| edl       | 5-15s | One LLM call + deterministic beat-snap |
| preview   | 10-30s | 480p, no titles |
| titles    | 5-15s × n_titles, parallel ×3 | Remotion → ProRes 4444 |
| final     | 30-90s | depends on n_shots and Ken Burns count |

End-to-end for a 30s reel with 6 shots and 4 titles: ~5-8 minutes (mostly the music generation step).

## See also

- [DESIGN.md](DESIGN.md) — architectural spec
- [REFERENCE.md](REFERENCE.md) — schema details, EDL contract, title style props
- `bg-music-hq` skill — for music generation
- `asset-generator` skill — if you need to generate placeholder images for shots
