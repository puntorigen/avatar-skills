#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Support weights live OUTSIDE the repo, in a shared hidden home dir so they are
# never committed and can be reused across skills. Override with AVATAR_SKILLS_HOME.
MODELS_DIR="${AVATAR_SKILLS_HOME:-$HOME/.avatar-skills}/models"
mkdir -p "$MODELS_DIR"

SHORT_URL="https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
FULL_URL="https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/1/blaze_face_full_range.tflite"

pip3 install -r "$SKILL_DIR/scripts/requirements.txt"

for pair in "short_range:$SHORT_URL" "full_range:$FULL_URL"; do
  name="blaze_face_${pair%%:*}.tflite"
  url="${pair#*:}"
  dest="$MODELS_DIR/$name"
  if [[ ! -f "$dest" ]]; then
    echo "Downloading $name -> $dest"
    curl -fsSL -o "$dest" "$url"
  fi
done

echo "avatar-frames skill ready. Models in $MODELS_DIR"
