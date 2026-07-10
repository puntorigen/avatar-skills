---
name: broll-cursor
description: Turn a declarative session JSON into a short, realistic animated IDE agent-chat B-roll clip (a Cursor-style "Agent" panel) for technical reels — a user prompt typed with human jitter into the composer, then a streaming assistant turn with tool-call rows (skills) that spin then resolve with a check, in a themed high-DPI window. Renders deterministically with HTML/CSS + Playwright (frame-exact, reproducible) and NEVER runs a real agent or shell. Optionally composites the talking avatar in a PiP corner (the "base + avatar overlay" architecture). Use when you want B-roll of an AI coding agent / Cursor chat, an agent prompt + streamed skill/tool calls shown on screen, or "the request that built this" proof footage, to overlay under narration in a short video. Sibling of broll-terminal (shell) — use this one for IDE/agent-chat, that one for a command line.
---

# broll-cursor

Produce the **base layer** of a technical reel from an animated **IDE agent chat**
— a Cursor-style "Agent" panel. It's the sibling of [`broll-terminal`](../broll-terminal/SKILL.md):
where that renders a shell (typed commands + streamed stdout), this renders a chat
(a typed user prompt + a streaming assistant turn with **tool-call rows**). Use it
when the story is "someone asked an agent to do something and it did it" — the exact
register for a set of **Cursor skills**.

It renders **deterministically** (HTML/CSS + Playwright, frame by frame) so the
output is crisp and reproducible, and it **never runs a real agent or shell** — the
assistant only "says"/"does" whatever your `session.json` declares.

Two-layer architecture (shared with `broll-terminal` / `broll-web-capture`):

```
broll-cursor / broll-terminal / broll-web-capture   ← BASE layer (proof visual)
        +
talking avatar in PiP                                ← OVERLAY layer (credential anchor)
```

## When to use

- "Make B-roll of a Cursor / AI agent chat doing this."
- "Show the agent being prompted and streaming the skills/tool-calls."
- "Animated 'this is the request that built the video' opener."
- Anything where the proof visual is an **IDE agent conversation** (not a terminal).

Use [`broll-terminal`](../broll-terminal/SKILL.md) instead when the proof visual is a
**command line** (typed commands + stdout).

## Setup

```bash
pip3 install -r .cursor/skills/broll-core/scripts/requirements.txt
pip3 install -r .cursor/skills/broll-cursor/scripts/requirements.txt
playwright install chromium
```

Requires the **`broll-core`** skill alongside this one (shared geometry + the PiP
compositor) and `ffmpeg`/`ffprobe` on PATH. Fonts: chat text uses the system UI sans
(`-apple-system`/`Segoe UI`/Inter…); tool-call rows and file paths use JetBrains Mono
/ Fira Code if installed, falling back to **Menlo** (always on macOS) — no download.

## Quick start

```bash
S=.cursor/skills/broll-cursor/scripts

# 1) Render the bundled example -> 9:16 base clip
python3 $S/make_broll_cursor.py $S/../examples/session.json

# 2) Your own session, a kicker + model pill
python3 $S/make_broll_cursor.py my_session.json \
  --kicker "one prompt → one reel" --model "claude-4.6-sonnet"

# 3) Base + avatar PiP overlay (avatar circle, bottom-right)
python3 $S/make_broll_cursor.py my_session.json \
  --avatar sherlock/generated-videos/pip_locked.mp4 --layout pip-circle --corner br
```

Output: a numbered clip under `--out-dir` (default `broll_cursor/`) + a
`manifest.json` that drops into `avatar-reel-composer` (see Integration).

## How it works

```
timeline.py   session JSON -> deterministic event list with absolute-ms timing:
              the user prompt typed with human jitter (variable per-key delay, an
              occasional typo+backspace), an assistant turn that streams token-by-
              token after a believable latency, and tool-call rows that spin then
              resolve with a checkmark.
   ↓ timeline
cursor.html   Playwright loads it (high-DPI) and exposes seekTo(t); a themed Cursor-
              style window (traffic lights, "Agent" header + model pill, message
              transcript with user bubbles / assistant text / tool rows, a composer
              with a blinking caret while typing, autoscroll tail).
render_cursor.py  drives seekTo(t) once per frame, screenshots each (frame-exact),
              muxes the PNG sequence to H.264 at the canonical reel dims.
   ↓ base clip (silent)
pip_overlay.py (broll-core, optional --avatar)  composite the talking avatar in a
              PiP circle/split; the avatar's audio drives length, base loops.
   ↓ final clip + manifest entry
```

## The session JSON

Everything but `steps` is optional. Steps run in order; the timeline threads them
into one conversation.

```json
{
  "theme": "cursor-dark",                 // cursor-dark | cursor-light
  "title": "Cursor — avatar-skills",      // window title-bar text
  "kicker": "one prompt → one reel",      // small uppercase label above the window
  "model": "claude-4.6-sonnet",           // model pill in the header + composer
  "agent_name": "Agent",                  // header / assistant label
  "font_size": 21,                        // base chat font (logical px)
  "placeholder": "Plan, search, build anything…",   // composer placeholder
  "typing": { "typo_chance": 0.1 },       // per-key jitter (see REFERENCE.md)
  "assistant": { "cps": 55 },             // assistant streaming speed (chars/sec)
  "steps": [
    { "user": "invent a Sherlock-style detective host for an avatar-skills demo" },
    { "say": "On it — building the presenter with the pipeline." },
    { "tool": "avatar-invent", "detail": "inventing the face", "duration_ms": 1600, "done": "hero + 5 angles" },
    { "say": "Done — your detective is live in {c}avatares/sherlock{/}." }
  ],
  "tail_ms": 1000
}
```

Step kinds:
- **`user`** — a prompt typed into the composer key-by-key (human jitter), then
  "sent" so it becomes a user bubble at the top of the transcript.
- **`say`** — an assistant message that streams in token-by-token. Accepts inline
  color markup `{c}…{/}` (and `g y b m w r dim bold`) for paths/keywords.
- **`tool`** — a tool-call row (a **skill**): `name` (mono) + `detail` (shown while
  it spins) → resolves to a check + `done`. `duration_ms` sets the spin time.
- **`sleep_ms`** — a pause.

Keep the user prompt to **one short sentence** and tool `name`/`done` short so rows
don't wrap. A tight beat (one prompt + a few tool rows + a closing line) reads best.

## Avatar PiP overlay (`--avatar`)

Identical compositor (and rules) as `broll-terminal`, from `broll-core`:

- `--layout pip-circle` (default): avatar in a corner circle over the near-full chat
  — `--corner br` (default) sits over the composer's empty area.
- `--layout split`: chat on top, avatar on the bottom.
- `--face-bias 0..1` (default `0.4`): vertical crop of the circle (lower keeps the face).
- The avatar clip must be a **static, face-forward `pip` shot**
  (`avatar-camera-angles --move pip`) lip-synced **locked** with
  **`avatar-talking-video` (`p-video-avatar`)**.
- The base is **silent**; the avatar carries the audio and sets the length (the
  ending hold auto-extends to cover the narration, so the chat never loops mid-clip).

## Key options

| Flag | Default | Notes |
|---|---|---|
| `session` | — | path to the session JSON |
| `--aspect` | `9:16` | `9:16\|16:9\|1:1\|4:5` |
| `--fps` | `30` | frame rate (lower = faster render) |
| `--seed` | `7` | RNG seed for typing jitter (change for a different "hand") |
| `--duration` | auto | force total seconds (≥ natural extends the ending hold) |
| `--theme / --title / --kicker / --model` | from JSON | overrides |
| `--avatar PATH` | – | composite avatar PiP overlay (locked `pip` clip) |
| `--layout / --corner` | `pip-circle` / `br` | PiP placement |
| `--face-bias` | `0.4` | vertical crop of the PiP circle |
| `--out-dir / --slug` | `broll_cursor/` / from filename | output location + name |
| `--keep-frames` | off | keep the PNG sequence (debug) |

## Integration with avatar-reel-composer

Each clip is a drop-in B-roll scene:

```json
{ "id": "s1", "type": "broll", "broll_source": "existing",
  "broll_clip": "broll_cursor/001_session.mp4", "text": "…" }
```

**Subtitles belong to the reel, not the clip.** Don't bake captions into the chat or
the avatar — `avatar-reel-composer`'s finishing pass burns the segment subtitles over
the **whole 9:16 frame**. The only text this skill draws is the chat's own content +
the optional `kicker` label.

**When the clip is trimmed to a short hook slot** (the composer trims a B-roll to its
scene's narration length, from the start): **front-load** the session — faster
`typing`, low `assistant.latency_ms`, short tool `duration_ms` — so the prompt lands
and the first skill rows tick within the first ~3s.

## Notes

- Base clips are **silent**; the avatar carries audio.
- Rendering is one screenshot per frame, so cost scales with `fps × duration`. Drop
  `--fps` for quick drafts.
- See [REFERENCE.md](REFERENCE.md) for the full session schema, the timeline model,
  theming, and troubleshooting.
```
