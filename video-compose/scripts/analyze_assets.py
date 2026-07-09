#!/usr/bin/env python3
"""Analyze a folder of source videos and images and emit assets.json.

Pipeline per video:
  1. ffprobe → duration, fps, resolution
  2. PySceneDetect (ContentDetector) → scene boundaries
  3. Per scene: extract midpoint keyframe (OpenCV)
  4. Per scene: blur score (Laplacian variance), brightness, dominant color
  5. Per scene: motion score (sampled frame diff)
  6. Per scene: Gemini Vision 1-line description of the keyframe

Pipeline per image:
  1. Dimensions, dominant color
  2. Gemini Vision 1-line description

Cache: assets.json includes a `_cache` map of {path: signature} so repeated runs
skip already-analyzed media. Pass --force to re-analyze everything.

Usage:
    python3 analyze_assets.py --assets ./media/ -o assets.json
    python3 analyze_assets.py --assets ./media/ -o assets.json --force
    python3 analyze_assets.py --assets ./media/ -o assets.json --no-vision
    python3 analyze_assets.py --assets ./media/ -o assets.json --max-scenes 8
"""

import argparse
import concurrent.futures
import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (IMAGE_EXTS, VIDEO_EXTS, asset_signature, ffprobe_video,
                     get_gemini_api_key, is_image, is_video, list_media_files,
                     load_json, save_json)

VISION_MODEL = "gemini-2.5-flash"
VISION_PARALLEL = 6
SCENE_THRESHOLD = 27.0
MAX_SCENES_PER_CLIP = 12
KEYFRAME_QUALITY = 90


def detect_scenes(video_path, *, threshold=SCENE_THRESHOLD, max_scenes=MAX_SCENES_PER_CLIP):
    """Return list of (start_sec, end_sec) scene tuples."""
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import AdaptiveDetector
    except ImportError:
        print("  Warning: scenedetect not available, treating clip as single scene",
              file=sys.stderr)
        info = ffprobe_video(video_path)
        return [(0.0, info["duration"])] if info["duration"] > 0 else []

    try:
        video = open_video(str(video_path))
        scene_manager = SceneManager()
        scene_manager.add_detector(AdaptiveDetector(adaptive_threshold=3.0,
                                                     min_scene_len=15))
        scene_manager.detect_scenes(video=video, show_progress=False)
        scene_list = scene_manager.get_scene_list()

        if not scene_list:
            info = ffprobe_video(video_path)
            return [(0.0, info["duration"])] if info["duration"] > 0 else []

        scenes = [(float(s.get_seconds()), float(e.get_seconds())) for s, e in scene_list]

        if len(scenes) > max_scenes:
            kept = sorted(range(len(scenes)),
                          key=lambda i: scenes[i][1] - scenes[i][0],
                          reverse=True)[:max_scenes]
            scenes = sorted([scenes[i] for i in kept], key=lambda x: x[0])

        return scenes
    except Exception as e:
        print(f"  scenedetect failed for {Path(video_path).name}: {e}", file=sys.stderr)
        info = ffprobe_video(video_path)
        return [(0.0, info["duration"])] if info["duration"] > 0 else []


def extract_keyframe(video_path, timestamp, output_path):
    """Extract a single frame at `timestamp` (seconds) using OpenCV.

    OpenCV is much faster than spawning ffmpeg here since we're sampling many
    frames per video.
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return False

    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        return False

    cv2.imwrite(str(output_path), frame, [cv2.IMWRITE_JPEG_QUALITY, KEYFRAME_QUALITY])
    cap.release()
    return True


def score_frame_quality(frame_bgr):
    """Compute blur (Laplacian variance, normalized) and brightness for a BGR frame.

    Returns (blur_score [0..1], brightness [0..1], dominant_color "#rrggbb").
    """
    import cv2
    import numpy as np

    if frame_bgr is None or frame_bgr.size == 0:
        return 0.0, 0.0, "#000000"

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F).var()
    blur_score = float(min(1.0, laplacian / 800.0))

    brightness = float(gray.mean() / 255.0)

    small = cv2.resize(frame_bgr, (32, 32), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.float32)
    mean_bgr = pixels.mean(axis=0)
    b, g, r = (int(round(c)) for c in mean_bgr)
    dom = f"#{r:02x}{g:02x}{b:02x}"

    return blur_score, brightness, dom


def score_motion(video_path, start_sec, end_sec, *, samples=4):
    """Score motion intensity in a scene by frame-differencing sampled frames.

    Higher = more motion. Normalized to [0..1].
    """
    import cv2
    import numpy as np

    if end_sec - start_sec < 0.5:
        return 0.0

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0.0

    n = max(2, samples)
    times = [start_sec + (end_sec - start_sec) * i / (n - 1) for i in range(n)]
    prev_gray = None
    diffs = []

    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                diffs.append(float(diff.mean()))
            prev_gray = gray
    finally:
        cap.release()

    if not diffs:
        return 0.0

    avg_diff = sum(diffs) / len(diffs)
    return float(min(1.0, avg_diff / 30.0))


def score_image(image_path):
    """Compute (resolution, dominant_color) for an image."""
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        try:
            from PIL import Image
            with Image.open(image_path) as pil:
                pil = pil.convert("RGB")
                w, h = pil.size
                small = pil.resize((32, 32))
                pixels = list(small.getdata())
                avg = tuple(sum(p[c] for p in pixels) // len(pixels) for c in range(3))
                dom = f"#{avg[0]:02x}{avg[1]:02x}{avg[2]:02x}"
                return [w, h], dom
        except Exception as e:
            print(f"  Could not read image {image_path}: {e}", file=sys.stderr)
            return [0, 0], "#000000"

    h, w = img.shape[:2]
    _, _, dom = score_frame_quality(img)
    return [w, h], dom


VISION_PROMPT = (
    "Describe this image in ONE concise English sentence (max 25 words). "
    "Focus on: subject, action/expression, setting, lighting/mood, framing. "
    "Be specific (e.g. 'golden retriever puppy sleeping on a striped blanket, "
    "soft window light, intimate close-up') rather than generic ('a dog')."
)


def describe_image(image_path, *, api_key=None):
    """Call Gemini Vision to describe a single image. Returns a string or None."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    if api_key is None:
        api_key = get_gemini_api_key()

    try:
        client = genai.Client(api_key=api_key)
        img_bytes = Path(image_path).read_bytes()
        mime = "image/jpeg" if Path(image_path).suffix.lower() in (".jpg", ".jpeg") else "image/png"

        resp = client.models.generate_content(
            model=VISION_MODEL,
            contents=[VISION_PROMPT, types.Part.from_bytes(data=img_bytes, mime_type=mime)],
            config=types.GenerateContentConfig(temperature=0.4, max_output_tokens=80),
        )
        text = (resp.text or "").strip()
        text = text.replace("\n", " ").strip()
        return text or None
    except Exception as e:
        print(f"  Gemini Vision error on {Path(image_path).name}: {e}", file=sys.stderr)
        return None


def analyze_video(video_path, *, with_vision=True, max_scenes=MAX_SCENES_PER_CLIP,
                  api_key=None, tmpdir=None):
    """Analyze a single video and return a structured dict."""
    info = ffprobe_video(video_path)
    if info["duration"] <= 0.05:
        return None

    print(f"  → {Path(video_path).name} ({info['duration']:.1f}s, {info['width']}x{info['height']})",
          file=sys.stderr)

    scenes_raw = detect_scenes(video_path, max_scenes=max_scenes)
    print(f"     scenes: {len(scenes_raw)}", file=sys.stderr)

    import cv2

    scenes_out = []
    keyframe_paths = []

    cap = cv2.VideoCapture(str(video_path))

    try:
        for idx, (s, e) in enumerate(scenes_raw):
            mid = s + (e - s) / 2.0
            cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            blur, bright, dom = score_frame_quality(frame)
            motion = score_motion(video_path, s, e)

            kf_path = Path(tmpdir) / f"{Path(video_path).stem}_scene{idx:02d}.jpg"
            cv2.imwrite(str(kf_path), frame, [cv2.IMWRITE_JPEG_QUALITY, KEYFRAME_QUALITY])

            scene = {
                "in": round(s, 3),
                "out": round(e, 3),
                "duration": round(e - s, 3),
                "blur_score": round(blur, 3),
                "motion_score": round(motion, 3),
                "brightness": round(bright, 3),
                "dominant_color": dom,
                "description": None,
            }
            scenes_out.append(scene)
            keyframe_paths.append(kf_path)
    finally:
        cap.release()

    if with_vision and api_key and keyframe_paths:
        descriptions = describe_keyframes_parallel(keyframe_paths, api_key=api_key)
        for scene, desc in zip(scenes_out, descriptions):
            scene["description"] = desc

    for kf in keyframe_paths:
        try:
            kf.unlink()
        except FileNotFoundError:
            pass

    return {
        "duration": round(info["duration"], 3),
        "fps": info["fps"],
        "resolution": [info["width"], info["height"]],
        "scenes": scenes_out,
    }


def analyze_image(image_path, *, with_vision=True, api_key=None):
    """Analyze a single image and return a structured dict."""
    res, dom = score_image(image_path)
    description = None
    if with_vision and api_key and res != [0, 0]:
        description = describe_image(image_path, api_key=api_key)

    return {
        "resolution": res,
        "dominant_color": dom,
        "description": description,
    }


def describe_keyframes_parallel(image_paths, *, api_key, max_workers=VISION_PARALLEL):
    """Describe multiple keyframes in parallel. Preserves input order."""
    results = [None] * len(image_paths)
    if not image_paths:
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(describe_image, str(p), api_key=api_key): i
            for i, p in enumerate(image_paths)
        }
        for fut in concurrent.futures.as_completed(future_to_idx):
            i = future_to_idx[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                print(f"  Vision worker error: {e}", file=sys.stderr)
                results[i] = None
    return results


def main():
    parser = argparse.ArgumentParser(description="Analyze source media folder for video-compose")
    parser.add_argument("--assets", required=True, help="Folder containing source media")
    parser.add_argument("-o", "--output", required=True, help="Output assets.json path")
    parser.add_argument("--force", action="store_true",
                        help="Re-analyze everything, ignoring cache")
    parser.add_argument("--no-vision", action="store_true",
                        help="Skip Gemini Vision descriptions (faster, no API calls)")
    parser.add_argument("--max-scenes", type=int, default=MAX_SCENES_PER_CLIP,
                        help=f"Max scenes per clip (default: {MAX_SCENES_PER_CLIP})")
    parser.add_argument("--vision-parallel", type=int, default=VISION_PARALLEL,
                        help=f"Parallel Vision API workers (default: {VISION_PARALLEL})")
    args = parser.parse_args()

    assets_dir = Path(args.assets).resolve()
    if not assets_dir.is_dir():
        print(f"Error: assets folder not found: {assets_dir}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if output_path.exists() and not args.force:
        try:
            existing = load_json(output_path)
        except Exception:
            existing = {}

    cache = existing.get("_cache", {}).get("entries", {}) if isinstance(existing, dict) else {}
    videos_out = existing.get("videos", {}) if isinstance(existing, dict) else {}
    images_out = existing.get("images", {}) if isinstance(existing, dict) else {}

    api_key = None
    if not args.no_vision:
        api_key = get_gemini_api_key()

    media_files = list_media_files(assets_dir)
    if not media_files:
        print(f"No media files found in {assets_dir}", file=sys.stderr)
        save_json(output_path, {"videos": {}, "images": {}, "_cache": {"version": 1, "entries": {}}})
        return

    print(f"Found {len(media_files)} media files in {assets_dir}", file=sys.stderr)

    new_cache = {}
    new_videos = {}
    new_images = {}

    with tempfile.TemporaryDirectory(prefix="vc_keyframes_") as tmpdir:
        for path in media_files:
            rel = str(path.relative_to(assets_dir)) if path.is_relative_to(assets_dir) else str(path)
            sig = asset_signature(path)

            if sig and cache.get(rel) == sig and not args.force:
                if is_video(path) and rel in videos_out:
                    new_videos[rel] = videos_out[rel]
                    new_cache[rel] = sig
                    continue
                if is_image(path) and rel in images_out:
                    new_images[rel] = images_out[rel]
                    new_cache[rel] = sig
                    continue

            if is_video(path):
                result = analyze_video(
                    path, with_vision=not args.no_vision,
                    max_scenes=args.max_scenes, api_key=api_key, tmpdir=tmpdir,
                )
                if result:
                    new_videos[rel] = result
                    new_cache[rel] = sig
            elif is_image(path):
                print(f"  → {path.name} (image)", file=sys.stderr)
                result = analyze_image(
                    path, with_vision=not args.no_vision, api_key=api_key,
                )
                new_images[rel] = result
                new_cache[rel] = sig

    output = {
        "version": 1,
        "assets_root": str(assets_dir),
        "videos": new_videos,
        "images": new_images,
        "_cache": {"version": 1, "entries": new_cache},
    }

    save_json(output_path, output)

    n_v = len(new_videos)
    n_i = len(new_images)
    n_scenes = sum(len(v.get("scenes", [])) for v in new_videos.values())
    cached = sum(1 for k, s in new_cache.items() if cache.get(k) == s)
    print(f"\nWrote {output_path}", file=sys.stderr)
    print(f"  videos: {n_v} ({n_scenes} scenes total)", file=sys.stderr)
    print(f"  images: {n_i}", file=sys.stderr)
    print(f"  cache hits: {cached}/{n_v + n_i}", file=sys.stderr)

    print(json.dumps({
        "output": str(output_path),
        "videos": n_v,
        "images": n_i,
        "scenes": n_scenes,
        "cache_hits": cached,
    }))


if __name__ == "__main__":
    main()
