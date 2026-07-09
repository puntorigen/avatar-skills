---
name: gpt-image-2
description: Generate and edit images with OpenAI GPT Image 2 (openai/gpt-image-2) on Replicate. Excels at precise instruction-following, in-image text, photorealism, and character consistency across images using reference pictures. Use to generate images with gpt-image-2, edit/compose images from references, build character reference sheets / turnarounds from 1-3 reference pictures, build product reference sheets (4-view) from a product or product photo, or produce multi-panel storyboard sheets from a story. Defaults to high quality (the model's native maximum resolution) and 16:9. Trigger when the user mentions gpt-image-2, gpt image 2, a character sheet, character turnaround, a product sheet / product reference sheet, or a storyboard sheet, or asks to generate/edit images via Replicate.
---

# GPT Image 2 (Replicate)

Generate and edit images with **OpenAI GPT Image 2** (`openai/gpt-image-2`) on Replicate. Strengths: precise instruction-following, accurate in-image text, photorealism, and **character consistency** — it preserves the identity of reference images at high fidelity, which is ideal for character sheets and storyboards.

## Setup

Install dependencies (one-time, usually already present from sibling skills):

```bash
pip3 install -r ~/.cursor/skills/gpt-image-2/scripts/requirements.txt
```

The Replicate API token is **shared** with the other Replicate skills (`avatar-video-reel`, `brand-asset-studio`, `bg-music`, `sound-effects`, ...). It is auto-discovered from `REPLICATE_API_TOKEN`, this skill's `config.json`, or any sibling skill's config. Only run setup if no valid token is found:

```bash
python3 ~/.cursor/skills/gpt-image-2/scripts/setup_key.py YOUR_REPLICATE_API_TOKEN
python3 ~/.cursor/skills/gpt-image-2/scripts/setup_key.py --show   # check current token
```

## Defaults

This skill defaults to **`--quality high`** (the model's native maximum — gpt-image-2 has no resolution control, so nothing is ever upscaled) and **`--aspect-ratio 16:9`**, matching the intended use for character sheets and storyboards.

## Quick Reference

```bash
# Text -> image (16:9, highest native quality)
python3 ~/.cursor/skills/gpt-image-2/scripts/generate_image.py \
  "a red origami crane on a weathered wooden table, soft window light" \
  --aspect-ratio 16:9 --quality high -o crane.png

# Edit / compose with reference images (identity preserved automatically)
python3 ~/.cursor/skills/gpt-image-2/scripts/generate_image.py \
  "the same character sitting in a Parisian cafe, reading a book" \
  --ref hero.png -o cafe.png

# Long prompt from a file (best for storyboards)
python3 ~/.cursor/skills/gpt-image-2/scripts/generate_image.py \
  --prompt-file board.txt --aspect-ratio 16:9 -o storyboard.png

# Several variations
python3 ~/.cursor/skills/gpt-image-2/scripts/generate_image.py \
  "logo for a coffee brand called \"EMBER\", bold sans-serif" \
  --aspect-ratio 1:1 --count 4 -o ember.png
```

Every script prints a JSON object to stdout ending with `"files": [...]` listing the saved paths.

## Workflow 1: Character Reference Sheet

Generate a clean **4-view** reference sheet — full-body front (three-quarter), full-body rear, a front head-and-shoulders close-up, and a 90° profile close-up — with locked facial identity and costume, from **1-3 reference pictures of the same character**. (Exactly four views: no expression sheet or eye-direction studies, so the canvas isn't flooded with extra faces.)

```bash
python3 ~/.cursor/skills/gpt-image-2/scripts/character_sheet.py \
  --ref ref1.png --ref ref2.png \
  --subject "young magician boy, around 10 years old" \
  --description "Slim build, large observant eyes, messy dark-brown hair. Deep midnight-blue robe covered in gold stars, matching pointed wizard hat. Curious, gentle, imaginative." \
  --style "Premium illustrated storybook, hand-painted fairy-tale art, warm magical realism" \
  -o magician_sheet.png
```

How to use it well:
1. Always pass the reference picture(s) with `--ref` (repeatable, 1-3). GPT Image 2 preserves their identity automatically.
2. Look at the references and write `--subject` (a short noun phrase) and `--description` (build, face, hair, costume, personality). For non-default looks, set `--style`.
3. The script reproduces the fixed 4-view frame (the four views, lighting, no-text / no-extra-figures rules, consistency mandate). See [prompts/character_sheet_framework.md](prompts/character_sheet_framework.md) for the full framework and the worked magician example.
4. Defaults are `--quality high --aspect-ratio 16:9` (native maximum resolution; nothing is upscaled). Inspect the assembled prompt first with `--print-prompt` if you want to review/tweak it.
5. To use a completely custom prompt instead of the scaffold, pass `--prompt-file path.txt`.

`character_sheet.py` options: `--ref` (repeatable), `--subject`, `--description` / `--description-file`, `--style` / `--style-file`, `--bg`, `--prompt-file`, `--aspect-ratio` (16:9), `--quality` (high), `--count`, `--pad-color`, `--output`, `--print-prompt`.

## Workflow 2: Product Reference Sheet

Generate a clean **4-view** product sheet — front three-quarter, rear straight-on, a front close-up, and a left-side profile close-up — in photorealistic product-photography style, with consistent identity/colour/materials/details across all four views. Optionally pass a product photo with `--ref` to lock the exact look.

```bash
python3 ~/.cursor/skills/gpt-image-2/scripts/product_sheet.py \
  --ref iphone.png \
  --product "iPhone 17 Pro Max in Cosmic Orange" \
  --front "6.9-inch Super Retina XDR display, Dynamic Island, anodized aluminum unibody, Camera Control on the right edge, USB-C on the bottom." \
  --rear "Full-width camera plateau, three 48MP lenses in a triangular pattern, LiDAR + LED flash, recessed Ceramic Shield glass panel, centred Apple logo." \
  --closeup "Dynamic Island housing the front camera, Ceramic Shield 2 glass, precision-machined frame edges, Action + volume buttons on the left." \
  --profile "Camera plateau tapering into the unibody, 8.75mm body, seamless matte aluminum to glass transitions." \
  -o iphone_sheet.png
```

How to use it well:
1. Write `--product` (a noun phrase incl. colour/finish) and adapt the four per-view slots (`--front` / `--rear` / `--closeup` / `--profile`) to what's actually visible in each view. Anything you omit falls back to the generic view instruction.
2. Pass a product photo with `--ref` (repeatable) to lock the exact look; without it the product is rendered from your description.
3. Set `--style` to override the default `Photorealistic product photography style.` (e.g. a clean 3D render or minimalist e-commerce look).
4. The script reproduces the fixed 4-view frame (the four views, lighting, no-text / no-extra-objects rules, consistency mandate). See [prompts/product_sheet_framework.md](prompts/product_sheet_framework.md) for the full framework and the worked iPhone example.
5. Defaults `--quality high --aspect-ratio 16:9`. Review with `--print-prompt`; use `--prompt-file` for a fully custom prompt.

`product_sheet.py` options: `--ref` (repeatable), `--product`, `--front`, `--rear`, `--closeup`, `--profile`, `--style` / `--style-file`, `--bg`, `--prompt-file`, `--aspect-ratio` (16:9), `--quality` (high), `--count`, `--pad-color`, `--output`, `--print-prompt`.

## Workflow 3: Storyboard Sheet

Produce a professional multi-panel storyboard sheet (numbered panels with timecodes and shot notes) as one composite image. The prompt is **authored per story** using the storyboard framework; the script just generates it.

Steps:
1. Read [prompts/storyboard_framework.md](prompts/storyboard_framework.md) and build the **Phase 1 storyboard image prompt** for the story (adapt the framework — title/format header, style, character DNA, visual tone, layout, per-panel scene breakdown, art-direction + format footers). Use the user's exact prompt instead if they provide one.
2. Save the prompt to a file (it is long — 1,200-2,000 words for 15 panels).
3. Generate, passing any character reference sheet with `--ref` to keep characters consistent across panels:

```bash
python3 ~/.cursor/skills/gpt-image-2/scripts/generate_image.py \
  --prompt-file storyboard_prompt.txt \
  --ref magician_sheet.png \
  --aspect-ratio 16:9 --quality high -o storyboard.png
```

4. After the user approves the storyboard, hand off to the **`seedance-2`** skill, which builds the framework's **Phase 2** cinematic video prompt and animates the storyboard sheet into video (passing the sheet as a reference). This skill only produces the Phase 1 image.

Grid layout maps to panel count in the prompt text: 9→3×3, 12→3×4, 15→3×5 (default), 20→4×5. For 9:16 vertical, flip the grid (e.g. 15→5×3) and pass `--aspect-ratio 9:16`.

## Model Capabilities & Constraints

| Capability | Detail |
|---|---|
| Strengths | Instruction-following, in-image text, photorealism, character consistency, precise editing |
| Reference images | One or more via `--ref` (`input_images`); identity preserved at high fidelity, no knob needed |
| Quality | `low` / `medium` / `high` / `auto` (we default `high`). Affects fidelity only, not pixel count. |
| Output size | Fixed by aspect ratio: ~1024² (1:1), 1536×1024 (3:2), 1024×1536 (2:3). **No size/resolution input — this is the native maximum.** |
| Native aspect ratios | **`1:1`, `3:2`, `2:3` only** |
| Transparency | Limited — `--background transparent` is accepted by the API but unreliable; use `openai/gpt-image-1.5` for dependable transparent PNGs |

The model has **no resolution control**, so this skill never upscales — `--quality high` already gives the maximum resolution gpt-image-2 produces. The only post-processing is:
- **16:9 / 9:16 / 4:3 / 3:4**: generated at the nearest native ratio, then the canvas is seamlessly extended to the exact target using the sampled background color (no letterbox bars, no cropping, **no upscaling** — the content keeps its native resolution; the frame just gains matching-color margin).

## generate_image.py Options

| Option | Default | Description |
|---|---|---|
| `prompt` / `--prompt-file` | — | Prompt text, or read a long prompt from a file |
| `--ref PATH` | — | Reference image (repeatable) → `input_images` |
| `--aspect-ratio`, `-ar` | `3:2` | `1:1`,`3:2`,`2:3` (native) or `16:9`,`9:16`,`4:3`,`3:4` (canvas-reframed at native resolution) |
| `--quality`, `-q` | `high` | `low`,`medium`,`high`,`auto` — fidelity only; `high` = native maximum |
| `--format`, `-f` | `png` | `png`,`webp`,`jpeg` |
| `--compression` | `90` | 0-100; affects `webp`/`jpeg`, `png` stays lossless |
| `--background` | `auto` | `auto`,`opaque`,`transparent` (transparency unreliable) |
| `--moderation` | `auto` | `auto`,`low` |
| `--pad-color` | `auto` | Canvas-extension fill: `auto` (sample border) or hex `#1a1a1a` |
| `--count`, `-n` | `1` | 1-10 images per call |
| `--output`, `-o` | slug | Output path |
| `--openai-key` | — | Optional: bring your own OpenAI key (pay OpenAI directly) |

Note: `generate_image.py` defaults `--aspect-ratio` to `3:2`; the `character_sheet.py`, `product_sheet.py`, and storyboard flows pass `16:9` explicitly. There is no resolution flag — output is always the model's native maximum.

## Prompting Tips (from the model's guidance)

- **Be specific**: "add soft coastal daylight" beats "make it better".
- **Photo language for realism**: lens, lighting quality, framing ("shot with a 50mm lens, soft daylight, shallow depth of field").
- **Lock what shouldn't change when editing**: "change only the lighting; preserve the subject's face, pose, and clothing".
- **Put in-image text in "quotes"** and describe the typography ("bold sans-serif, centered, high contrast").
- **Iterate with small changes** rather than rewriting everything.
- **Reference multiple images by number**: "apply the style from image 1 to the subject in image 2".

## Additional Resources

- Character sheet framework + worked example: [prompts/character_sheet_framework.md](prompts/character_sheet_framework.md)
- Product sheet framework + worked example: [prompts/product_sheet_framework.md](prompts/product_sheet_framework.md)
- Storyboard (two-phase) framework: [prompts/storyboard_framework.md](prompts/storyboard_framework.md)
- Full API details, schema, and post-processing internals: [REFERENCE.md](REFERENCE.md)
