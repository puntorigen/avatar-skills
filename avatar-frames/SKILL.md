---
name: avatar-frames
description: Extract ready avatar reference frames from talking-head videos — single face, face-region sharpness, no burned-in subtitles. Optionally saves inpaint candidates (1 face, sharp, with subtitles) in with_subtitles/ when requested or when no ready frames exist. Uses MediaPipe and EasyOCR. Use when the user asks to extract avatar frames, clean frames from video, reference images for virtual avatar, or talking-head frame extraction.
---

# Avatar Frames Extractor

Extract production-ready avatar frames from video reels, interviews, or talking-head clips.

## Setup

```bash
bash ~/.cursor/skills/avatar-frames/scripts/setup.sh
```

## Quick Reference

### Default — ready frames only

```bash
python3 ~/.cursor/skills/avatar-frames/scripts/extract_clean_frames.py video.mp4 -o frames/
```

Output: `frame_0001.png`, `frame_0002.png`, … (1 face, sharp, no subtitles)

### Explicitly include inpaint candidates

```bash
python3 ~/.cursor/skills/avatar-frames/scripts/extract_clean_frames.py video.mp4 \
  -o frames/ --with-subtitles
```

### Debug rejections

```bash
python3 ~/.cursor/skills/avatar-frames/scripts/extract_clean_frames.py video.mp4 \
  -o frames/ --save-rejected
```

## Output Rules

| Output | Criteria | When saved |
|--------|----------|------------|
| **Root** (`frame_*.png`) | 1 face, sharp face, no subtitles | Always |
| **`with_subtitles/`** | 1 face, sharp face, has subtitles | Only with `--with-subtitles` **or** when zero ready frames found (auto-fallback) |
| **`rejected/`** | blur, no_face, multi_face | Only with `--save-rejected` |

When clean frames exist and `--with-subtitles` is not set, inpaint candidates are counted in `manifest.json` but **not written to disk**.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output`, `-o` | `frames` | Output directory |
| `--with-subtitles` | off | Also save inpaint candidates in `with_subtitles/` |
| `--interval` | `2.0` | Seconds per selection window |
| `--face-sharpness-percentile` | `10` | Adaptive face blur threshold |
| `--face-min-confidence` | `0.7` | MediaPipe face detection confidence |
| `--face-min-area-ratio` | `0.05` | Min face bbox area vs frame |
| `--ocr-min-conf` | `0.35` | EasyOCR subtitle confidence |
| `--save-rejected` | off | Save rejected frames for tuning |
| `--no-subtitle-style` | on | Skip profiling the burned-in caption style |
| `--subtitle-style-sample` | `24` | Max subtitled frames to profile for caption style |

## Output Structure

**Typical (ready frames found):**

```
frames/
├── frame_0001.png
├── frame_0002.png
└── manifest.json
```

**No ready frames (auto-fallback) or `--with-subtitles`:**

```
frames/
├── frame_0001.png              # may be empty
├── with_subtitles/
│   ├── subtitle_0001.png
│   └── subtitle_0002.png
└── manifest.json
```

## Pipeline

Per interval window (best frame every 2s):

1. **Single face** — short + full-range BlazeFace; reject 0 or 2+ faces
2. **Face sharpness** — Laplacian on face bbox (not full frame)
3. **Subtitle check** — EasyOCR on top (40%), overlay (30–85%), bottom (60–100%) zones
4. **Route** — ready → root; subtitled → inpaint pool; else → rejected
5. **Dedup** — perceptual hash per output group
6. **Write** — root always; `with_subtitles/` only per output rules above

## Manifest

`manifest.json` keys:

- `frames` — saved ready frames
- `with_subtitles` — saved inpaint frames (empty if skipped)
- `inpaint_saved`, `inpaint_reason` (`user_requested` | `no_clean_frames` | null)
- `frames_with_subtitles_skipped` — candidates found but not saved
- `rejected` — metadata only (images only with `--save-rejected`)
- `subtitle_style` — burned-in caption style profiled from subtitled frames (null if none)

## Subtitle style profile

When a video has burned-in captions, the extractor profiles their **style** from
the subtitled frames and writes both a `subtitle_style` block in `manifest.json`
and a standalone `subtitle_style.json`:

```
{ "y_frac": 0.62, "text_height_frac": 0.059, "fontsize_frac": 0.082,
  "lines": 2, "words_per_caption": 3, "casing": "lower",
  "color_rgb": [240,228,224], "color_hex": "#f0e4e0",
  "progression": "replace", "mean_word_overlap": 0.10,
  "emphasis": { "auto_detected": false, "convention": "…" },
  "samples": 21, "note": "…" }
```

- **Measured reliably:** vertical position (`y_frac`), text size
  (`text_height_frac` / suggested `fontsize_frac`), `lines`, `words_per_caption`,
  text `color`.
- **Progression (approximate):** `progression` is `replace` vs `accumulate`,
  derived from the word overlap between consecutive caption samples
  (`mean_word_overlap`). It tells downstream tools whether captions swap out per
  phrase (`replace`) or build up within a phrase (`accumulate`). Sparse sampling
  makes it a hint, not a measurement.
- **Emphasis (convention, not detected):** OCR can't read weight/italic, so
  `emphasis.convention` documents *what* the originals highlight and *why* — on
  these reels the breath-ending **payoff** words are set in bold-italic of the same
  serif. Downstream reproduces this by emphasizing each breath group's completion.
- **Low confidence:** `casing` — EasyOCR lowercases its output, so only `upper`
  (all-caps) is trustworthy; treat a reported `lower` as `natural`.
- **Not detected:** font family (serif vs sans), weight, italic emphasis.

Downstream (e.g. `avatar-reel-composer/finish_reel.py --style-from`) consumes this
to place/size new captions and to mirror the originals' replace-per-phrase
progression + payoff emphasis. Disable with `--no-subtitle-style`.

## Tuning

| Symptom | Fix |
|---------|-----|
| Too many blur rejections | Lower `--face-sharpness-percentile` (try `5`) |
| Subtitles missed on ready frames | Lower `--ocr-min-conf 0.4` |
| No ready frames, need inpaint | Auto-fallback creates `with_subtitles/`; or use `--with-subtitles` |
| Reels with captions everywhere | Expect few ready frames; rely on inpaint fallback |

## Batch

```bash
for f in videos/*.mp4; do
  name=$(basename "$f" .mp4)
  python3 ~/.cursor/skills/avatar-frames/scripts/extract_clean_frames.py "$f" -o "frames/$name"
done
```

Only merge **ready** `frame_*.png` files unless the user asks for inpaint candidates.

## Integration

- **Inpaint**: run on `with_subtitles/` after auto-fallback or `--with-subtitles`
- **Asset generation**: use root `frame_*.png` as `--ref` in asset-generator or gpt-image-2

## Notes

- Face sharpness uses the **face bbox**, not the full frame.
- Social-media captions sit in the **center overlay zone** (35–85% height).
- EasyOCR is the bottleneck (~1–2s per candidate frame).
