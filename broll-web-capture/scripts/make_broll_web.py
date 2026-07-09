#!/usr/bin/env python3
"""broll-web-capture orchestrator.

Turn a website or a GitHub repo into a short, polished B-roll clip (the *base
layer* of a technical reel): capture a high-DPI still, then animate it (Ken
Burns / scroll-reveal / spotlight) framed on the target aspect. With --avatar it
also composites the talking avatar in a PiP corner (the overlay layer).

Presets
  generic     any URL -> framed Ken Burns (or --mode scroll for a full page)
  landing     a landing page -> full-page scroll-reveal by default
  producthunt like landing
  github      owner/repo (or URL) -> money-shots (header/readme/contrib) with a
              live animated star counter + owner/repo caption

Output: numbered clip(s) under --out-dir + a manifest.json drop-in for
avatar-reel-composer (scene: broll_source "existing", broll_clip <path>).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CORE = _HERE.parent.parent / "broll-core" / "scripts"
if not _CORE.exists():
    raise SystemExit(f"[broll-web-capture] ERROR: broll-core not found at {_CORE}. "
                     "Install the broll-core skill alongside this one.")
sys.path.insert(0, str(_HERE))      # local: capture, motion
sys.path.insert(0, str(_CORE))      # shared: _common, pip_overlay
import _common as C  # noqa: E402
import capture as CAP  # noqa: E402
import motion as M  # noqa: E402
import pip_overlay as PIP  # noqa: E402

C.PREFIX = "broll-web-capture"


def slugify(s: str, maxlen: int = 48) -> str:
    s = re.sub(r"https?://", "", s.strip().lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:maxlen].strip("-") or "clip")


def detect_preset(url: str, explicit: str | None) -> str:
    if explicit and explicit != "auto":
        return explicit
    if "github.com" in url or CAP.parse_repo(url):
        return "github"
    return "generic"


def _finish_clip(base_clip: Path, out_dir: Path, idx: int, slug: str, *,
                 avatar: Path | None, layout: str, corner: str, aspect: str,
                 caption: str | None, counter: int | None = None,
                 face_bias: float = 0.4) -> Path:
    """Optional text layer (counter + caption) + optional avatar PiP."""
    work = out_dir / f"_{slug}_work"
    cur = base_clip
    if caption or counter:
        # Keep the caption clear of a bottom-corner avatar PiP by aligning it
        # to the opposite side.
        cap_align = "center"
        if avatar and layout == "pip-circle":
            cap_align = "left" if corner in ("br", "tr") else "right"
        txt_out = work / f"{slug}_txt.mp4"
        cur = M.add_text_overlay(cur, txt_out, counter=counter, caption=caption,
                                 caption_align=cap_align)
    final = out_dir / f"{idx:03d}_{slug}.mp4"
    if avatar:
        # If there's a bottom caption, lift a bottom-corner PiP so it never
        # covers the repo/site name.
        _, fh = C.aspect_dims(aspect)
        bottom_clear = int(fh * 0.12) if (caption and corner in ("br", "bl")
                                          and layout == "pip-circle") else 0
        PIP.overlay_pip(cur, avatar, final, layout=layout, corner=corner,
                        aspect=aspect, bottom_clear=bottom_clear, face_bias=face_bias)
    else:
        # mute (stills have no audio) and normalize container
        C.run(["ffmpeg", "-y", "-i", str(cur), "-an", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", str(final), "-loglevel", "error"],
              desc=f"finalize -> {final.name}")
    return final


def build_generic(url, out_dir, slug, *, preset, mode, aspect, duration, fps,
                  viewport, full_page, dark, hide, selector, caption, avatar,
                  layout, corner, face_bias=0.4) -> list[dict]:
    work = out_dir / f"_{slug}_work"
    work.mkdir(parents=True, exist_ok=True)
    scroll = (mode == "scroll") or (preset in ("landing", "producthunt") and mode == "auto")
    if mode == "auto":
        mode = "in"
    nav = mode in M.NAV_MODES
    full_page = full_page or scroll
    focus_sel = selector if mode == "spotlight" else None
    sel = selector if (selector and mode != "spotlight") else None

    meta = CAP.capture_page(
        url, work / f"{slug}_cap.png", viewport=viewport, full_page=full_page,
        selector=sel, focus_selector=focus_sel, dark_mode=dark, hide=hide)

    base_clip = work / f"{slug}_base.mp4"
    if scroll:
        M.render_scroll(meta["path"], base_clip, aspect=aspect, duration=duration, fps=fps)
    elif nav:
        M.render_navigate(meta["path"], base_clip, aspect=aspect, mode=mode,
                          duration=duration, fps=fps)
    else:
        framed = work / f"{slug}_framed.png"
        geo = M.compose_frame(meta["path"], aspect, framed,
                              focus_bbox=meta.get("bbox"),
                              highlight=(mode == "spotlight"))
        M.render_motion(framed, base_clip, mode=mode, duration=duration, fps=fps,
                        aspect=aspect, focus=geo.get("focus_center"))

    idx = C.next_index(out_dir)
    final = _finish_clip(base_clip, out_dir, idx, slug, avatar=avatar, layout=layout,
                         corner=corner, aspect=aspect, caption=caption, face_bias=face_bias)
    return [{
        "id": f"{idx:03d}_{slug}", "slug": slug, "clip": str(final),
        "source": "broll-web-capture", "preset": preset, "url": url,
        "mode": "scroll" if scroll else mode, "aspect": aspect,
        "duration": duration, "still": meta["path"], "silent": avatar is None,
        "avatar": str(avatar) if avatar else None, "created_at": C.now_iso(),
    }]


def build_github(url, out_dir, slug, *, mode, aspect, duration, fps, dark, shots,
                 counter, caption, avatar, layout, corner, face_bias=0.4) -> list[dict]:
    repo = CAP.parse_repo(url)
    if not repo:
        C.die(f"--preset github needs owner/repo or a github URL (got {url!r})")
    owner, name = repo
    work = out_dir / f"_{slug}_work"
    work.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("GITHUB_TOKEN")
    stats = CAP.github_stats(owner, name, token=token)
    full_name = stats.get("full_name", f"{owner}/{name}")
    cap_text = caption if caption is not None else full_name

    grabs = CAP.github_shots(owner, name, work, dark=dark, shots=shots)
    entries: list[dict] = []
    for shot, meta in grabs.items():
        sslug = f"{slug}-{shot}"
        base_clip = work / f"{sslug}_base.mp4"
        # Default: full-bleed navigation so the repo is legible (not a tiny card).
        # README -> vertical scroll; header/contrib -> horizontal pan from top-left.
        eff = mode
        if eff == "auto":
            eff = "scroll" if shot == "readme" else "pan-right"
        if eff == "scroll":
            M.render_scroll(meta["path"], base_clip, aspect=aspect,
                            duration=max(duration, 6.5), fps=fps)
            this_mode = "scroll"
        elif eff in M.NAV_MODES:
            M.render_navigate(meta["path"], base_clip, aspect=aspect, mode=eff,
                              duration=duration, fps=fps)
            this_mode = eff
        else:
            framed = work / f"{sslug}_framed.png"
            geo = M.compose_frame(meta["path"], aspect, framed)
            M.render_motion(framed, base_clip, mode=eff, duration=duration, fps=fps,
                            aspect=aspect, focus=geo.get("focus_center"))
            this_mode = eff

        # Animated star counter only on the header shot.
        shot_counter = int(stats["stars"]) if (
            shot == "header" and counter and stats.get("stars")) else None

        idx = C.next_index(out_dir)
        final = _finish_clip(base_clip, out_dir, idx, sslug, avatar=avatar,
                             layout=layout, corner=corner, aspect=aspect,
                             caption=cap_text, counter=shot_counter, face_bias=face_bias)
        entries.append({
            "id": f"{idx:03d}_{sslug}", "slug": sslug, "clip": str(final),
            "source": "broll-web-capture", "preset": "github", "shot": shot,
            "repo": full_name, "stars": stats.get("stars"),
            "language": stats.get("language"), "url": f"https://github.com/{owner}/{name}",
            "mode": this_mode, "aspect": aspect, "duration": duration,
            "still": meta["path"], "silent": avatar is None,
            "avatar": str(avatar) if avatar else None, "created_at": C.now_iso(),
        })
    if not entries:
        C.die("github preset captured no shots (all selectors failed)")
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="web URL, or owner/repo / github URL for the github preset")
    ap.add_argument("--preset", default="auto",
                    choices=["auto", "generic", "landing", "producthunt", "github"])
    ap.add_argument("--mode", default="auto",
                    help="in|out|left|right|up|down|spotlight|scroll|static (default: auto)")
    ap.add_argument("--aspect", default="9:16", choices=list(C.ASPECTS))
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--fps", type=int, default=C.DEFAULT_FPS)
    ap.add_argument("--slug", default=None, help="filename slug (default from URL)")
    ap.add_argument("--out-dir", type=Path, default=Path("broll_web"))
    ap.add_argument("--viewport", default="1440x900", help="WxH for capture")
    ap.add_argument("--full-page", action="store_true", help="capture full scrollable page")
    ap.add_argument("--dark", action="store_true", help="emulate dark mode (default on for github)")
    ap.add_argument("--no-dark", action="store_true", help="force light mode for github")
    ap.add_argument("--hide", action="append", default=[], help="CSS selector to hide (repeatable)")
    ap.add_argument("--selector", default=None,
                    help="capture/spotlight this element (with --mode spotlight, push in + highlight it)")
    ap.add_argument("--caption", default=None, help="lower caption text ('' to disable)")
    ap.add_argument("--shots", default="header",
                    help="github shots: comma list of header,readme,contrib (default header)")
    ap.add_argument("--no-counter", action="store_true", help="disable github star counter")
    # avatar PiP overlay
    ap.add_argument("--avatar", type=Path, default=None, help="avatar clip -> PiP overlay")
    ap.add_argument("--layout", default="pip-circle", choices=["pip-circle", "split"])
    ap.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"])
    ap.add_argument("--face-bias", type=float, default=0.4,
                    help="vertical crop bias for the PiP circle (0=top..1=bottom; keep the face)")
    args = ap.parse_args()

    C.require_tool("ffmpeg")
    C.require_tool("ffprobe")
    if args.avatar and not args.avatar.exists():
        C.die(f"--avatar not found: {args.avatar}")

    preset = detect_preset(args.url, args.preset)
    slug = args.slug or slugify(args.url)
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    viewport = tuple(int(x) for x in args.viewport.lower().split("x"))
    caption = None if args.caption == "" else args.caption

    C.log(f"[broll-web-capture] preset={preset} slug={slug} aspect={args.aspect} "
          f"-> {out_dir}")

    if preset == "github":
        dark = not args.no_dark  # github defaults to dark
        shots = [s.strip() for s in args.shots.split(",") if s.strip()]
        entries = build_github(
            args.url, out_dir, slug, mode=args.mode, aspect=args.aspect,
            duration=args.duration, fps=args.fps, dark=dark, shots=shots,
            counter=not args.no_counter, caption=caption, avatar=args.avatar,
            layout=args.layout, corner=args.corner, face_bias=args.face_bias)
    else:
        entries = build_generic(
            args.url, out_dir, slug, preset=preset, mode=args.mode, aspect=args.aspect,
            duration=args.duration, fps=args.fps, viewport=viewport,
            full_page=args.full_page, dark=args.dark, hide=args.hide,
            selector=args.selector, caption=caption, avatar=args.avatar,
            layout=args.layout, corner=args.corner, face_bias=args.face_bias)

    manifest = None
    for e in entries:
        manifest = C.append_manifest(out_dir, e)
        C.log(f"[done] {e['id']} -> {e['clip']}")

    import json
    print(json.dumps({"clips": entries, "manifest": str(manifest),
                      "out_dir": str(out_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
