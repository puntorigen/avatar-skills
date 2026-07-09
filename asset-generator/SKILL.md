---
name: asset-generator
description: Generate image assets for web and mobile apps using Google Gemini 3 Pro Image (Nano Banana Pro). Supports style presets (icon, illustration, logo, mascot, hero, marketing, infographic, etc.), transparent backgrounds via ML removal, multiple formats (PNG, WebP, JPEG), up to 14 reference images, native 4K resolution, and platform-specific export (iOS icons, Android icons, favicons, PWA, social media). Use when the user asks to generate, create, or produce images, icons, illustrations, logos, mascots, app assets, or any visual content for their app or website.
---

# AI Asset Generator

Generate production-ready image assets for web and mobile apps using Google Gemini 3 Pro Image (Nano Banana Pro).

## Setup

Install dependencies (one-time):

```bash
pip3 install -r ~/.cursor/skills/asset-generator/scripts/requirements.txt
```

Set your Gemini API key (one-time):

```bash
python3 ~/.cursor/skills/asset-generator/scripts/setup_key.py YOUR_GEMINI_API_KEY
```

First use of `--transparent` downloads the rembg model (~170MB). Subsequent runs are fast.

## Quick Reference

### Generate an asset

```bash
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py "a friendly robot" \
  --style icon --transparent --output robot_icon.png
```

### Generate with reference images

Use `--ref` to pass images that Gemini incorporates into the output. Place `{image1}`, `{image2}`, etc. in your prompt to control where each reference appears:

```bash
# Edit/restyle a single reference (image placed before text for optimal results)
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "redesign this icon in a modern flat style with blue and purple tones" \
  --ref old_icon.png --style icon --transparent -o modern_icon.png

# Incorporate a screenshot into a generated scene
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "a rabbit using a computer that shows {image1} on screen" \
  --ref screenshot.png --style illustration -o rabbit_at_computer.png

# Multiple references (up to 14)
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "combine the style of {image1} with the logo from {image2} into a new app icon" \
  --ref style_ref.png --ref logo.png --style icon --transparent -o new_icon.png

# Brand consistency: use 3-5 reference images
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "create a new marketing banner maintaining the exact brand style, colors, and typography from these references" \
  --ref brand1.png --ref brand2.png --ref brand3.png --style marketing -ar 16:9 -o banner.png
```

### Remove background from any image

```bash
python3 ~/.cursor/skills/asset-generator/scripts/remove_bg.py input.png --output transparent.png
```

### Export to platform-specific sizes

```bash
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py icon.png --preset ios-icon --output icons/
```

### List available style presets

```bash
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py --list-styles
```

## generate_asset.py Options

| Option | Short | Description |
|--------|-------|-------------|
| `--style STYLE` | `-s` | Style preset (see presets below) |
| `--aspect-ratio AR` | `-ar` | `1:1`, `16:9`, `9:16`, `3:2`, `2:3`, `3:4`, `4:3`, `4:5`, `5:4`, `21:9` |
| `--resolution RES` | `-r` | `1K` (default), `2K`, `4K` |
| `--transparent` | `-t` | Remove background (outputs RGBA PNG) |
| `--format FMT` | `-f` | `png` (default), `webp`, `jpeg` |
| `--output PATH` | `-o` | Output file path |
| `--ref PATH` | | Reference image (repeatable, up to 14). Use `{image1}`..`{imageN}` in prompt. |
| `--thinking LEVEL` | | `high` (default, best quality) or `low` (faster) |
| `--count N` | `-n` | Number of variations to generate (1-4) |
| `--sizes SIZES` | | Also export at these pixel sizes (e.g. `64,128,256`) |
| `--raw-prompt` | | Use prompt as-is without style wrapping |

## Style Presets

| Preset | Best For | Default Ratio | Transparent |
|--------|----------|---------------|-------------|
| `icon` | App icons, toolbar icons | 1:1 | Recommended |
| `illustration` | Flat vector-style graphics | 1:1 | No |
| `photo` | Photorealistic images | 16:9 | No |
| `logo` | Brand marks, symbols | 1:1 | Recommended |
| `ui-element` | Buttons, badges, UI parts | 1:1 | Recommended |
| `background` | Patterns, textures | 1:1 | No |
| `hero` | Landing page hero banners | 21:9 | No |
| `mascot` | Character mascots | 1:1 | Recommended |
| `3d-render` | 3D objects, product shots | 1:1 | Recommended |
| `pixel-art` | Retro pixel art sprites | 1:1 | Recommended |
| `emoji` | Emoji stickers, reactions | 1:1 | Recommended |
| `splash` | Mobile splash screens | 9:16 | No |
| `decorative` | Abstract accents, textures, overlays | 1:1 | Recommended |
| `marketing` | Marketing materials with text | 16:9 | No |
| `infographic` | Data visualizations, informational graphics | 2:3 | No |

Style presets are defined in `scripts/styles.json` and can be customized or extended.

## Model

This skill uses **Gemini 3 Pro Image** (`gemini-3-pro-image-preview`), Google's most advanced image generation model. Key capabilities:

| Feature | Specification |
|---------|--------------|
| Max Resolution | Native 4K |
| Reference Images | Up to 14 per request |
| Text Rendering | ~94% accuracy across languages |
| Identity Preservation | Up to 5 human subjects |
| Thinking Mode | Reasons through complex prompts before generating |
| Search Grounding | Factually accurate content via Google Search |

Use `--thinking high` (default) for best quality on complex compositions. Use `--thinking low` for faster generation on simple prompts.

## Reference Images - Best Practices

Gemini 3 Pro Image natively understands reference images through its Thinking mode -- no pre-processing or description step needed.

### Placement strategy

- **Single reference, no placeholder**: Image is placed **before** the text prompt (optimal for edits/restyling)
- **With `{imageN}` placeholders**: Images are interleaved at the exact position in the prompt
- **Multiple references, no placeholders**: Each image gets a labeled role description

### Tips for best results

- **Be explicit about each image's role**: "Use the colors from {image1}", "match the art style of {image1}", "display {image1} on the monitor screen"
- **For brand consistency**: Upload 3-5 reference images of existing brand assets
- **For character consistency**: Include character reference and specify "maintain exact facial features and characteristics"
- **For style transfer**: Place the style reference first, then describe the new subject
- **Keep prompts natural**: Gemini 3 Pro understands conversational language better than keyword-stuffed prompts
- **Don't over-prompt**: Avoid "4k, trending on artstation, masterpiece" -- the model handles quality natively

## Background Removal

Gemini cannot natively generate transparent images. This skill uses a smart two-step approach:

1. **Smart color picking**: Analyzes the prompt text and reference images to choose a solid background color (from magenta, green, blue, red, cyan, yellow) that doesn't conflict with the subject's colors. For example, a "green stethoscope vet dog" prompt will avoid green and pick magenta instead.
2. **Chroma-key removal**: After generation, removes the chosen background color using fast, precise chroma keying with anti-aliased edges. Falls back to rembg ML if no chroma color is available.

The `--transparent` flag handles both steps automatically. The chosen background color is printed during generation.

### Standalone background removal

```bash
# ML-based (best quality, for arbitrary photos)
python3 ~/.cursor/skills/asset-generator/scripts/remove_bg.py photo.jpg --output clean.png

# Chroma key (fast, for solid-color backgrounds)
python3 ~/.cursor/skills/asset-generator/scripts/remove_bg.py greenscreen.png --method chroma --color 00FF00
python3 ~/.cursor/skills/asset-generator/scripts/remove_bg.py magenta_bg.png --method chroma --color FF00FF

# Batch process a directory
python3 ~/.cursor/skills/asset-generator/scripts/remove_bg.py images/ --batch --output transparent/
```

## Platform Export (resize_assets.py)

Export a source image to all sizes needed for a platform:

```bash
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py icon.png --preset ios-icon --output ios/
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py icon.png --preset android-icon --output android/
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py icon.png --preset favicon --output public/
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py icon.png --preset pwa-icon --output pwa/
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py banner.png --preset social-media --output social/
```

### Export Presets

| Preset | Sizes Generated |
|--------|----------------|
| `ios-icon` | 20-1024px (15 files: all @1x/@2x/@3x variants) |
| `android-icon` | 48-512px (6 files: mdpi through xxxhdpi + Play Store) |
| `favicon` | 16-512px (6 files: favicons + apple-touch-icon) |
| `pwa-icon` | 64-512px (9 files: all PWA manifest sizes) |
| `social-media` | Platform-specific (OG, Twitter, Instagram, LinkedIn, YouTube) |

### Custom sizes

```bash
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py icon.png --sizes "64,128,256,512" --output sizes/
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py banner.png --sizes "1200x630,1080x1080" --output custom/
```

## Common Workflows

### Generate app icon set for iOS and Android

```bash
# 1. Generate the master icon
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py "a rocket ship" \
  --style icon --transparent --resolution 2K --output master_icon.png

# 2. Export for iOS
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py master_icon.png \
  --preset ios-icon --output ios-icons/

# 3. Export for Android
python3 ~/.cursor/skills/asset-generator/scripts/resize_assets.py master_icon.png \
  --preset android-icon --output android-icons/
```

### Generate consistent illustration set

```bash
# Generate first asset
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py "a shopping cart" \
  --style illustration --output assets/cart.png

# Use it as style reference for subsequent assets (image placed before text automatically)
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "a credit card in the same visual style as {image1}" \
  --ref assets/cart.png --style illustration --output assets/card.png

python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "a delivery truck in the same visual style as {image1}" \
  --ref assets/cart.png --style illustration --output assets/truck.png
```

### Marketing materials with accurate text

```bash
# Gemini 3 Pro Image excels at rendering text accurately
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "a minimalist movie poster titled 'THE SILENT ECHO' in large distressed sans-serif font at the top, with a lone cabin in a snowy forest viewed from above, high contrast black and white" \
  --style marketing --resolution 2K -o poster.png

# Infographic with accurate labels
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "a step-by-step infographic showing how to brew pour-over coffee, clean vector art with pastel colors, label all ingredients correctly" \
  --style infographic --resolution 2K -o coffee_infographic.png
```

### Incorporate screenshots or photos into generated art

```bash
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "a cute owl mascot sitting at a desk, looking at a monitor that displays {image1}" \
  --ref website_screenshot.png --style mascot -o mascot_at_work.png

python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "a hand holding {image1} with a beautiful sunset background" \
  --ref product_photo.png --style photo -ar 16:9 -o hero_product.png
```

### Generate landing page hero image

```bash
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py \
  "abstract technology network with glowing nodes and connections, deep blue to purple gradient" \
  --style hero --resolution 2K --output hero.png
```

### Generate multiple variations and pick the best

```bash
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py "a friendly owl mascot" \
  --style mascot --count 4 --transparent --output owl.png
# Generates: owl_1.png, owl_2.png, owl_3.png, owl_4.png
```

### Fast iteration with low thinking

```bash
# Use --thinking low for quick drafts during ideation
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py "a space helmet" \
  --style icon --thinking low --transparent --output draft_helmet.png

# Then use --thinking high (default) for the final version
python3 ~/.cursor/skills/asset-generator/scripts/generate_asset.py "a space helmet" \
  --style icon --transparent --resolution 2K --output final_helmet.png
```

## Configuration

Config stored at `~/.cursor/skills/asset-generator/config.json`:

```json
{
  "gemini_api_key": "YOUR_KEY",
  "default_style": "illustration",
  "default_format": "png"
}
```

Update defaults:

```bash
python3 ~/.cursor/skills/asset-generator/scripts/setup_key.py --set-default-style icon
python3 ~/.cursor/skills/asset-generator/scripts/setup_key.py --show
```

## Additional Resources

- For advanced prompt engineering, custom styles, and API details, see [REFERENCE.md](REFERENCE.md)
