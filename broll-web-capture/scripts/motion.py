#!/usr/bin/env python3
"""Motion engine for broll-web-capture.

Turns a still capture into a short, polished B-roll clip:

  * compose_frame()  - PIL framing: blurred-fill background + sharp, rounded,
                       shadowed content centered on the target aspect. Optional
                       highlight box around a focus region.
  * render_motion()  - ffmpeg Ken Burns (in/out/left/right/up/down) or spotlight
                       push-in toward a focus point, on a composed still.
  * render_scroll()  - ffmpeg vertical scroll-reveal over a tall full-page still.
  * add_counter()    - animated count-up overlay (e.g. a GitHub star counter).
  * add_caption()    - static lower caption (e.g. owner/repo).

All output is H.264 yuv420p at the canonical reel dimensions.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CORE = _HERE.parent.parent / "broll-core" / "scripts"
if not _CORE.exists():
    raise SystemExit(f"[broll-web-capture] ERROR: broll-core not found at {_CORE}. "
                     "Install the broll-core skill alongside this one.")
sys.path.insert(0, str(_CORE))
import _common as C  # noqa: E402

ACCENT = (88, 166, 255)  # GitHub-ish blue for highlight borders
GOLD = (255, 197, 66)     # star color for the GitHub counter


def _star_points(cx, cy, r_out, r_in, n=5, rot_deg=-90):
    pts = []
    for i in range(n * 2):
        ang = math.radians(rot_deg + i * 180.0 / n)
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


# --------------------------------- framing ---------------------------------

def _round_mask(size, radius):
    from PIL import Image, ImageDraw
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def compose_frame(content_png, aspect, out_png, *, bg="blur", pad=0.06,
                  radius=20, shadow=True, focus_bbox=None, highlight=False) -> dict:
    """Frame `content_png` onto the target aspect. Returns placement geometry."""
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

    W, H = C.aspect_dims(aspect)
    content = Image.open(content_png).convert("RGBA")
    cw, ch = content.size

    inner_w, inner_h = W * (1 - 2 * pad), H * (1 - 2 * pad)
    f = min(inner_w / cw, inner_h / ch)
    fw, fh = max(2, int(round(cw * f))), max(2, int(round(ch * f)))
    fw -= fw % 2
    fh -= fh % 2
    fg = content.resize((fw, fh), Image.LANCZOS)

    # Background: cover-scale + crop + blur + darken, or a flat dark fill.
    if bg == "blur":
        cover = max(W / cw, H / ch)
        bw, bh = int(math.ceil(cw * cover)), int(math.ceil(ch * cover))
        bgi = content.convert("RGB").resize((bw, bh), Image.LANCZOS)
        left, top = (bw - W) // 2, (bh - H) // 2
        bgi = bgi.crop((left, top, left + W, top + H))
        bgi = bgi.filter(ImageFilter.GaussianBlur(radius=max(18, W // 36)))
        bgi = ImageEnhance.Brightness(bgi).enhance(0.55)
        bgi = ImageEnhance.Color(bgi).enhance(0.85)
    else:
        bgi = Image.new("RGB", (W, H), (14, 16, 20))
    base = bgi.convert("RGBA")

    ox, oy = (W - fw) // 2, (H - fh) // 2

    # Rounded corners on the foreground.
    mask = _round_mask((fw, fh), radius)
    fg.putalpha(mask)

    # Drop shadow grounds the card.
    if shadow:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sh_card = Image.new("RGBA", (fw, fh), (0, 0, 0, 170))
        sh_card.putalpha(mask.point(lambda p: int(p * 0.66)))
        sh.paste(sh_card, (ox, oy + max(6, fh // 90)), sh_card)
        sh = sh.filter(ImageFilter.GaussianBlur(radius=max(10, fw // 60)))
        base = Image.alpha_composite(base, sh)

    base.paste(fg, (ox, oy), fg)

    focus_center = (W / 2, H / 2)
    if focus_bbox:
        bx, by, bbw, bbh = focus_bbox
        mx, my = ox + bx * f, oy + by * f
        mw, mh = bbw * f, bbh * f
        focus_center = (mx + mw / 2, my + mh / 2)
        if highlight:
            draw = ImageDraw.Draw(base)
            tw = max(4, int(W * 0.006))
            draw.rounded_rectangle([mx - tw, my - tw, mx + mw + tw, my + mh + tw],
                                   radius=radius // 2, outline=ACCENT + (255,), width=tw)

    base.convert("RGB").save(out_png)
    return {"frame": [W, H], "scale": f, "offset": [ox, oy],
            "fg_size": [fw, fh], "focus_center": list(focus_center)}


# ---------------------------- ffmpeg motion --------------------------------

def _zoompan_vf(mode, n, W, H, fps, *, zoom_max=1.12, prescale=2, focus=None):
    sw, sh = W * prescale, H * prescale
    zm = round(zoom_max, 4)
    zs = round((zoom_max - 1.0) / max(1, n - 1), 6)
    cx = f"iw/2-(iw/zoom/2)"
    cy = f"ih/2-(ih/zoom/2)"
    if mode == "in":
        z = f"min(zoom+{zs},{zm})"
        x, y = cx, cy
    elif mode == "out":
        z = f"if(eq(on,0),{zm},max(zoom-{zs},1))"
        x, y = cx, cy
    elif mode in ("left", "right"):
        z = f"{zm}"
        prog = f"on/{max(1, n - 1)}"
        if mode == "right":
            prog = f"(1-{prog})"
        x = f"(iw-iw/zoom)*{prog}"
        y = cy
    elif mode in ("up", "down"):
        z = f"{zm}"
        prog = f"on/{max(1, n - 1)}"
        if mode == "up":
            prog = f"(1-{prog})"
        x = cx
        y = f"(ih-ih/zoom)*{prog}"
    elif mode == "spotlight":
        fx = (focus[0] if focus else W / 2) * prescale
        fy = (focus[1] if focus else H / 2) * prescale
        z = f"min(zoom+{zs},{zm})"
        x = f"max(0,min({fx}-(iw/zoom/2),iw-iw/zoom))"
        y = f"max(0,min({fy}-(ih/zoom/2),ih-ih/zoom))"
    else:
        raise SystemExit(f"unknown motion mode: {mode}")
    return (f"scale={sw}:{sh},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={fps},"
            f"format=yuv420p")


def render_motion(still_png, out_mp4, *, mode="in", duration=5.0, fps=C.DEFAULT_FPS,
                  aspect="9:16", focus=None, zoom_max=1.12, prescale=2) -> Path:
    W, H = C.aspect_dims(aspect)
    n = max(2, int(round(duration * fps)))
    out_mp4 = Path(out_mp4)
    if mode == "static":
        vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
        cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{duration}", "-i", str(still_png),
               "-vf", vf, "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p",
               str(out_mp4), "-loglevel", "error"]
    else:
        vf = _zoompan_vf(mode, n, W, H, fps, zoom_max=zoom_max, prescale=prescale, focus=focus)
        cmd = ["ffmpeg", "-y", "-i", str(still_png),
               "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]",
               "-r", str(fps), "-t", f"{duration}",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_mp4),
               "-loglevel", "error"]
    C.run(cmd, desc=f"motion {mode} -> {out_mp4.name}")
    return out_mp4


NAV_MODES = {"pan-right", "pan-left", "pan-down", "pan-up", "zoom-tl", "zoom-center"}


def render_navigate(raw_png, out_mp4, *, aspect="9:16", mode="pan-right",
                    duration=6.0, fps=C.DEFAULT_FPS, zoom_max=1.7, ease=True) -> Path:
    """Full-bleed navigation over a capture at native resolution (legible).

    Instead of shrinking the whole capture into a centered card, this fills the
    frame and moves a target-aspect window across the high-DPI capture:
      pan-right/left  - horizontal scroll (covers the page width), top-anchored
      pan-down/up     - vertical scroll
      zoom-tl         - zoom into the top-left corner
      zoom-center     - zoom into the center
    """
    from PIL import Image
    W, H = C.aspect_dims(aspect)
    out_mp4 = Path(out_mp4)
    with Image.open(raw_png) as im:
        cw, ch = im.size
    prog = f"(0.5-0.5*cos(PI*t/{duration}))" if ease else f"(t/{duration})"

    if mode in ("pan-right", "pan-left"):
        sh = H
        sw = max(W, round(cw * H / ch)); sw += sw % 2
        travel = sw - W
        x = f"({travel}*{prog})" if mode == "pan-right" else f"({travel}*(1-{prog}))"
        vf = f"scale={sw}:{sh},crop={W}:{H}:x='{x}':y=0,format=yuv420p"
    elif mode in ("pan-down", "pan-up"):
        sw = W
        sh = max(H, round(ch * W / cw)); sh += sh % 2
        travel = sh - H
        y = f"({travel}*{prog})" if mode == "pan-down" else f"({travel}*(1-{prog}))"
        vf = f"scale={sw}:{sh},crop={W}:{H}:x=0:y='{y}',format=yuv420p"
    elif mode in ("zoom-tl", "zoom-center"):
        cover = max(W / cw, H / ch)
        sw = max(W, round(cw * cover)); sw += sw % 2
        sh = max(H, round(ch * cover)); sh += sh % 2
        ww = f"({W}/(1+({zoom_max}-1)*{prog}))"
        hh = f"({H}/(1+({zoom_max}-1)*{prog}))"
        if mode == "zoom-tl":
            x, y = "0", "0"
        else:
            x, y = f"(in_w-{ww})/2", f"(in_h-{hh})/2"
        vf = (f"scale={sw}:{sh},crop=w='{ww}':h='{hh}':x='{x}':y='{y}',"
              f"scale={W}:{H},format=yuv420p")
    else:
        raise SystemExit(f"unknown navigate mode: {mode}")

    cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{duration}", "-i", str(raw_png),
           "-vf", vf, "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           str(out_mp4), "-loglevel", "error"]
    C.run(cmd, desc=f"navigate {mode} -> {out_mp4.name}")
    return out_mp4


def render_scroll(tall_png, out_mp4, *, aspect="9:16", duration=6.0, fps=C.DEFAULT_FPS,
                  direction="down", pad=0.06, ease=True) -> Path:
    """Vertical scroll-reveal over a tall (full-page) capture."""
    from PIL import Image, ImageFilter, ImageEnhance
    W, H = C.aspect_dims(aspect)
    out_mp4 = Path(out_mp4)
    img = Image.open(tall_png).convert("RGB")
    cw, ch = img.size
    wc = int(W * (1 - 2 * pad)); wc -= wc % 2
    hc = int(round(ch * wc / cw)); hc -= hc % 2
    travel = hc - H
    if travel <= 8:  # not tall enough to scroll -> fall back to a gentle push-in
        framed = out_mp4.with_suffix(".framed.png")
        compose_frame(tall_png, aspect, framed)
        return render_motion(framed, out_mp4, mode="in", duration=duration, fps=fps, aspect=aspect)

    work = out_mp4.parent
    content_scaled = work / "_scroll_content.png"
    img.resize((wc, hc), Image.LANCZOS).save(content_scaled)
    # Blurred background from the top crop.
    cover = max(W / cw, H / (ch))
    bw, bh = int(math.ceil(cw * cover)), int(math.ceil(ch * cover))
    bgi = img.resize((bw, bh), Image.LANCZOS).crop((0, 0, min(bw, W * 2), min(bh, H * 2)))
    bgi = bgi.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(max(18, W // 36)))
    bgi = ImageEnhance.Brightness(bgi).enhance(0.5)
    bg_png = work / "_scroll_bg.png"
    bgi.save(bg_png)

    prog = f"(t/{duration})"
    if ease:
        prog = f"(0.5-0.5*cos(PI*t/{duration}))"
    if direction == "down":
        yexpr = f"-({travel}*{prog})"
    else:
        yexpr = f"-({travel}*(1-{prog}))"
    xoff = (W - wc) // 2
    fc = (f"[0:v]scale={W}:{H}[bg];"
          f"[1:v]scale={wc}:{hc}[ct];"
          f"[bg][ct]overlay=x={xoff}:y='{yexpr}':shortest=1,format=yuv420p[v]")
    cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{duration}", "-i", str(bg_png),
           "-loop", "1", "-t", f"{duration}", "-i", str(content_scaled),
           "-filter_complex", fc, "-map", "[v]", "-r", str(fps),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_mp4), "-loglevel", "error"]
    C.run(cmd, desc=f"scroll {direction} -> {out_mp4.name}")
    return out_mp4


# ------------------------------- overlays ----------------------------------
# This ffmpeg may be built without `drawtext` (no libfreetype), so text overlays
# are rendered with PIL and composited via ffmpeg `overlay` instead.

def _load_font(size: int):
    from PIL import ImageFont
    path = C.find_font(bold=True)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _pill_png(text, font, out_png, *, pad, fill=(255, 255, 255, 255),
              bg=(0, 0, 0, 150)) -> tuple[int, int]:
    """Render a single rounded-pill label to a tight transparent PNG. Returns size."""
    from PIL import Image, ImageDraw
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    pw, ph = tw + 2 * pad, th + 2 * pad
    img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=ph // 2, fill=bg)
    d.text((pad - l, pad - t), text, font=font, fill=fill)
    img.save(out_png)
    return pw, ph


def add_text_overlay(in_mp4, out_mp4, *, counter=None, counter_label="\u2605",
                     caption=None, caption_align="center", ramp=1.8,
                     fps=C.DEFAULT_FPS) -> Path:
    """Composite a static caption and/or an animated count-up via PIL + overlay.

    The caption is a single static pill; the counter is a small PNG sequence
    (15 fps, count-up over `ramp` then hold) — both kept tiny so ffmpeg overlay
    is fast. Output has no audio (applied before the avatar PiP step).
    """
    from PIL import Image, ImageDraw
    in_mp4, out_mp4 = Path(in_mp4), Path(out_mp4)
    if not counter and not caption:
        if in_mp4 != out_mp4:
            C.run(["ffmpeg", "-y", "-i", str(in_mp4), "-c", "copy", str(out_mp4),
                   "-loglevel", "error"], check=False)
        return out_mp4

    W, H = C.ffprobe_dims(in_mp4)
    p = C.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(in_mp4)], check=False)
    try:
        dur = float((p.stdout or "0").strip())
    except ValueError:
        dur = 5.0
    margin = int(W * 0.05)
    work = out_mp4.parent / f"_{out_mp4.stem}_txt"
    work.mkdir(parents=True, exist_ok=True)

    inputs: list[str] = []
    filters: list[str] = []
    last = "0:v"
    idx = 1

    if caption:
        capfont = _load_font(max(26, int(H * 0.028)))
        cap_png = work / "caption.png"
        pw, ph = _pill_png(caption, capfont, cap_png, pad=int(H * 0.014),
                           bg=(0, 0, 0, 140))
        if caption_align == "left":
            cx = margin
        elif caption_align == "right":
            cx = W - margin - pw
        else:
            cx = (W - pw) // 2
        cy = H - margin - ph
        inputs += ["-loop", "1", "-i", str(cap_png)]
        filters.append(f"[{last}][{idx}:v]overlay={cx}:{cy}:shortest=1[c{idx}]")
        last = f"c{idx}"; idx += 1

    if counter and counter > 0:
        cfont = _load_font(max(30, int(H * 0.036)))
        cpad = int(H * 0.018)
        # Size the box to the final value (with thousands separators) so the
        # pill never jumps as the number grows. A drawn gold star avoids relying
        # on a font glyph for U+2605.
        probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        l, t, r, b = probe.textbbox((0, 0), f"{int(counter):,}", font=cfont)
        nw, nh = r - l, b - t
        ro = nh * 0.62
        gap = int(ro * 0.8)
        star_w = int(2 * ro)
        bw = star_w + gap + nw + 2 * cpad
        bh = max(nh, int(2 * ro)) + 2 * cpad
        fps_txt = 15
        n = max(1, int(round(dur * fps_txt)))
        seqdir = work / "counter"
        seqdir.mkdir(exist_ok=True)
        star_cx = cpad + ro
        star_cy = bh / 2
        num_x = cpad + star_w + gap - l
        num_y = (bh - nh) // 2 - t
        for i in range(n):
            tt = i / fps_txt
            val = counter if tt >= ramp else int(round(counter * _ease_out(tt / ramp)))
            img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=bh // 2, fill=(0, 0, 0, 150))
            d.polygon(_star_points(star_cx, star_cy, ro, ro * 0.42), fill=GOLD)
            d.text((num_x, num_y), f"{val:,}", font=cfont, fill=(255, 255, 255, 255))
            img.save(seqdir / f"{i:05d}.png")
        inputs += ["-framerate", str(fps_txt), "-i", str(seqdir / "%05d.png")]
        filters.append(f"[{last}][{idx}:v]overlay={margin}:{margin}:shortest=1[c{idx}]")
        last = f"c{idx}"; idx += 1

    fc = ";".join(filters) + f";[{last}]format=yuv420p[v]"
    C.run(["ffmpeg", "-y", "-i", str(in_mp4), *inputs, "-filter_complex", fc,
           "-map", "[v]", "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           str(out_mp4), "-loglevel", "error"],
          desc=f"text overlay -> {out_mp4.name}")
    return out_mp4


def main() -> int:
    ap = argparse.ArgumentParser(description="Animate a still capture into a B-roll clip.")
    ap.add_argument("still", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("motion.mp4"))
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--mode", default="in",
                    help="in|out|left|right|up|down|spotlight|static|scroll")
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--fps", type=int, default=C.DEFAULT_FPS)
    ap.add_argument("--no-frame", action="store_true",
                    help="skip PIL framing (still already at target aspect)")
    args = ap.parse_args()
    C.require_tool("ffmpeg")
    if args.mode == "scroll":
        render_scroll(args.still, args.out, aspect=args.aspect,
                      duration=args.duration, fps=args.fps)
    elif args.mode in NAV_MODES:
        render_navigate(args.still, args.out, aspect=args.aspect, mode=args.mode,
                        duration=args.duration, fps=args.fps)
    else:
        still = args.still
        if not args.no_frame:
            framed = args.out.with_suffix(".framed.png")
            compose_frame(args.still, args.aspect, framed)
            still = framed
        render_motion(still, args.out, mode=args.mode, duration=args.duration,
                      fps=args.fps, aspect=args.aspect)
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
