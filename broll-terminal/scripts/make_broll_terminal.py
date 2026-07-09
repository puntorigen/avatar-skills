#!/usr/bin/env python3
"""broll-terminal orchestrator.

Turn a declarative terminal `session.json` into a short, polished B-roll clip
(the *base layer* of a technical reel): render an animated, human-feeling
terminal (typed commands + streamed output) and, with --avatar, composite the
talking avatar in a PiP corner (the overlay layer).

Nothing in the session is executed — the output is whatever the JSON declares.
This never runs a real shell, so it can't touch your machine.

Output: a numbered clip under --out-dir + a manifest.json drop-in for
avatar-reel-composer (scene: broll_source "existing", broll_clip <path>).
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
    raise SystemExit(f"[broll-terminal] ERROR: broll-core not found at {_CORE}. "
                     "Install the broll-core skill alongside this one.")
sys.path.insert(0, str(_HERE))      # local: render_terminal, timeline
sys.path.insert(0, str(_CORE))      # shared: _common, pip_overlay
import _common as C  # noqa: E402
import pip_overlay as PIP  # noqa: E402
import render_terminal as RT  # noqa: E402

C.PREFIX = "broll-terminal"


def slugify(s: str, maxlen: int = 48) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")
    return (s[:maxlen].strip("-") or "terminal")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", type=Path, help="terminal session JSON (see REFERENCE.md)")
    ap.add_argument("--aspect", default="9:16", choices=list(C.ASPECTS))
    ap.add_argument("--fps", type=int, default=C.DEFAULT_FPS)
    ap.add_argument("--seed", type=int, default=7, help="RNG seed for typing jitter")
    ap.add_argument("--duration", type=float, default=None,
                    help="force total seconds (>= natural extends the ready-prompt hold)")
    ap.add_argument("--slug", default=None, help="filename slug (default from session name)")
    ap.add_argument("--out-dir", type=Path, default=Path("broll_terminal"))
    ap.add_argument("--title", default=None, help="override window title-bar text")
    ap.add_argument("--kicker", default=None, help="small uppercase label above the window")
    ap.add_argument("--theme", default=None, help="override theme (warp-dark|one-dark|mono-light)")
    ap.add_argument("--keep-frames", action="store_true", help="keep the PNG frame sequence")
    # avatar PiP overlay (shortcut; the compositor lives in broll-core)
    ap.add_argument("--avatar", type=Path, default=None, help="avatar clip -> PiP overlay")
    ap.add_argument("--layout", default="pip-circle", choices=["pip-circle", "split"])
    ap.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"])
    ap.add_argument("--face-bias", type=float, default=0.4,
                    help="vertical crop bias for the PiP circle (0=top..1=bottom; keep the face)")
    args = ap.parse_args()

    C.require_tool("ffmpeg")
    C.require_tool("ffprobe")
    if not args.session.exists():
        C.die(f"session not found: {args.session}")
    if args.avatar and not args.avatar.exists():
        C.die(f"--avatar not found: {args.avatar}")

    session = json.loads(args.session.read_text(encoding="utf-8"))
    if args.title is not None:
        session["title"] = args.title
    if args.kicker is not None:
        session["kicker"] = args.kicker
    if args.theme:
        session["theme"] = args.theme

    slug = args.slug or slugify(args.session.stem)
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / f"_{slug}_work"
    work.mkdir(parents=True, exist_ok=True)

    C.log(f"[broll-terminal] session={args.session.name} slug={slug} "
          f"aspect={args.aspect} -> {out_dir}")

    # Match the base length to the avatar so the PiP overlay never restarts the
    # typing mid-clip (the avatar's audio drives the final length).
    duration = args.duration
    if args.avatar and duration is None:
        duration = C.ffprobe_duration(args.avatar) or None

    base_clip = work / f"{slug}_base.mp4"
    meta = RT.render_base(session, base_clip, aspect=args.aspect, fps=args.fps,
                          scale=2, seed=args.seed, duration=duration,
                          keep_frames=args.keep_frames)

    idx = C.next_index(out_dir)
    final = out_dir / f"{idx:03d}_{slug}.mp4"
    if args.avatar:
        PIP.overlay_pip(base_clip, args.avatar, final, layout=args.layout,
                        corner=args.corner, aspect=args.aspect, face_bias=args.face_bias)
    else:
        shutil.copyfile(base_clip, final)

    entry = {
        "id": f"{idx:03d}_{slug}", "slug": slug, "clip": str(final),
        "source": "broll-terminal", "session": str(args.session),
        "aspect": args.aspect, "fps": args.fps,
        "duration": meta["duration"], "theme": meta["theme"],
        "silent": args.avatar is None,
        "avatar": str(args.avatar) if args.avatar else None,
        "created_at": C.now_iso(),
    }
    manifest = C.append_manifest(out_dir, entry)
    C.log(f"[done] {entry['id']} -> {entry['clip']}")
    print(json.dumps({"clips": [entry], "manifest": str(manifest),
                      "out_dir": str(out_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
