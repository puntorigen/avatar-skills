# broll-browser-recorder Reference

Full reference for the three tools this skill wraps — the recording server
(`browser_server.py`), the post-processor (`process_video.py`) and the auto-camera
(`auto_camera.py`) — plus the finalizer (`make_broll_demo.py`) and the base-driven
avatar PiP.

Throughout, `S=.cursor/skills/broll-browser-recorder/scripts`.

## Finalizer: `make_broll_demo.py`

Post-processes a recording and emits a numbered `NNN_<slug>.mp4` + a `manifest.json`
entry that drops into `avatar-reel-composer` (`broll_source: "existing"`). It
delegates framing/trim/speed to `process_video.py`, then (with `--avatar`)
composites the avatar PiP via `broll-core`'s `pip_overlay` in **base-driven** mode.

```
python3 $S/make_broll_demo.py <recording.webm | recording-dir> [options]
  --aspect         final geometry 9:16|16:9|1:1|4:5 (default 9:16)
  --preset         social preset (reel/post/…) — overrides --aspect geometry
  --speed          playback speed multiplier
  --max-duration   target max seconds; auto-calculates speed
  --crop x:y:w:h   manual framing (else auto-camera / fit)
  --zoom JSON      zoom keyframes JSON or @file.json
  --no-auto-camera disable manifest-driven reframe
  --fit            pad|crop|stretch|blur (default pad)
  --start/--end    trim (seconds or HH:MM:SS)
  --fade-in/out    fade durations (seconds)
  --avatar PATH    composite avatar PiP narrating the demo
  --layout         pip-circle (default) | split
  --corner         br|bl|tr|tl (default br)
  --face-bias      vertical crop of the PiP circle 0..1 (default 0.4)
  --length         base (default; demo drives length) | avatar (narration drives)
  --out-dir/--slug output location (default broll_demo/) + filename slug
```

Pass either the recording directory (it picks the newest `.webm`/`.mp4` and relies
on the sibling `manifest.json` for auto-camera) or the video path directly.

### PiP length modes

- `--length base` (default): the recorded demo is the hero and plays once at its own
  length. The avatar is overlaid and, when its narration ends first, **freezes on
  its last frame** (`tpad` clone) with its audio padded by trailing silence
  (`apad`). This is the right mode for product demos.
- `--length avatar`: the avatar narration sets the length and the base demo is
  looped to cover it. Use only for short snippets.

The same behavior is available directly on `pip_overlay.py` (in `broll-core`) via
its `--length {avatar,base}` flag.

## Browser Server API

Start the server, then control it over HTTP (`http://localhost:<port>`).

### GET /status

```json
{"alive": true, "url": "https://...", "title": "Page Title", "recording": true, "elapsed": 12.5}
```

### GET /snapshot

Screenshot + page state + interactive elements (up to 50 visible: buttons, inputs,
links, `role`/`tabindex`/`onclick`). Each element has a CSS `selector`, `tag`,
`text` (≤100 chars) and viewport-pixel `bbox`. The `screenshot` path is readable
with the Read tool.

```json
{
  "url": "https://example.com", "title": "Example",
  "screenshot": "/tmp/rec/snap_003.png",
  "viewport": {"width": 1440, "height": 900}, "snap_number": 3, "elapsed": 8.4,
  "elements": [{"selector": "button.submit", "tag": "button", "text": "Submit",
                "bbox": {"x": 500, "y": 300, "w": 120, "h": 40}}]
}
```

### POST /action

Execute a browser action (JSON body). Every response includes a fresh snapshot plus
an `action_result` field with the action-log entry.

| Action | Body | Description |
|--------|------|-------------|
| `click` | `selector` or `x`,`y` | Click element or coordinates |
| `type` | `selector`, `text`, `delay` | Type char-by-char (default delay 60ms) |
| `fill` | `selector`, `text` | Clear and fill input instantly |
| `press` | `key`, optional `selector` | Press a key (Enter, Tab, Escape, …) |
| `scroll` | `selector` or `x`,`y` | Scroll to element or by pixels |
| `hover` | `selector` or `x`,`y` | Hover over element/coordinates |
| `wait` | `seconds` | Fixed delay |
| `wait_for` | `selector`+`state` or `text` | Wait for element/text (states: visible, hidden, attached, detached) |
| `wait_for_response` | `url_pattern`, `method`, `timeout` | Wait for a network response matching a URL pattern (use HAR/practice data) |
| `wait_for_text_stable` | `selector`, `stable`, `timeout`, `min_growth` | Wait until element text stops changing (streaming AI responses) |
| `wait_for_text_contains` | `selector`, `text`, `timeout` | Wait until element text contains a substring |
| `navigate` | `url`, `wait_until` | Navigate to a new URL |
| `evaluate` | `expression` | Run JavaScript, return the result |
| `select` | `selector`, `value` | Select a dropdown option |
| `camera` | `region` or `center`+`zoom` | Camera hint for auto-camera (no visual effect while recording) |

Examples:

```json
{"action": "click", "selector": ".chat-btn"}
{"action": "type", "selector": ".input", "text": "Hello world!", "delay": 60}
{"action": "wait_for_response", "url_pattern": "/api/chat/message", "method": "POST", "timeout": 30}
{"action": "wait_for_text_stable", "selector": "#chat", "stable": 3, "timeout": 60, "min_growth": 10}
{"action": "camera", "region": [0, 168, 430, 764]}
```

### POST /discover

Lightweight element query (bounds + child count, no screenshot) — faster than
`/snapshot` for measuring during practice.

```json
{"selector": "#widget-root"}
→ {"selector": "#widget-root", "bounds": {"x": 1498, "y": 425, "w": 422, "h": 640}, "count": 1, "children": 131}
```

### GET /responses

Inspect tracked network responses: `GET /responses?last=20&pattern=chat`.

### POST /stop

Stops the server. Recording mode saves the video; practice mode writes a playbook.

```json
// recording mode
{"video": "/tmp/rec/abc.webm", "video_offset": 25.8, "duration": 45.2, "snapshots": 15, "manifest": "/tmp/rec/manifest.json"}
// practice mode
{"playbook": "/tmp/practice/playbook.json", "duration": 198.3, "snapshots": 16, "manifest": "/tmp/practice/manifest.json"}
```

`video_offset` = seconds between video start and manifest time zero (recording
starts before navigation). Convert manifest timestamps to video timestamps with
`video_ts = manifest_ts + video_offset` for precise `--start`/`--end` trimming.

## Server CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `url` | (required) | URL to navigate to |
| `--output, -o` | `/tmp/browser_recording/` | Output directory |
| `--viewport, -v` | `1920x1080` | Viewport WxH |
| `--port, -p` | `9222` | HTTP server port |
| `--device, -d` | | Device preset / Playwright device name |
| `--dark-mode` | off | Emulate dark color scheme |
| `--hide-scrollbar` | off | Hide scrollbars |
| `--no-cursor` | off | Disable the injected cursor indicator |
| `--wait, -w` | `0` | Wait seconds after initial load |
| `--wait-until` | `load` | `load\|domcontentloaded\|networkidle\|commit` |
| `--locale, -l` | | Browser locale (e.g. `es-ES`, `en-US`) |
| `--chrome` | off | Use system Chrome (enables H.264 video) |
| `--no-record, --practice` | off | Practice mode: no video, HAR + playbook on stop |
| `--cache-name` | | Cache the playbook by name (in the skill's `cache/` dir) |
| `--clean` | off | Fresh session (no cookies/storage). **Recommended** for demos |

### Cursor indicator

By default a realistic pointer is injected: it smoothly moves to each target
(0.35s), emits a ripple on click, hides over text inputs, stays on top, and is
invisible to mouse events. Disable with `--no-cursor`.

## Two-phase practice / playbook

Practice mode (`--no-record`) runs the browser without video, records a HAR, and
produces a playbook on stop so the record pass is clean. Playbook fields:

| Field | Description |
|-------|-------------|
| `action_plan` | Clean action sequence (`evaluate` filtered out) |
| `discoveries.element_bounds` | Bounding boxes of interacted elements |
| `discoveries.scroll_needed` / `message_count` | Scroll usage / send count |
| `timing.content_start_s` / `content_end_s` | Trim points |
| `crop_recommendation` | Tight `x:y:w:h` around interacted elements |
| `network.chat_api` | Detected messaging API (URL pattern, response times, streaming) |
| `network.page_load` | Load summary (media URLs, slowest resources) |

Cache with `--cache-name <name>` → stored in the skill's `cache/<name>/playbook.json`
with a `created_at` timestamp; check for a fresh one before re-practicing.

**Non-determinism:** AI responses vary run to run. Use `avg_response_time_s` + ~30%
as an initial wait, then verify state; the playbook removes cold-start guessing, not
the need to adapt.

## Post-processing: `process_video.py`

```
python3 $S/process_video.py <input> [options]
  --output, -o     Output path (default output.mp4)
  --crop, -c       Crop x:y:w:h
  --speed, -s      Playback speed multiplier
  --max-duration   Target max seconds; auto-calculates speed
  --preset, -p     reel|story|short|post|portrait|landscape
  --resolution, -r Custom WxH
  --fit            pad (default) | crop | stretch | blur
  --pad-color      Letterbox hex (default 000000)
  --blur-sigma / --blur-fill / --blur-feather   blur-fit tuning
  --zoom, -z       Zoom keyframes JSON or @file.json
  --no-auto-camera Disable manifest-driven camera keyframes
  --start / --end  Trim (seconds or HH:MM:SS)
  --fade-in / --fade-out   Fade durations
  --crf            H.264 quality 0-51 (default 20)
  --fps            Output FPS (default 30)
```

`make_broll_demo.py` calls this for you (deriving `--resolution` from `--aspect`);
you can also run it standalone.

### Social presets

| Preset | Resolution | Aspect |
|--------|-----------|--------|
| `reel` / `story` / `short` | 1080x1920 | 9:16 |
| `post` | 1080x1080 | 1:1 |
| `portrait` | 1080x1350 | 4:5 |
| `landscape` | 1920x1080 | 16:9 |

### Fit modes

- **pad** (default): fit within target, add black bars.
- **crop**: fill target, crop overflow (centered).
- **stretch**: distort to fill (not recommended).
- **blur**: sharp focus region (`--crop`) over a feathered blurred fill of the same
  frame (`--blur-sigma`/`--blur-fill`/`--blur-feather`).

### Computing trim points from the manifest

`video_offset` converts manifest timestamps to video timestamps. Start 0.5s before
the first click; hold ~3s after the last action:

```python
import json
m = json.load(open("/tmp/rec/manifest.json"))
vo = m["video_offset"]
first_click = next(a for a in m["actions"] if a["action"] == "click")
trim_start = first_click["timestamp"] + vo - 0.5
trim_end = m["actions"][-1]["timestamp"] + vo + 3
```

## Zoom keyframes

`--zoom` accepts a JSON array of keyframes for smooth pan/zoom (used internally by
auto-camera, or supply your own with `--no-auto-camera`):

```json
[
  {"t": 0, "region": [0, 0, 1440, 900]},
  {"t": 2.0, "region": [900, 200, 500, 700], "ease": "ease-in-out"},
  {"t": 10.0, "region": [900, 200, 500, 700]},
  {"t": 12.0, "region": [0, 0, 1440, 900], "ease": "ease-in-out"}
]
```

Each keyframe: `t` (seconds), `region` `[x, y, w, h]` in source pixels, optional
`ease: "ease-in-out"`. Regions are interpolated frame-by-frame (OpenCV).

## Auto-camera: `auto_camera.py`

When the output aspect differs from the source and a `manifest.json` sits next to
the input, `process_video.py` auto-generates camera keyframes that dynamically
pan/zoom to follow the recorded interactions — no manual `--crop` needed.

Key behaviors:

- **Action-log-driven only.** Reacts to actions in the manifest, not background page
  events. `wait`/`type`/`press`/`evaluate`/`wait_for_*` hold; only off-frame
  `click`/`scroll` or an explicit `camera` hint pans.
- **Dead zone** (default 40px) prevents jitter; **lookahead** minimizes moves;
  **lead time** (0.3s) arrives just before the action.
- **Selective vertical blur**: the top ~30% (page chrome/headers) fades from blurred
  to sharp while the interaction area stays crisp.

Standalone:

```bash
python3 $S/auto_camera.py manifest.json --preset reel --video input.webm \
  --margin 40 --establish 2.0 --lead 0.3 -o keyframes.json
```

| Option | Default | Description |
|--------|---------|-------------|
| `manifest` | (required) | manifest.json |
| `--preset, -p` / `--resolution, -r` | | target geometry |
| `--video, -v` / `--video-size` | | source dimensions (ffprobe / explicit) |
| `--margin` | 40 | dead-zone px |
| `--establish` | 2.0 | establishing-shot seconds |
| `--lead` | 0.3 | camera lead time |
| `--output, -o` | stdout | keyframes JSON path |

### Priority

1. Explicit `--zoom` keyframes (auto-camera disabled)
2. Auto-camera from manifest (aspect differs + manifest present)
3. Fit-mode fallback: pad/crop/stretch/blur

## Recording tips

- **Act fast after load.** Click CTAs/widgets before proactive popups change the
  state. Take one snapshot to verify, then act.
- **Never manipulate page behavior programmatically** (no `evaluate` to dismiss
  popups) — interact as a real user.
- **Tight transitions.** Act → `wait_for_response` (API URL pattern) → short
  `wait(0.5)` → act. Chain `curl` with `&&`.
- **Record at the page's natural viewport**; auto-camera handles the 9:16 reframe.
- **Speed**: 4-6x for AI-chat waits, 2-3x for cleaner flows, 1.5-2x for product
  tours. `make_broll_demo.py --max-duration` picks speed to hit a target length.
