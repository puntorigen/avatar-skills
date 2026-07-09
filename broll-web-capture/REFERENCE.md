# broll-web-capture — reference

Detail for the workflow in [SKILL.md](SKILL.md). The three scripts are also
importable modules (`capture`, `motion`, `pip_overlay`) so the orchestrator and
other skills can reuse them.

---

## 1. The polished look (why it reads as "produced")

A raw landscape screenshot dropped into a 9:16 frame looks amateur. The framing
in `motion.compose_frame` makes it read as intentional B-roll:

1. **Blurred-fill background** — the same capture, cover-scaled to the frame,
   heavily Gaussian-blurred and darkened. Fills the 9:16 frame with on-brand
   color instead of black bars.
2. **Sharp content card** — the capture scaled to fit (with a margin), with
   **rounded corners** and a soft **drop shadow** so it floats above the bg.
3. **Subtle motion** — a slow Ken Burns push-in (zoom 1.0→~1.12) keeps it alive
   without distracting. Keep zoom modest so the screenshot stays crisp.

When the capture aspect already matches the target (e.g. a 16:9 capture for a
16:9 output) the card nearly fills the frame; the blurred bg only shows at the
edges.

---

## 2. Motion modes & the ffmpeg expressions

`motion.render_motion` builds a `zoompan` graph. To avoid zoompan's classic
sub-pixel jitter, the still is **pre-scaled** (`prescale=2`) before zoompan
downsamples to the target — that smooths the move.

| Mode | What | Expression sketch |
|---|---|---|
| `in` | center push-in | `z=min(zoom+step,zmax)`, x/y centered |
| `out` | center pull-out | `z=if(on==0,zmax,max(zoom-step,1))` |
| `left`/`right` | horizontal pan at constant zoom | `x=(iw-iw/zoom)*prog` |
| `up`/`down` | vertical pan | `y=(ih-ih/zoom)*prog` |
| `spotlight` | push-in toward a focus point | x/y clamped to center on `focus` |
| `static` | held frame (letterboxed) | no zoompan |

`render_scroll` is a separate graph for **tall** full-page captures: the content
is scaled to a centered column and `overlay`'d on a blurred bg with an animated
`y` (cosine-eased). If the page isn't tall enough to scroll it falls back to a
push-in automatically.

**Full-bleed navigation (`render_navigate`)** is the legible alternative to the
card framing: instead of shrinking the whole capture into a centered card (tiny
for a dense landscape page), it scales the capture to **cover** the frame and
moves a target-aspect crop window across it at native resolution. Modes:
`pan-right`/`pan-left` (height-cover, horizontal crop pan from the top-left,
`y=0`), `pan-down`/`pan-up` (width-cover, vertical pan), `zoom-tl`/`zoom-center`
(cover, then a shrinking crop window anchored at the corner/center). This is the
**github default (`pan-right`)** because repo pages are dense and unreadable when
shrunk. Use the card framing instead when the whole page reads well small (a
clean hero/landing).

Tunables: `--duration`, `--fps` (default 30), `zoom_max` / `prescale` (in code).
Default reel dims come from `_common.ASPECTS` (9:16 = 1080×1920).

---

## 3. Spotlight (highlight one element)

`--mode spotlight --selector "<css>"`:

1. `capture.capture_page(focus_selector=...)` grabs the **full viewport** and
   measures the element's bounding box (image px = CSS px × device scale).
2. `compose_frame(focus_bbox=..., highlight=True)` draws an accent rounded border
   around the mapped box and returns its center.
3. `render_motion(mode="spotlight", focus=center)` pushes in toward it.

Spotlight uses a viewport capture (not full-page) so the bbox is meaningful;
pick an element that's above the fold or set a taller `--viewport`.

---

## 4. GitHub preset internals

- **Stats:** `capture.github_stats(owner, repo)` hits
  `api.github.com/repos/{owner}/{repo}` (User-Agent required; `GITHUB_TOKEN`
  optional). Returns stars / forks / language / description / full_name. If the
  API is unreachable it degrades gracefully (no counter).
- **Money-shots:** `github_shots` captures
  - `header` → repo landing viewport (name + description + stars + README top),
  - `readme` → `article.markdown-body` (tall → scroll-reveal),
  - `contrib` → the owner profile's contribution calendar
    (`.js-calendar-graph, .ContributionCalendar, …`).
- **Star counter:** `motion.add_counter` overlays an animated count-up
  (`0 → stars`) via a `drawtext` `%{eif:…}` expression, drawn as `★ N` in a pill.
- **Selector drift:** GitHub changes its DOM. If a shot looks wrong, override the
  viewport (`--viewport`) or drop the failing shot from `--shots`; `header` is a
  full-viewport grab and is the most robust.

---

## 5. Avatar PiP overlay (`pip_overlay.py`)

The compositor for the **base + avatar** architecture (reused by the future
`broll-demo-avatar` skill):

- **pip-circle (default):** avatar cover-cropped to a square, masked into a
  circle (PIL mask + ffmpeg `alphamerge`), overlaid in a corner with an optional
  white ring. Diameter = `--diameter` × width (default 0.36). Corner via
  `--corner`.
- **split:** base and avatar each cover-cropped to half height and `vstack`'d.
- The **avatar audio drives length** (`-t <avatar duration>`); the base is
  `-stream_loop -1` looped and `-shortest`-trimmed.
- For a clean cut-out, matte the avatar first with `video-bg-replace` (alpha
  webm/mov). Without a matte, the avatar's own background shows inside the
  circle — acceptable for most reels.
- **`face_bias`** (default 0.4) sets the vertical crop of the circle so the
  **face** stays in frame (a circle reads as a face). Lower = keep more of the
  top. Pair it with a face-focused source.
- A bottom-corner PiP is auto-lifted (`bottom_clear`) when there's a caption, so
  it never covers the repo/site name.
- **No avatar motion here.** The compositor only scales/cover-crops and overlays
  statically — it never zooms or dollies the avatar. Any movement inside the
  circle comes from the *source clip*, so that clip must be locked (see below).

### Material requirements (this scene type, on-demand in a reel)

When the agent builds a reel that uses a base + avatar PiP, it must prepare the
avatar layer specifically — this is *different material* from a full-frame
talking head:

1. **Face-focused, tight, LOCKED framing.** Generate a **dedicated** badge shot
   with `avatar-camera-angles` using the **`pip`** move at `1:1`
   (`--move pip -ar 1:1`) — a centered, even-margin close-up — then lip-sync it
   with **`avatar-talking-video` (`p-video-avatar`, always for the PiP — not
   seedance)** on a **locked camera** (no push-in/out, zoom or dolly;
   `--video-prompt "The person is talking, head still, no camera movement"`).
   Don't reuse `push_in`/`pull_out` and don't let the source clip drift: the
   face must stay put inside the circle. Generate the `pip` angle on-demand if it
   doesn't exist yet. A waist/wide shot disappears in the circle.
2. **No burned-in subtitles in the avatar.** Subtitles are a **reel-level**
   concern: `avatar-reel-composer`'s finish pass burns the segment captions over
   the whole 9:16 frame (across base + PiP). Captions trapped inside the circle
   are wrong. The only burned text here is the small source caption (repo/site
   name).
3. **Matte (recommended).** `video-bg-replace` → transparent avatar so only the
   person shows in the circle.

---

## 6. Output & integration

Each run appends to `<out-dir>/manifest.json` (`{"clips": [...]}`), with per-clip
`id`, `clip` path, `preset`, `mode`, `aspect`, `duration`, and (github) `repo` /
`stars` / `shot`. Drop a clip into an `avatar-reel-composer` storyboard as a
`broll_source: "existing"` scene with `broll_clip: <path>`; the composer loops or
freeze-pads it to the narration slot. Base clips are silent by design.

Working files live under `<out-dir>/_<slug>_work/` (stills, intermediate clips,
masks) and can be deleted after.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `playwright` import error | `pip3 install -r scripts/requirements.txt && playwright install chromium` |
| Cookie/consent banner in capture | `--hide "<selector>"` (a few common ones are hidden by default) |
| Blurry screenshot when zoomed | raise capture `--viewport` (more pixels) or lower `zoom_max` |
| Star counter missing | GitHub API rate-limited/unreachable — set `GITHUB_TOKEN`, or `--no-counter` |
| README shot not scrolling | it wasn't tall enough → rendered as a push-in (expected) |
| Avatar circle shows a background | matte it first with `video-bg-replace` |
| `drawtext` font error | install a TTF (DejaVu) or rely on the macOS Arial fallback in `_common.find_font` |
```
