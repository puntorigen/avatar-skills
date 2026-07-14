#!/usr/bin/env python3
"""Post-process a video for social media: crop, speed, resize, zoom, trim, fade.

Usage:
    python3 process_video.py input.webm --crop 1200:100:600:900 --speed 3 --preset reel -o output.mp4
    python3 process_video.py input.webm --preset post --speed 2 --fade-in 0.5 --fade-out 0.5 -o output.mp4
    python3 process_video.py input.webm --zoom @keyframes.json --preset reel -o output.mp4
"""

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PRESETS = {
    "reel":      {"width": 1080, "height": 1920},
    "story":     {"width": 1080, "height": 1920},
    "short":     {"width": 1080, "height": 1920},
    "post":      {"width": 1080, "height": 1080},
    "portrait":  {"width": 1080, "height": 1350},
    "landscape": {"width": 1920, "height": 1080},
}


def get_video_info(input_path):
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(input_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error probing video: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    info = json.loads(result.stdout)
    video_stream = next((s for s in info.get("streams", []) if s["codec_type"] == "video"), None)
    if not video_stream:
        print("Error: No video stream found", file=sys.stderr)
        sys.exit(1)
    return {
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "duration": float(info.get("format", {}).get("duration", 0)),
        "fps": eval(video_stream.get("r_frame_rate", "30/1")),
        "codec": video_stream.get("codec_name", "unknown"),
    }


def parse_crop(crop_str):
    parts = crop_str.split(":")
    if len(parts) != 4:
        print(f"Error: Crop must be x:y:w:h (got '{crop_str}')", file=sys.stderr)
        sys.exit(1)
    return {"x": int(parts[0]), "y": int(parts[1]), "w": int(parts[2]), "h": int(parts[3])}


def parse_resolution(res_str):
    parts = res_str.lower().split("x")
    if len(parts) != 2:
        print(f"Error: Resolution must be WxH (got '{res_str}')", file=sys.stderr)
        sys.exit(1)
    return {"width": int(parts[0]), "height": int(parts[1])}


def parse_time(time_str):
    if ":" in str(time_str):
        parts = str(time_str).split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    return float(time_str)


def load_zoom_keyframes(zoom_arg):
    if not zoom_arg:
        return None
    if zoom_arg.startswith("@"):
        path = Path(zoom_arg[1:])
        if not path.exists():
            print(f"Error: Zoom file not found: {path}", file=sys.stderr)
            sys.exit(1)
        return json.loads(path.read_text())
    return json.loads(zoom_arg)


def ease_in_out(t):
    """Smooth ease-in-out interpolation (cubic)."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


def lerp(a, b, t):
    return a + (b - a) * t


def process_with_ffmpeg(input_path, output_path, crop, speed, target_res, fit,
                        pad_color, start, end, fade_in, fade_out, crf, fps):
    """Static processing pipeline using FFmpeg filter chains."""
    filters = []
    info = get_video_info(input_path)

    input_args = ["-i", str(input_path)]

    if start is not None:
        input_args = ["-ss", str(start)] + input_args
    if end is not None:
        if start:
            input_args += ["-t", str(end - start)]
        else:
            input_args += ["-t", str(end)]

    if crop:
        filters.append(f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}")

    if speed and speed != 1.0:
        filters.append(f"setpts=PTS/{speed}")

    src_w = crop["w"] if crop else info["width"]
    src_h = crop["h"] if crop else info["height"]

    if target_res:
        tw, th = target_res["width"], target_res["height"]

        if fit == "stretch":
            filters.append(f"scale={tw}:{th}")
        elif fit == "crop":
            filters.append(f"scale={tw}:{th}:force_original_aspect_ratio=increase")
            filters.append(f"crop={tw}:{th}")
        else:
            filters.append(f"scale={tw}:{th}:force_original_aspect_ratio=decrease")
            filters.append(f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=#{pad_color}")

    effective_duration = info["duration"]
    if start:
        effective_duration -= start
    if end:
        effective_duration = min(effective_duration, end - (start or 0))
    if speed and speed != 1.0:
        effective_duration /= speed

    if fade_in and fade_in > 0:
        filters.append(f"fade=t=in:st=0:d={fade_in}")
    if fade_out and fade_out > 0:
        fade_start = max(0, effective_duration - fade_out)
        filters.append(f"fade=t=out:st={fade_start}:d={fade_out}")

    filters.append("format=yuv420p")

    vf = ",".join(filters)

    cmd = ["ffmpeg", "-y"] + input_args
    cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    cmd += ["-r", str(fps)]
    cmd += ["-an"]
    cmd += [str(output_path)]

    print(f"Running FFmpeg...", file=sys.stderr)
    print(f"  Filters: {vf}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg error:\n{result.stderr[-1000:]}", file=sys.stderr)
        sys.exit(1)
    return True


def process_with_blur(input_path, output_path, crop, speed, target_res,
                      blur_sigma, blur_fill, blur_feather, start, end,
                      fade_in, fade_out, crf, fps):
    """Selective focus blur with smooth feathered edges.

    Crops a context region at the target aspect ratio centered on the focus
    crop, sized so the focus fills ``blur_fill`` of the output by its
    constraining dimension. Uses maskedmerge with a feathered gradient mask
    so the sharp focus area blends smoothly into the blurred background.
    """
    info = get_video_info(input_path)
    src_w, src_h = info["width"], info["height"]
    tw, th = target_res["width"], target_res["height"]

    input_args = ["-i", str(input_path)]
    if start is not None:
        input_args = ["-ss", str(start)] + input_args
    if end is not None:
        if start:
            input_args += ["-t", str(end - start)]
        else:
            input_args += ["-t", str(end)]

    speed_filter = f"setpts=PTS/{speed}" if speed and speed != 1.0 else "null"

    effective_duration = info["duration"]
    if start:
        effective_duration -= start
    if end:
        effective_duration = min(effective_duration, end - (start or 0))
    if speed and speed != 1.0:
        effective_duration /= speed

    post_filters = []
    if fade_in and fade_in > 0:
        post_filters.append(f"fade=t=in:st=0:d={fade_in}")
    if fade_out and fade_out > 0:
        fade_start = max(0, effective_duration - fade_out)
        post_filters.append(f"fade=t=out:st={fade_start}:d={fade_out}")
    post_filters.append("format=yuv420p")
    post_str = "," + ",".join(post_filters)

    if crop:
        target_ar = tw / th
        cx = crop["x"] + crop["w"] / 2
        cy = crop["y"] + crop["h"] / 2

        focus_ar = crop["w"] / crop["h"]
        if focus_ar <= target_ar:
            bg_h = crop["h"] / blur_fill
            bg_w = bg_h * target_ar
        else:
            bg_w = crop["w"] / blur_fill
            bg_h = bg_w / target_ar

        if bg_w > src_w:
            bg_w = src_w
            bg_h = bg_w / target_ar
        if bg_h > src_h:
            bg_h = src_h
            bg_w = bg_h * target_ar

        bg_w = int(bg_w) - int(bg_w) % 2
        bg_h = int(bg_h) - int(bg_h) % 2

        bg_x = int(max(0, min(cx - bg_w / 2, src_w - bg_w)))
        bg_y = int(max(0, min(cy - bg_h / 2, src_h - bg_h)))

        anchor_margin = 50
        focus_b = crop["y"] + crop["h"]
        focus_r = crop["x"] + crop["w"]
        if focus_b + anchor_margin >= src_h:
            bg_y = max(0, int(focus_b - bg_h))
        if focus_r + anchor_margin >= src_w:
            bg_x = max(0, int(focus_r - bg_w))
        if crop["y"] < anchor_margin:
            bg_y = int(crop["y"])
        if crop["x"] < anchor_margin:
            bg_x = int(crop["x"])

        scale_factor = tw / bg_w
        sfx = int((crop["x"] - bg_x) * scale_factor)
        sfy = int((crop["y"] - bg_y) * scale_factor)
        sfw = int(crop["w"] * scale_factor)
        sfh = int(crop["h"] * scale_factor)
        sfw -= sfw % 2
        sfh -= sfh % 2

        edge_snap = int(blur_feather * 2)
        mx = 0 if sfx < edge_snap else sfx
        my = 0 if sfy < edge_snap else sfy
        mr = tw if (tw - (sfx + sfw)) < edge_snap else sfx + sfw
        mb = th if (th - (sfy + sfh)) < edge_snap else sfy + sfh
        mw = mr - mx
        mh = mb - my

        filter_complex = (
            f"[0:v]crop={bg_w}:{bg_h}:{bg_x}:{bg_y},{speed_filter},"
            f"scale={tw}:{th},split=3[sharp][forblur][formask];"
            f"[forblur]gblur=sigma={blur_sigma}[blurred];"
            f"[formask]drawbox=x=0:y=0:w=iw:h=ih:c=black:t=fill,"
            f"drawbox=x={mx}:y={my}:w={mw}:h={mh}:c=white:t=fill,"
            f"gblur=sigma={blur_feather}[mask];"
            f"[blurred][sharp][mask]maskedmerge{post_str}[out]"
        )
    else:
        filter_complex = (
            f"[0:v]{speed_filter},"
            f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},"
            f"gblur=sigma={blur_sigma}{post_str}[out]"
        )

    cmd = ["ffmpeg", "-y"] + input_args
    cmd += ["-filter_complex", filter_complex, "-map", "[out]"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    cmd += ["-r", str(fps)]
    cmd += ["-an"]
    cmd += [str(output_path)]

    print(f"Running FFmpeg (blur mode)...", file=sys.stderr)
    print(f"  Filter complex: {filter_complex}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg error:\n{result.stderr[-1500:]}", file=sys.stderr)
        sys.exit(1)
    return True


def process_with_zoom(input_path, output_path, keyframes, target_res, crf, fps,
                      blur_bg=True, blur_sigma=25):
    """Dynamic zoom/pan using OpenCV frame-by-frame processing.

    When blur_bg is True and the camera window doesn't fill the source frame,
    a blurred version of the full frame is composited behind the sharp crop
    for a polished look (like Screen Studio / Instagram reels).
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("Error: opencv-python and numpy required for zoom. Run:", file=sys.stderr)
        print("  pip3 install opencv-python numpy", file=sys.stderr)
        sys.exit(1)

    info = get_video_info(input_path)
    src_w, src_h = info["width"], info["height"]
    tw = target_res["width"] if target_res else src_w
    th = target_res["height"] if target_res else src_h

    for kf in keyframes:
        if "region" not in kf:
            kf["region"] = [0, 0, src_w, src_h]

    needs_blur = blur_bg and any(
        kf["region"][2] < src_w or kf["region"][3] < src_h for kf in keyframes
    )
    blur_ksize = max(3, int(blur_sigma) * 2 + 1)

    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        print(f"Error: Cannot open {input_path}", file=sys.stderr)
        sys.exit(1)

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    temp_raw = tempfile.mktemp(suffix=".mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(temp_raw, fourcc, src_fps, (tw, th))

    def get_region_at_time(t):
        if t <= keyframes[0]["t"]:
            return keyframes[0]["region"]
        if t >= keyframes[-1]["t"]:
            return keyframes[-1]["region"]

        for i in range(len(keyframes) - 1):
            kf0, kf1 = keyframes[i], keyframes[i + 1]
            if kf0["t"] <= t <= kf1["t"]:
                seg_duration = kf1["t"] - kf0["t"]
                if seg_duration <= 0:
                    return kf1["region"]
                raw_t = (t - kf0["t"]) / seg_duration
                eased = ease_in_out(raw_t) if kf1.get("ease") else raw_t
                r0, r1 = kf0["region"], kf1["region"]
                return [lerp(r0[j], r1[j], eased) for j in range(4)]

        return keyframes[-1]["region"]

    frame_idx = 0
    blur_mask = None
    mode_label = "zoom+blur" if needs_blur else "zoom"
    print(f"Processing {total_frames} frames with {mode_label} keyframes...", file=sys.stderr)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t = frame_idx / src_fps
        rx, ry, rw, rh = get_region_at_time(t)
        rx, ry = int(max(0, rx)), int(max(0, ry))
        rw, rh = int(max(1, rw)), int(max(1, rh))

        rx = min(rx, src_w - rw)
        ry = min(ry, src_h - rh)

        cropped = frame[ry:ry+rh, rx:rx+rw]
        sharp = cv2.resize(cropped, (tw, th), interpolation=cv2.INTER_LANCZOS4)

        if needs_blur:
            soft_ksize = max(3, int(blur_sigma * 0.7) * 2 + 1)
            soft = cv2.GaussianBlur(sharp, (soft_ksize, soft_ksize), blur_sigma * 0.6)

            if blur_mask is None or blur_mask.shape[:2] != (th, tw):
                blur_mask = np.ones((th, tw), dtype=np.float32)
                bt = int(th * 0.15)
                ft = int(th * 0.15)
                fb = int(th * 0.04)
                bb = int(th * 0.02)
                blur_mask[:bt, :] = 0.0
                for yp in range(ft):
                    blur_mask[bt + yp, :] = yp / ft
                for yp in range(fb):
                    blur_mask[th - bb - fb + yp, :] = (fb - yp) / fb
                blur_mask[th - bb:, :] = 0.0
                blur_mask = np.stack([blur_mask] * 3, axis=-1)

            composited = (sharp.astype(np.float32) * blur_mask +
                          soft.astype(np.float32) * (1.0 - blur_mask))
            writer.write(composited.astype(np.uint8))
        else:
            writer.write(sharp)

        frame_idx += 1
        if frame_idx % 100 == 0:
            print(f"  Frame {frame_idx}/{total_frames} ({round(100*frame_idx/total_frames)}%)", file=sys.stderr)

    cap.release()
    writer.release()

    cmd = [
        "ffmpeg", "-y", "-i", temp_raw,
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-r", str(fps), "-pix_fmt", "yuv420p",
        str(output_path)
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    os.unlink(temp_raw)

    print(f"  Zoom processing complete: {frame_idx} frames", file=sys.stderr)
    return True


def main():
    parser = argparse.ArgumentParser(description="Post-process video for social media")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("--output", "-o", default="output.mp4", help="Output path")
    parser.add_argument("--crop", "-c", help="Crop region as x:y:w:h")
    parser.add_argument("--speed", "-s", type=float, default=1.0,
                        help="Playback speed multiplier (default: 1.0)")
    parser.add_argument("--preset", "-p", choices=list(PRESETS.keys()),
                        help="Social media preset (reel, post, portrait, landscape)")
    parser.add_argument("--resolution", "-r", help="Custom resolution WxH")
    parser.add_argument("--fit", default="pad", choices=["pad", "crop", "stretch", "blur"],
                        help="How to fit video into target resolution (default: pad)")
    parser.add_argument("--pad-color", default="000000", help="Padding color hex (default: 000000)")
    parser.add_argument("--blur-sigma", type=float, default=25.0,
                        help="Gaussian blur strength for --fit blur (default: 25.0)")
    parser.add_argument("--blur-fill", type=float, default=1.0,
                        help="How much of the output the focus area fills, 0.0-1.0 (default: 1.0)")
    parser.add_argument("--blur-feather", type=float, default=30.0,
                        help="Feather radius for blur-to-focus transition (default: 30.0)")
    parser.add_argument("--zoom", "-z", help="Zoom keyframes JSON or @file.json")
    parser.add_argument("--start", help="Trim start time (seconds or HH:MM:SS)")
    parser.add_argument("--end", help="Trim end time")
    parser.add_argument("--fade-in", type=float, help="Fade-in duration in seconds")
    parser.add_argument("--fade-out", type=float, help="Fade-out duration in seconds")
    parser.add_argument("--crf", type=int, default=20,
                        help="H.264 quality 0-51 (default: 20, lower=better)")
    parser.add_argument("--fps", type=int, default=30, help="Output FPS (default: 30)")
    parser.add_argument("--max-duration", type=float,
                        help="Target max output duration in seconds; auto-calculates speed")
    parser.add_argument("--no-auto-camera", action="store_true",
                        help="Disable automatic camera keyframe generation from manifest")

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    info = get_video_info(input_path)
    print(f"Input: {input_path}", file=sys.stderr)
    print(f"  Size: {info['width']}x{info['height']}", file=sys.stderr)
    print(f"  Duration: {info['duration']:.1f}s", file=sys.stderr)
    print(f"  FPS: {info['fps']:.1f}", file=sys.stderr)

    crop = parse_crop(args.crop) if args.crop else None
    target_res = None
    if args.preset:
        target_res = PRESETS[args.preset]
    elif args.resolution:
        target_res = parse_resolution(args.resolution)

    start = parse_time(args.start) if args.start else None
    end = parse_time(args.end) if args.end else None

    if args.max_duration:
        content_duration = info["duration"]
        if start:
            content_duration -= start
        if end:
            content_duration = min(content_duration, end - (start or 0))
        needed_speed = content_duration / args.max_duration
        if needed_speed > args.speed:
            args.speed = round(needed_speed, 2)
            print(f"  Auto speed: {args.speed}x (to fit {args.max_duration}s max duration)", file=sys.stderr)

    zoom_keyframes = load_zoom_keyframes(args.zoom)

    if not zoom_keyframes and not args.no_auto_camera and target_res:
        src_ar = info["width"] / info["height"]
        tgt_ar = target_res["width"] / target_res["height"]
        if abs(src_ar - tgt_ar) > 0.05:
            manifest_path = input_path.parent / "manifest.json"
            if manifest_path.exists():
                print(f"  Auto-camera: manifest found, aspect ratio differs "
                      f"({src_ar:.2f} vs {tgt_ar:.2f})", file=sys.stderr)
                try:
                    script_dir = Path(__file__).resolve().parent
                    sys.path.insert(0, str(script_dir))
                    from auto_camera import generate_keyframes
                    manifest = json.loads(manifest_path.read_text())
                    zoom_keyframes = generate_keyframes(
                        manifest, info["width"], info["height"],
                        target_res["width"], target_res["height"],
                    )
                    if start is not None:
                        for kf in zoom_keyframes:
                            kf["t"] = max(0, kf["t"] - start)
                    print(f"  Auto-camera: generated {len(zoom_keyframes)} keyframes",
                          file=sys.stderr)
                except Exception as e:
                    print(f"  Auto-camera failed, falling back: {e}", file=sys.stderr)
                    zoom_keyframes = None

    if zoom_keyframes:
        if crop:
            print("Note: --crop is ignored when --zoom is used (zoom handles regions)", file=sys.stderr)

        zoom_input = input_path
        trim_tmp = None
        if start is not None or end is not None:
            trim_suffix = input_path.suffix or ".webm"
            trim_tmp = Path(tempfile.mktemp(suffix=trim_suffix))
            trim_cmd = ["ffmpeg", "-y"]
            if start is not None:
                trim_cmd += ["-ss", str(start)]
            trim_cmd += ["-i", str(input_path)]
            if end is not None:
                dur = (end - (start or 0))
                trim_cmd += ["-t", str(dur)]
            trim_cmd += ["-c", "copy", str(trim_tmp)]
            result = subprocess.run(trim_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                trim_cmd[-2:] = ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                                 "-an", str(trim_tmp)]
                subprocess.run(trim_cmd, capture_output=True, text=True, check=True)
            zoom_input = trim_tmp
            print(f"  Pre-trimmed to {trim_tmp} for zoom processing", file=sys.stderr)

        process_with_zoom(zoom_input, output_path, zoom_keyframes, target_res, args.crf, args.fps,
                          blur_bg=True, blur_sigma=args.blur_sigma)

        if trim_tmp and trim_tmp.exists():
            trim_tmp.unlink()

        if args.speed != 1.0 or args.fade_in or args.fade_out:
            temp = output_path.with_suffix(".tmp.mp4")
            output_path.rename(temp)
            process_with_ffmpeg(temp, output_path, None, args.speed, None, args.fit,
                                args.pad_color, None, None, args.fade_in, args.fade_out,
                                args.crf, args.fps)
            temp.unlink()
    elif args.fit == "blur" and target_res:
        process_with_blur(input_path, output_path, crop, args.speed, target_res,
                          args.blur_sigma, args.blur_fill, args.blur_feather,
                          start, end, args.fade_in, args.fade_out, args.crf, args.fps)
    else:
        process_with_ffmpeg(input_path, output_path, crop, args.speed, target_res, args.fit,
                            args.pad_color, start, end, args.fade_in, args.fade_out,
                            args.crf, args.fps)

    final_info = get_video_info(output_path)
    result = {
        "input": str(input_path),
        "output": str(output_path),
        "size": f"{final_info['width']}x{final_info['height']}",
        "duration": round(final_info["duration"], 1),
        "file_size_mb": round(output_path.stat().st_size / 1024 / 1024, 2),
    }
    print(f"\nSaved: {output_path} ({result['size']}, {result['duration']}s, {result['file_size_mb']}MB)", file=sys.stderr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
