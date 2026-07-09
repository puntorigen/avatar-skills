# broll-terminal — reference

Internals and design notes. The skill turns a declarative `session.json` into a
realistic animated-terminal B-roll clip, deterministically and without ever
running a real shell.

## 1. Why this approach (realism)

A fake terminal is given away by three things; we fix each:

1. **Robotic typing.** Real typing has variable per-key cadence. `timeline.py`
   gives every keystroke a jittered delay (`min_ms..max_ms`), adds a little on
   spaces and punctuation, and — with `typo_chance` — occasionally types a wrong
   char or two, pauses to "notice", backspaces, and resumes.
2. **Output dumping all at once.** Real output appears after a latency and then
   streams. Output lines get a `latency_ms` after the command, then arrive one
   by one (`stream_ms` apart); spinners animate over a duration then resolve.
3. **Generic look.** A Warp/iTerm-style window (traffic lights, title bar, soft
   shadow, rounded corners), a real coding font (JetBrains Mono → Menlo), a
   starship-ish colored prompt, ANSI-colored output, a blinking block cursor.

Rendering is **deterministic frame capture**: the page exposes `seekTo(t)`, a
pure function of time, and we screenshot one frame per output frame. No video
recording, so no dropped frames or timing drift; the same `--seed` always yields
the same clip.

## 2. Pipeline & files

```
timeline.py        session JSON -> {lines[], durationMs, theme, font, ...}
terminal.html      themed renderer: window.__INIT__(data) + window.seekTo(tMs)
render_terminal.py Playwright high-DPI capture: seekTo per frame -> PNG seq -> H.264
make_broll_terminal.py  orchestrator: render base (+ optional avatar PiP) -> numbered clip + manifest
```

Shared from **`broll-core`** (single source of truth, imported via a sys.path
shim resolved relative to the skill): `_common.py` (geometry/ffmpeg/manifest) and
`pip_overlay.py` (the avatar-PiP compositor). Nothing is duplicated here.

## 3. The timeline model (`timeline.py`)

The terminal is an ordered list of `lines`, each carrying absolute-ms timing:

- **`cmd`** — a prompt + a typed command. Instead of a naive prefix, it stores a
  **keystroke list** (`keys: [{t, ch} | {t, bs:true}]`). `seekTo(t)` rebuilds the
  visible string by replaying every key with `t <= now` (append, or pop on
  backspace). This is what makes typo-corrections render correctly. `start` is
  when the prompt appears; `submitT` is when Enter is "pressed" (the cursor is
  active/blinking only while `start <= t < submitT`).
- **`out`** — a pre-rendered HTML line (escaped + markup expanded), shown at `t`.
- **`spin`** — a spinner that animates braille frames (`periodMs`) between
  `tStart` and `tEnd`, then is replaced by `doneHtml`.

A trailing **empty "ready" prompt** is appended so the clip ends on a calm
blinking cursor instead of mid-output; `tail_ms` holds on it.

### Session schema (all ms; everything but `steps` optional)

| Key | Default | Meaning |
|---|---|---|
| `theme` | `warp-dark` | `warp-dark` / `one-dark` / `mono-light` |
| `font` / `font_size` | JetBrains Mono / `19` | font family (→ Menlo) and logical px |
| `title` | `""` | window title-bar text |
| `kicker` | `""` | small uppercase label above the window |
| `prompt` | — | explicit prompt markup; else built from `cwd` + `branch` |
| `cwd` / `branch` | `~` / `main` | starship-ish auto prompt |
| `typing.min_ms/max_ms` | `42`/`120` | per-key delay range |
| `typing.space_extra_ms` | `60` | extra pause on space |
| `typing.punct_extra_ms` | `45` | extra pause on `,.;:/_-="'` |
| `typing.pre_type_ms` | `220` | "think" pause before a command starts typing |
| `typing.submit_pause_ms` | `320` | pause after typing before Enter |
| `typing.typo_chance` | `0.10` | probability of one stumble per long (≥10-char) command |
| `output.latency_ms` | `420` | delay after Enter before output |
| `output.stream_ms` | `170` | gap between streamed output lines |
| `output.spinner_period_ms` | `90` | spinner frame period |
| `tail_ms` | `1100` | hold on the ending ready prompt |

Per-step overrides: `cmd` steps accept `pre_type_ms` / `submit_pause_ms`; `out`
steps accept `latency_ms` / `stream_ms`; `spinner` steps accept `latency_ms` /
`duration_ms` / `done` / `period_ms`; `sleep_ms` inserts a pause.

### Inline markup

`{g}` green `{r}` red `{y}` yellow `{b}` blue `{c}` cyan `{m}` magenta `{w}`
white `{dim}` muted `{bold}` bold, closed with `{/}`. Applies to **output lines
and the prompt only** — commands are plain (monochrome, like real typing). Text
is HTML-escaped first, so `<`, `&`, quotes are safe.

## 4. Renderer (`terminal.html`)

- Themes are CSS-variable sets selected by `body[data-theme]`. Colors map to
  `.c-g/.c-r/...`, `.dim`, `.bold`.
- The page **is the full target frame** (no separate framing step): a gradient
  background, the window centered (`92vw × 74vh`), title bar, and a scrolling
  `#screen`. Autoscroll keeps the latest line visible by translating `#content`
  up when it overflows (real terminal tail behavior).
- High-DPI: rendered at `viewport = (W/scale, H/scale)` with
  `device_scale_factor = scale` (default 2) → screenshots land at the canonical
  reel dims (e.g. 1080×1920) with supersampled, crisp text.
- The blinking cursor is a CSS block toggled by `Math.floor(t/530)%2`, shown only
  on the active command line.

## 5. Avatar PiP overlay

Delegated to `broll-core`'s `pip_overlay.overlay_pip` — identical to
`broll-web-capture`. The orchestrator probes the avatar duration and renders the
base to **match** it (extending the ready-prompt hold via `render_base(duration=…)`),
so the looped base never restarts the typing mid-clip.

**Material the PiP needs:** a static, face-forward **`pip`** shot
(`avatar-camera-angles --move pip` at `1:1`) lip-synced **locked** with
`avatar-talking-video` (`p-video-avatar`). No camera move, no burned-in
subtitles (those go on the whole reel via `avatar-reel-composer`).

## 6. Output & integration

Each run appends to `<out-dir>/manifest.json` (`{"clips":[...]}`) with per-clip
`id` (`NNN_slug`), `clip`, `source: "broll-terminal"`, `aspect`, `fps`,
`duration`, `theme`, `silent`, `avatar`. Reference the clip in an
`avatar-reel-composer` storyboard as a `broll` scene with
`broll_source: "existing"`.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `broll-core not found` | install the `broll-core` skill next to this one (same `.cursor/skills/` dir) |
| `playwright` import error | `pip3 install -r scripts/requirements.txt && playwright install chromium` |
| Commands wrap onto 2 lines | shorten the command or lower `font_size` (more columns) |
| Render feels slow | drop `--fps` (cost = fps × duration screenshots); 15fps is fine for drafts |
| Fonts look generic | install JetBrains Mono / Fira Code; otherwise Menlo is used |
| Typing too fast/slow | tune `typing.min_ms`/`max_ms`; bump `typo_chance` for more "human" stumbles |
| PiP avatar drifts/zooms | the source clip isn't locked — regenerate the `pip` shot lip-synced locked (p-video-avatar) |
```
