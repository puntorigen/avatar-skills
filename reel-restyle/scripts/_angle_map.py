#!/usr/bin/env python3
"""Map video-scene-analysis camera-angle slugs -> avatar-camera-angles moves.

The analysis pipeline tags each talking-head scene with a ``camera.angle`` from
a fixed vocabulary (see video-scene-analysis/scripts/_camera_vocabulary.py). The
avatar-camera-angles skill generates stills named ``<slug>_<move>_916.png`` (or
``_169.png`` for 16:9 landscape) from a slightly different move catalog
(avatar-camera-angles/scripts/camera_moves.json).
This bridges the two so a template's per-beat angle resolves to a real still for
the new avatar.

  analysis camera.angle  ->  camera-angles move
  ---------------------      -------------------
  eye_level                  eye_level
  low_angle                  low_angle
  low_angle_v2               low_angle        (v2 is a stronger contrapicado; same still)
  high_angle                 high_angle
  three_quarter              three_quarter
  dutch_tilt                 dutch_tilt
  negative_space             negative_space_left
  pull_out                   pull_out
  zoom_in                    push_in          (a tighter framing == a push-in still)
  none                       (None)           B-roll / non-pipeline insert: no still
"""

from __future__ import annotations

ANALYSIS_TO_MOVE = {
    "eye_level": "eye_level",
    "low_angle": "low_angle",
    "low_angle_v2": "low_angle",
    "high_angle": "high_angle",
    "three_quarter": "three_quarter",
    "dutch_tilt": "dutch_tilt",
    "negative_space": "negative_space_left",
    "pull_out": "pull_out",
    "zoom_in": "push_in",
    "none": None,
}

# Neutral fallback for unknown/missing angles so a talking-head beat always
# resolves to a usable image.
DEFAULT_MOVE = "eye_level"


def move_for_angle(angle):
    """Return the camera-angles move for an analysis ``camera.angle`` slug.

    ``none`` -> None (B-roll). Unknown or missing angles fall back to the
    neutral ``eye_level`` still.
    """
    if angle is None:
        return DEFAULT_MOVE
    if angle in ANALYSIS_TO_MOVE:
        return ANALYSIS_TO_MOVE[angle]
    return DEFAULT_MOVE


def needed_moves(angles) -> list[str]:
    """Ordered, de-duplicated list of moves to generate for a set of angles.

    Skips ``none`` (B-roll). Preserves first-seen order so the most-used opening
    angle is generated first.
    """
    out: list[str] = []
    for a in angles:
        mv = move_for_angle(a)
        if mv and mv not in out:
            out.append(mv)
    return out


if __name__ == "__main__":  # tiny self-check
    import json
    import sys

    angles = sys.argv[1:] or list(ANALYSIS_TO_MOVE)
    print(json.dumps({
        "mapping": {a: move_for_angle(a) for a in angles},
        "needed_moves": needed_moves(angles),
    }, indent=2))
