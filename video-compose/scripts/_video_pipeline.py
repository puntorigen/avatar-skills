#!/usr/bin/env python3
"""Video composition pipeline primitives.

Copies and adapts the proven Ken Burns motion + xfade logic from
avatar-video-reel/scripts/stitch_video.py and exposes it as reusable functions
that consume the video-compose `timeline.json` schema (instead of a storyboard).

Public functions:
    cut_subclip(src, src_in, src_out, output, target_w, target_h)
        Cut a sub-range from a source video, scale+pad to format dims.
    image_to_clip(src, duration, output, target_w, target_h, ken_burns)
        Render a still image as a video clip with optional Ken Burns motion.
    apply_camera_motion(src, output, target_w, target_h, motion, ...)
        Apply Ken Burns motion to an existing clip (for image segments).
    stitch_with_xfade(clips, durations, transitions, output, target_w, target_h)
        Concatenate clips with xfade transitions between them.
    stitch_with_concat(clips, output)
        Fallback: simple concat without transitions.
    overlay_title(input_video, title_clip, in_at, out_at, output)
        Composite a transparent title overlay on top of the video at in/out times.
    mix_music(input_video, music_path, output, *, volume, fade_in_ms, fade_out_ms)
        Mix background music with fades into the video audio track.
    render_preview(timeline, output, scale=0.5)
        Build a low-res preview MP4 (no titles, no music, basic concat).
"""

import math
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (FORMAT_PRESETS, ffprobe_video, get_format_preset,
                     run_ffmpeg)

# Camera motion presets (copied from avatar-video-reel/stitch_video.py)
ZOOM_AMOUNT = {"subtle": 0.20, "medium": 0.30, "strong": 0.40}
DRIFT_ZOOM = {"subtle": 0.08, "medium": 0.12, "strong": 0.16}

MOTION_DEFS = {
    "zoom_center": {"zoom": True,  "pan0": (0, 0),       "pan1": (0, 0),       "ease": "inout"},
    "push_in":     {"zoom": True,  "pan0": (-0.8, -0.4), "pan1": (0, 0),       "ease": "out"},
    "push_out":    {"zoom": True,  "pan0": (0, 0),       "pan1": (0.8, 0.4),   "ease": "in", "reverse_zoom": True},
    "drift_right": {"zoom": False, "pan0": (-1, 0),      "pan1": (1, 0),       "ease": "inout"},
    "drift_left":  {"zoom": False, "pan0": (1, 0),       "pan1": (-1, 0),      "ease": "inout"},
    "drift_up":    {"zoom": False, "pan0": (0, 0.8),     "pan1": (0, -0.8),    "ease": "inout"},
    "drift_down":  {"zoom": False, "pan0": (0, -0.8),    "pan1": (0, 0.8),     "ease": "inout"},
    "none":        None,
}


def _ease_inout(t, dur):
    return 0.5 - 0.5 * math.cos(math.pi * t / max(0.01, dur))


def _ease_out(t, dur):
    x = min(1.0, t / max(0.01, dur))
    return 1.0 - (1.0 - x) ** 2.5


def _ease_in(t, dur):
    x = min(1.0, t / max(0.01, dur))
    return x ** 2.5


_EASE_FN = {"inout": _ease_inout, "out": _ease_out, "in": _ease_in}


def cut_subclip(src, src_in, src_out, output, target_w, target_h, *, fps=30):
    """Cut [src_in, src_out] from src and scale+pad to target_w x target_h.

    Uses -ss before -i for fast seek, then accurate -ss/-t after for frame precision.
    Re-encodes (so xfade transitions work cleanly downstream).
    """
    src = str(src)
    output = str(output)
    duration = max(0.1, src_out - src_in)

    seek_pre = max(0.0, src_in - 1.0)
    accurate_in = src_in - seek_pre

    vf = (f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
          f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")

    args = [
        "-ss", f"{seek_pre:.3f}",
        "-i", src,
        "-ss", f"{accurate_in:.3f}",
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-r", str(fps),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
        "-shortest",
        output,
    ]
    return run_ffmpeg(args, description=f"Cut subclip {Path(src).name}[{src_in:.2f}-{src_out:.2f}]")


def cut_subclip_silent(src, src_in, src_out, output, target_w, target_h, *, fps=30):
    """Same as cut_subclip but adds a silent audio track (so xfade audio works)."""
    src = str(src)
    output = str(output)
    duration = max(0.1, src_out - src_in)

    seek_pre = max(0.0, src_in - 1.0)
    accurate_in = src_in - seek_pre

    vf = (f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
          f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")

    args = [
        "-ss", f"{seek_pre:.3f}",
        "-i", src,
        "-ss", f"{accurate_in:.3f}",
        "-t", f"{duration:.3f}",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf,
        "-r", str(fps),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
        "-t", f"{duration:.3f}",
        output,
    ]
    return run_ffmpeg(args, description=f"Cut+silent {Path(src).name}[{src_in:.2f}-{src_out:.2f}]")


def image_to_clip(src, duration, output, target_w, target_h, *,
                  ken_burns=None, intensity="subtle", fps=30):
    """Render a still image as a video clip with optional Ken Burns motion.

    If ken_burns is None or 'none', renders a static image.
    Always adds a silent audio track so xfade transitions work cleanly.
    """
    src = str(src)
    output = str(output)
    duration = max(0.1, duration)

    if not ken_burns or ken_burns == "none":
        vf = (f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
              f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
              f"fps={fps}")
        args = [
            "-loop", "1", "-i", src,
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{duration:.3f}",
            "-vf", vf,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "libx264", "-crf", "20", "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
            output,
        ]
        return run_ffmpeg(args, description=f"Image-to-clip {Path(src).name} ({duration:.2f}s)")

    return _image_with_motion(src, duration, output, target_w, target_h,
                              ken_burns, intensity, fps)


def _image_with_motion(src, duration, output, target_w, target_h,
                       motion, intensity, fps):
    """Render a still image with Ken Burns motion using MoviePy."""
    try:
        from moviepy import ImageClip, AudioClip
    except ImportError:
        print("  Warning: moviepy not available, falling back to static image", file=sys.stderr)
        return image_to_clip(src, duration, output, target_w, target_h, ken_burns=None, fps=fps)

    from PIL import Image
    import numpy as np

    mdef = MOTION_DEFS.get(motion)
    if mdef is None:
        return image_to_clip(src, duration, output, target_w, target_h, ken_burns=None, fps=fps)

    if mdef["zoom"]:
        z_amount = ZOOM_AMOUNT.get(intensity, 0.20)
        if mdef.get("reverse_zoom"):
            z0, z1 = 1.0 + z_amount, 1.0
        else:
            z0, z1 = 1.0, 1.0 + z_amount
    else:
        z_base = 1.0 + DRIFT_ZOOM.get(intensity, 0.08)
        z0, z1 = z_base, z_base

    px0, py0 = mdef["pan0"]
    px1, py1 = mdef["pan1"]
    ease_fn = _EASE_FN.get(mdef.get("ease", "inout"), _ease_inout)

    img = Image.open(src).convert("RGB")
    iw, ih = img.size

    src_aspect = iw / ih
    tgt_aspect = target_w / target_h
    if src_aspect > tgt_aspect:
        new_h = target_h
        new_w = int(round(new_h * src_aspect))
    else:
        new_w = target_w
        new_h = int(round(new_w / src_aspect))

    new_w = int(round(new_w * 1.05))
    new_h = int(round(new_h * 1.05))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    base_arr = np.array(img)

    base_clip = ImageClip(base_arr, duration=duration).with_fps(fps)

    def motion_frame(get_frame, t):
        frame = get_frame(t)
        p = ease_fn(t, duration)

        zoom = z0 + (z1 - z0) * p
        pan_x = px0 + (px1 - px0) * p
        pan_y = py0 + (py1 - py0) * p

        h, w = frame.shape[:2]
        crop_w = max(2, int(target_w / zoom))
        crop_h = max(2, int(target_h / zoom))
        crop_w = min(crop_w, w)
        crop_h = min(crop_h, h)

        max_off_x = (w - crop_w) / 2.0
        max_off_y = (h - crop_h) / 2.0
        cx = int(w / 2.0 + pan_x * max_off_x)
        cy = int(h / 2.0 + pan_y * max_off_y)

        x1 = max(0, min(cx - crop_w // 2, w - crop_w))
        y1 = max(0, min(cy - crop_h // 2, h - crop_h))

        cropped = frame[y1:y1 + crop_h, x1:x1 + crop_w]
        return np.array(Image.fromarray(cropped).resize((target_w, target_h), Image.LANCZOS))

    out_clip = base_clip.transform(motion_frame, apply_to=["mask"]).with_duration(duration)
    silence = AudioClip(lambda t: [0.0, 0.0], duration=duration, fps=44100)
    out_clip = out_clip.with_audio(silence)

    out_clip.write_videofile(
        str(output),
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="128k",
        preset="medium",
        logger=None,
    )
    out_clip.close()
    return Path(output).exists()


def apply_camera_motion(input_path, output_path, target_w, target_h,
                        motion, *, intensity="subtle", fps=30):
    """Apply Ken Burns to an existing video clip (e.g. a previously cut subclip).

    For static images use image_to_clip directly. This function is for video sources
    that should also have a subtle camera move applied on top.
    """
    if motion in (None, "none"):
        return run_ffmpeg(
            ["-i", str(input_path),
             "-c:v", "libx264", "-crf", "20", "-preset", "medium",
             "-c:a", "copy", str(output_path)],
            description="Pass-through (no motion)",
        )

    try:
        from moviepy import VideoFileClip
    except ImportError:
        print("  Warning: moviepy not available, copying input through", file=sys.stderr)
        return run_ffmpeg(
            ["-i", str(input_path), "-c", "copy", str(output_path)],
            description="Pass-through (no moviepy)",
        )

    mdef = MOTION_DEFS.get(motion)
    if mdef is None:
        return run_ffmpeg(
            ["-i", str(input_path), "-c", "copy", str(output_path)],
            description="Pass-through (unknown motion)",
        )

    from PIL import Image
    import numpy as np

    if mdef["zoom"]:
        z_amount = ZOOM_AMOUNT.get(intensity, 0.20)
        if mdef.get("reverse_zoom"):
            z0, z1 = 1.0 + z_amount, 1.0
        else:
            z0, z1 = 1.0, 1.0 + z_amount
    else:
        z_base = 1.0 + DRIFT_ZOOM.get(intensity, 0.08)
        z0, z1 = z_base, z_base

    px0, py0 = mdef["pan0"]
    px1, py1 = mdef["pan1"]
    ease_fn = _EASE_FN.get(mdef.get("ease", "inout"), _ease_inout)

    clip = VideoFileClip(str(input_path)).resized((target_w, target_h))
    dur = clip.duration

    def motion_frame(get_frame, t):
        frame = get_frame(t)
        p = ease_fn(t, dur)

        zoom = z0 + (z1 - z0) * p
        pan_x = px0 + (px1 - px0) * p
        pan_y = py0 + (py1 - py0) * p

        h, w = frame.shape[:2]
        crop_w = int(w / zoom)
        crop_h = int(h / zoom)

        max_off_x = (w - crop_w) / 2.0
        max_off_y = (h - crop_h) / 2.0
        cx = int(w / 2.0 + pan_x * max_off_x)
        cy = int(h / 2.0 + pan_y * max_off_y)

        x1 = max(0, min(cx - crop_w // 2, w - crop_w))
        y1 = max(0, min(cy - crop_h // 2, h - crop_h))

        cropped = frame[y1:y1 + crop_h, x1:x1 + crop_w]
        return np.array(Image.fromarray(cropped).resize((w, h), Image.LANCZOS))

    out_clip = clip.transform(motion_frame)
    out_clip.write_videofile(
        str(output_path), fps=fps, codec="libx264",
        audio_codec="aac", audio_bitrate="128k",
        preset="medium", logger=None,
    )
    clip.close()
    return Path(output_path).exists()


def stitch_with_xfade(clips, durations, transitions, output, target_w, target_h, *, fps=30):
    """Stitch clips with per-pair xfade transitions.

    Args:
        clips: list of clip paths (already normalized to target dims)
        durations: list of durations matching clips (length N)
        transitions: list of (kind, duration) tuples for transitions BETWEEN clips (length N-1).
            kind is one of: cut, fade, dissolve, slideleft, slideright, slideup,
                            slidedown, circleopen, circleclose, wipeleft, wiperight,
                            radial, smoothleft, smoothright, smoothup, smoothdown.
            'cut' means duration=0 (no transition).
        output: output mp4 path
        target_w, target_h: video dimensions
        fps: target frame rate

    Returns True on success.
    """
    n = len(clips)
    if n == 0:
        return False
    if n == 1:
        return run_ffmpeg(
            ["-i", str(clips[0]), "-c:v", "libx264", "-crf", "20", "-preset", "medium",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(output)],
            description="Single-clip pass-through",
        )

    if len(transitions) != n - 1:
        raise ValueError(f"Need {n-1} transitions, got {len(transitions)}")

    input_args = []
    for clip in clips:
        input_args.extend(["-i", str(clip)])

    vfilters = []
    afilters = []

    offsets = []
    cumulative = 0.0
    for i in range(n - 1):
        td_i = max(0.0, transitions[i][1])
        offset = cumulative + durations[i] - td_i
        offsets.append(offset)
        cumulative = offset

    prev_v = "[0:v]"
    prev_a = "[0:a]"

    for i in range(1, n):
        kind, td_i = transitions[i - 1]
        offset = offsets[i - 1]
        out_v = f"[v{i}]" if i < n - 1 else "[vout]"
        out_a = f"[a{i}]" if i < n - 1 else "[aout]"

        if kind == "cut" or td_i <= 0.001:
            vfilters.append(f"{prev_v}[{i}:v]concat=n=2:v=1:a=0{out_v}")
            afilters.append(f"{prev_a}[{i}:a]concat=n=2:v=0:a=1{out_a}")
        else:
            xfade_kind = "fade" if kind == "dissolve" else kind
            vfilters.append(
                f"{prev_v}[{i}:v]xfade=transition={xfade_kind}:duration={td_i}:offset={offset:.3f}{out_v}"
            )
            afilters.append(
                f"{prev_a}[{i}:a]acrossfade=d={td_i}:c1=tri:c2=tri{out_a}"
            )

        prev_v = out_v
        prev_a = out_a

    filter_str = ";\n".join(vfilters + afilters)

    return run_ffmpeg(
        input_args + [
            "-filter_complex", filter_str,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "20", "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
            "-r", str(fps),
            str(output),
        ],
        description=f"Stitching {n} clips with xfade transitions",
    )


def stitch_with_concat(clips, output, *, target_w=None, target_h=None, fps=30):
    """Concat clips without transitions using the concat demuxer.

    Assumes all clips already have matching dims/codec/sample rate.
    """
    if not clips:
        return False
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for clip in clips:
            f.write(f"file '{Path(clip).resolve()}'\n")
        list_file = f.name

    args = ["-f", "concat", "-safe", "0", "-i", list_file]
    if target_w and target_h:
        args += ["-vf", f"scale={target_w}:{target_h},setsar=1", "-r", str(fps),
                 "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k"]
    else:
        args += ["-c:v", "libx264", "-crf", "20", "-preset", "medium",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k"]
    args += [str(output)]
    ok = run_ffmpeg(args, description=f"Concat {len(clips)} clips")
    Path(list_file).unlink(missing_ok=True)
    return ok


def overlay_titles(input_video, titles, output, *, target_w=None, target_h=None):
    """Composite multiple transparent title overlays onto a base video.

    Args:
        input_video: base mp4 path
        titles: list of dicts: {path, in_at, out_at}
        output: final mp4 path

    Each title is overlayed at its [in_at, out_at] window using FFmpeg's
    overlay=enable='between(t,X,Y)'. Titles are stacked sequentially; output of
    one overlay becomes input of the next.
    """
    if not titles:
        import shutil
        shutil.copy2(str(input_video), str(output))
        return True

    input_args = ["-i", str(input_video)]
    for title in titles:
        input_args.extend(["-i", str(title["path"])])

    filter_parts = []
    prev = "[0:v]"
    for i, title in enumerate(titles, start=1):
        out_label = f"[v{i}]" if i < len(titles) else "[vout]"
        in_at = float(title["in_at"])
        out_at = float(title["out_at"])
        filter_parts.append(
            f"{prev}[{i}:v]overlay=0:0:enable='between(t,{in_at:.3f},{out_at:.3f})'{out_label}"
        )
        prev = out_label

    filter_str = ";".join(filter_parts)

    return run_ffmpeg(
        input_args + [
            "-filter_complex", filter_str,
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", "20", "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(output),
        ],
        description=f"Overlaying {len(titles)} titles",
    )


def mix_music(input_video, music_path, output, *, volume=0.7,
              fade_in_ms=500, fade_out_ms=2000, video_has_audio=True):
    """Mix background music with fade-in/out into the video's audio track.

    If the input video has no original audio, music becomes the only track.
    """
    fade_in_s = fade_in_ms / 1000.0
    fade_out_s = fade_out_ms / 1000.0

    duration = ffprobe_video(input_video)["duration"]
    fade_out_start = max(0.0, duration - fade_out_s)

    music_filter = (
        f"[1:a]volume={volume},"
        f"afade=t=in:st=0:d={fade_in_s:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_s:.3f}[music]"
    )

    if video_has_audio:
        filter_complex = (
            music_filter +
            ";[0:a][music]amix=inputs=2:duration=first:dropout_transition=3,volume=1.4[aout]"
        )
        map_args = ["-map", "0:v", "-map", "[aout]"]
    else:
        filter_complex = music_filter + ";[music]anull[aout]"
        map_args = ["-map", "0:v", "-map", "[aout]"]

    return run_ffmpeg(
        ["-i", str(input_video), "-i", str(music_path),
         "-filter_complex", filter_complex] +
        map_args +
        ["-c:v", "copy",
         "-c:a", "aac", "-ar", "44100", "-b:a", "192k",
         "-shortest",
         str(output)],
        description="Mixing background music",
    )


def detect_video_audio(path):
    """Return True if the video has an audio stream."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "stream=codec_type",
        "-of", "json", str(path)
    ]
    import json as _json
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        info = _json.loads(result.stdout)
        return any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    except Exception:
        return False
