#!/usr/bin/env python3
"""Composite a talking avatar over a base B-roll layer (the avatar PiP overlay).

Single source of truth for the "base layer + avatar PiP" architecture, shared by
every base-layer skill (broll-web-capture, broll-terminal) and the overlay skill
(broll-demo-avatar). Two layouts:
  * pip-circle (default) : avatar masked into a corner circle over a near-full base.
  * split                : base on top, avatar on the bottom (each cover-cropped).

The avatar clip carries the narration, so its audio drives the output length and
the base is looped to cover it.

The avatar clip MUST be a static, face-forward "pip" shot (avatar-camera-angles
`--move pip`), lip-synced LOCKED with avatar-talking-video (p-video-avatar): this
compositor never moves the avatar, so any drift inside the circle would come from
the source clip.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import _common as C


def _has_audio(path: Path) -> bool:
    p = C.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
               "-show_entries", "stream=index", "-of", "csv=p=0", str(path)], check=False)
    return bool((p.stdout or "").strip())


def _circle_masks(diameter: int, work: Path, ring: bool, ring_w: int):
    from PIL import Image, ImageDraw
    d = diameter
    fill = Image.new("L", (d, d), 0)
    ImageDraw.Draw(fill).ellipse([0, 0, d - 1, d - 1], fill=255)
    fill_p = work / "_pip_circle.png"
    fill.save(fill_p)
    ring_p = None
    if ring:
        r = Image.new("RGBA", (d, d), (0, 0, 0, 0))
        ImageDraw.Draw(r).ellipse([ring_w // 2, ring_w // 2, d - 1 - ring_w // 2,
                                   d - 1 - ring_w // 2],
                                  outline=(255, 255, 255, 235), width=ring_w)
        ring_p = work / "_pip_ring.png"
        r.save(ring_p)
    return fill_p, ring_p


def overlay_pip(base, avatar, out, *, layout="pip-circle", aspect="9:16",
                corner="br", diameter_frac=0.36, margin_frac=0.045, ring=True,
                bottom_clear=0, face_bias=0.4, fps=C.DEFAULT_FPS) -> Path:
    base, avatar, out = Path(base), Path(avatar), Path(out)
    W, H = C.aspect_dims(aspect)
    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    dur = C.ffprobe_duration(avatar) or 5.0
    amap = ["-map", "1:a"] if _has_audio(avatar) else []

    if layout == "split":
        half = (H // 2) - ((H // 2) % 2)
        fc = (f"[0:v]scale={W}:{half}:force_original_aspect_ratio=increase,"
              f"crop={W}:{half},setsar=1[top];"
              f"[1:v]scale={W}:{half}:force_original_aspect_ratio=increase,"
              f"crop={W}:{half},setsar=1[bot];"
              f"[top][bot]vstack=inputs=2,format=yuv420p[v]")
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(base),
               "-i", str(avatar), "-filter_complex", fc, "-map", "[v]", *amap,
               "-t", f"{dur}", "-r", str(fps), "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-shortest", str(out), "-loglevel", "error"]
        C.run(cmd, desc=f"pip split -> {out.name}")
        return out

    # pip-circle
    d = int(W * diameter_frac); d -= d % 2
    margin = int(W * margin_frac)
    fill_p, ring_p = _circle_masks(d, work, ring, ring_w=max(4, d // 60))
    by = margin + max(0, int(bottom_clear))  # lift bottom corners to clear a caption
    xy = {
        "br": (f"W-w-{margin}", f"H-h-{by}"),
        "bl": (f"{margin}", f"H-h-{by}"),
        "tr": (f"W-w-{margin}", f"{margin}"),
        "tl": (f"{margin}", f"{margin}"),
    }.get(corner, (f"W-w-{margin}", f"H-h-{by}"))

    fb = max(0.0, min(1.0, face_bias))  # vertical crop bias: lower = keep more of the top (face)
    inputs = ["-stream_loop", "-1", "-i", str(base), "-i", str(avatar),
              "-loop", "1", "-i", str(fill_p)]
    fc = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},setsar=1[bg];"
          f"[1:v]scale={d}:{d}:force_original_aspect_ratio=increase,"
          f"crop={d}:{d}:(iw-{d})/2:(ih-{d})*{fb}[sq];"
          f"[2:v]format=gray,scale={d}:{d}[m];"
          f"[sq][m]alphamerge[ava];"
          f"[bg][ava]overlay=x={xy[0]}:y={xy[1]}:shortest=1[comp]")
    last = "comp"
    if ring and ring_p:
        ring_idx = 3  # inputs: base(0), avatar(1), circle-mask(2), ring(3)
        inputs += ["-loop", "1", "-i", str(ring_p)]
        fc += (f";[{ring_idx}:v]format=rgba[ring];"
               f"[comp][ring]overlay=x={xy[0]}:y={xy[1]}:shortest=1[comp2]")
        last = "comp2"
    fc += f";[{last}]format=yuv420p[v]"
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[v]", *amap,
           "-t", f"{dur}", "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-shortest", str(out), "-loglevel", "error"]
    C.run(cmd, desc=f"pip circle ({corner}) -> {out.name}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Composite avatar PiP over a base clip.")
    ap.add_argument("base", type=Path, help="base B-roll layer (web/terminal)")
    ap.add_argument("avatar", type=Path, help="talking avatar clip (carries audio)")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--layout", default="pip-circle", choices=["pip-circle", "split"])
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"])
    ap.add_argument("--diameter", type=float, default=0.36, help="circle diameter as frac of width")
    ap.add_argument("--no-ring", action="store_true")
    ap.add_argument("--bottom-clear", type=int, default=0,
                    help="px reserved at the bottom (lifts a bottom-corner PiP above a caption)")
    ap.add_argument("--face-bias", type=float, default=0.4,
                    help="vertical crop bias for the circle (0=top..1=bottom; lower keeps the face)")
    args = ap.parse_args()
    C.require_tool("ffmpeg")
    overlay_pip(args.base, args.avatar, args.out, layout=args.layout, aspect=args.aspect,
                corner=args.corner, diameter_frac=args.diameter, ring=not args.no_ring,
                bottom_clear=args.bottom_clear, face_bias=args.face_bias)
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
