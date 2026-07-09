#!/usr/bin/env python3
"""Replace the background of a talking-head clip.

Two stages:
  1. MATTE  -- extract a temporally-stable matte of the speaker with Robust
     Video Matting (RVM) on Replicate. RVM returns ONE video per run:
       --matte alpha  -> output_type=alpha-mask  (grayscale matte)   [default]
       --matte green  -> output_type=green-screen (speaker on green)
  2. COMPOSITE -- with ffmpeg, put the matted speaker on top of a new
     background video/image:
       Route A (alpha): alphamerge the ORIGINAL RGB with the matte, overlay on bg
       Route B (green): chromakey + despill the green clip, overlay on bg

Realism touches (all optional): edge feather, grounding drop-shadow, and a
unifying color grade / vignette over the whole composite. The speaker's
original audio is preserved.

Examples:
    # Route A (recommended): matte + composite over a generated b-roll bg
    python3 replace_bg.py lolo/generated-videos/scene01.mp4 \
        --bg lolo/broll/003_calle-de-noche.mp4 --shadow --grade

    # Iterate the composite cheaply without re-running RVM
    python3 replace_bg.py scene01.mp4 --bg new_bg.mp4 --reuse-matte scene01.matte.mp4

    # Just print the planned RVM call + ffmpeg command, run nothing
    python3 replace_bg.py scene01.mp4 --bg bg.mp4 --dry-run
"""

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

FORMAT_PRESETS = {
    "reel": (1080, 1920),
    "post": (1080, 1080),
    "landscape": (1920, 1080),
}


def _even(n):
    n = int(round(n))
    return n - (n % 2)


def resolve_target(args, speaker_info):
    """Decide output WxH. Default: match the speaker clip (keeps the face crisp)."""
    if args.width and args.height:
        return _even(args.width), _even(args.height)
    if args.format:
        return FORMAT_PRESETS[args.format]
    w = speaker_info.get("width") or 1080
    h = speaker_info.get("height") or 1920
    return _even(w), _even(h)


def resolve_out_paths(args, speaker_path):
    speaker_path = Path(speaker_path)
    if args.out:
        final_path = Path(args.out).expanduser().resolve()
        out_dir = final_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir, final_path, out_dir / "manifest.json"

    avatar_dir = None
    if args.avatar_dir:
        avatar_dir = Path(args.avatar_dir).expanduser().resolve()
    if avatar_dir is None:
        avatar_dir = C.infer_avatar_dir(speaker_path)

    if avatar_dir and avatar_dir.is_dir():
        out_dir = avatar_dir / "generated-videos" / "bg-replaced"
    elif args.out_dir:
        out_dir = Path(args.out_dir).expanduser().resolve()
    else:
        out_dir = Path.cwd() / "bg-replaced"

    out_dir.mkdir(parents=True, exist_ok=True)
    bg_stem = C.slugify(Path(args.bg).stem) if args.bg else "bg"
    stem = args.out_name or f"{speaker_path.stem}__bg-{bg_stem}"
    return out_dir, out_dir / f"{stem}.mp4", out_dir / "manifest.json"


def build_filter(mode, w, h, fps, *, feather=0.0, shadow=False,
                 shadow_opacity=0.45, shadow_dx=10, shadow_dy=14, shadow_blur=18,
                 grade=False, chroma_color="0x00FF00", chroma_sim=0.12,
                 chroma_blend=0.10, despill=True):
    """Build the ffmpeg -filter_complex graph and the final output label.

    Input order:
      Route A (alpha): 0=bg, 1=speaker(original RGB), 2=matte
      Route B (green): 0=bg, 1=green clip,            2=speaker(audio only)
    """
    stages = []
    # Background prep: cover-fit + crop to the target frame, conform fps.
    stages.append(
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},fps={fps},setsar=1,format=yuv420p[bgp]"
    )

    if mode == "alpha":
        a_chain = f"[2:v]fps={fps},scale={w}:{h},format=gray"
        if feather and feather > 0:
            a_chain += f",boxblur={feather}:1"
        a_chain += ",split=2[a][ash_src]" if shadow else "[a]"
        stages.append(a_chain)
        stages.append(f"[1:v]fps={fps},scale={w}:{h},setsar=1,format=yuva420p[fgc]")
        stages.append("[fgc][a]alphamerge[fg]")

        bg_label = "bgp"
        if shadow:
            stages.append(f"[ash_src]boxblur={shadow_blur}:1[ashb]")
            stages.append(f"color=c=black:s={w}x{h}:r={fps},format=rgba[shc]")
            stages.append(
                f"[shc][ashb]alphamerge,colorchannelmixer=aa={shadow_opacity}[shadow]"
            )
            stages.append(
                f"[bgp][shadow]overlay=x={shadow_dx}:y={shadow_dy}:shortest=1[bgs]"
            )
            bg_label = "bgs"
        stages.append(f"[{bg_label}][fg]overlay=0:0:shortest=1[comp]")
    else:  # green
        fg = (f"[1:v]fps={fps},scale={w}:{h},setsar=1,"
              f"chromakey={chroma_color}:{chroma_sim}:{chroma_blend}")
        if despill:
            fg += ",despill=type=green"
        fg += "[fg]"
        stages.append(fg)
        stages.append("[bgp][fg]overlay=0:0:shortest=1[comp]")

    if grade:
        stages.append(
            "[comp]eq=contrast=1.03:saturation=1.04,vignette=angle=PI/5[vout]"
        )
        final = "vout"
    else:
        final = "comp"

    return ";".join(stages), final


def bg_input_args(bg_path):
    """Looping flags so a short bg covers the speaker's full duration."""
    suffix = Path(bg_path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return ["-loop", "1", "-i", str(bg_path)]
    return ["-stream_loop", "-1", "-i", str(bg_path)]


def main():
    ap = argparse.ArgumentParser(
        description="Replace a talking-head clip's background via RVM matte + ffmpeg composite.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("speaker", help="The talking-head clip whose background to replace.")
    ap.add_argument("--bg", required=True, help="Background video or image to place behind the speaker.")
    ap.add_argument("--matte", choices=["alpha", "green"], default="alpha",
                    help="Matting route: 'alpha' (alpha-mask + original RGB, best) or "
                         "'green' (green-screen + chromakey). Default: alpha.")

    # Matte reuse / model controls
    ap.add_argument("--reuse-matte", default=None,
                    help="Use this existing matte/green clip instead of calling RVM "
                         "(iterate the composite cheaply, no API spend).")
    ap.add_argument("--rvm-version", default=None,
                    help="Override the pinned RVM Replicate version (\"\" = latest).")
    ap.add_argument("--keep-matte", action="store_true",
                    help="Keep the intermediate matte/green clip next to the output.")

    # Output framing
    ap.add_argument("--format", choices=list(FORMAT_PRESETS.keys()), default=None,
                    help="Output frame preset. Default: match the speaker clip.")
    ap.add_argument("--width", type=int, default=None, help="Explicit output width.")
    ap.add_argument("--height", type=int, default=None, help="Explicit output height.")
    ap.add_argument("--fps", type=float, default=None,
                    help="Output fps. Default: the speaker clip's fps.")

    # Realism touches
    ap.add_argument("--feather", type=float, default=0.0,
                    help="Soften matte edges by this blur radius in px (e.g. 1.5). Default: 0.")
    ap.add_argument("--shadow", action="store_true",
                    help="Add a soft grounding drop-shadow under the subject (alpha route).")
    ap.add_argument("--shadow-opacity", type=float, default=0.45)
    ap.add_argument("--shadow-dx", type=int, default=10)
    ap.add_argument("--shadow-dy", type=int, default=14)
    ap.add_argument("--shadow-blur", type=int, default=18)
    ap.add_argument("--grade", action="store_true",
                    help="Apply a subtle unifying color grade + vignette over the composite.")

    # Green-route chroma controls
    ap.add_argument("--chroma-color", default="0x00FF00", help="Green route key color.")
    ap.add_argument("--chroma-similarity", type=float, default=0.12)
    ap.add_argument("--chroma-blend", type=float, default=0.10)
    ap.add_argument("--no-despill", action="store_true", help="Disable green despill.")

    ap.add_argument("--no-audio", action="store_true", help="Drop the speaker's audio.")

    # Output location
    ap.add_argument("--avatar-dir", default=None,
                    help="Avatar folder; saves to <avatar>/generated-videos/bg-replaced/.")
    ap.add_argument("--out-dir", default=None, help="Explicit output folder.")
    ap.add_argument("--out", default=None, help="Explicit output file path.")
    ap.add_argument("--out-name", default=None, help="Override the output filename stem.")

    ap.add_argument("--dry-run", action="store_true",
                    help="Print the planned RVM call + ffmpeg command and exit (no API/render).")
    args = ap.parse_args()

    speaker = Path(args.speaker).expanduser().resolve()
    if not speaker.exists():
        print(f"Error: speaker clip not found: {speaker}", file=sys.stderr)
        sys.exit(1)
    bg = Path(args.bg).expanduser().resolve()
    if not bg.exists():
        print(f"Error: background not found: {bg}", file=sys.stderr)
        sys.exit(1)

    info = C.probe_video(speaker)
    duration = info.get("duration")
    fps = args.fps or info.get("fps") or 30.0
    w, h = resolve_target(args, info)

    out_dir, final_path, manifest_path = resolve_out_paths(args, speaker)
    matte_keep = final_path.with_name(final_path.stem + ".matte.mp4")
    matte_tmp = final_path.with_name("." + final_path.stem + ".matte.mp4")
    matte_path = matte_keep if args.keep_matte else matte_tmp

    out_type = "alpha-mask" if args.matte == "alpha" else "green-screen"

    print(f"Speaker : {speaker}  ({info.get('width')}x{info.get('height')} "
          f"@ {info.get('fps')}fps, {duration}s)", file=sys.stderr)
    print(f"Backgrnd: {bg}", file=sys.stderr)
    print(f"Target  : {w}x{h} @ {fps}fps | route={args.matte} ({out_type})", file=sys.stderr)
    print(f"Output  : {final_path}", file=sys.stderr)

    # ── Stage 1: matte ────────────────────────────────────────────────
    if args.reuse_matte:
        src_matte = Path(args.reuse_matte).expanduser().resolve()
        if not src_matte.exists():
            print(f"Error: --reuse-matte not found: {src_matte}", file=sys.stderr)
            sys.exit(1)
        matte_path = src_matte
        print(f"Matte   : reusing {src_matte}", file=sys.stderr)
    elif args.dry_run:
        print(f"\n[dry-run] RVM call -> {C.rvm_model_ref(args.rvm_version)}", file=sys.stderr)
        print(f"[dry-run]   input_video = {speaker.name}", file=sys.stderr)
        print(f"[dry-run]   output_type = {out_type}", file=sys.stderr)
        matte_path = matte_path  # placeholder for the printed ffmpeg cmd
    else:
        with open(speaker, "rb") as fh:
            output = C.run_replicate(
                C.rvm_model_ref(args.rvm_version),
                {"input_video": fh, "output_type": out_type},
                token=C.get_replicate_token(),
            )
        saved = C.save_output(output, matte_path)
        if not saved or not Path(saved).exists():
            print("Error: RVM matting failed (no output).", file=sys.stderr)
            sys.exit(2)
        print(f"Matte   : {matte_path}", file=sys.stderr)

    # ── Stage 2: composite ────────────────────────────────────────────
    filter_str, final_label = build_filter(
        args.matte, w, h, fps,
        feather=args.feather, shadow=args.shadow,
        shadow_opacity=args.shadow_opacity, shadow_dx=args.shadow_dx,
        shadow_dy=args.shadow_dy, shadow_blur=args.shadow_blur,
        grade=args.grade, chroma_color=args.chroma_color,
        chroma_sim=args.chroma_similarity, chroma_blend=args.chroma_blend,
        despill=not args.no_despill,
    )

    inputs = bg_input_args(bg)
    if args.matte == "alpha":
        inputs += ["-i", str(speaker), "-i", str(matte_path)]
        audio_map = ["-map", "1:a?"]
    else:
        inputs += ["-i", str(matte_path), "-i", str(speaker)]
        audio_map = ["-map", "2:a?"]
    if args.no_audio:
        audio_map = ["-an"]

    ff_args = inputs + [
        "-filter_complex", filter_str,
        "-map", f"[{final_label}]", *audio_map,
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
    ]
    if duration:
        ff_args += ["-t", f"{float(duration):.3f}"]
    ff_args.append(str(final_path))

    if args.dry_run:
        print("\n[dry-run] ffmpeg command:", file=sys.stderr)
        print("ffmpeg -y " + " ".join(_shquote(a) for a in ff_args), file=sys.stderr)
        print(json.dumps({"dry_run": True, "filter_complex": filter_str,
                          "output": str(final_path)}, ensure_ascii=False))
        return

    ok = C.run_ffmpeg(ff_args, description=f"Compositing speaker over {bg.name}")
    if not ok:
        print("Error: ffmpeg composite failed.", file=sys.stderr)
        sys.exit(3)

    if not args.keep_matte and not args.reuse_matte:
        try:
            Path(matte_path).unlink(missing_ok=True)
        except OSError:
            pass

    out_info = C.probe_video(final_path)
    manifest = C.load_manifest(manifest_path)
    entry = {
        "file": final_path.name,
        "path": str(final_path),
        "speaker": str(speaker),
        "background": str(bg),
        "matte_route": args.matte,
        "rvm_output_type": out_type,
        "rvm_model": C.rvm_model_ref(args.rvm_version),
        "reused_matte": str(args.reuse_matte) if args.reuse_matte else None,
        "kept_matte": str(matte_path) if args.keep_matte else None,
        "feather": args.feather,
        "shadow": bool(args.shadow),
        "grade": bool(args.grade),
        "width": out_info.get("width") or w,
        "height": out_info.get("height") or h,
        "fps": out_info.get("fps") or fps,
        "duration_sec": out_info.get("duration") or duration,
        "audio": not args.no_audio,
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    manifest["items"].append(entry)
    C.write_manifest(manifest_path, manifest)

    print(f"Done: {final_path}", file=sys.stderr)
    print(f"Manifest: {manifest_path}", file=sys.stderr)
    print(json.dumps({
        "video": str(final_path),
        "manifest": str(manifest_path),
        "matte_route": args.matte,
        "width": entry["width"], "height": entry["height"],
        "duration_sec": entry["duration_sec"],
    }, ensure_ascii=False))


def _shquote(s):
    s = str(s)
    if any(ch in s for ch in " \t\"'()[]*;|&$"):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


if __name__ == "__main__":
    main()
