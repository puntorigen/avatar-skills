#!/usr/bin/env python3
"""Prompt assembly for the avatar-camera-angles skill.

A camera-angle prompt is built from three pieces:

1. A FIXED block that locks identity + wardrobe + scene + lighting (so the
   output reads as another real frame of the *same* recording, not a new
   scene). This comes from a "scene profile" describing the reference image.
2. A CAMERA slot - the single thing that changes - taken from the move catalog
   (camera_moves.json).
3. A FRAMING ANCHOR that stops the model from drifting wider/looser than the
   source (the main failure mode). Each move can override the default anchor.

The wording was validated empirically against a talking-head reference frame:
the fixed block + framing anchor reliably preserve identity and the room while
only the virtual camera position changes.
"""

import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CATALOG_FILE = SCRIPT_DIR / "camera_moves.json"

PROFILE_FIELDS = ("subject", "wardrobe", "scene", "light")

TEMPLATE = """\
Photorealistic camera re-frame of the attached photograph. It must look like another real frame from the very same video recording - the same person, same outfit, same room, same lighting, same moment - captured a fraction of a second later from a slightly different camera position. This is NOT a new scene, a portrait restyle, or an illustration.

PRESERVE EXACTLY (identity and scene must not drift):
- The subject: {subject}
- Wardrobe: {wardrobe}
- The exact background and props: {scene}
- Lighting and color: {light}
- Realistic detail: authentic skin texture and pores, real reflections (including any eyewear), no beauty smoothing, no plastic look, no added text, captions, logos or watermark.

The subject keeps looking and talking directly into the lens, with a natural mid-sentence expression.

CHANGE ONLY THE CAMERA / FRAMING:
{camera}

{anchor}

Output a single clean photorealistic image, vertical orientation, shot on a modern smartphone front camera (about 26-28mm equivalent), with the subject in sharp focus and the background gently soft. It must be indistinguishable from a real still from the same recording."""


def load_catalog():
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return data["moves"], data.get("_default_anchor", "")


def load_profile(scene_file=None, overrides=None):
    """Build a scene profile dict from an optional JSON file plus CLI overrides."""
    profile = {}
    if scene_file:
        p = Path(scene_file)
        if not p.exists():
            raise FileNotFoundError(f"scene file not found: {p}")
        profile.update(json.loads(p.read_text(encoding="utf-8")))
    if overrides:
        profile.update({k: v for k, v in overrides.items() if v})
    missing = [f for f in PROFILE_FIELDS if not profile.get(f)]
    if missing:
        raise ValueError(
            "scene profile is missing required field(s): "
            + ", ".join(missing)
            + ". Provide them via --scene-file or --subject/--wardrobe/--scene/--light."
        )
    return profile


def asset_lines(profile):
    """Placement instructions for any reference assets carried by the scene
    profile (``assets: [{file, placement}]``) -- e.g. a location's logo on a
    shirt or a prop. Empty when there are none, so non-asset scenes are
    unaffected."""
    out = []
    for a in (profile.get("assets") or []):
        placement = (a.get("placement") or "").strip() if isinstance(a, dict) else ""
        if placement:
            out.append(placement)
    return out


def build_prompt(profile, move_key, moves=None, default_anchor=None):
    """Assemble the full prompt string for one camera move."""
    if moves is None or default_anchor is None:
        moves, default_anchor = load_catalog()
    if move_key not in moves:
        raise KeyError(f"unknown move: {move_key}. Known: {', '.join(moves)}")
    move = moves[move_key]
    anchor = move.get("anchor") or default_anchor
    prompt = TEMPLATE.format(
        subject=profile["subject"],
        wardrobe=profile["wardrobe"],
        scene=profile["scene"],
        light=profile["light"],
        camera=move["camera"],
        anchor=anchor,
    )
    # If this look carries asset refs, keep them crisp and correctly placed
    # across angle re-renders (they are also attached as gpt-image-2 references).
    assets = asset_lines(profile)
    if assets:
        block = "\n".join(f"- {p}" for p in assets)
        prompt += ("\n\nALSO INCORPORATE THE ATTACHED REFERENCE ASSET(S), kept identical to the "
                   "source frame (match shape, colors and any text exactly):\n" + block)
    return prompt
