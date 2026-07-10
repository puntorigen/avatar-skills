#!/usr/bin/env python3
"""Render a Cursor agent-chat session JSON into a base B-roll clip (deterministic).

Loads cursor.html in headless Chromium (high-DPI), injects the timeline built by
timeline.py, then drives `window.seekTo(t)` once per frame and screenshots each — a
pure function of time, so the result is frame-exact and reproducible (no recording
jitter, no dropped frames). The PNG sequence is muxed to H.264.

Nothing from the session is ever executed: the "assistant" only says/does whatever
the session JSON declares. This never runs a real agent or shell.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CORE = _HERE.parent.parent / "broll-core" / "scripts"
if not _CORE.exists():
    raise SystemExit(f"[broll-cursor] ERROR: broll-core not found at {_CORE}. "
                     "Install the broll-core skill alongside this one.")
sys.path.insert(0, str(_HERE))      # local: timeline
sys.path.insert(0, str(_CORE))      # shared: _common
import _common as C  # noqa: E402
import timeline as TL  # noqa: E402

C.PREFIX = "broll-cursor"

TEMPLATE = _HERE / "cursor.html"

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    C.die("playwright not installed. Run:\n"
          "  pip3 install -r .cursor/skills/broll-cursor/scripts/requirements.txt\n"
          "  playwright install chromium")


def render_base(session: dict, out_mp4: Path, *, aspect: str = "9:16",
                fps: int = C.DEFAULT_FPS, scale: int = 2, seed: int = 7,
                duration: float | None = None, keep_frames: bool = False) -> dict:
    """Render the session to a silent base clip. Returns render metadata."""
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    W, H = C.aspect_dims(aspect)
    vw, vh = W // scale, H // scale

    tl = TL.build_timeline(session, seed=seed)
    natural_s = tl["durationMs"] / 1000.0
    total_s = max(natural_s, float(duration)) if duration else natural_s
    nframes = max(2, int(round(total_s * fps)))

    frames_dir = out_mp4.parent / f"_{out_mp4.stem}_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    C.log(f"[broll-cursor] render {aspect} {W}x{H} @ {fps}fps  "
          f"{total_s:.2f}s ({nframes} frames)  theme={tl['theme']}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": vw, "height": vh},
                                  device_scale_factor=scale)
        page = ctx.new_page()
        page.goto(TEMPLATE.as_uri(), wait_until="load", timeout=30000)
        page.evaluate("(d) => window.__INIT__(d)", tl)
        page.wait_for_timeout(80)  # let fonts settle
        for i in range(nframes):
            t_ms = (i / fps) * 1000.0
            page.evaluate("(t) => window.seekTo(t)", t_ms)
            page.screenshot(path=str(frames_dir / f"{i:05d}.png"))
        ctx.close()
        browser.close()

    C.run(["ffmpeg", "-y", "-framerate", str(fps), "-i", str(frames_dir / "%05d.png"),
           "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-vf", f"scale={W}:{H}:flags=lanczos", str(out_mp4), "-loglevel", "error"],
          desc=f"mux frames -> {out_mp4.name}")

    if not keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    return {"clip": str(out_mp4), "aspect": aspect, "fps": fps,
            "duration": round(total_s, 3), "natural_duration": round(natural_s, 3),
            "frames": nframes, "theme": tl["theme"], "events": len(tl["events"])}


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a Cursor agent-chat session JSON to a base clip.")
    ap.add_argument("session", type=Path, help="session JSON (see timeline.py schema)")
    ap.add_argument("-o", "--out", type=Path, default=Path("cursor_base.mp4"))
    ap.add_argument("--aspect", default="9:16", choices=list(C.ASPECTS))
    ap.add_argument("--fps", type=int, default=C.DEFAULT_FPS)
    ap.add_argument("--scale", type=int, default=2, help="device scale factor (supersampling)")
    ap.add_argument("--seed", type=int, default=7, help="RNG seed for typing jitter")
    ap.add_argument("--duration", type=float, default=None,
                    help="force total seconds (>= natural extends the ending hold)")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()
    C.require_tool("ffmpeg")
    if not TEMPLATE.exists():
        C.die(f"cursor.html template missing at {TEMPLATE}")
    session = json.loads(args.session.read_text(encoding="utf-8"))
    meta = render_base(session, args.out, aspect=args.aspect, fps=args.fps,
                       scale=args.scale, seed=args.seed, duration=args.duration,
                       keep_frames=args.keep_frames)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
