# Asset Generator Reference - Advanced Patterns

## Prompt Engineering for Gemini 3 Pro Image

### The Perfect Prompt Formula

Gemini 3 Pro Image (Nano Banana Pro) responds best to **natural language prompts** with distinct structural components. Stop using 2023-era keyword-stuffed prompts.

**Formula:**
```
[Subject + Adjectives] doing [Action] in [Location/Context].
[Composition/Camera Angle]. [Lighting/Atmosphere].
[Style/Media]. [Specific Constraint/Text].
```

**Example breakdown:**
```
A translucent glass robot barista pouring latte art
inside a cozy cyberpunk coffee shop.
Macro close-up shot, shallow depth of field (f/1.8).
Illuminated by neon pink and teal signage reflection.
Cinematic 8k render, Octane render style.
The robot's chest display reads "WAKE UP" in bold LCD font.
```

### What to AVOID

- **Keyword spam**: "4k, trending on artstation, masterpiece, highly detailed, best quality" -- the model handles quality natively
- **Redundant descriptors**: "beautiful stunning gorgeous amazing" -- pick one specific adjective
- **Vague text instructions**: Say `Write "HELLO" in bold red serif font on the sign` instead of `add text`
- **Over-prompting**: Be descriptive but not repetitive. Quality > quantity of words

### Prompt Components Reference

| Component | Purpose | Example |
|-----------|---------|---------|
| Subject | What the image contains | "A crystalline chess set" |
| Action | What's happening | "with pieces melting where they touch" |
| Context | Setting/environment | "on a board made of burning lava" |
| Composition | Camera/framing | "Macro photography, eye-level" |
| Lighting | Light source and mood | "Dramatic rim lighting, warm tones" |
| Style | Artistic treatment | "Hyper-realistic 3D render" |
| Text | Any text in the image | `The sign reads "OPEN" in neon script` |
| Constraints | What to exclude | "No people, no text unless specified" |

### Style-Specific Prompts

#### Icons
```
# Good - specific, constrained
"a cloud with a lightning bolt, flat design, geometric shapes, centered"

# Bad - vague, too complex
"a weather app icon with clouds and rain and sun and lightning"
```

Tips:
- Request "centered composition" to avoid off-center subjects
- Use "simple shapes" and "geometric" for scalable designs
- Add "no text, no words" to prevent unwanted text
- Specify "single subject" for clean icons

#### Illustrations
```
# Consistent style across a set
"Modern flat illustration of [SUBJECT]. Clean lines, limited color palette
of blue and orange tones, digital art style, consistent with material design."
```

Tips:
- Mention a specific color palette for consistency across sets
- Reference design systems (material design, human interface) for familiar aesthetics
- Use `--ref` to maintain visual consistency with a previously generated image

#### Logos
```
# Lettermark
"Minimalist lettermark logo for 'AB'. Clean geometric construction,
single color, modern sans-serif influenced, scalable."

# Symbol
"Abstract geometric logo symbol representing connection and growth.
Simple interlocking shapes, balanced composition, works at small sizes."
```

#### Marketing Assets with Text
```
# Gemini 3 Pro Image renders text with ~94% accuracy
"Create a minimalist movie poster for 'THE SILENT ECHO'.
Large distressed sans-serif font at the top.
A lone cabin in a snowy forest viewed from above.
High contrast black and white. Title perfectly legible and centered."
```

#### Infographics
```
# Leverages the model's world knowledge and search grounding
"Step-by-step infographic showing how to make Elaichi Chai.
Include accurate ingredients: cardamom pods, loose tea leaves, milk.
Clean vector art with pastel colors. Label ingredients correctly."
```

#### Hero Images
```
"Abstract gradient background with flowing geometric shapes and soft
light particles. Modern tech aesthetic, deep blue to purple.
Wide cinematic composition with negative space for text overlay on the left."
```

## Reference Images - Complete Guide

### How It Works

Gemini 3 Pro Image natively understands reference images through its Thinking mode. Unlike earlier models, **you do NOT need to pre-describe references** -- the model sees and reasons about them directly.

The model supports up to **14 reference images** per request, maintaining:
- Strict style consistency across complex scenes
- Identity preservation for up to 5 human subjects
- Accurate color and brand element reproduction

### Placement Strategies

#### Strategy 1: Single Reference, No Placeholder (Edit/Restyle)

Best for: Restyling, editing, or transforming an existing image.

```bash
python3 generate_asset.py "redesign this in a modern flat style" --ref old_icon.png
```

**What happens internally:** The reference image is placed **before** the text prompt:
```
[old_icon.png image] → "redesign this in a modern flat style"
```

This is the optimal order for single-image edits per Google's multimodal prompt guidelines.

#### Strategy 2: Placeholders for Precise Positioning

Best for: Compositing, placing references at specific positions in a scene.

```bash
python3 generate_asset.py \
  "a cat watching {image1} on a TV screen in the style of {image2}" \
  --ref screenshot.png --ref art_style.png
```

**What happens internally:**
```
"a cat watching" → [screenshot.png] → "on a TV screen in the style of" → [art_style.png]
```

#### Strategy 3: Multiple References, No Placeholders (Brand Kit)

Best for: Brand consistency, character consistency across scenes.

```bash
python3 generate_asset.py \
  "create a new social media banner for this brand" \
  --ref brand_logo.png --ref brand_colors.png --ref brand_style.png
```

**What happens internally:**
```
"Reference image 1 (brand_logo):" → [brand_logo.png]
"Reference image 2 (brand_colors):" → [brand_colors.png]
"Reference image 3 (brand_style):" → [brand_style.png]
"Instruction: create a new social media banner for this brand"
```

### Reference Image Best Practices

1. **Be explicit about roles**: Tell the model exactly what to do with each image
   - "Use the color palette from {image1}"
   - "Match the art style of {image1}"
   - "Place {image1} on the computer screen"
   - "Keep the character from {image1} in the pose from {image2}"

2. **Optimal reference count by use case**:
   - **Style transfer**: 1-2 references
   - **Brand consistency**: 3-5 references
   - **Complex composition**: 3-6 references
   - **Character + scene**: 2-3 references
   - **Maximum fidelity**: 5-8 references (quality may degrade beyond this)

3. **Image quality matters**: Higher-resolution, well-lit reference images produce better results

4. **Identity preservation**: When maintaining character identity across images, include a clear front-facing reference and specify "maintain exact facial features and characteristics"

## Thinking Mode

Gemini 3 Pro Image uses a "Thinking" process that reasons through your prompt before generating. This is especially valuable for:

- **Complex compositions**: Multiple subjects interacting in a scene
- **Text rendering**: Ensures correct spelling and placement
- **Physical interactions**: Reflections, shadows, transparency, material interactions
- **Logic-dependent scenes**: "A mirror reflecting the scene but with one change"
- **Reference image fusion**: Combining elements from multiple reference images

### When to use each level

| Thinking Level | Use For | Speed |
|---------------|---------|-------|
| `high` (default) | Production assets, complex scenes, text-heavy images | ~30s |
| `low` | Quick drafts, simple subjects, rapid iteration | ~10-15s |

## Custom Style Presets

Edit `scripts/styles.json` to add custom presets:

```json
{
  "my-brand": {
    "name": "My Brand Style",
    "description": "Assets matching our brand guidelines",
    "aesthetic": "Modern tech branding with blue and white colors, SaaS product aesthetic",
    "qualities": ["clean professional design", "SaaS product aesthetic", "modern minimalist"],
    "default_framing": "Centered, balanced composition",
    "default_constraints": ["No text unless specified", "Consistent with brand guidelines"],
    "recommended_aspect_ratio": "1:1",
    "recommended_transparent": true,
    "bg_hint": "on a solid bright green (#00FF00) background"
  }
}
```

### Style Preset Fields

| Field | Description |
|-------|-------------|
| `aesthetic` | Visual style description woven into the natural language prompt |
| `qualities` | List of style qualities joined with commas in the prompt |
| `default_framing` | Composition guidance added to the prompt |
| `default_constraints` | Constraints joined with periods and appended |
| `recommended_aspect_ratio` | Default ratio when none specified |
| `recommended_transparent` | Whether transparent bg is typical for this style |
| `bg_hint` | Text added when `--transparent` is used |

### Natural Language Prompt Pipeline

The asset generator builds prompts as natural flowing sentences (not rigid sections). A user prompt like "a friendly robot" with the `icon` style becomes:

```
a friendly robot. Clean flat design app icon with bold, simple geometry.
centered composition, simple geometric shapes, modern minimalist, high contrast,
crisp edges, scalable at small sizes. Centered, full subject visible, square format.
on a solid bright green (#00FF00) background. Ensure the subject is clearly
separated from the background with clean edges. No text or words in the image.
Suitable for display at small sizes (64px). Single cohesive subject.
```

The `--raw-prompt` flag bypasses this system entirely, sending your prompt as-is.

## Google Gemini 3 Pro Image API - Direct Usage

### Basic Generation

```python
from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO

client = genai.Client(api_key="YOUR_KEY")

response = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents=["A flat design icon of a rocket ship on a green background"],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        thinking_level="high",
        image_config=types.ImageConfig(
            aspect_ratio="1:1",
            image_size="2K",
        ),
    ),
)

for part in response.candidates[0].content.parts:
    if part.inline_data:
        img = Image.open(BytesIO(part.inline_data.data))
        img.save("rocket.png")
```

### Reference Image Editing

```python
from PIL import Image

reference = Image.open("original_icon.png")

# For single-image edits, place image BEFORE text for best results
response = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents=[
        reference,
        "Redesign this icon in a modern flat style with blue and purple tones. Keep the same subject.",
    ],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        thinking_level="high",
    ),
)
```

### Multi-Image Composition

```python
from PIL import Image

screenshot = Image.open("website_screenshot.png")
style_ref = Image.open("art_style.png")

# Interleave images naturally with descriptive text
response = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents=[
        "Generate an illustration of a friendly robot sitting at a desk, "
        "looking at a monitor that displays",
        screenshot,
        "The art style should match",
        style_ref,
        "Use warm lighting and a cozy office atmosphere.",
    ],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        thinking_level="high",
        image_config=types.ImageConfig(aspect_ratio="16:9"),
    ),
)
```

### Brand Consistency with Multiple References

```python
from PIL import Image

logo = Image.open("brand_logo.png")
palette = Image.open("brand_palette.png")
existing = Image.open("existing_asset.png")

response = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents=[
        "Reference - our brand logo:",
        logo,
        "Reference - our brand color palette:",
        palette,
        "Reference - existing brand asset for style matching:",
        existing,
        "Create a new hero banner for our landing page. "
        "Maintain the exact brand colors, logo style, and visual language from the references. "
        "Wide cinematic composition with space for a headline on the left side.",
    ],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        thinking_level="high",
        image_config=types.ImageConfig(
            aspect_ratio="21:9",
            image_size="2K",
        ),
    ),
)
```

### Aspect Ratios Available

| Ratio | Best For |
|-------|----------|
| `1:1` | Icons, avatars, app icons, square social media |
| `3:2` | Landscape photos |
| `2:3` | Portrait photos, infographics |
| `3:4` | Product images |
| `4:3` | Presentations, thumbnails |
| `4:5` | Instagram portrait |
| `5:4` | Photo prints |
| `9:16` | Mobile splash screens, stories |
| `16:9` | Hero banners, YouTube thumbnails |
| `21:9` | Ultra-wide hero banners |

### Pricing Reference

| Resolution | Standard Rate | Batch Rate (50% off) |
|------------|--------------|---------------------|
| 1K / 2K | $0.134/image | $0.067/image |
| 4K | $0.24/image | $0.12/image |
| Reference input | $0.0011/image | — |

Use 1K during development, 2K for production web assets, 4K only for print.

## Background Removal - Advanced

### rembg with Custom Model

```python
from rembg import remove, new_session

# Use isnet-general-use for better general results
session = new_session("isnet-general-use")
result = remove(input_image, session=session)

# Available models: u2net, u2netp, u2net_human_seg, u2net_cloth_seg,
#                   silueta, isnet-general-use, isnet-anime, sam
```

### Post-Processing Transparent Images

```python
from PIL import Image, ImageFilter

img = Image.open("transparent.png")

# Smooth jagged edges
alpha = img.split()[3]
alpha = alpha.filter(ImageFilter.SMOOTH)
img.putalpha(alpha)

# Add padding
padded = Image.new("RGBA", (img.width + 40, img.height + 40), (0, 0, 0, 0))
padded.paste(img, (20, 20))
padded.save("padded.png")

# Add drop shadow
shadow_color = (0, 0, 0, 80)
shadow = Image.new("RGBA", img.size, shadow_color)
shadow.putalpha(img.split()[3])
shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))

canvas = Image.new("RGBA", (img.width + 20, img.height + 20), (0, 0, 0, 0))
canvas.paste(shadow, (10, 10))
canvas.paste(img, (0, 0), img)
canvas.save("with_shadow.png")
```

## Platform-Specific Export Guidelines

### iOS App Icons

- Must be square with no transparency (iOS adds rounded corners)
- 1024x1024 is the master size for App Store
- Do NOT include rounded corners in the image itself

### Android Adaptive Icons

- Foreground: 108x108dp with 72x72dp safe zone centered
- For full icon: generate at 512x512 with subject in center 66%
- Play Store icon: 512x512 with no alpha

### Web Favicons

- 16x16 and 32x32 for browser tabs
- 180x180 for Apple touch icon
- 192x192 and 512x512 for PWA manifest
- Consider providing both SVG and PNG versions

### Expo / React Native

For Expo apps, generate:
- `icon.png`: 1024x1024 (app icon)
- `splash.png`: 1284x2778 (splash screen)
- `adaptive-icon.png`: 1024x1024 (Android adaptive)
- `favicon.png`: 48x48 (web favicon)

## Batch Generation Workflow

For generating a complete asset set:

```bash
#!/bin/bash
SCRIPT=~/.cursor/skills/asset-generator/scripts/generate_asset.py
RESIZE=~/.cursor/skills/asset-generator/scripts/resize_assets.py

# Generate core assets (use --thinking low for drafts, default high for finals)
python3 $SCRIPT "a rocket ship" --style icon --transparent -o assets/icon.png
python3 $SCRIPT "a rocket launching into space" --style hero --resolution 2K -ar 21:9 -o assets/hero.png
python3 $SCRIPT "a rocket ship character" --style mascot --transparent -o assets/mascot.png

# Export platform sizes
python3 $RESIZE assets/icon.png --preset ios-icon -o assets/ios/
python3 $RESIZE assets/icon.png --preset android-icon -o assets/android/
python3 $RESIZE assets/icon.png --preset favicon -o assets/web/

echo "Done! Assets generated in assets/"
```

## Troubleshooting

### "SAFETY" block or no image returned
The prompt may have triggered content safety filters. Try:
- Rephrasing to be more specific about the visual style
- Avoiding ambiguous terms that could be misinterpreted
- Using `--raw-prompt` with a carefully crafted prompt

### Inconsistent style across assets
- Use `--ref` with a previously generated image to maintain consistency
- Keep the same `--style` preset across related assets
- Include specific color palette descriptions in your prompt
- Use 3-5 brand reference images for strict consistency

### Background removal artifacts
- For complex subjects (hair, fur, translucent objects), use `--method ml`
- For images generated with green screen hint, try `--method chroma` first
- Post-process with Pillow for edge smoothing if needed

### Rate limiting
The script automatically retries with exponential backoff (up to 3 attempts). If you consistently hit rate limits:
- Add delays between batch generations
- Use Google's Batch API for high-volume workloads
- Check your quota at Google AI Studio

### Text rendering issues
- Be very specific: `Write "HELLO WORLD" in bold red serif font on the sign`
- Use `--thinking high` for text-heavy images
- Keep text short and specify font style, color, and position
