# GPT Image 2 — Reference

Detailed API notes, post-processing internals, and advanced usage for the
`gpt-image-2` skill. Start with [SKILL.md](SKILL.md); read this when you need
the exact model inputs or want to understand the framing pipeline.

## Model

`openai/gpt-image-2` on Replicate — OpenAI's state-of-the-art image model for
text-to-image and instruction-based editing. It processes reference images at
high fidelity automatically (no strength knob) and preserves identity,
composition, and lighting unless you ask it to change them.

## Replicate inputs

| Input | Values | Notes |
|---|---|---|
| `prompt` | string | What to generate, or how to edit the inputs |
| `input_images` | list of files/URLs | One or more references for editing/composing |
| `aspect_ratio` | `1:1`, `3:2`, `2:3` | The only native ratios. No 16:9 / 9:16. Default `1:1`. |
| `quality` | `low`, `medium`, `high`, `auto` | Fidelity only (not pixel count). Lower is faster/cheaper. Default `auto`. |
| `number_of_images` | 1-10 | Multiple images per call |
| `output_format` | `png`, `jpeg`, `webp` | Model default `webp`; this skill defaults to `png` |
| `output_compression` | 0-100 | Default 90. Affects `webp`/`jpeg`; `png` stays lossless. |
| `background` | `auto`, `opaque`, `transparent` | Transparency is unreliable on this model (see note) |
| `moderation` | `auto` (default), `low` | `low` = less strict filtering |
| `openai_api_key` | string (optional) | Bring your own OpenAI key to pay OpenAI directly |

There is **no size / resolution / seed** input. `quality` controls fidelity,
not dimensions. Native output is fixed by aspect ratio at `1024×1024` (1:1),
`1536×1024` (3:2), `1024×1536` (2:3) — this is the model's maximum, so the
skill requests `quality high` and never upscales.

Although the schema accepts `background: transparent`, the model's readme states
transparency is not supported and results are unreliable. For dependable
transparent PNGs use `openai/gpt-image-1.5`.

## Resolution: native maximum, no upscaling

gpt-image-2 has no size input and `quality` only changes fidelity, so the
maximum resolution is whatever the chosen aspect ratio produces — `1536×1024`
for landscape (3:2), `1024×1536` for portrait (2:3), `1024×1024` for square.
The skill requests `--quality high` to get the best detail at that size and
**never upscales** — no Lanczos resize, no AI super-resolution. Pixels are only
ever added as background margin when reframing to a non-native ratio (below),
never invented inside the subject.

If you need true 4K, run a dedicated upscaler afterwards as a separate, explicit
step (e.g. `nightmareai/real-esrgan` or `recraft-ai/recraft-crisp-upscale` on
Replicate) — the skill intentionally leaves that out so its output is always the
model's genuine resolution.

## How 16:9 / 9:16 / 4:3 / 3:4 are produced

The model can't render these ratios, so `reframe_image()` in `_common.py`:

1. Generates at the **nearest native ratio** (`16:9`/`4:3` → `3:2`; `9:16`/`3:4` → `2:3`).
2. **Extends the canvas** to the exact target ratio with `pad_to_aspect()`. The
   new margin is filled with the color sampled from the image's border
   (`sample_background_color()`), so a uniform studio/board background extends
   seamlessly with no visible bars. Content is centered, never cropped, and
   never scaled — the result keeps the model's native resolution (e.g. a 16:9
   reframe of a 3:2 image is `1820×1024`).

Override the fill with `--pad-color "#1a1a1a"` when the background is not uniform
and you want a specific frame color.

## Reference images & character consistency

- Pass references with `--ref` (repeatable). They become `input_images`; the
  model preserves their identity at high fidelity with no extra parameters.
- For a **single reference**, the model edits/restyles it.
- For **multiple references**, describe how they relate and refer to them by
  number in the prompt: "apply the style from image 1 to the subject in image 2".
- For **character sheets**, 1-3 clear shots of the same character (different
  angles/expressions) lock identity best. State "the exact same character from
  the attached illustrations" and "preserve facial identity".

## Editing recipes

```bash
# Targeted edit — lock everything else
generate_image.py "change only the hat to light blue velvet; preserve the face, pose, lighting, and background" --ref portrait.png -o edited.png

# Style transfer across two images
generate_image.py "apply the painterly style of image 1 to the photo in image 2" --ref style.png --ref photo.png -o styled.png

# Insert a subject into a new scene
generate_image.py "place the person from image 1 on a sunny rooftop terrace at golden hour, preserving their likeness and outfit" --ref person.png -ar 16:9 -o rooftop.png

# In-image text (gpt-image-2 renders text well)
generate_image.py "movie poster, the title \"THE SILENT ECHO\" in large distressed sans-serif at the top, lone cabin in a snowy forest from above, high-contrast" -ar 2:3 -o poster.png
```

## Output contract

Each script writes progress/logs to **stderr** and a single JSON object to
**stdout**. Parse `["files"]` for the saved image paths. `generate_image.py`
also returns `model`, `prompt`, `aspect_ratio`, `native_ratio`, `quality`,
`format`, `compression`, `background`, and `references`.

## Token discovery order

`get_replicate_token()` resolves, in order:

1. `REPLICATE_API_TOKEN` environment variable
2. `~/.cursor/skills/gpt-image-2/config.json` → `replicate_api_token`
3. Sibling skill configs: `avatar-video-reel`, `brand-asset-studio`,
   `bg-music-hq`, `bg-music`, `sound-effects`, `video-compose`

Set or refresh with `scripts/setup_key.py YOUR_REPLICATE_API_TOKEN`. Get a token
at https://replicate.com/account/api-tokens.

## Cost & latency

Cost scales with `quality` and `number_of_images` (billed per image by
Replicate/OpenAI). `high` quality generations typically take ~1-3 minutes. Use
`--quality low` or `medium` for fast drafts, then re-run `high` for finals.

## Troubleshooting

- **401 / 403 from Replicate**: the token is missing, expired, or revoked.
  Refresh it with `setup_key.py` (verify with `--show`).
- **`replicate` / `PIL` import error**: `pip3 install -r scripts/requirements.txt`.
- **Output not big enough**: ~1536px is the model's hard maximum — there is no
  larger size. Upscale separately afterwards if you truly need 4K (see
  "Resolution" above).
- **Visible bars after canvas extension**: the background wasn't uniform — set an
  explicit `--pad-color`, or generate at a native ratio (`3:2` / `2:3`).
- **Identity drift in a character sheet**: add more/clearer `--ref` images and
  strengthen the preservation language in `--description`.
