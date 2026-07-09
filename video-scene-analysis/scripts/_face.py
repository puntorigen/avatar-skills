"""MediaPipe face detection helpers for scene classification."""

import os
from pathlib import Path

import cv2
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions
from mediapipe.tasks.python.vision.core import image as mp_image

SKILL_DIR = Path(__file__).resolve().parent.parent
_LEGACY_MODELS_DIR = SKILL_DIR / "models"


def _models_dir() -> Path:
    """Support models live OUTSIDE the repo, in a shared hidden home dir
    (override with AVATAR_SKILLS_HOME)."""
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
                    f"Face model not found: {path}. "
                    f"Run: bash {SKILL_DIR}/scripts/setup_models.sh"
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
