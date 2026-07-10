# broll-cursor — reference

Internals and design notes. The skill turns a declarative `session.json` into a
realistic animated **IDE agent-chat** B-roll clip (a Cursor-style "Agent" panel),
deterministically and without ever running a real agent or shell. It is the sibling
of `broll-terminal` and shares its render/PiP/manifest harness via `broll-core`.

## 1. Why this approach (realism)

A fake agent chat is given away by three things; we fix each:

1. **Robotic typing.** Real typing has variable per-key cadence. `timeline.py` gives
   the user prompt's every keystroke a jittered delay (`min_ms..max_ms`), adds a
   little on spaces/punctuation, and — with `typo_chance` — occasionally types a
   wrong char, pauses to "notice", backspaces, and resumes. (Same model as
   `broll-terminal`.)
2. **Everything appearing at once.** A real assistant streams. Assistant `say` lines
   reveal token-by-token at `assistant.cps` chars/sec after a latency; tool rows
   spin for `duration_ms` then resolve to a checkmark; the transcript grows and
   autoscrolls.
3. **Generic look.** A Cursor-style window (traffic lights, title bar, an "✦ Agent"
   header with a model pill, user bubbles + assistant text + bordered tool-call rows,
   a composer with a blinking caret and a send button), UI-sans chat text with
   monospace tool names/paths.

Rendering is **deterministic frame capture**: the page exposes `seekTo(t)`, a pure
function of time, and we screenshot one frame per output frame. No video recording,
so no dropped frames or timing drift; the same `--seed` always yields the same clip.

## 2. Pipeline & files

```
timeline.py         session JSON -> {events[], durationMs, theme, ...}
cursor.html         themed renderer: window.__INIT__(data) + window.seekTo(tMs)
render_cursor.py    Playwright high-DPI capture: seekTo per frame -> PNG seq -> H.264
make_broll_cursor.py  orchestrator: render base (+ optional avatar PiP) -> numbered clip + manifest
```

Shared from **`broll-core`** (single source of truth, imported via a sys.path shim
resolved relative to the skill): `_common.py` (geometry/ffmpeg/manifest) and
`pip_overlay.py` (the avatar-PiP compositor). Nothing is duplicated here.

## 3. The timeline model (`timeline.py`)

The chat is an ordered list of `events`, each carrying absolute-ms timing:

- **`user`** — a prompt typed into the composer. Stored as a **keystroke list**
  (`keys: [{t, ch} | {t, bs:true}]`) plus `start` (composer caret appears), `submitT`
  (Enter pressed → the text moves from the composer to a **user bubble** in the
  transcript), and `textHtml` (the escaped full prompt for the bubble). `seekTo(t)`
  rebuilds the composer string by replaying keys with `t <= now` (append / pop on
  backspace), so typo-corrections render correctly.
- **`say`** — an assistant message. `{t0, t1, msPerChar, text}`. `seekTo(t)` shows
  `text.slice(0, floor((t-t0)/msPerChar))` with a thin caret while `t < t1`. Inline
  `{tag}…{/}` markup is expanded on the (possibly truncated) slice, closing any span
  left open by mid-stream truncation.
- **`tool`** — a tool-call row (a skill). `{tStart, tEnd, name, detail, done,
  periodMs}`. Before `tStart` hidden; `tStart..tEnd` a braille spinner + `name` +
  `detail`; after `tEnd` a green check + `name` + `done`.

There is no trailing "ready prompt" line (that's a terminal idiom); instead `tail_ms`
holds on the finished transcript with an empty composer.

### Session schema (all ms; everything but `steps` optional)

| Key | Default | Meaning |
|---|---|---|
| `theme` | `cursor-dark` | `cursor-dark` / `cursor-light` |
| `title` | `""` | window title-bar text |
| `kicker` | `""` | small uppercase label above the window |
| `model` | `""` | model pill in the header + composer bar (empty = hidden pill) |
| `agent_name` | `Agent` | header label + assistant role name |
| `font_size` | `21` | base chat font (logical px in the W/scale capture space) |
| `placeholder` | `Plan, search, build anything…` | composer placeholder when idle |
| `typing.min_ms/max_ms` | `34`/`92` | per-key delay range |
| `typing.space_extra_ms` | `40` | extra pause on space |
| `typing.punct_extra_ms` | `28` | extra pause on `,.;:/_-="'` |
| `typing.pre_type_ms` | `180` | "think" pause before the prompt starts typing |
| `typing.submit_pause_ms` | `260` | pause after typing before "Enter" |
| `typing.typo_chance` | `0.10` | probability of one stumble per long (≥10-char) prompt |
| `assistant.cps` | `55` | assistant streaming speed (chars/sec) |
| `assistant.latency_ms` | `320` | delay before a `say` starts streaming |
| `assistant.line_gap_ms` | `260` | gap after a `say` / `tool` before the next event |
| `assistant.tool_gap_ms` | `170` | delay before a `tool` row appears |
| `assistant.spinner_period_ms` | `90` | tool-row spinner frame period |
| `tail_ms` | `1000` | hold on the finished transcript |

Per-step overrides: `user` steps accept `pre_type_ms` / `submit_pause_ms`; `say`
steps accept `latency_ms` / `line_gap_ms`; `tool` steps accept `tool_gap_ms` /
`duration_ms` / `line_gap_ms` / `period_ms`; `sleep_ms` inserts a pause.

### Inline markup (assistant `say` only)

`{g}` green `{r}` red `{y}` yellow `{b}` blue `{c}` cyan `{m}` magenta `{w}` white
`{dim}` muted `{bold}` bold, closed with `{/}`. Text is HTML-escaped first, so `<`,
`&`, quotes are safe. The user prompt is plain (typed like real text); tool
`name`/`detail`/`done` are plain-escaped.

## 4. Renderer (`cursor.html`)

- Themes are CSS-variable sets selected by `body[data-theme]` (`cursor-dark` /
  `cursor-light`).
- The page **is the full target frame**: a gradient background, the window centered
  (`92vw × 84vh`), title bar, chat header, a scrolling `#screen`/`#content`
  transcript, and a fixed composer at the bottom. Autoscroll keeps the latest message
  visible by translating `#content` up when it overflows (real chat tail behavior).
- High-DPI: rendered at `viewport = (W/scale, H/scale)` with
  `device_scale_factor = scale` (default 2) → screenshots land at the canonical reel
  dims (e.g. 1080×1920) with supersampled, crisp text.
- The blinking caret (composer + streaming `say`) is toggled by
  `Math.floor(t/530)%2`.

## 5. Avatar PiP overlay

Delegated to `broll-core`'s `pip_overlay.overlay_pip` — identical to `broll-terminal`
/ `broll-web-capture`. The orchestrator probes the avatar duration and renders the
base to **match** it (extending the ending hold via `render_base(duration=…)`), so
the looped base never restarts the chat mid-clip.

**Material the PiP needs:** a static, face-forward **`pip`** shot
(`avatar-camera-angles --move pip` at `1:1`) lip-synced **locked** with
`avatar-talking-video` (`p-video-avatar`). No camera move, no burned-in subtitles
(those go on the whole reel via `avatar-reel-composer`).

## 6. Output & integration

Each run appends to `<out-dir>/manifest.json` (`{"clips":[...]}`) with per-clip `id`
(`NNN_slug`), `clip`, `source: "broll-cursor"`, `aspect`, `fps`, `duration`, `theme`,
`silent`, `avatar`. Reference the clip in an `avatar-reel-composer` storyboard as a
`broll` scene with `broll_source: "existing"`.

**Trimming to a short hook slot.** `avatar-reel-composer` trims a B-roll to its
scene's narration length **from the start**. For a ~3s opening hook, **front-load**:
raise typing speed (`typing.min_ms/max_ms` low), drop `assistant.latency_ms`, and use
short tool `duration_ms`, so the prompt is fully typed and the first skill rows tick
within the visible window. Verify by extracting a frame at the slot length
(`ffmpeg -ss <slot> -i clip.mp4 -frames:v 1 f.png`).

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `broll-core not found` | install the `broll-core` skill next to this one (same `.cursor/skills/` dir) |
| `playwright` import error | `pip3 install -r scripts/requirements.txt && playwright install chromium` |
| User prompt wraps to many lines | keep it one short sentence; it's a bubble so 2 lines is fine, but long prompts push the transcript |
| Tool row wraps | shorten `name` / `detail` / `done` |
| Render feels slow | drop `--fps` (cost = fps × duration screenshots); 15–20fps is fine for drafts |
| Assistant streams too fast/slow | tune `assistant.cps` |
| Typing too fast/slow | tune `typing.min_ms`/`max_ms`; bump `typo_chance` for more "human" stumbles |
| PiP avatar drifts/zooms | the source clip isn't locked — regenerate the `pip` shot lip-synced locked (p-video-avatar) |
```
