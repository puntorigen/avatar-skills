#!/usr/bin/env python3
"""Shared helpers for the avatar-invent skill.

avatar-invent fabricates a brand-new fictional avatar from a text description:
a photoreal (by default) front-facing presenter still, a set of camera angles,
and a designed voice -- written into the exact same folder structure every other
avatar in this repo uses, so avatar-reel-composer / reel-restyle can drive it.

This module only holds: config/key discovery (shared with the sibling skills),
JSON IO, the hero-prompt builder, a center-crop, sibling-script resolution and a
couple of subprocess helpers. The heavy lifting lives in the skills we delegate
to (gpt-image-2, asset-generator, avatar-camera-angles, voice-clone).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"
PRESETS_FILE = SKILL_DIR / "prompts" / "presets.json"
USER_SKILLS = Path.home() / ".cursor/skills"

PY = sys.executable or "python3"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


# ---------------------------------------------------------------------------
# Sibling-script resolution: prefer the project-local .cursor/skills copy, then
# the user-level install (gpt-image-2 / asset-generator usually only exist at
# the user level; the avatar-* and voice-* skills are version-controlled here).
# ---------------------------------------------------------------------------
def _skills_root() -> Path:
    local = SKILL_DIR.parent
    if (local / "voice-clone/scripts/clone_voice.py").exists():
        return local
    return USER_SKILLS


SKILLS_ROOT = _skills_root()


def skill_script(rel: str) -> Path:
    """Resolve a sibling skill script, preferring the project-local skills root."""
    for root in (SKILLS_ROOT, USER_SKILLS):
        cand = root / rel
        if cand.exists():
            return cand
    return SKILLS_ROOT / rel


GENERATE_ANGLES = skill_script("avatar-camera-angles/scripts/generate_angles.py")
CLONE_VOICE = skill_script("voice-clone/scripts/clone_voice.py")
GPT_IMAGE = skill_script("gpt-image-2/scripts/generate_image.py")
GEMINI_ASSET = skill_script("asset-generator/scripts/generate_asset.py")


# ---------------------------------------------------------------------------
# Config / API keys  (shared with the sibling skills, discovered automatically)
# ---------------------------------------------------------------------------
# Sibling configs that may already hold the keys we need.
_SIBLING_CONFIGS = [
    USER_SKILLS / "audio-theater/config.json",      # elevenlabs + gemini + replicate
    USER_SKILLS / "asset-generator/config.json",    # gemini
    USER_SKILLS / "gpt-image-2/config.json",        # replicate
    USER_SKILLS / "avatar-video-reel/config.json",  # replicate
    USER_SKILLS / "brand-asset-studio/config.json",
    USER_SKILLS / "bg-music-hq/config.json",
    USER_SKILLS / "bg-music/config.json",
    USER_SKILLS / "sound-effects/config.json",
    USER_SKILLS / "video-compose/config.json",
]


def load_config() -> dict:
    return try_load_json(CONFIG_FILE) or {}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _discover(env_keys, cfg_keys, *, required=False, label=""):
    for ev in env_keys:
        v = os.environ.get(ev)
        if v:
            return v
    own = load_config()
    for ck in cfg_keys:
        v = own.get(ck)
        if v:
            return v
    for path in _SIBLING_CONFIGS:
        cfg = try_load_json(path)
        if not isinstance(cfg, dict):
            continue
        for ck in cfg_keys:
            v = cfg.get(ck)
            if v:
                return v
    if required:
        print(f"Error: no {label} found.", file=sys.stderr)
        print(f"  Set it: python3 {SCRIPT_DIR / 'setup_key.py'} --help", file=sys.stderr)
        sys.exit(1)
    return None


def get_elevenlabs_api_key(required=True):
    return _discover(["ELEVENLABS_API_KEY", "ELEVEN_API_KEY"],
                     ["elevenlabs_api_key"], required=required, label="ElevenLabs API key")


def get_replicate_token(required=True):
    return _discover(["REPLICATE_API_TOKEN"],
                     ["replicate_api_token"], required=required, label="Replicate API token")


def get_gemini_api_key(required=True):
    return _discover(["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                     ["gemini_api_key"], required=required, label="Gemini API key")


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------
def load_presets() -> dict:
    return load_json(PRESETS_FILE)


# ---------------------------------------------------------------------------
# JSON IO
# ---------------------------------------------------------------------------
def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def try_load_json(path):
    try:
        return load_json(path)
    except (OSError, ValueError):
        return None


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def rel_to(path, base) -> str:
    path = Path(path).resolve()
    base = Path(base).resolve()
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def first_image(folder) -> Path | None:
    folder = Path(folder)
    if not folder.is_dir():
        return None
    imgs = sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    return imgs[0] if imgs else None


# ---------------------------------------------------------------------------
# Hero-prompt assembly
# ---------------------------------------------------------------------------
SCENE_FIELDS = ("subject", "wardrobe", "scene", "light")


def is_vertical(aspect_ratio: str) -> bool:
    return aspect_ratio.strip() in ("9:16", "2:3", "3:4", "4:5")


def style_block(style: str, presets: dict) -> dict:
    """Return {'preamble','negative_extra'} for a named style, or a custom string."""
    styles = presets.get("styles", {})
    if style in styles:
        return styles[style]
    # Treat an unknown --style value as a literal custom render-style description.
    return {"preamble": style, "negative_extra": ""}


def asset_lines(profile: dict) -> list[str]:
    """Placement instructions for a location's asset refs (logo on a shirt, a
    prop in the scene). Read from the scene profile's optional ``assets`` array
    (``[{"file": ..., "placement": ...}]``). Empty list when there are none, so
    the prompt is unchanged for avatars/looks without assets."""
    out = []
    for a in profile.get("assets") or []:
        placement = (a.get("placement") or "").strip() if isinstance(a, dict) else ""
        if placement:
            out.append(placement)
    return out


def build_hero_prompt(profile: dict, style: str, aspect_ratio: str, presets: dict,
                      *, anchor_identity: bool = False) -> str:
    """Assemble the full hero-still prompt from the scene profile + baked-in UGC
    reel framing/lighting/camera defaults + the chosen render style.

    ``anchor_identity`` prepends an identity-lock instruction (use it when a
    person reference image is attached via gpt-image-2, so a re-dressed/re-roomed
    LOCATION keeps the exact same face). The scene profile's optional ``assets``
    array adds placement instructions for attached asset refs (logo/prop). With
    ``anchor_identity=False`` and no ``assets`` the output is byte-for-byte the
    same as before (invent_avatar's behavior is untouched)."""
    sb = style_block(style, presets)
    fr = presets["framing"]
    orient = fr["vertical_note"] if is_vertical(aspect_ratio) else fr["horizontal_note"]
    neg = sb.get("negative_extra", "")
    light = (profile.get("light") or "").strip() or presets["default_light"]
    parts = [sb["preamble"], ""]
    if anchor_identity:
        parts += [
            "IDENTITY (CRITICAL): keep the EXACT same person as in the attached reference "
            "photo - same face, bone structure, skin, hair and apparent age. Only the "
            "wardrobe, setting and lighting below change. Do NOT invent a new person.",
            "",
        ]
    parts += [
        f"SUBJECT: {profile.get('subject', '').strip()}",
        f"WARDROBE: {profile.get('wardrobe', '').strip()}",
        f"SETTING: {profile.get('scene', '').strip()}",
        f"LIGHTING: {light}",
        "",
        f"FRAMING: {fr['default']} {orient}",
        f"CAMERA: {presets['camera']}",
        f"EXPRESSION: {presets['delivery']}",
        f"CONSTRAINTS: {presets['constraints']}"
        + (f" Avoid: {neg}." if neg else ""),
    ]
    assets = asset_lines(profile)
    if assets:
        parts += ["", "INCORPORATE THE ATTACHED REFERENCE ASSET(S) faithfully (match shape, "
                  "colors and any text exactly):"]
        parts += [f"- {p}" for p in assets]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Drafting (seed the structured files from a freeform brief)
# ---------------------------------------------------------------------------
def draft_scene(brief: dict, presets: dict) -> dict:
    """Seed scene.json (subject/wardrobe/scene/light) from the brief + setting."""
    setting = (brief.get("setting") or "").strip().lower()
    s = presets.get("settings", {}).get(setting) or presets["default_setting"]
    return {
        "subject": brief.get("description", "").strip(),
        "wardrobe": s["wardrobe"],
        "scene": s["scene"],
        "light": presets["default_light"],
    }


def draft_talking_profile(presets: dict) -> dict:
    dp = presets["delivery_profile"]
    return {
        "_comment": "Reusable p-video-avatar prompts for this INVENTED avatar. "
                    "Auto-loaded by avatar-talking-video when --video-prompt/"
                    "--negative-prompt are omitted.",
        "video_prompt": dp["video_prompt"],
        "negative_prompt": dp["negative_prompt"],
        "mannerisms_summary": dp["mannerisms_summary"],
    }


def draft_voice_brief(brief: dict, presets: dict) -> dict:
    lang = (brief.get("language") or "es").strip()
    v = presets["voice"]
    desc = (brief.get("voice_description") or "").strip()
    if not desc:
        desc = f"{brief.get('description', '').strip()}. {v['default_suffix']}"
    return {
        "voice_description": desc,
        "language": lang,
        "model_id": v["model_id"],
        "preview_text": v["preview_text"].get(lang, v["preview_text"]["en"]),
        "sample_text": v["sample_text"].get(lang, v["sample_text"]["en"]),
    }


# ---------------------------------------------------------------------------
# Image crop (center-crop to ratio, no upscaling)
# ---------------------------------------------------------------------------
def crop_to_ratio(src_path, target_ratio: float, out_path) -> str:
    try:
        from PIL import Image
    except ImportError:
        print("Error: Pillow is required. Run:", file=sys.stderr)
        print(f"  pip3 install -r {SCRIPT_DIR / 'requirements.txt'}", file=sys.stderr)
        sys.exit(1)
    img = Image.open(str(src_path)).convert("RGB")
    w, h = img.size
    src_ratio = w / h
    if abs(src_ratio - target_ratio) < 1e-3:
        img.save(str(out_path))
        return f"{w}x{h}"
    if target_ratio < src_ratio:
        new_w = round(h * target_ratio)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:
        new_h = round(w / target_ratio)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)
    cropped = img.crop(box)
    cropped.save(str(out_path))
    return f"{cropped.size[0]}x{cropped.size[1]}"


def ratio_value(aspect_ratio: str) -> float:
    a, b = aspect_ratio.split(":")
    return float(a) / float(b)


# ---------------------------------------------------------------------------
# Process / checkpoints
# ---------------------------------------------------------------------------
def stop(headline: str, lines, code: int = 2):
    """Print an agent-checkpoint message and exit with ``code`` (2 by default)."""
    print(f"\n  ==> {headline}", file=sys.stderr)
    for ln in lines:
        print(f"      {ln}", file=sys.stderr)
    raise SystemExit(code)


def run_child_json(cmd, *, desc=None):
    """Run a child process, stream stderr, capture stdout, parse the last JSON.

    Returns (exit_code, parsed_json_or_None).
    """
    cmd = [str(c) for c in cmd]
    if desc:
        print(f"\n  >>> {desc}", file=sys.stderr)
    print(f"      $ {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _pump():
        assert proc.stderr is not None
        for line in proc.stderr:
            sys.stderr.write(line)
        sys.stderr.flush()

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    out = proc.stdout.read() if proc.stdout else ""
    proc.wait()
    t.join(timeout=5)
    return proc.returncode, _parse_last_json(out)


def _parse_last_json(text: str):
    for line in reversed([ln for ln in (text or "").splitlines() if ln.strip()]):
        s = line.strip()
        if s.startswith("{"):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                continue
    if text and "{" in text:
        try:
            return json.loads(text[text.index("{"):])
        except json.JSONDecodeError:
            return None
    return None
