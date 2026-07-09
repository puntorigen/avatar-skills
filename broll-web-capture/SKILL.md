---
name: broll-web-capture
description: Turn a website or a GitHub repo into a short, polished B-roll clip for technical reels — a high-DPI Playwright capture animated with Ken Burns zoom/pan, a vertical scroll-reveal, or a spotlight push-in, framed on the target aspect (9:16 etc.) with a blurred-fill background. A github preset captures repo money-shots (landing/README/contribution graph) with a live animated star counter pulled from the GitHub API. Optionally composites the talking avatar in a PiP corner (the "base + avatar overlay" architecture). Use when you want B-roll showing a website, landing page, product page, or GitHub repository, a screen capture with zoom-in of a repo/site, or animated proof footage to overlay under narration in a short video.
---

# broll-web-capture

Produce the **base layer** of a technical reel: a website or GitHub repo turned
into a short, animated B-roll clip. In a 40–60s reel a full live demo doesn't fit
(it needs context and eats the runtime — reserve real demos for YouTube
long-form). Complementary **capture B-roll** is the right register: a smooth
zoom-in/pan or scroll over a crisp screenshot, illustrating while the
narration/avatar carries the message.

Two-layer architecture (see the scene types in `brand-content-strategy`):

```
broll-web-capture / broll-terminal   ← BASE layer (proof visual)
        +
talking avatar in PiP                 ← OVERLAY layer (credential anchor)
```

This skill builds the base layer and, with `--avatar`, also composites the PiP
overlay (via `pip_overlay.py`, the same compositor `broll-demo-avatar` reuses).

## When to use

- "Make B-roll of this website / landing page / repo."
- "Show this GitHub repo with a zoom-in" / "screen capture of my repos."
- "Animated proof footage to overlay under my narration."

## Setup

```bash
pip3 install -r .cursor/skills/broll-core/scripts/requirements.txt
pip3 install -r .cursor/skills/broll-web-capture/scripts/requirements.txt
playwright install chromium
```

Requires the **`broll-core`** skill alongside this one (shared geometry + the PiP
compositor, imported via a sys.path shim). `ffmpeg` + `ffprobe` must be on PATH
(libx264). Optional `GITHUB_TOKEN` env var
raises the GitHub API rate limit for the star counter (unauthenticated works for
low volume).

## Quick start

```bash
S=.cursor/skills/broll-web-capture/scripts

# 1) A website -> framed Ken Burns push-in, 9:16
python3 $S/make_broll_web.py https://pabloschaffner.com --mode in --duration 5

# 2) A landing page -> full-page vertical scroll-reveal
python3 $S/make_broll_web.py https://example.com --preset landing --mode scroll

# 3) A GitHub repo -> header money-shot + live animated star counter + caption
python3 $S/make_broll_web.py anthropics/anthropic-sdk-python --preset github

# 4) Several github money-shots at once
python3 $S/make_broll_web.py https://github.com/owner/repo \
  --preset github --shots header,readme,contrib

# 5) Spotlight push-in onto one element of a page (darkened context + highlight)
python3 $S/make_broll_web.py https://news.site/article \
  --mode spotlight --selector "h1"

# 6) Base + avatar PiP overlay in one shot (avatar circle, bottom-right)
python3 $S/make_broll_web.py owner/repo --preset github \
  --avatar lolo/generated-videos/scene01.mp4 --layout pip-circle --corner br
```

Output: numbered clips under `--out-dir` (default `broll_web/`) + a
`manifest.json` that drops into `avatar-reel-composer` (see Integration).

## How it works

```
capture.py   Playwright headless Chromium @ device_scale_factor 2 (retina-crisp).
             viewport | full-page (tall, for scroll) | element (with bbox) |
             github money-shots + live stars/forks/lang via the GitHub API.
   ↓ PNG (+ bbox / stats)
motion.py    PIL framing (blurred-fill bg + sharp rounded+shadowed content) →
             ffmpeg motion: Ken Burns (in/out/left/right/up/down), scroll-reveal,
             or spotlight push-in. Optional animated count-up (star counter) +
             lower caption.
   ↓ base clip (silent)
pip_overlay.py (optional, --avatar)  composite the talking avatar in a PiP
             circle (default) or split; the avatar's audio drives the length,
             the base loops to cover it.
   ↓ final clip + manifest entry
```

## Presets

| Preset | Input | Default behavior |
|---|---|---|
| `generic` (auto) | any URL | framed Ken Burns push-in (`--mode scroll` for a full page) |
| `landing` | a landing/marketing page | full-page **scroll-reveal** by default |
| `producthunt` | a product page | like `landing` |
| `github` | `owner/repo` or a github URL | repo money-shots + **animated star counter** + `owner/repo` caption |

`github` shots (`--shots`, default `header`): `header` (repo landing, gets the
star counter), `readme` (tall → scroll-reveal), `contrib` (the contribution
calendar from the owner's profile). Defaults to **dark mode** (`--no-dark` for
light). Selectors fall back gracefully since GitHub's DOM drifts.

## Motion modes (`--mode`)

Two families:

- **Full-bleed navigation** (capture fills the frame at native resolution —
  *legible*, best for dense pages like GitHub): `pan-right` / `pan-left`
  (horizontal scroll from the top-left corner across the page width),
  `pan-down` / `pan-up` (vertical scroll), `zoom-tl` (zoom into the top-left
  corner), `zoom-center`.
- **Card framing** (capture shrunk onto a blurred-fill background — best for a
  clean landing page seen whole): `in` / `out` (center zoom),
  `left` / `right` / `up` / `down` (pan), `spotlight` (push-in toward
  `--selector` with a highlight box), `static`.

Plus `scroll` (vertical reveal over a tall full-page capture). `auto` picks a
sensible default per preset — **github → `pan-right`** (full-bleed, legible),
landing → `scroll`, generic → `in`.

## Avatar PiP overlay (`--avatar`)

- `--layout pip-circle` (default): avatar masked into a corner circle over a
  near-full base — best for technical content (the base is the value).
- `--layout split`: base on top, avatar on the bottom — when the avatar's
  gestures matter more.
- `--corner br|bl|tr|tl` (default `br`). When there's a bottom caption, a
  bottom-corner PiP is **lifted automatically** so it never covers the
  repo/site name (tune with `pip_overlay.py --bottom-clear`).
- `--face-bias 0..1` (default `0.4`): vertical crop of the circle; lower keeps
  more of the **top (the face)**. A circle reads as a face, so the avatar must
  be face-forward.

### Material this scene needs (READ THIS when building a reel)

This skill is called **on-demand while producing a reel**. For the PiP to look
right, prepare the avatar layer accordingly:

1. **Face-focused, locked avatar clip.** The circle is small and must read as a
   face, so feed a **tight, centered, face-forward** talking clip whose **face
   stays put** — no push-in/out, zoom or dolly. Don't reuse a generic close-up:
   generate a **dedicated** shot with
   [`avatar-camera-angles`](../avatar-camera-angles/SKILL.md) using the **`pip`**
   move at `1:1` (a centered, even-margin badge framing):

   ```bash
   python3 ~/.cursor/skills/avatar-camera-angles/scripts/generate_angles.py \
     --ref frame.png --scene-file scene.json --move pip -ar 1:1 -o avatar/pip/
   ```

   Then lip-sync that still with
   [`avatar-talking-video`](../avatar-talking-video/SKILL.md) (`p-video-avatar`)
   — **always p-video-avatar for the PiP, not seedance** — on a **locked
   camera** (`--video-prompt "The person is talking, head still, no camera
   movement"`; no push/pull/zoom/dolly). Generate the `pip` angle on-demand when
   a reel needs it and it doesn't exist yet — don't substitute
   `push_in`/`pull_out`. This skill's compositor **never zooms the avatar**:
   motion comes only from the base layer, so any drift inside the circle comes
   from the source clip — keep it locked.
2. **No burned-in subtitles in the avatar clip.** The segment's **subtitles go
   on the full reel frame**, not inside the PiP. Leave the avatar clean; let
   `avatar-reel-composer`'s finishing pass burn captions over the whole 9:16
   (they read across the base + PiP, never trapped in the circle).
3. **Matte for a clean cut-out (recommended).** Run the avatar through
   [`video-bg-replace`](../video-bg-replace/SKILL.md) to get a transparent
   webm/mov so only the person shows in the circle; without it the avatar's own
   background fills the circle (acceptable, less clean).
4. **Audio.** The avatar clip carries the segment's voice and sets the clip
   length; the base loops to cover it.

## Key options

| Flag | Default | Notes |
|---|---|---|
| `--preset` | `auto` | `generic\|landing\|producthunt\|github` |
| `--mode` | `auto` | see Motion modes |
| `--aspect` | `9:16` | `9:16\|16:9\|1:1\|4:5` |
| `--duration` | `5.0` | seconds (scroll auto-extends) |
| `--viewport WxH` | `1440x900` | capture viewport |
| `--full-page` | off | capture the whole scrollable page |
| `--dark` / `--no-dark` | github=dark | color scheme |
| `--selector CSS` | – | element to capture / spotlight |
| `--hide CSS` | – | hide a selector (cookie banners; repeatable) |
| `--shots` | `header` | github: `header,readme,contrib` |
| `--no-counter` | off | disable the github star counter |
| `--caption TEXT` | github=`owner/repo` | lower caption (`''` to disable) |
| `--avatar PATH` | – | composite avatar PiP overlay (face-focused + **locked** `pip` clip, no burned subs) |
| `--layout / --corner` | `pip-circle` / `br` | PiP placement |
| `--face-bias` | `0.4` | vertical crop of the PiP circle (lower keeps the face) |
| `--out-dir` / `--slug` | `broll_web/` / from URL | output location + filename |

## Integration with avatar-reel-composer

Each clip is a drop-in B-roll scene. In the storyboard:

```json
{ "id": "s2", "type": "broll", "broll_source": "existing",
  "broll_clip": "broll_web/001_owner-repo-header.mp4", "text": "..." }
```

The composer loops/pads it to the narration slot. For a base + avatar shot,
generate it here with `--avatar` and reference the final clip the same way.

**Subtitles belong to the reel, not the clip.** Don't burn captions here or into
the avatar — `avatar-reel-composer`'s finishing pass burns the segment subtitles
over the **whole 9:16 frame**, so they read across the base + PiP. The only text
this skill burns is the small source **caption** (repo/site name), which is a
label, not subtitles.

## Notes

- Base clips are **silent** (stills have no audio); the avatar carries audio.
- Capture shares the Playwright stack with the `web-screenshot` skill.
- See [REFERENCE.md](REFERENCE.md) for the polished-look recipe, the ffmpeg
  motion expressions, GitHub selector overrides, and troubleshooting.
```
