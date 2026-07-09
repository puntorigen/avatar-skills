# Product Reference Sheet — Prompt Framework (4 views)

Canonical framework for **product** reference sheets — the product equivalent of
the character sheet. It produces **exactly four views**: front three-quarter,
rear straight-on, a front close-up, and a left-side profile close-up, in a
photorealistic product-photography style, with consistent identity, colour,
materials, and details across all four.

`scripts/product_sheet.py` reproduces this frame verbatim and lets you adapt it
per product via `--product` (noun phrase) and the per-view detail slots
(`--front` / `--rear` / `--closeup` / `--profile`), plus `--style` and `--bg`
(default `neutral grey`). Pass a product photo with `--ref` to lock the exact
look. Keep the four `[VIEW ...]` lines and the `Lighting & presentation:` line
intact; adapt only the product noun and the per-view details.

## Adapting it

> Adapt this framework into a prompt for a product reference sheet for **[INSERT PRODUCT]**.

Look at the product (and any reference image), then fill each view with the
details that are actually visible in that view (front features, rear features,
close-up surface/finish, profile thickness/edge hardware).

## Framework (fill the bracketed slots)

```
PRODUCT REFERENCE SHEET TEMPLATE
Product reference sheet — four views on a neutral grey background:
[VIEW 1 — FRONT, THREE-QUARTER] Front-facing three-quarter view of the [PRODUCT]. Full product visible top to bottom. [FRONT-FACING FEATURES]
[VIEW 2 — REAR, STRAIGHT-ON] Full rear view of the same [PRODUCT], directly from behind. Full product visible. [REAR FEATURES]
[VIEW 3 — FRONT CLOSE-UP] Top third close-up, straight-on front view. [CLOSE-UP SURFACE / FINISH DETAIL]
[VIEW 4 — PROFILE, LEFT SIDE] Full left-profile close-up showing the product edge-on. [SIDE PROFILE / EDGE DETAIL]
Lighting & presentation: Clean studio lighting — soft key light upper left, gentle fill from the right. Consistent product identity, proportions, colour, materials, and surface details across all four views. Photorealistic product photography style. No text, no watermarks, no extra objects, no background environment.
```

## Worked example (iPhone 17 Pro Max)

```
PRODUCT REFERENCE SHEET TEMPLATE
Product reference sheet — four views on a neutral grey background:
[VIEW 1 — FRONT, THREE-QUARTER] Front-facing three-quarter view of the iPhone 17 Pro Max in Cosmic Orange. Full device visible top to bottom. 6.9-inch Super Retina XDR display with ultra-thin bezels, Dynamic Island pill-shaped cutout at top centre of the screen. Screen showing a subtle gradient wallpaper. Heat-forged anodized aluminum unibody frame with a warm matte orange finish. Camera Control button visible on the right edge, USB-C port centred on the bottom edge.
[VIEW 2 — REAR, STRAIGHT-ON] Full rear view of the same iPhone 17 Pro Max, directly from behind. Full device visible. The defining feature: a full-width camera plateau spanning the entire top of the rear, machined from the same anodized Cosmic Orange aluminum unibody. Three 48MP camera lenses arranged in a triangular pattern on the plateau, with a LiDAR scanner and LED flash. Below the camera plateau, a recessed Ceramic Shield glass panel covers the lower back with a subtle two-tone contrast against the aluminum. Clean Apple logo centred on the glass panel. No visible rings, circles, or markings on the back surface.
[VIEW 3 — FRONT CLOSE-UP] Top third close-up, straight-on front view. Sharp detail on the Dynamic Island cutout housing the Center Stage front camera system. Fine detail on the Ceramic Shield 2 display glass, the precision-machined aluminum frame edges, and the subtle curvature where glass meets metal. Action button and volume buttons visible on the left edge of frame.
[VIEW 4 — PROFILE, LEFT SIDE] Full left-profile close-up showing the device edge-on. The camera plateau's thickness and how it tapers into the aluminum unibody clearly visible from the side. Action button and volume rocker in sharp detail on this edge. The slim 8.75mm body profile, the seamless transition from matte anodized aluminum frame to front display glass and rear Ceramic Shield panel.
Lighting & presentation: Clean studio lighting — soft key light upper left, gentle fill from the right. Consistent device identity, proportions, colour, and hardware details across all four views. Photorealistic product photography style. No text, no watermarks, no extra objects, no background environment.
```

This maps to:
`--product "iPhone 17 Pro Max in Cosmic Orange"`, `--front "..."`, `--rear "..."`,
`--closeup "..."`, `--profile "..."` (the script uses the generic word "product"
where the worked example says "device").
