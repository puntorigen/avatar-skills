---
name: pdf-remix
description: Analyze the design + narrative MOLD of a reference PDF (marketing lead-magnet, brochure, editorial piece) — palette, typographic roles, emphasis/highlight rules, per-page layout archetypes, camera angles, imagery treatment and the full narrative arc — then REGENERATE a brand-new, on-topic PDF that reuses that exact mold at equal or better quality. Imagery is produced with the asset-generator skill (including placing a person from reference photos into poses that fit each page); text is rendered as crisp HTML via Chromium. Use when the user wants to clone/replicate the look-and-feel of a PDF, turn a lead magnet into a template, or produce a premium multi-page marketing PDF in the style of an existing one.
---

# pdf-remix — extract a PDF's mold, then remix it with new content

`reel-discovery` finds a winning *video* and lets you restyle it. **pdf-remix does
the same for a PDF**: it deconstructs a premium document into a reusable **mold**
(design system + per-page archetypes + narrative arc) and then rebuilds a new
document — new topic, new copy, freshly generated imagery — that follows the mold
faithfully. Text stays crisp and editable (HTML → Chromium PDF) while
[`asset-generator`](../asset-generator/SKILL.md) produces the visuals.

**Two phases, one skill:**

```
ANALYZE   reference.pdf ─▶ blueprint.json + blueprint.md + content_template.json
REMIX     content.json (+brand +refs) ─▶ assets/*.png ─▶ output.pdf
```

The skill is **brand-agnostic**: any reference PDF, any topic, any brand. Point it
at reference photos (e.g. a person) and it will generate that person into poses
that fit the new pages (a cover portrait, etc.).

Built on two skills **bundled in this repo** (credentials are reused, nothing new
to configure):
- Image generation → [`asset-generator`](../asset-generator/SKILL.md) (Gemini 3 Pro Image + vision, key from its `config.json`).
- Apify token → [`reel-discovery`](../reel-discovery/SKILL.md) (only if you later fetch web assets).

## When to use

- "Analyze this PDF and make me a template I can reuse."
- "Create a lead magnet that looks exactly like this one but about <topic>."
- "Replicate the design of this brochure with my brand and this person on the cover."
- "Turn this marketing PDF into a mold and generate a better version."

## Setup

```bash
pip3 install -r .cursor/skills/pdf-remix/scripts/requirements.txt
python3 -m playwright install chromium                       # one-time Chromium runtime
python3 .cursor/skills/pdf-remix/scripts/setup_fonts.py      # bundled OFL fonts
```

Credentials are **reused, not re-entered** (env var first, then a git-ignored
`config.json`; repo-local sibling first, then the global `~/.cursor/skills`):
- Gemini key ← `GEMINI_API_KEY` env → this skill's `config.json` → `asset-generator/config.json` (vision analysis + image generation).
- Apify token ← `APIFY_TOKEN` env → this skill's `config.json` → `reel-discovery/config.json` (only if you later fetch web assets).

If `asset-generator` is not set up yet:
`python3 .cursor/skills/asset-generator/scripts/setup_key.py YOUR_GEMINI_API_KEY`
(or store it here: `python3 .cursor/skills/pdf-remix/scripts/setup_key.py --gemini-api-key AIza...`).

## Workflow

```
- [ ] 1. ANALYZE   → analyze_pdf.py reference.pdf  → runs/<slug>/{blueprint.*, content_template.json, preview/}
- [ ] 2. REVIEW    → read blueprint.md; confirm palette, archetypes, section unit, arc
- [ ] 3. AUTHOR    → copy content_template.json → content.json; write the NEW copy onto the mold,
                     set brand (name/handle/palette_override) + reference_images, define assets[] prompts
- [ ] 4. ASSETS    → generate_assets.py --content content.json --blueprint blueprint.json
- [ ] 5. BUILD     → build_pdf.py --content content.json --blueprint blueprint.json -o output.pdf
- [ ] 6. VERIFY    → pdftoppm -r 90 output.pdf /tmp/prev/p -png ; inspect; iterate on copy/assets
```

A ready-to-adapt authored sample lives in [`examples/content.example.json`](examples/content.example.json).

### 1. Analyze the reference

```bash
python3 .cursor/skills/pdf-remix/scripts/analyze_pdf.py "/path/to/reference.pdf" \
    --out-dir runs/mydoc
```

Produces:
- `blueprint.json` — machine-readable mold (design_system, layout_archetypes, per-page specs, narrative_arc).
- `blueprint.md` — human-readable mold (paste into a class / share with the user).
- `content_template.json` — editable skeleton (one entry per page: archetype + content fields + asset slots).
- `preview/page-NN.png` — rendered reference pages.

### 2. Review the mold

Open `blueprint.md`. Confirm the **palette**, the **typographic roles**, the
**emphasis/highlight rules**, the recurring **section unit** (e.g. "3 pages per
item: opener → what-is → split-grid") and the **narrative arc**. These are the
rules the new document must obey to match or beat the original.

### 3. Author the new content (the creative step)

Copy `content_template.json` → `content.json` and write the new document *onto*
the mold. Keep the mold's structure; adapt only the message. See
[REFERENCE.md](REFERENCE.md) for the full per-archetype content schema. Essentials:

- Set `brand`: `name`, `handle`, `author_byline`, `channel_url`,
  `reference_images` (absolute paths — e.g. photos of the person for the cover),
  and optional `palette_override`.
- For each page keep its `archetype`; fill the text fields with new copy.
- Inline markup in any string: `**bold**` (key claim), `*italic*` (self-talk /
  quote), `==accent==` (highlighted word in the brand color), blank line = new
  paragraph. **Respect the mold's emphasis rules** (e.g. handwriting only for the
  reader's inner voice; the accent color only for emotional hits, never full
  paragraphs).
- Define each page's `assets[]` with a stable `id`, a `kind`
  (`author_portrait|emotive_photo|symbolic_bg|product_mockup|texture|hero_photo`),
  an `aspect`, and a `prompt` describing what to depict for the NEW topic. For a
  person on the cover, use `kind:"author_portrait"` — it automatically uses
  `brand.reference_images` for identity and you describe the pose/composition.

### 4. Generate the assets (in the mold's visual language)

```bash
python3 .cursor/skills/pdf-remix/scripts/generate_assets.py \
    --content runs/mydoc/content.json --blueprint runs/mydoc/blueprint.json --resolution 2K
```

A global **style directive** derived from the mold (e.g. cinematic 35mm grain,
muted chiaroscuro) is prepended to every prompt so all imagery is consistent.
Re-run with `--only id1,id2 --force` to regenerate specific assets, or
`--dry-run` to preview prompts first.

### 5. Build the PDF

```bash
python3 .cursor/skills/pdf-remix/scripts/build_pdf.py \
    --content runs/mydoc/content.json --blueprint runs/mydoc/blueprint.json \
    -o runs/mydoc/output.pdf
```

Use `--html-only` for instant layout iteration without re-rendering the PDF (open
the `.render.html` in a browser). The palette comes from the blueprint and is
overridden by `brand.palette_override`; fonts come from the bundled OFL set.

### 6. Verify visually

```bash
pdftoppm -r 90 runs/mydoc/output.pdf /tmp/prev/p -png
```

Open the pages. Iterate on copy (edit `content.json`, rebuild — seconds) and on
imagery (regenerate specific assets with `--only ... --force`).

## How the mold maps to layout

`analyze_pdf.py` classifies each page into a canonical **archetype** so any
similar marketing PDF maps onto the same replicable library:

| Archetype | Typical use |
|---|---|
| `cover` | Full-bleed portrait + title + promise + byline + brand bar |
| `quote_dark` | Solid-dark cold-open quote (serif italic + brush accent) |
| `manifesto_text` | Headline (serif + brush) + justified body, optional photo |
| `statement_object` | Full-bleed symbolic still-life + big serif statement + handwritten note |
| `section_opener` | Split photo panel + "Item #N" kicker + serif name + inner-voice quote |
| `what_is` | Full-bleed dark photo (or photo-top) + accent section title + body |
| `split_grid` | 2×2 grid alternating photos and short "how it activates / shows up" text |
| `bridge` | Transition: brush+serif headline + body + secondary headline |
| `cta_closing` | Lead + product mockup + accent CTA button + urgency line |
| `freeform` | Fallback for anything the archetype set doesn't cover |

## Anti-patterns

1. **Do not** copy the reference's *words* — copy its *structure*. The new
   document must be genuinely new content adapted to the mold.
2. **Do not** bake body text into generated images. Only imagery is generated;
   all text is crisp HTML. (Headline words inside a photo are unreliable.)
3. **Do not** break the mold's emphasis semantics (handwriting = inner voice
   only; accent color = emotional hits only; never whole paragraphs in script).
4. **Do not** use generic stock-looking images. Keep the mold's photographic
   treatment (the style directive enforces it) for a premium, cohesive feel.
5. **Do not** skip the review step — the section unit and arc are what make the
   result feel like the original.
6. **Do not** commit `runs/` — it holds research previews and generated media
   (gitignored, along with the fetched `fonts/*.ttf`).

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/analyze_pdf.py` | Extract the mold → blueprint.json/.md + content_template.json + previews |
| `scripts/generate_assets.py` | Generate every asset a content.json needs, in the mold's style (via asset-generator) |
| `scripts/build_pdf.py` | Render content.json → premium multi-page PDF (Chromium), crisp text + generated imagery |
| `scripts/setup_fonts.py` | Fetch the bundled OFL font set (Playfair/Inter/Caveat/Great Vibes/Kaushan) |
| `scripts/setup_key.py` | Optional: store Gemini/Apify creds in this skill's `config.json` |
| `scripts/_common.py` | Credentials + sibling-skill resolution, PDF render/extract, palette, Gemini vision, asset bridge, fonts, HTML→PDF |
| `templates/base.css` | Design-system-driven stylesheet (archetype layouts via CSS variables) |

## Additional resources

- Full schemas (blueprint, content, per-archetype fields), palette semantics and
  troubleshooting: [REFERENCE.md](REFERENCE.md).
- Imagery engine: [`asset-generator`](../asset-generator/SKILL.md) (Gemini 3 Pro Image).
