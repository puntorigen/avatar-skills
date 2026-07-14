#!/usr/bin/env python3
"""Generate virtual camera keyframes from a broll-browser-recorder manifest.

Reads the action log and computes a smooth pan/zoom path at the target aspect
ratio.  The camera is **lazy** -- it holds position until an interaction falls
outside the current frame, then pans to include it.

Output is a JSON array of zoom keyframes compatible with process_video.py
``--zoom``.

Usage:
    python3 auto_camera.py manifest.json --preset reel -o keyframes.json
    python3 auto_camera.py manifest.json --preset reel --video input.webm
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PRESETS = {
    "reel":      {"width": 1080, "height": 1920},
    "story":     {"width": 1080, "height": 1920},
    "short":     {"width": 1080, "height": 1920},
    "post":      {"width": 1080, "height": 1080},
    "portrait":  {"width": 1080, "height": 1350},
    "landscape": {"width": 1920, "height": 1080},
}

ACTIONS_THAT_MOVE = {"click", "scroll"}


def probe_video_size(path):
    """Return (width, height) from an input video file via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(r.stdout)
    vs = next((s for s in info.get("streams", []) if s["codec_type"] == "video"), None)
    if not vs:
        print(f"Error: no video stream in {path}", file=sys.stderr)
        sys.exit(1)
    return int(vs["width"]), int(vs["height"])


def compute_camera_window(src_w, src_h, target_w, target_h):
    """Return the max camera (w, h) that fits in source at the target ratio."""
    target_ratio = target_w / target_h
    if src_w / src_h > target_ratio:
        cam_h = src_h
        cam_w = round(cam_h * target_ratio)
    else:
        cam_w = src_w
        cam_h = round(cam_w / target_ratio)
    cam_w = min(cam_w, src_w)
    cam_h = min(cam_h, src_h)
    return cam_w, cam_h


def roi_for_action(action):
    """Extract a point-ROI (x, y) from an action, or None if irrelevant."""
    atype = action.get("action", "")
    if atype == "camera":
        return None
    if atype in ACTIONS_THAT_MOVE:
        if "x" in action and "y" in action:
            return (action["x"], action["y"])
    return None


def region_contains_point(region, x, y, margin):
    """Check if (x, y) with margin is inside [rx, ry, rw, rh]."""
    rx, ry, rw, rh = region
    return (x >= rx + margin and x <= rx + rw - margin and
            y >= ry + margin and y <= ry + rh - margin)


def clamp_region(region, src_w, src_h):
    """Clamp a region so it stays within the viewport."""
    rx, ry, rw, rh = region
    rx = max(0, min(rx, src_w - rw))
    ry = max(0, min(ry, src_h - rh))
    return [rx, ry, rw, rh]


def center_camera_on_point(x, y, cam_w, cam_h, src_w, src_h):
    """Return a camera region centered on (x, y), clamped to viewport."""
    rx = x - cam_w / 2
    ry = y - cam_h / 2
    return clamp_region([rx, ry, cam_w, cam_h], src_w, src_h)


def regions_close(r1, r2, tolerance=2):
    """Check if two regions are effectively the same."""
    return all(abs(a - b) <= tolerance for a, b in zip(r1, r2))


def generate_keyframes(manifest, src_w, src_h, target_w, target_h,
                       margin=40, establish_duration=2.0, lead_time=0.3,
                       pan_speed_short=0.3, pan_speed_long=0.8):
    """Generate lazy-camera zoom keyframes from a manifest action log.

    Returns a list of keyframe dicts: [{"t": float, "region": [x,y,w,h], ...}]
    """
    cam_w, cam_h = compute_camera_window(src_w, src_h, target_w, target_h)
    actions = manifest.get("actions", [])
    video_offset = manifest.get("video_offset", 0)

    first_points = []
    for a in actions[:8]:
        p = roi_for_action(a)
        if p:
            first_points.append(p)
            break

    if first_points:
        fx, fy = first_points[0]
        establishing = center_camera_on_point(fx, fy, cam_w, cam_h, src_w, src_h)
    else:
        establishing = clamp_region([0, 0, cam_w, cam_h], src_w, src_h)

    current_frame = list(establishing)
    keyframes = [{"t": 0, "region": list(establishing)}]

    for idx, action in enumerate(actions):
        atype = action.get("action", "")
        ts = action.get("timestamp", 0) + video_offset

        if atype == "camera":
            region = action.get("region")
            if region and len(region) == 4:
                new_frame = clamp_region(region, src_w, src_h)
            elif "center" in action:
                cx, cy = action["center"]
                zoom = action.get("zoom", 1.0)
                zw = max(1, int(cam_w / zoom))
                zh = max(1, int(cam_h / zoom))
                new_frame = clamp_region(
                    [cx - zw // 2, cy - zh // 2, zw, zh], src_w, src_h
                )
            else:
                continue

            if not regions_close(current_frame, new_frame):
                dist = _pan_distance(current_frame, new_frame, src_w, src_h)
                dur = pan_speed_short if dist < 0.2 else pan_speed_long
                t_start = max(0, ts - lead_time - dur)
                keyframes.append({"t": t_start, "region": list(current_frame)})
                keyframes.append({"t": max(t_start + 0.01, ts - lead_time),
                                  "region": list(new_frame), "ease": "ease-in-out"})
            current_frame = list(new_frame)
            continue

        point = roi_for_action(action)
        if point is None:
            continue

        x, y = point
        if region_contains_point(current_frame, x, y, margin):
            continue

        new_frame = center_camera_on_point(x, y, cam_w, cam_h, src_w, src_h)

        lookahead = actions[idx + 1: idx + 6]
        for la in lookahead:
            lp = roi_for_action(la)
            if lp and not region_contains_point(new_frame, lp[0], lp[1], margin // 2):
                mid_x = (x + lp[0]) / 2
                mid_y = (y + lp[1]) / 2
                candidate = center_camera_on_point(
                    mid_x, mid_y, cam_w, cam_h, src_w, src_h
                )
                if (region_contains_point(candidate, x, y, margin // 2) and
                        region_contains_point(candidate, lp[0], lp[1], margin // 2)):
                    new_frame = candidate
                break

        if regions_close(current_frame, new_frame):
            continue

        dist = _pan_distance(current_frame, new_frame, src_w, src_h)
        dur = pan_speed_short if dist < 0.2 else pan_speed_long
        t_start = max(0, ts - lead_time - dur)

        keyframes.append({"t": t_start, "region": list(current_frame)})
        keyframes.append({"t": max(t_start + 0.01, ts - lead_time),
                          "region": list(new_frame), "ease": "ease-in-out"})
        current_frame = list(new_frame)

    keyframes = _deduplicate(keyframes)
    return keyframes


def _pan_distance(r1, r2, src_w, src_h):
    """Normalized distance between two region centers (0..1)."""
    cx1 = r1[0] + r1[2] / 2
    cy1 = r1[1] + r1[3] / 2
    cx2 = r2[0] + r2[2] / 2
    cy2 = r2[1] + r2[3] / 2
    dx = (cx2 - cx1) / src_w
    dy = (cy2 - cy1) / src_h
    return (dx ** 2 + dy ** 2) ** 0.5


def _deduplicate(keyframes):
    """Remove consecutive keyframes with the same region."""
    if len(keyframes) <= 1:
        return keyframes
    out = [keyframes[0]]
    for kf in keyframes[1:]:
        if not regions_close(out[-1]["region"], kf["region"]):
            out.append(kf)
        elif kf.get("ease"):
            out.append(kf)
        else:
            out[-1]["t"] = kf["t"]
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Generate auto-camera zoom keyframes from a manifest"
    )
    parser.add_argument("manifest", help="Path to manifest.json")
    parser.add_argument("--preset", "-p", choices=list(PRESETS.keys()),
                        help="Target preset (reel, post, portrait, landscape)")
    parser.add_argument("--resolution", "-r",
                        help="Custom target resolution WxH")
    parser.add_argument("--video", "-v",
                        help="Input video file (reads dimensions via ffprobe)")
    parser.add_argument("--video-size",
                        help="Source video size WxH (alternative to --video)")
    parser.add_argument("--margin", type=int, default=40,
                        help="Dead-zone margin in pixels (default: 40)")
    parser.add_argument("--establish", type=float, default=2.0,
                        help="Establishing shot duration in seconds (default: 2.0)")
    parser.add_argument("--lead", type=float, default=0.3,
                        help="Camera lead time before action (default: 0.3s)")
    parser.add_argument("--output", "-o", default="-",
                        help="Output keyframes JSON path (default: stdout)")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)
    manifest = json.loads(manifest_path.read_text())

    if args.preset:
        tw, th = PRESETS[args.preset]["width"], PRESETS[args.preset]["height"]
    elif args.resolution:
        parts = args.resolution.lower().split("x")
        tw, th = int(parts[0]), int(parts[1])
    else:
        print("Error: --preset or --resolution required", file=sys.stderr)
        sys.exit(1)

    if args.video:
        src_w, src_h = probe_video_size(args.video)
    elif args.video_size:
        parts = args.video_size.split("x")
        src_w, src_h = int(parts[0]), int(parts[1])
    else:
        vp = manifest.get("viewport")
        if vp:
            src_w, src_h = vp["width"], vp["height"]
        else:
            print("Error: provide --video, --video-size, or a manifest with viewport info",
                  file=sys.stderr)
            sys.exit(1)

    keyframes = generate_keyframes(
        manifest, src_w, src_h, tw, th,
        margin=args.margin,
        establish_duration=args.establish,
        lead_time=args.lead,
    )

    out_json = json.dumps(keyframes, indent=2)
    if args.output == "-":
        print(out_json)
    else:
        Path(args.output).write_text(out_json)
        print(f"Wrote {len(keyframes)} keyframes to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
