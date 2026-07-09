---
name: broll-terminal
description: Turn a declarative session JSON into a short, realistic animated-terminal B-roll clip for technical reels — commands typed with human jitter (variable per-key delay, the odd typo+backspace), output that streams in with spinners and ANSI colors, a macOS/Warp-style window, themed and high-DPI. Renders deterministically with HTML/CSS + Playwright (frame-exact, reproducible) and NEVER executes a real shell. Optionally composites the talking avatar in a PiP corner (the "base + avatar overlay" architecture). Use when you want B-roll of terminal commands, a CLI demo, code/agent commands shown on screen, or animated proof footage of a tool/pipeline running, to overlay under narration in a short video.
---

# broll-terminal

Produce the **base layer** of a technical reel from an animated terminal. In a
40–60s reel a full live demo doesn't fit; a tight, believable terminal that
types a command and streams a little output is the right register — it
illustrates while the narration/avatar carries the message.

It renders **deterministically** (HTML/CSS + Playwright, frame by frame) so the
output is crisp and reproducible, and it **never runs a real shell** — the
"output" is whatever your `session.json` declares. Zero risk to your machine.

Two-layer architecture (shared with `broll-web-capture`, see `brand-content-strategy`):

```
broll-terminal / broll-web-capture    ← BASE layer (proof visual)
        +
talking avatar in PiP                  ← OVERLAY layer (credential anchor)
```

## When to use

- "Make B-roll of these commands running in a terminal."
- "Show the CLI / the agent orchestrator doing its thing."
- "Animated terminal to overlay under my narration."

## Setup

```bash
pip3 install -r .cursor/skills/broll-core/scripts/requirements.txt
pip3 install -r .cursor/skills/broll-terminal/scripts/requirements.txt
playwright install chromium
```

Requires the **`broll-core`** skill alongside this one (shared geometry + the PiP
compositor) and `ffmpeg`/`ffprobe` on PATH. Fonts: it prefers JetBrains Mono /
Fira Code if installed and falls back to **Menlo** (always present on macOS), so
no font download is needed.

## Quick start

```bash
S=.cursor/skills/broll-terminal/scripts

# 1) Render the bundled example -> 9:16 base clip
python3 $S/make_broll_terminal.py $S/../examples/session.json

# 2) Your own session, one-dark theme, a kicker label
python3 $S/make_broll_terminal.py my_session.json \
  --theme one-dark --kicker "build pipeline"

# 3) Base + avatar PiP overlay (avatar circle, bottom-right)
python3 $S/make_broll_terminal.py my_session.json \
  --avatar lolo/generated-videos/pip_locked.mp4 --layout pip-circle --corner br
```

Output: a numbered clip under `--out-dir` (default `broll_terminal/`) + a
`manifest.json` that drops into `avatar-reel-composer` (see Integration).

## How it works

```
timeline.py   session JSON -> deterministic event list with absolute-ms timing:
              human typing jitter (variable per-key delay, space/punct pauses,
              an occasional typo+backspace), output that streams line-by-line
              after a believable latency, spinners, an ending "ready" prompt.
   ↓ timeline
terminal.html Playwright loads it (high-DPI) and exposes seekTo(t); themed Warp/
              iTerm-style window (chrome, blinking cursor, ANSI colors, autoscroll).
render_terminal.py  drives seekTo(t) once per frame, screenshots each (frame-exact),
              muxes the PNG sequence to H.264 at the canonical reel dims.
   ↓ base clip (silent)
pip_overlay.py (broll-core, optional --avatar)  composite the talking avatar in a
              PiP circle/split; the avatar's audio drives length, base loops.
   ↓ final clip + manifest entry
```

## The session JSON

Everything but `steps` is optional. Commands are plain text (typed key by key);
output lines + the prompt accept inline color markup `{g}…{/}` (green), plus
`r y b c m w dim bold`.

```json
{
  "theme": "warp-dark",                 // warp-dark | one-dark | mono-light
  "title": "zsh — virtual-avatar",      // window title-bar text
  "kicker": "agent orchestration",      // small uppercase label above the window
  "cwd": "~/virtual-avatar", "branch": "main",   // builds a starship-ish prompt
  "font_size": 19,                       // logical px; smaller = more columns
  "typing": { "typo_chance": 0.25 },     // see REFERENCE.md for all knobs
  "steps": [
    { "cmd": "reel make --topic \"ai agents\" --avatar lolo" },
    { "out": ["{dim}▸ discovering…{/}", "{g}✓{/} ranked 18"], "stream_ms": 320 },
    { "spinner": "rendering avatar", "duration_ms": 1800, "done": "{g}✓{/} ready" },
    { "sleep_ms": 350 },
    { "cmd": "ls reels/" },
    { "out": "001_ai-agents.mp4  cover.png" }
  ],
  "tail_ms": 1200
}
```

Keep commands **short** (≈40 cols at the default size) so they don't wrap, and
keep clips tight — a single beat (one command + a few output lines) reads best.

## Avatar PiP overlay (`--avatar`)

Same compositor (and rules) as `broll-web-capture`, from `broll-core`:

- `--layout pip-circle` (default): avatar in a corner circle over the near-full
  terminal — `--corner br` (default) sits over the terminal's empty lower area,
  so it rarely covers text.
- `--layout split`: terminal on top, avatar on the bottom.
- `--face-bias 0..1` (default `0.4`): vertical crop of the circle (lower keeps
  the face).
- The avatar clip must be a **static, face-forward `pip` shot**
  (`avatar-camera-angles --move pip`) lip-synced **locked** with
  **`avatar-talking-video` (`p-video-avatar`)** — the compositor never moves the
  avatar, so any drift inside the circle comes from the source clip.
- The base is **silent**; the avatar carries the audio and sets the length (the
  terminal's `tail_ms` auto-extends to cover the narration, so the typing never
  loops mid-clip).

## Key options

| Flag | Default | Notes |
|---|---|---|
| `session` | — | path to the session JSON |
| `--aspect` | `9:16` | `9:16\|16:9\|1:1\|4:5` |
| `--fps` | `30` | frame rate (lower = faster render) |
| `--seed` | `7` | RNG seed for typing jitter (change for a different "hand") |
| `--duration` | auto | force total seconds (≥ natural extends the ready-prompt hold) |
| `--theme / --title / --kicker` | from JSON | overrides |
| `--avatar PATH` | – | composite avatar PiP overlay (locked `pip` clip) |
| `--layout / --corner` | `pip-circle` / `br` | PiP placement |
| `--face-bias` | `0.4` | vertical crop of the PiP circle |
| `--out-dir / --slug` | `broll_terminal/` / from filename | output location + name |
| `--keep-frames` | off | keep the PNG sequence (debug) |

## Integration with avatar-reel-composer

Each clip is a drop-in B-roll scene:

```json
{ "id": "s3", "type": "broll", "broll_source": "existing",
  "broll_clip": "broll_terminal/001_session.mp4", "text": "..." }
```

**Subtitles belong to the reel, not the clip.** Don't bake captions into the
terminal or the avatar — `avatar-reel-composer`'s finishing pass burns the
segment subtitles over the **whole 9:16 frame**. The only text this skill draws
is the terminal's own content + the optional `kicker` label.

## Notes

- Base clips are **silent**; the avatar carries audio.
- Rendering is one screenshot per frame, so cost scales with `fps × duration`
  (≈28s for a 16s clip at 15fps). Drop `--fps` for quick drafts.
- See [REFERENCE.md](REFERENCE.md) for the full session schema, the timeline
  model (keystroke replay + typo logic), theming, and troubleshooting.
```
