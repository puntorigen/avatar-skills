# Character Reference Sheet — Prompt Framework (4 views)

This is the canonical framework for character reference sheets. It produces
**exactly four views** — full-body front, full-body rear, a front close-up, and
a profile close-up. It deliberately has **no expression sheet and no
eye-direction studies**, because those make the model flood the canvas with
many extra faces instead of the four clean views.

`scripts/character_sheet.py` reproduces this frame verbatim and lets you adapt
the character to the references via `--subject` / `--description` / `--style`
(and `--bg`, default `neutral grey`). Keep the four `[VIEW ...]` lines and the
`Lighting & presentation:` line intact; only adapt the
`[DESCRIBE CHARACTER AND CLOTHING]` and `[INSERT DESIRED STYLE]` slots.

## Framework (fill the bracketed slots)

```
CHARACTER REFERENCE SHEET FOR STYLE
Show the same [DESCRIBE CHARACTER AND CLOTHING]
Character reference sheet — four views on a neutral grey background:
[VIEW 1 — FULL BODY, FRONT] Full-body front-facing three-quarter view of this character, full body visible head to feet.
[VIEW 2 — FULL BODY, REAR] Full-body rear view of the same character, directly from behind. Full body visible head to feet.
[VIEW 3 — FRONT CLOSE-UP] Head and shoulders close-up, straight-on front view. Sharp detail on skin texture, accessories, and costume surface detail. Chest and shoulder armour/clothing visible at the bottom of frame.
[VIEW 4 — PROFILE CLOSE-UP] Head and shoulders close-up, 90-degree left profile view. Neck and upper shoulder visible.
Lighting & presentation: Clean studio lighting — soft key light upper left, gentle fill from the right. Consistent character identity, proportions, and costume details across all four views. No text, no watermarks, no extra figures, no background environment, in the below style... [INSERT DESIRED STYLE]
```

## Worked example (magician boy)

```
CHARACTER REFERENCE SHEET FOR STYLE
Show the same young magician boy, around 10 years old, from the attached reference image(s). Slim build, large observant eyes, messy dark-brown hair. Deep midnight-blue magician robe covered with gold embroidered stars, loose magical sleeves, and a matching pointed wizard hat.
Character reference sheet — four views on a neutral grey background:
[VIEW 1 — FULL BODY, FRONT] Full-body front-facing three-quarter view of this character, full body visible head to feet.
[VIEW 2 — FULL BODY, REAR] Full-body rear view of the same character, directly from behind. Full body visible head to feet.
[VIEW 3 — FRONT CLOSE-UP] Head and shoulders close-up, straight-on front view. Sharp detail on skin texture, accessories, and costume surface detail. Chest and shoulder armour/clothing visible at the bottom of frame.
[VIEW 4 — PROFILE CLOSE-UP] Head and shoulders close-up, 90-degree left profile view. Neck and upper shoulder visible.
Lighting & presentation: Clean studio lighting — soft key light upper left, gentle fill from the right. Consistent character identity, proportions, and costume details across all four views. No text, no watermarks, no extra figures, no background environment, in the below style... Premium illustrated storybook character design — hand-painted fantasy illustration, warm magical realism, highly expressive character-animation design.
```

This is the exact prompt `character_sheet.py` assembles from:
`--subject "young magician boy, around 10 years old"`,
`--description "Slim build, large observant eyes, messy dark-brown hair. Deep midnight-blue magician robe ..."`,
`--style "Premium illustrated storybook character design ..."`.
