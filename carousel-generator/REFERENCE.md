# carousel-generator — reference

Full detail for the scripts, schemas and knobs. Read this when you need the exact
shapes; the day-to-day flow lives in `SKILL.md`.

## Scripts

| Script | Purpose | Key args |
| --- | --- | --- |
| `research_carousels.py` | Scrape competitor posts, split carousel vs reel, rank winners, download slides | `--handles` / `--handles-file`, `--per-profile`, `--top`, `--min-slides`, `--out-dir`, `--no-download` |
| `analyze_structure.py` | Gemini-vision slide-by-slide blueprint + reel-discovery fusion | `--run-dir`, `--max` |
| `research_hashtags.py` | Rank hashtags from winning captions (+ optional Apify enrichment) | `--run-dir`, `--seed`, `--limit` |
| `generate_carousel.py` | Plan + brand → 4:5 slides via asset-generator | `--plan`, `--brand`, `--out-dir`, `--dry-run` |
| `setup_key.py` | Optional: store Gemini/Apify creds in this skill's `config.json` | `--gemini-api-key`, `--apify-token`, `--show` |
| `_common.py` | Shared: credential + sibling-skill resolution, Apify runner, text utils | (imported) |

## Credentials & sibling resolution

The skill reuses the bundled sibling skills — nothing new to configure. Each
credential is resolved in this order:

- Gemini: `GEMINI_API_KEY` / `GOOGLE_API_KEY` env → this skill's `config.json`
  (`gemini_api_key`) → `asset-generator/config.json`.
- Apify: `APIFY_TOKEN` env → this skill's `config.json` (`APIFY_TOKEN`) →
  `reel-discovery/config.json`.

Sibling skills (and their configs) are looked up **repo-local first, then the
global install** (`~/.cursor/skills`), so the skill works both when run from this
repo and after `npx skills add ...`. The renderer
(`asset-generator/scripts/generate_asset.py`) is resolved the same way.

Override the Apify actors or vision model with env vars:
- `APIFY_IG_ACTOR` (default `apify~instagram-scraper`)
- `APIFY_HASHTAG_ACTOR` (default `apify~instagram-hashtag-scraper`)
- `CAROUSEL_VISION_MODEL` (default `gemini-flash-latest`)

## research_carousels.py output

`runs/<name>/`:
- `research.json` — handles, engagement evidence by type, ranked `top_carousels`.
- `summary.md` — carousel-vs-reel table + ranked winners (human-readable).
- `<handle>/<shortcode>/` — `slide_01.jpg…`, `caption.txt`, `meta.json`.

`engagement = likes + comments` (IG rarely exposes post views). A carousel needs
`>= --min-slides` (default 3) to be considered.

## Blueprint (`analyze_structure.py`)

`blueprint.json` keys:
- `typical_slide_count` — most common slide count among winners.
- `recommended_slides` — `[{n, role, purpose}]` role sequence to replicate.
- `dominant_narrative_patterns` — counts of listicle/contrarian/mind-reading/question/how-to.
- `hook_techniques`, `reel_discovery_patterns`, `per_carousel` (raw vision output).

Roles: `portada`, `idea`, `cita`, `dato`, `recap`, `cta` (mirror `slide_styles.json`).

## plan.json schema (input to generate_carousel.py)

```json
{
  "title": "7 señales de que ya estás sanando",
  "aspect_ratio": "4:5",
  "slides": [
    {"role": "portada", "headline": "7 señales de que\nya estás sanando", "body": "", "show_face": true, "style": "portada"},
    {"role": "idea", "headline": "1. Dejaste de revisar\nsu perfil", "body": "El impulso a mirar bajó sin que lo forzaras.", "show_face": false, "style": "idea"},
    {"role": "cta", "headline": "Guárdalo para tus\ndías difíciles", "body": "Sígueme para acompañarte en el proceso.", "show_face": true, "style": "cta"}
  ],
  "caption": "Texto del caption con su estructura ganadora…",
  "hashtags": ["superarunaruptura", "dueloamoroso", "amorpropio"]
}
```

A full runnable sample lives in [`examples/plan.example.json`](examples/plan.example.json).

Field notes:
- `headline` — text rendered verbatim; `\n` = line breaks. Keep it short.
- `body` — optional supporting line (smaller).
- `show_face` — if true and the brand has `identity_photos`, the person is added
  to that slide keeping their exact features; otherwise the slide is typographic.
- `style` — a key in `slide_styles.json`; defaults to `role`.
- `caption` / `hashtags` — optional; written to `caption.txt` / `hashtags.txt`.

## Brand schema (`brands/*.json`)

```json
{
  "name": "Arnoldo",
  "handle": "@arnoldo_schaffner_bofill",
  "language": "es",
  "tone": "cálido, cercano, esperanzador; valida el dolor y ofrece camino",
  "default_aspect_ratio": "4:5",
  "default_slide_count": 7,
  "palette": {"background": "#F7F1EA", "ink": "#26201B", "accent": "#D97A6C", "muted": "#9B8E82"},
  "fonts": {"heading": "…", "body": "…"},
  "visual_style": "editorial minimalista y cálido…",
  "assets": {"logo": "logo.png", "identity_photos": ["arnoldo1.jpg", "arnoldo2.jpg"]},
  "cta_default": "Guarda este post y sígueme para más"
}
```

- Asset paths are relative to the brand JSON's folder (or absolute).
- Up to 2 identity photos are used per face slide; logo (if present) is placed discreetly.
- The `handle` is stamped on the closing CTA slide.
- Identity photos / logos are images, so the repo git-ignores them; keep them next
  to the brand JSON (they are read at generation time, not committed).

## slide_styles.json

Presets (`portada`, `idea`, `cita`, `dato`, `recap`, `cta`) each define `layout`,
`text_treatment` and `face_position`, injected into the per-slide prompt. Tune
these to change the look globally without touching Python.

## Visual consistency

The cover (`slide_01.png`) is generated first, then passed as `--ref` (role
`style_ref`) to every later slide alongside the brand logo/photos. This mirrors
asset-generator's "consistent set" pattern so all slides share palette,
typography and margins.

## Troubleshooting

- **Empty research / 0 posts** — the Apify actor version may use different field
  names or the profile is private. Field access is defensive; check the token has
  credits and try `--per-profile` lower.
- **Blueprint used heuristic** — no Gemini key or vision model rejected; set
  `CAROUSEL_VISION_MODEL` to an available model.
- **Slide failed to generate** — rerun; `generate_asset.py` retries on 429. Use
  `--dry-run` to inspect prompts.
- **Text misspelled in image** — shorten the headline; Gemini renders short
  strings most reliably. Keep one idea per slide.
