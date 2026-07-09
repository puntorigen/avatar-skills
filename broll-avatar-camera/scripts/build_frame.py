#!/usr/bin/env python3
"""Build ONE action/POV start (or last) frame for a broll-avatar-camera clip.

Thin wrapper around the gpt-image-2 skill (same idea as avatar-camera-angles), but
instead of a talking-head re-frame it builds an ACTION shot: the avatar DOING
something, framed so we mostly see hands/props/wardrobe and the scene — a first-person
POV, over-the-shoulder, hands insert, or full-body action beat. This still then drives
prunaai/p-video (make_broll_camera.py) into a short silent clip.

The prompt locks the avatar's wardrobe + scene + lighting from a scene profile
(the same JSON used by avatar-camera-angles: subject/wardrobe/scene/light) so the
action shot reads as the same person in the same room; the --action text drives the
composition and the framing.

Usage:
    # POV over-the-hands start frame (native 2:3 master + 9:16 reel crop)
    python3 build_frame.py \
      --ref antiguo/refs/antiguo_hero.png \
      --scene-file antiguo/scene.json \
      --action "first-person POV from the old man's own eyeline, looking down at his own \
hands as they slowly turn the page of a large open antique numerology book resting on his lap" \
      --face out --crop916 -o antiguo/broll/camera/_frames/ --slug antiguo_book_open

Notes:
- gpt-image-2 renders natively at 1:1 / 3:2 / 2:3; we master at 2:3 and (--crop916)
  center-crop a clean 9:16 reel frame (native res, no upscaling, no padding bars).
- Feed the 9:16 frame to p-video so the clip comes out 9:16 (p-video follows the
  input image's ratio).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GPT_IMAGE_SCRIPT = (
    Path.home() / ".cursor/skills/gpt-image-2/scripts/generate_image.py"
)
PROFILE_FIELDS = ("subject", "wardrobe", "scene", "light")

# Face-visibility presets: how strictly to lock the avatar's face for the shot.
FACE_RULES = {
    "visible": ("The subject's face IS visible and must be the EXACT same person described above "
                "(same face, hair, beard, age) — identity must not drift. Whenever the face is "
                "turned toward the camera (frontal or three-quarter-front), the EYES MEET THE LENS "
                "— the subject looks directly at the viewer, warm and present; only let the gaze "
                "fall on the object/action when the head is clearly turned down or to the side."),
    "partial": ("Only part of the subject's face is visible (e.g. chin, cheek, side, or soft "
                "background); whatever shows must read as the same person, but the focus is the "
                "action, hands and wardrobe in the foreground."),
    "out":     ("The subject's face is OUT of frame (a true first-person POV / hands insert). "
                "Do NOT invent a floating face; lock the wardrobe, hands and scene instead so it "
                "still reads as the same person filming themselves."),
}

TEMPLATE = """\
Photorealistic action B-roll frame of the SAME person and place shown in the attached photograph — another real frame from the very same video recording (same person, same outfit, same room, same lighting), captured a moment later, but now an ACTION / point-of-view shot rather than a talking-head. This is NOT a new scene, a portrait, or an illustration.

PRESERVE EXACTLY (must not drift from the attached reference):
- Who it is: {subject}
- Wardrobe (identical, same fabric/colors/wear): {wardrobe}
- The exact room, props and background: {scene}
- Lighting and color: {light}
- Realistic detail: authentic skin and hand texture with pores and fine wrinkles, real fabric folds, real reflections, natural candle/window light; no beauty smoothing, no plastic CGI look, no added text, captions, logos or watermark.

FACE: {face_rule}

THE SHOT (this is what to compose):
{action}

{framing}

Output a single clean photorealistic frame, vertical orientation, shot on a full-frame mirrorless camera with a natural prime lens and a shallow, believable depth of field, foreground action in sharp focus and the background gently soft. It must be indistinguishable from a real still grabbed from the same recording."""

DEFAULT_FRAMING = (
    "Framing: a natural, slightly imperfect hand-held feel; the foreground subject (hands / "
    "object / action) fills the frame with the wardrobe and scene clearly placed around it; keep "
    "a little clean negative space so a caption could sit over the frame later."
)


def load_profile(scene_file, overrides):
    profile = {}
    if scene_file:
        p = Path(scene_file)
        if not p.exists():
            raise SystemExit(f"scene file not found: {p}")
        profile.update(json.loads(p.read_text(encoding="utf-8")))
    if overrides:
        profile.update({k: v for k, v in overrides.items() if v})
    missing = [f for f in PROFILE_FIELDS if not profile.get(f)]
    if missing:
        raise SystemExit("scene profile missing field(s): " + ", ".join(missing)
                         + " (provide via --scene-file or --subject/--wardrobe/--scene/--light).")
    return profile


def build_prompt(profile, action, face, framing):
    return TEMPLATE.format(
        subject=profile["subject"],
        wardrobe=profile["wardrobe"],
        scene=profile["scene"],
        light=profile["light"],
        face_rule=FACE_RULES[face],
        action=action.strip(),
        framing=(framing or DEFAULT_FRAMING).strip(),
    )


def crop_to_ratio(src_path, target_ratio, out_path):
    """Center-crop to target_ratio (w/h), no upscaling. Returns 'WxH'."""
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("Pillow is required for --crop916 (pip3 install pillow).")
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


def main():
    ap = argparse.ArgumentParser(
        description="Build one action/POV start (or last) frame via gpt-image-2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--ref", action="append", default=[], metavar="PATH",
                    help="Avatar reference image (repeatable, 1-3). Required to generate.")
    ap.add_argument("--scene-file", help="JSON scene profile (subject/wardrobe/scene/light)")
    for f in PROFILE_FIELDS:
        ap.add_argument(f"--{f}", help=f"Override the '{f}' field of the scene profile")
    ap.add_argument("--action", required=False,
                    help="What to compose: the action / POV shot of the avatar doing something.")
    ap.add_argument("--action-file", type=Path, help="Read --action from a file (for long shots).")
    ap.add_argument("--face", choices=list(FACE_RULES), default="partial",
                    help="How much of the avatar's face is in frame (default: partial).")
    ap.add_argument("--framing", help="Override the framing anchor line.")
    ap.add_argument("--aspect-ratio", "-ar", default="2:3",
                    help="Master ratio for gpt-image-2 (default 2:3 native vertical).")
    ap.add_argument("--crop916", action="store_true",
                    help="Also write a 9:16 reel crop (center-crop, no upscaling).")
    ap.add_argument("--quality", "-q", default="high", choices=["low", "medium", "high", "auto"])
    ap.add_argument("--count", "-n", type=int, default=1, help="Variations (1-10).")
    ap.add_argument("--output", "-o", default=".", help="Output dir (or path prefix).")
    ap.add_argument("--slug", default="action", help="Filename prefix.")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--gpt-image-2-script", default=str(DEFAULT_GPT_IMAGE_SCRIPT))
    ap.add_argument("--print-prompt", action="store_true", help="Print the prompt and exit.")
    args = ap.parse_args()

    action = None
    if args.action_file:
        action = Path(args.action_file).read_text(encoding="utf-8").strip()
    elif args.action:
        action = args.action
    if not action:
        ap.error("Provide --action (or --action-file).")

    profile = load_profile(args.scene_file, {f: getattr(args, f) for f in PROFILE_FIELDS})
    prompt = build_prompt(profile, action, args.face, args.framing)

    if args.print_prompt:
        print(prompt)
        return

    if not args.ref:
        ap.error("--ref is required to generate (pass the avatar reference image).")
    gpt_script = Path(args.gpt_image_2_script)
    if not gpt_script.exists():
        ap.error(f"gpt-image-2 script not found: {gpt_script}")

    out_arg = Path(args.output)
    out_dir = out_arg if (out_arg.is_dir() or args.output.endswith("/") or not out_arg.suffix) else out_arg.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    master = out_dir / f"{args.slug}.png"
    prompt_file = master.with_suffix(".prompt.txt")
    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = [sys.executable, str(gpt_script), "--prompt-file", str(prompt_file),
           "-ar", args.aspect_ratio, "-q", args.quality, "-n", str(args.count),
           "-o", str(master)]
    for r in args.ref:
        cmd += ["--ref", str(r)]

    files, last_err = [], ""
    for attempt in range(1, args.retries + 2):
        print(f"  -> generating frame (attempt {attempt})...", file=sys.stderr)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout[proc.stdout.index("{"):])
                files = payload.get("files", [])
                break
            except (ValueError, json.JSONDecodeError):
                last_err = "could not parse generate_image.py output"
        else:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
            last_err = tail[0] if tail else f"exit {proc.returncode}"
        print(f"     failed: {last_err}", file=sys.stderr)
    if not files:
        raise SystemExit(f"frame generation failed: {last_err}")

    crops = []
    if args.crop916:
        for fp in files:
            fp = Path(fp)
            cp = fp.with_name(fp.stem + "_916" + fp.suffix)
            dims = crop_to_ratio(fp, 9.0 / 16.0, cp)
            crops.append(str(cp))
            print(f"  9:16 crop: {cp} ({dims})", file=sys.stderr)

    print(json.dumps({"masters": files, "reel_916": crops,
                      "prompt_file": str(prompt_file)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
