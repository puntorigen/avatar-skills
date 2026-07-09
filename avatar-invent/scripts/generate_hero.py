#!/usr/bin/env python3
"""Generate the hero still of an invented avatar: a front-facing, well-lit,
seated half-body presenter, photoreal by default, in a room fit for the topic.

The prompt is assembled from the scene profile (subject/wardrobe/scene/light)
plus the baked-in UGC talking-head reel defaults (framing/camera/expression/
constraints) and the chosen render style (photoreal | soft3d | anime | custom).

Two backends:
  gpt-image-2 (default) -- best identity fidelity (so the camera-angle cuts stay
    the same person). Renders natively at 2:3 / 3:2, then we center-crop to the
    exact 9:16 / 16:9 reel frame (native resolution, no upscaling).
  gemini  (asset-generator) -- native 9:16 / 16:9 up to 4K, no crop needed.

Usage:
    python3 generate_hero.py --scene-file scene.json -o out/ --slug nora
    python3 generate_hero.py --scene-file scene.json --style soft3d -ar 16:9 -o out/
    python3 generate_hero.py --scene-file scene.json --generator gemini -o out/
    python3 generate_hero.py --scene-file scene.json --print-prompt
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _common as C  # noqa: E402


def _gpt_generate(prompt_file, out_master, *, aspect_ratio, quality, count, retries, refs=()):
    master_ratio = "2:3" if C.is_vertical(aspect_ratio) else "3:2"
    cmd = [C.PY, str(C.GPT_IMAGE),
           "--prompt-file", str(prompt_file),
           "-ar", master_ratio, "-q", quality, "-n", str(count),
           "-o", str(out_master)]
    # Reference images forwarded as gpt-image-2 input_images: an identity anchor
    # (the avatar's hero_master, so a re-dressed/re-roomed location stays the same
    # person) and/or asset refs (a logo/prop to incorporate). No refs = today's
    # text-only behavior.
    for r in refs:
        cmd += ["--ref", str(r)]
    last_err = ""
    for attempt in range(1, retries + 2):
        print(f"  -> gpt-image-2 (attempt {attempt})...", file=sys.stderr)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout[proc.stdout.index("{"):])
                files = payload.get("files", [])
                if files:
                    return files
                last_err = "no files in output"
            except (ValueError, json.JSONDecodeError):
                last_err = "could not parse generate_image.py output"
        else:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
            last_err = tail[0] if tail else f"exit {proc.returncode}"
        print(f"     failed: {last_err}", file=sys.stderr)
    raise RuntimeError(f"gpt-image-2 failed after {retries + 1} attempt(s): {last_err}")


def _gemini_generate(prompt, out_hero, *, aspect_ratio, count):
    cmd = [C.PY, str(C.GEMINI_ASSET), prompt,
           "--raw-prompt", "-ar", aspect_ratio, "-r", "2K",
           "-n", str(count), "-o", str(out_hero)]
    print("  -> gemini (asset-generator)...", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError("gemini generation failed (see asset-generator output above).")
    # asset-generator writes to -o (and _1/_2 for count>1). Collect what exists.
    out_hero = Path(out_hero)
    cands = [out_hero] if out_hero.exists() else []
    cands += sorted(out_hero.parent.glob(out_hero.stem + "_*" + out_hero.suffix))
    # Also try to read a JSON "files" array if present.
    try:
        payload = json.loads(proc.stdout[proc.stdout.index("{"):])
        for f in payload.get("files", []) or []:
            if Path(f).exists() and Path(f) not in cands:
                cands.append(Path(f))
    except (ValueError, json.JSONDecodeError):
        pass
    if not cands:
        raise RuntimeError("gemini produced no output file.")
    return [str(p) for p in cands]


def main():
    ap = argparse.ArgumentParser(
        description="Generate the hero presenter still of an invented avatar.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--scene-file", required=True, help="scene.json (subject/wardrobe/scene/light)")
    ap.add_argument("--style", default="photoreal",
                    help="Render style: photoreal | soft3d | anime | stylized_real | <custom text>")
    ap.add_argument("--aspect-ratio", "-ar", default="9:16", choices=["9:16", "16:9"])
    ap.add_argument("--generator", default="gpt-image-2", choices=["gpt-image-2", "gemini"])
    ap.add_argument("--quality", "-q", default="high", choices=["low", "medium", "high", "auto"])
    ap.add_argument("--count", "-n", type=int, default=1, help="Variations to generate (1-4)")
    ap.add_argument("--output", "-o", default=".", help="Output directory")
    ap.add_argument("--slug", default="avatar", help="Filename prefix")
    ap.add_argument("--ref", action="append", default=[], metavar="PATH",
                    help="Reference image forwarded to gpt-image-2 (repeatable). Use the "
                         "avatar's hero_master to keep the SAME person across a new look, "
                         "and/or asset images (logo/prop) to incorporate. No refs = text-only.")
    ap.add_argument("--anchor-identity", action="store_true",
                    help="Prepend an identity-lock instruction to the prompt (use with a "
                         "person reference passed via --ref, so the look changes but the face does not).")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--print-prompt", action="store_true", help="Print the prompt and exit")
    args = ap.parse_args()

    presets = C.load_presets()
    profile = C.try_load_json(args.scene_file)
    if not profile:
        ap.error(f"scene file not found or invalid: {args.scene_file}")
    missing = [f for f in C.SCENE_FIELDS if not (profile.get(f) or "").strip()]
    if missing and not args.print_prompt:
        ap.error(f"scene.json is missing fields: {', '.join(missing)}")

    for r in args.ref:
        if not Path(r).exists():
            ap.error(f"reference image not found: {r}")
    if args.ref and args.generator == "gemini":
        print("  ! --ref is only forwarded to gpt-image-2; ignoring for --generator gemini.",
              file=sys.stderr)

    prompt = C.build_hero_prompt(profile, args.style, args.aspect_ratio, presets,
                                 anchor_identity=args.anchor_identity)
    if args.print_prompt:
        print(prompt)
        return 0

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = out_dir / f"{args.slug}_hero.prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    target = C.ratio_value(args.aspect_ratio)
    masters, heroes = [], []

    if args.generator == "gpt-image-2":
        master_path = out_dir / f"{args.slug}_hero_master.png"
        files = _gpt_generate(prompt_file, master_path, aspect_ratio=args.aspect_ratio,
                              quality=args.quality, count=args.count, retries=args.retries,
                              refs=args.ref)
        for i, fp in enumerate(files):
            fp = Path(fp)
            masters.append(str(fp))
            hero = fp.with_name(f"{args.slug}_hero{'' if len(files) == 1 else f'_{i + 1}'}.png")
            dims = C.crop_to_ratio(fp, target, hero)
            heroes.append(str(hero))
            print(f"  hero {args.aspect_ratio}: {hero} ({dims})", file=sys.stderr)
    else:
        hero_path = out_dir / f"{args.slug}_hero.png"
        files = _gemini_generate(prompt, hero_path, aspect_ratio=args.aspect_ratio, count=args.count)
        heroes = files
        masters = files

    result = {
        "generator": args.generator,
        "style": args.style,
        "aspect_ratio": args.aspect_ratio,
        "prompt_file": str(prompt_file),
        "refs": args.ref,
        "anchor_identity": args.anchor_identity,
        "master": masters,
        "hero": heroes,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
