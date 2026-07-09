---
name: broll-core
description: Internal shared library for the broll-* B-roll skills (broll-web-capture, broll-terminal, broll-demo-avatar). Provides the canonical reel geometry/fps that match avatar-reel-composer, thin ffmpeg/ffprobe wrappers, the numbered-clip + manifest.json conventions, and the avatar picture-in-picture (PiP) compositor (pip_overlay). NOT invoked directly — it is imported by the other broll-* skills. Do not run this skill to make content; use broll-web-capture or broll-terminal.
---

# broll-core (shared library)

Single source of truth for the `broll-*` family so the base-layer skills produce
**interchangeable** output and the avatar-PiP compositor lives in exactly one
place (DRY). It is a library, not a user-facing skill — you never invoke it
directly.

## What's here (`scripts/`)

| Module | What |
|---|---|
| `_common.py` | Canonical `ASPECTS` (9:16 = 1080×1920) + `DEFAULT_FPS=30`, `run`/`ffprobe_*` wrappers, `next_index` + `append_manifest` (numbered clips + `manifest.json`), `find_font`. Set `C.PREFIX` per skill for nicer logs. |
| `pip_overlay.py` | `overlay_pip(base, avatar, ...)` — composites the talking avatar in a PiP circle (default) or split layout over any base clip. Used by every base-layer skill's `--avatar` shortcut and by `broll-demo-avatar`. |

## Who uses it

```
broll-web-capture ─┐
broll-terminal ────┼─► broll-core  (geometry, ffmpeg, manifest, PiP compositor)
broll-demo-avatar ─┘
```

## How skills import it

Each consumer adds `broll-core/scripts` to `sys.path` (resolved relative to the
skill, assuming the sibling `.cursor/skills/<skill>/scripts/` layout) and then
`import _common as C` / `import pip_overlay as PIP`. If `broll-core` is missing,
the consumer fails fast with an install hint.

## Setup

```bash
pip3 install -r .cursor/skills/broll-core/scripts/requirements.txt
```

`ffmpeg` + `ffprobe` must be on PATH. This library has no other runtime deps.

## Conventions (keep these stable — other skills depend on them)

- **Geometry:** outputs use `ASPECTS`; 9:16 is **1080×1920** at **30fps**, matching
  `avatar-reel-composer`.
- **Output:** clips are `NNN_<slug>.mp4` (zero-padded, auto-incremented via
  `next_index`) and each run appends an entry to `manifest.json` (`{"clips": [...]}`),
  a drop-in for `avatar-reel-composer` (`broll_source: "existing"`).
- **Avatar PiP:** the avatar carries audio and drives length; the base loops to
  cover it. The avatar clip should be a static, face-forward `pip` shot
  (`avatar-camera-angles --move pip`) lip-synced locked with `p-video-avatar`.
