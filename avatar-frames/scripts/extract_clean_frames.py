#!/usr/bin/env python3
"""Extract clean frames from video: sharp, no subtitles, single face."""

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions
from mediapipe.tasks.python.vision.core import image as mp_image

try:
    import easyocr
except ImportError:
    easyocr = None


def sharpness_score(frame_gray):
    return cv2.Laplacian(frame_gray, cv2.CV_64F).var()


def sharpness_in_region(frame_gray, x, y, w, h):
    h_img, w_img = frame_gray.shape[:2]
    x1 = max(0, int(x))
    y1 = max(0, int(y))
    x2 = min(w_img, int(x + w))
    y2 = min(h_img, int(y + h))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return sharpness_score(frame_gray[y1:y2, x1:x2])


def perceptual_hash(frame_gray, hash_size=8):
    resized = cv2.resize(frame_gray, (hash_size, hash_size), interpolation=cv2.INTER_AREA)
    mean_val = resized.mean()
    return (resized > mean_val).flatten()


def hamming_distance(h1, h2):
    return int(np.count_nonzero(h1 != h2))


def format_timestamp(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    return f"{h:02d}:{int(m):02d}:{s:05.2f}"


def get_video_info(cap):
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps if fps > 0 else 0
    return {
        "fps": fps,
        "total_frames": total_frames,
        "width": width,
        "height": height,
        "duration": duration,
    }


def subtitle_zones(frame):
    h, w = frame.shape[:2]
    return [
        ("top", frame[0 : int(h * 0.40), :]),
        ("overlay", frame[int(h * 0.30) : int(h * 0.85), :]),
        ("bottom", frame[int(h * 0.60) : h, :]),
    ]


def has_subtitle_text(reader, frame, min_conf=0.35, min_chars=2, min_text_height_ratio=0.02):
    h, _ = frame.shape[:2]
    min_text_height = h * min_text_height_ratio
    for zone_name, zone in subtitle_zones(frame):
        if zone.size == 0:
            continue
        results = reader.readtext(zone, detail=1, paragraph=False)
        for bbox, text, conf in results:
            cleaned = text.strip()
            if conf < min_conf or len(cleaned) < min_chars:
                continue
            ys = [point[1] for point in bbox]
            text_height = max(ys) - min(ys)
            if text_height < min_text_height:
                continue
            return True, zone_name, cleaned, float(conf)
    return False, None, None, None


def _sample_text_color(frame, boxes, bright_pct=80):
    """Mean RGB of the brightest pixels inside the caption boxes (the glyph
    strokes), so we recover the text color (usually white)."""
    pix = []
    for b in boxes:
        crop = frame[int(b["y0"]):int(b["y1"]), int(b["x0"]):int(b["x1"])]
        if crop.size == 0:
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        thr = np.percentile(gray, bright_pct)
        mask = gray >= thr
        if not mask.any():
            continue
        pix.append(crop[mask].reshape(-1, 3))
    if not pix:
        return None
    allpix = np.concatenate(pix, axis=0)
    b_, g_, r_ = allpix.mean(axis=0)  # OpenCV is BGR
    return [int(round(r_)), int(round(g_)), int(round(b_))]


def profile_caption_frame(reader, frame, *, min_conf=0.35, region_top_frac=0.45,
                          min_text_height_ratio=0.02):
    """Measure caption STYLE from one subtitled frame.

    Returns a dict with the burned-in caption's vertical position, text height,
    line count, color and casing (all as full-frame fractions / ratios), or None
    if no caption text is found. Captions in these reels sit in the lower-middle,
    so we OCR the lower region and map box coords back to full-frame.
    """
    h, w = frame.shape[:2]
    top = int(h * region_top_frac)
    region = frame[top:h, :]
    if region.size == 0:
        return None
    min_text_height = h * min_text_height_ratio
    boxes = []
    for bbox, text, conf in reader.readtext(region, detail=1, paragraph=False):
        cleaned = (text or "").strip()
        if conf < min_conf or len(cleaned) < 2:
            continue
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        th = max(ys) - min(ys)
        if th < min_text_height:
            continue
        boxes.append({"text": cleaned, "yc": top + (min(ys) + max(ys)) / 2.0, "h": th,
                      "x0": min(xs), "x1": max(xs), "y0": top + min(ys), "y1": top + max(ys)})
    if not boxes:
        return None

    boxes.sort(key=lambda b: b["yc"])
    lines = 1
    for a, b in zip(boxes, boxes[1:]):
        if (b["yc"] - a["yc"]) > 0.6 * a["h"]:
            lines += 1

    text = " ".join(b["text"] for b in sorted(boxes, key=lambda b: (b["yc"], b["x0"])))
    letters = [c for c in text if c.isalpha()]
    upper = sum(1 for c in letters if c.isupper())
    casing_ratio = (upper / len(letters)) if letters else 0.0

    return {
        "y_center_frac": (sum(b["yc"] for b in boxes) / len(boxes)) / h,
        "text_height_frac": (sum(b["h"] for b in boxes) / len(boxes)) / h,
        "lines": lines,
        "color_rgb": _sample_text_color(frame, boxes),
        "casing_ratio": casing_ratio,
        "text": text,
        "n_words": len([t for t in text.split() if any(c.isalnum() for c in t)]),
    }


def _caption_words(text):
    out = set()
    for tok in (text or "").split():
        norm = "".join(c for c in tok.lower() if c.isalnum())
        if len(norm) >= 2:
            out.add(norm)
    return out


def _estimate_progression(profs):
    """Estimate how captions change between frames: do new captions REPLACE the
    screen, or ACCUMULATE (text grows within a phrase)?  Compares consecutive
    DISTINCT caption texts and measures how much of the earlier caption survives
    into the next. Sparse/dedup'd sampling makes this approximate.
    """
    overlaps = []
    prev = None
    for p in profs:
        cur = _caption_words(p.get("text", ""))
        if not cur:
            continue
        if prev is not None and cur != prev and prev:
            overlaps.append(len(cur & prev) / max(1, len(prev)))
        prev = cur
    if not overlaps:
        return None, None
    mean_overlap = float(np.mean(overlaps))
    return ("accumulate" if mean_overlap > 0.6 else "replace"), round(mean_overlap, 3)


def aggregate_subtitle_style(profiles):
    """Aggregate per-frame caption profiles into one style descriptor.

    Captures only what's reliably measurable (position, size, color, casing,
    line count). Font family (serif vs sans), weight and italic emphasis are NOT
    auto-detected — downstream tools keep a brand-matched serif + bold-italic.
    """
    profs = [p for p in profiles if p]
    if not profs:
        return None
    yc = float(np.median([p["y_center_frac"] for p in profs]))
    th = float(np.median([p["text_height_frac"] for p in profs]))
    lines = int(round(float(np.median([p["lines"] for p in profs]))))
    casing_ratio = float(np.median([p["casing_ratio"] for p in profs]))
    casing = "upper" if casing_ratio > 0.8 else ("lower" if casing_ratio < 0.12 else "natural")
    cols = [p["color_rgb"] for p in profs if p.get("color_rgb")]
    color = [int(round(x)) for x in np.median(np.array(cols), axis=0)] if cols else None
    wpc = [p["n_words"] for p in profs if p.get("n_words")]
    words_per_caption = int(round(float(np.median(wpc)))) if wpc else None
    progression, mean_overlap = _estimate_progression(profs)
    return {
        "samples": len(profs),
        "y_frac": round(yc, 3),
        "text_height_frac": round(th, 4),
        # PIL/ffmpeg fontsize ~ cap-height / ~0.72
        "fontsize_frac": round(th / 0.72, 4),
        "lines": lines,
        "words_per_caption": words_per_caption,
        "casing": casing,
        "casing_ratio": round(casing_ratio, 3),
        "color_rgb": color,
        "color_hex": ("#%02x%02x%02x" % tuple(color)) if color else None,
        "progression": progression,
        "mean_word_overlap": mean_overlap,
        "emphasis": {
            "auto_detected": False,
            "convention": "On these reels each phrase shows a regular setup line plus "
                          "a highlighted (bold-italic, same serif) PAYOFF line — the "
                          "breath-ending / key words that complete the thought. Font "
                          "weight & italic are not OCR-detectable, so the composer "
                          "reproduces this by emphasizing each breath group's completion.",
        },
        "note": "Measured from subtitled frames via OCR. Reliable: position (y_frac), "
                "size (text_height_frac/fontsize_frac), lines, words_per_caption, color. "
                "Approximate: progression (replace vs accumulate) from sparse sampling. "
                "Not detectable: font family, weight, italic emphasis (see 'emphasis'). "
                "casing is low-confidence — OCR lowercases output, so only 'upper' "
                "(all-caps) is reliable; treat 'lower' as 'natural'.",
    }


_LEGACY_MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def _models_dir() -> Path:
    """Support models live OUTSIDE the repo, in a shared hidden home dir
    (override with AVATAR_SKILLS_HOME). This keeps large weights out of the
    published skill and shared across skills that need blaze_face."""
    root = os.environ.get("AVATAR_SKILLS_HOME") or str(Path.home() / ".avatar-skills")
    return Path(root).expanduser() / "models"


def _resolve_model(filename: str) -> Path:
    home = _models_dir() / filename
    if home.exists():
        return home
    return _LEGACY_MODELS_DIR / filename  # backward-compat


MODELS_DIR = _models_dir()
DEFAULT_FACE_MODEL_SHORT = _resolve_model("blaze_face_short_range.tflite")
DEFAULT_FACE_MODEL_FULL = _resolve_model("blaze_face_full_range.tflite")


def _build_detector(model_path, min_detection_confidence):
    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        min_detection_confidence=min_detection_confidence,
    )
    return FaceDetector.create_from_options(options)


def _detections_to_faces(detections, frame_shape, min_confidence, min_area_ratio):
    h, w = frame_shape[:2]
    faces = []
    for det in detections or []:
        score = det.categories[0].score if det.categories else 0.0
        bbox = det.bounding_box
        area_ratio = (bbox.width * bbox.height) / (w * h)
        if score < min_confidence or area_ratio < min_area_ratio:
            continue
        faces.append(
            {
                "confidence": float(score),
                "area_ratio": float(area_ratio),
                "bbox": [bbox.origin_x, bbox.origin_y, bbox.width, bbox.height],
            }
        )
    return faces


class FaceAnalyzer:
    def __init__(self, min_confidence=0.7, min_area_ratio=0.05, model_path=None):
        self.min_confidence = min_confidence
        self.min_area_ratio = min_area_ratio

        short_path = Path(model_path or DEFAULT_FACE_MODEL_SHORT)
        full_path = DEFAULT_FACE_MODEL_FULL
        for path in (short_path, full_path):
            if not path.exists():
                raise RuntimeError(
                    f"Face model not found: {path}. Run scripts/setup.sh to download models."
                )

        self._short = _build_detector(short_path, min_detection_confidence=0.4)
        self._full = _build_detector(full_path, min_detection_confidence=0.3)

    def _count_faces(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = mp_image.Image(image_format=mp_image.ImageFormat.SRGB, data=rgb)

        short_faces = _detections_to_faces(
            self._short.detect(mp_img).detections,
            frame.shape,
            min_confidence=0.4,
            min_area_ratio=0.03,
        )
        full_faces = _detections_to_faces(
            self._full.detect(mp_img).detections,
            frame.shape,
            min_confidence=0.3,
            min_area_ratio=0.008,
        )
        return max(len(short_faces), len(full_faces))

    def analyze(self, frame):
        face_count = self._count_faces(frame)
        if face_count != 1:
            return [], face_count

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = mp_image.Image(image_format=mp_image.ImageFormat.SRGB, data=rgb)
        faces = _detections_to_faces(
            self._short.detect(mp_img).detections,
            frame.shape,
            self.min_confidence,
            self.min_area_ratio,
        )
        if len(faces) != 1:
            return [], max(len(faces), face_count)
        return faces, 1

    def close(self):
        self._short.close()
        self._full.close()


def collect_candidates(video_path, sample_rate, fps):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    candidates = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_rate != 0:
            frame_idx += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        candidates.append(
            {
                "frame_idx": frame_idx,
                "timestamp": frame_idx / fps if fps > 0 else 0,
                "sharpness": sharpness_score(gray),
                "frame": frame,
                "gray": gray,
            }
        )
        frame_idx += 1

    cap.release()
    return candidates


def select_by_interval(candidates, interval, duration):
    selected = []
    for t in np.arange(0, duration, interval):
        window = [c for c in candidates if t <= c["timestamp"] < t + interval]
        if window:
            selected.append(max(window, key=lambda c: c["sharpness"]))
    return selected


def deduplicate(candidates, threshold=5):
    if len(candidates) <= 1:
        return candidates

    hashes = [perceptual_hash(c["gray"]) for c in candidates]
    kept_indices = [0]
    for i in range(1, len(candidates)):
        is_dup = any(
            hamming_distance(hashes[i], hashes[j]) < threshold for j in kept_indices
        )
        if not is_dup:
            kept_indices.append(i)
    return [candidates[i] for i in kept_indices]


def save_frame_image(frame, filepath, fmt, quality):
    if fmt == "png":
        cv2.imwrite(str(filepath), frame)
    elif fmt in ("jpeg", "jpg"):
        cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    elif fmt == "webp":
        cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_WEBP_QUALITY, quality])
    else:
        cv2.imwrite(str(filepath), frame)


def resize_frame(frame, max_dimension):
    if not max_dimension:
        return frame
    h, w = frame.shape[:2]
    if max(h, w) <= max_dimension:
        return frame
    scale = max_dimension / max(h, w)
    return cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def extract_clean_frames(
    video_path,
    output_dir,
    interval=2.0,
    min_face_sharpness=None,
    face_sharpness_percentile=10,
    sample_rate=None,
    face_min_confidence=0.7,
    face_min_area_ratio=0.05,
    ocr_min_conf=0.35,
    ocr_langs=None,
    dedup=True,
    dedup_threshold=5,
    fmt="png",
    quality=90,
    max_dimension=None,
    prefix="frame",
    subtitle_prefix="subtitle",
    include_inpaint=False,
    save_rejected=False,
    analyze_subtitle_style=True,
    subtitle_style_sample=24,
):
    if easyocr is None:
        raise RuntimeError("easyocr is required. Install with: pip install easyocr")

    ocr_langs = ocr_langs or ["es", "en"]

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"Error: Cannot open video: {video_path}", file=sys.stderr)
        sys.exit(1)
    info = get_video_info(cap)
    cap.release()

    fps = info["fps"]
    if sample_rate is None:
        sample_rate = max(1, int(fps / 2))

    print(f"Video: {video_path}", file=sys.stderr)
    print(
        f"  {info['width']}x{info['height']}, {fps:.1f} fps, "
        f"{format_timestamp(info['duration'])}, sample every {sample_rate} frame(s)",
        file=sys.stderr,
    )

    candidates = collect_candidates(video_path, sample_rate, fps)
    print(f"  Sampled {len(candidates)} frames", file=sys.stderr)

    if not candidates:
        print("Error: No frames could be read.", file=sys.stderr)
        sys.exit(1)

    interval_candidates = select_by_interval(candidates, interval, info["duration"])
    print(f"  Interval windows: {len(interval_candidates)}", file=sys.stderr)

    reader = easyocr.Reader(ocr_langs, gpu=False, verbose=False)
    face_analyzer = FaceAnalyzer(
        min_confidence=face_min_confidence,
        min_area_ratio=face_min_area_ratio,
    )

    analyzed = []
    rejected = []
    stats = {
        "blur": 0,
        "no_face": 0,
        "multi_face": 0,
        "clean": 0,
        "with_subtitles": 0,
    }

    for candidate in interval_candidates:
        entry = {
            "frame_idx": candidate["frame_idx"],
            "timestamp": candidate["timestamp"],
            "sharpness": candidate["sharpness"],
        }

        faces, face_count = face_analyzer.analyze(candidate["frame"])
        entry["face_count"] = face_count

        if face_count == 0:
            entry["reason"] = "no_face"
            stats["no_face"] += 1
            rejected.append(entry)
            continue

        if face_count > 1:
            entry["reason"] = "multi_face"
            entry["faces"] = faces
            stats["multi_face"] += 1
            rejected.append(entry)
            continue

        if not faces:
            entry["reason"] = "no_face"
            stats["no_face"] += 1
            rejected.append(entry)
            continue

        face = faces[0]
        x, y, fw, fh = face["bbox"]
        face_sharpness = sharpness_in_region(candidate["gray"], x, y, fw, fh)
        entry["face_sharpness"] = face_sharpness
        entry["face"] = face
        entry["frame"] = candidate["frame"]
        entry["gray"] = candidate["gray"]
        analyzed.append(entry)

    face_analyzer.close()

    if min_face_sharpness is None:
        if analyzed:
            face_scores = [entry["face_sharpness"] for entry in analyzed]
            min_face_sharpness = float(np.percentile(face_scores, face_sharpness_percentile))
        else:
            min_face_sharpness = 0.0
    print(
        f"  Face sharpness threshold: {min_face_sharpness:.1f} (p{face_sharpness_percentile})",
        file=sys.stderr,
    )

    accepted = []
    inpaint_candidates = []

    for entry in analyzed:
        if entry["face_sharpness"] < min_face_sharpness:
            entry["reason"] = "blur"
            stats["blur"] += 1
            rejected.append({k: v for k, v in entry.items() if k not in ("frame", "gray")})
            continue

        has_text, zone_name, text, text_conf = has_subtitle_text(
            reader, entry["frame"], min_conf=ocr_min_conf
        )
        if has_text:
            entry["reason"] = "with_subtitles"
            entry["subtitle_zone"] = zone_name
            entry["subtitle_text"] = text
            entry["subtitle_conf"] = text_conf
            stats["with_subtitles"] += 1
            inpaint_candidates.append(entry)
            continue

        entry["reason"] = None
        stats["clean"] += 1
        accepted.append(entry)

    if dedup:
        for label, group in [("clean", accepted), ("inpaint", inpaint_candidates)]:
            if len(group) > 1:
                before = len(group)
                deduped = deduplicate(group, threshold=dedup_threshold)
                if label == "clean":
                    accepted = deduped
                else:
                    inpaint_candidates = deduped
                print(f"  Dedup {label}: {before} -> {len(deduped)}", file=sys.stderr)

    save_inpaint = include_inpaint or len(accepted) == 0
    if save_inpaint and inpaint_candidates:
        if include_inpaint:
            inpaint_reason = "user_requested"
        else:
            inpaint_reason = "no_clean_frames"
            print(
                "  No clean frames found — saving inpaint candidates as fallback",
                file=sys.stderr,
            )
    else:
        inpaint_reason = None
        if inpaint_candidates and not save_inpaint:
            print(
                f"  Skipping {len(inpaint_candidates)} inpaint candidate(s) "
                f"(use --with-subtitles to include)",
                file=sys.stderr,
            )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    subtitles_dir = output_dir / "with_subtitles"

    # Caption STYLE profile (position/size/color/casing) from subtitled frames.
    # Must run before persist_entries (which drops each entry's "frame").
    subtitle_style = None
    if analyze_subtitle_style and inpaint_candidates:
        sample = inpaint_candidates[: max(1, subtitle_style_sample)]
        print(f"  Profiling subtitle style on {len(sample)} subtitled frame(s)...",
              file=sys.stderr)
        profiles = [profile_caption_frame(reader, e["frame"], min_conf=ocr_min_conf)
                    for e in sample]
        subtitle_style = aggregate_subtitle_style(profiles)
        if subtitle_style:
            (output_dir / "subtitle_style.json").write_text(
                json.dumps(subtitle_style, indent=2), encoding="utf-8")
            print(f"    style: y_frac={subtitle_style['y_frac']} "
                  f"fontsize_frac={subtitle_style['fontsize_frac']} "
                  f"lines={subtitle_style['lines']} "
                  f"words/cap={subtitle_style.get('words_per_caption')} "
                  f"progression={subtitle_style.get('progression')} "
                  f"casing={subtitle_style['casing']} "
                  f"color={subtitle_style['color_hex']}", file=sys.stderr)

    if save_rejected:
        rejected_dir = output_dir / "rejected"
        rejected_dir.mkdir(exist_ok=True)
        cap = cv2.VideoCapture(str(video_path))
        for i, entry in enumerate(rejected):
            cap.set(cv2.CAP_PROP_POS_FRAMES, entry["frame_idx"])
            ret, frame = cap.read()
            if ret:
                name = f"rejected_{entry['reason']}_{i+1:04d}.png"
                cv2.imwrite(str(rejected_dir / name), frame)
        cap.release()

    def persist_entries(entries, target_dir, name_prefix):
        saved = []
        for i, entry in enumerate(entries):
            frame = resize_frame(entry.pop("frame"), max_dimension)
            entry.pop("gray", None)

            filename = f"{name_prefix}_{i+1:04d}.{fmt}"
            filepath = target_dir / filename
            save_frame_image(frame, filepath, fmt, quality)

            h_out, w_out = frame.shape[:2]
            entry["file"] = filename
            entry["path"] = str(filepath)
            entry["size"] = f"{w_out}x{h_out}"
            entry["timestamp_fmt"] = format_timestamp(entry["timestamp"])
            entry["sharpness"] = round(entry["sharpness"], 2)
            entry["face_sharpness"] = round(entry["face_sharpness"], 2)
            saved.append(entry)
        return saved

    saved_clean = persist_entries(list(accepted), output_dir, prefix)

    saved_inpaint = []
    if save_inpaint and inpaint_candidates:
        subtitles_dir.mkdir(exist_ok=True)
        saved_inpaint = persist_entries(list(inpaint_candidates), subtitles_dir, subtitle_prefix)

    manifest = {
        "video": str(video_path),
        "video_info": info,
        "filters": {
            "interval_sec": interval,
            "min_face_sharpness": round(min_face_sharpness, 2),
            "face_sharpness_percentile": face_sharpness_percentile,
            "face_min_confidence": face_min_confidence,
            "face_min_area_ratio": face_min_area_ratio,
            "ocr_min_conf": ocr_min_conf,
            "include_inpaint": include_inpaint,
        },
        "stats": stats,
        "frames_clean": len(saved_clean),
        "frames_with_subtitles": len(saved_inpaint),
        "frames_with_subtitles_skipped": 0 if save_inpaint else len(inpaint_candidates),
        "inpaint_saved": bool(saved_inpaint),
        "inpaint_reason": inpaint_reason,
        "subtitle_style": subtitle_style,
        "frames_rejected": len(rejected),
        "frames": saved_clean,
        "with_subtitles": saved_inpaint,
        "rejected": [
            {
                "frame_index": r["frame_idx"],
                "timestamp": round(r["timestamp"], 3),
                "timestamp_fmt": format_timestamp(r["timestamp"]),
                "reason": r["reason"],
                "sharpness": round(r["sharpness"], 2),
                "face_sharpness": round(r["face_sharpness"], 2) if r.get("face_sharpness") is not None else None,
                "face_count": r.get("face_count"),
                "subtitle_text": r.get("subtitle_text"),
            }
            for r in rejected
        ],
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\nResults:", file=sys.stderr)
    print(f"  Ready: {stats['clean']} -> saved {len(saved_clean)}", file=sys.stderr)
    if saved_inpaint:
        print(
            f"  Inpaint ({inpaint_reason}): {stats['with_subtitles']} -> saved {len(saved_inpaint)}",
            file=sys.stderr,
        )
    elif stats["with_subtitles"]:
        print(
            f"  Inpaint candidates found: {stats['with_subtitles']} (not saved)",
            file=sys.stderr,
        )
    print(
        f"  Rejected: blur={stats['blur']}, no_face={stats['no_face']}, multi_face={stats['multi_face']}",
        file=sys.stderr,
    )
    print(f"  Output: {output_dir}/", file=sys.stderr)
    if saved_inpaint:
        print(f"  Inpaint: {subtitles_dir}/", file=sys.stderr)
    print(json.dumps(manifest, indent=2))

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Extract clean single-face frames without subtitles")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--output", "-o", default="frames", help="Output directory")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds per selection window")
    parser.add_argument(
        "--min-face-sharpness",
        type=float,
        default=None,
        help="Fixed face-region sharpness threshold (Laplacian variance)",
    )
    parser.add_argument(
        "--face-sharpness-percentile",
        type=float,
        default=10,
        help="Adaptive face sharpness threshold percentile (default: 10)",
    )
    parser.add_argument("--sample-rate", type=int, default=None, help="Process every Nth frame")
    parser.add_argument("--face-min-confidence", type=float, default=0.7)
    parser.add_argument("--face-min-area-ratio", type=float, default=0.05)
    parser.add_argument("--ocr-min-conf", type=float, default=0.35)
    parser.add_argument("--ocr-langs", default="es,en", help="Comma-separated OCR languages")
    parser.add_argument("--no-dedup", action="store_true")
    parser.add_argument("--dedup-threshold", type=int, default=5)
    parser.add_argument("--format", "-f", default="png", choices=["png", "jpeg", "jpg", "webp"])
    parser.add_argument("--quality", "-q", type=int, default=90)
    parser.add_argument("--max-dimension", type=int, default=None)
    parser.add_argument("--prefix", default="frame")
    parser.add_argument("--subtitle-prefix", default="subtitle", help="Filename prefix for inpaint candidates")
    parser.add_argument(
        "--with-subtitles",
        action="store_true",
        help="Also save inpaint candidates (1 face, sharp, with subtitles) in with_subtitles/",
    )
    parser.add_argument("--save-rejected", action="store_true", help="Save rejected frames for debugging")
    parser.add_argument(
        "--no-subtitle-style",
        dest="subtitle_style",
        action="store_false",
        help="Skip profiling the burned-in caption style of subtitled frames",
    )
    parser.add_argument(
        "--subtitle-style-sample",
        type=int,
        default=24,
        help="Max subtitled frames to profile for the caption style (default: 24)",
    )

    args = parser.parse_args()
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: Video not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    extract_clean_frames(
        video_path=video_path,
        output_dir=args.output,
        interval=args.interval,
        min_face_sharpness=args.min_face_sharpness,
        face_sharpness_percentile=args.face_sharpness_percentile,
        sample_rate=args.sample_rate,
        face_min_confidence=args.face_min_confidence,
        face_min_area_ratio=args.face_min_area_ratio,
        ocr_min_conf=args.ocr_min_conf,
        ocr_langs=[lang.strip() for lang in args.ocr_langs.split(",") if lang.strip()],
        dedup=not args.no_dedup,
        dedup_threshold=args.dedup_threshold,
        fmt=args.format,
        quality=args.quality,
        max_dimension=args.max_dimension,
        prefix=args.prefix,
        subtitle_prefix=args.subtitle_prefix,
        include_inpaint=args.with_subtitles,
        save_rejected=args.save_rejected,
        analyze_subtitle_style=args.subtitle_style,
        subtitle_style_sample=args.subtitle_style_sample,
    )


if __name__ == "__main__":
    main()
