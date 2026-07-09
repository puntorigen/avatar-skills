#!/usr/bin/env bash
set -euo pipefail

# Support weights live OUTSIDE the repo, in a shared hidden home dir so they are
# never committed and can be reused across skills. Override with AVATAR_SKILLS_HOME.
MODELS="${AVATAR_SKILLS_HOME:-$HOME/.avatar-skills}/models"
mkdir -p "$MODELS"
curl -fsSL -o "$MODELS/blaze_face_short_range.tflite" \
  "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
curl -fsSL -o "$MODELS/blaze_face_full_range.tflite" \
  "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/1/blaze_face_full_range.tflite"
echo "Models ready in $MODELS"
