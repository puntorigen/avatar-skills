#!/usr/bin/env python3
"""Generate realistic camera-angle variations of a talking-head avatar.

Given ONE reference frame of a person speaking to camera, this produces new
stills of the *same* person, outfit, room and lighting, seen from a different
virtual camera position (push-in, pull-out, low/high angle, three-quarter,
Dutch tilt, off-center negative space, ...). The intent is to assemble reels
where the camera "cuts" every 4-8s while the same speaker keeps addressing the
lens - each still then drives a lip-synced talking clip (seedance-2 / VEED).

It is a thin wrapper around the `gpt-image-2` skill: it builds a validated
prompt (fixed identity/scene block + framing anchor + one camera move) and
calls that skill's generate_image.py. gpt-image-2 preserves the reference
identity at high fidelity, which is what makes the angles read as the same
recording.

gpt-image-2 renders natively only at 1:1 / 3:2 / 2:3, so we generate the
master at 2:3 (cleanest vertical) for 9:16 reels or at 3:2 (cleanest
horizontal) for 16:9 YouTube, and then center-crop the exact reel frame:
--crop916 -> a 9:16 version, --crop169 -> a 16:9 version (native resolution,
no upscaling). When you pass --crop169 without an explicit --aspect-ratio the
master defaults to 3:2 (landscape); otherwise it defaults to 2:3 (vertical).

Usage:
    # One move (vertical 9:16 reel)
    python3 generate_angles.py --ref frame.png --scene-file scene.json --move push_in -o out/

    # Several moves at once (each is its own generation)
    python3 generate_angles.py --ref frame.png --scene-file scene.json \
        --move push_in --move low_angle --move three_quarter --crop916 -o out/

    # Landscape 16:9 (YouTube): master rendered at 3:2, cropped to 16:9
    python3 generate_angles.py --ref frame.png --scene-file scene.json \
        --move push_in --move three_quarter --crop169 -o out/

    # The whole catalog / only the empirically validated moves
    python3 generate_angles.py --ref frame.png --scene-file scene.json --all -o out/
    python3 generate_angles.py --ref frame.png --scene-file scene.json --validated-only -o out/

    # Inspect the catalog or a built prompt without generating
    python3 generate_angles.py --list
    python3 generate_angles.py --scene-file scene.json --move dutch_tilt --print-prompt
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _prompt import (  # noqa: E402
    load_catalog, load_profile, build_prompt, PROFILE_FIELDS,
)

DEFAULT_GPT_IMAGE_SCRIPT = (
    Path.home() / ".cursor/skills/gpt-image-2/scripts/generate_image.py"
)


def crop_to_ratio(src_path, target_ratio, out_path):
    """Center-crop an image to target_ratio (width/height), no upscaling.

    Used to turn the native 2:3 master into a 9:16 reel frame (or the native
    3:2 master into a 16:9 frame) by trimming the sides. Returns "WxH".
    """
    try:
        from PIL import Image
    except ImportError:
        print("Error: Pillow is required for --crop916/--crop169. Run:", file=sys.stderr)
        print(f"  pip3 install -r {SCRIPT_DIR}/requirements.txt", file=sys.stderr)
        sys.exit(1)

    img = Image.open(str(src_path)).convert("RGB")
    w, h = img.size
    src_ratio = w / h
    if abs(src_ratio - target_ratio) < 1e-3:
        img.save(str(out_path))
        return f"{w}x{h}"
    if target_ratio < src_ratio:
        # Target is narrower -> trim width.
        new_w = round(h * target_ratio)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:
        # Target is taller -> trim height.
        new_h = round(w / target_ratio)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)
    cropped = img.crop(box)
    cropped.save(str(out_path))
    return f"{cropped.size[0]}x{cropped.size[1]}"


def run_one(prompt, refs, out_path, *, gpt_script, aspect_ratio, quality,
            count, retries):
    """Write the prompt to a file and call gpt-image-2's generate_image.py.

    Retries on failure (gpt-image-2 occasionally hits a transient Replicate
    read-timeout). Returns the list of saved master file paths.
    """
    prompt_file = Path(out_path).with_suffix(".prompt.txt")
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = [
        sys.executable, str(gpt_script),
        "--prompt-file", str(prompt_file),
        "-ar", aspect_ratio,
        "-q", quality,
        "-n", str(count),
        "-o", str(out_path),
    ]
    for r in refs:
        cmd += ["--ref", str(r)]

    last_err = ""
    for attempt in range(1, retries + 2):
        print(f"  -> generating (attempt {attempt})...", file=sys.stderr)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            # generate_image.py prints a JSON object as the last stdout block.
            try:
                start = proc.stdout.index("{")
                payload = json.loads(proc.stdout[start:])
                return payload.get("files", [])
            except (ValueError, json.JSONDecodeError):
                last_err = "could not parse generate_image.py output"
                print(f"     {last_err}", file=sys.stderr)
        else:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
            last_err = tail[0] if tail else f"exit code {proc.returncode}"
            print(f"     failed: {last_err}", file=sys.stderr)
    raise RuntimeError(f"generation failed after {retries + 1} attempt(s): {last_err}")


def cmd_list(moves, default_anchor):
    print("Camera moves catalog:\n")
    for key, m in moves.items():
        flag = "validated" if m.get("validated") else "experimental"
        tags = ", ".join(m.get("tags", []))
        print(f"  {key:22s} [{flag}]  {m.get('label', '')}")
        if tags:
            print(f"  {'':22s}  tags: {tags}")
    print(f"\nTotal: {len(moves)} moves "
          f"({sum(1 for m in moves.values() if m.get('validated'))} validated).")


def main():
    parser = argparse.ArgumentParser(
        description="Generate realistic camera-angle variations of a talking-head avatar.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ref", action="append", default=[], metavar="PATH",
                        help="Reference frame of the avatar (repeatable, 1-3). Required to generate.")
    parser.add_argument("--scene-file", help="JSON scene profile (keys: subject, wardrobe, scene, light)")
    for f in PROFILE_FIELDS:
        parser.add_argument(f"--{f}", help=f"Override the '{f}' field of the scene profile")
    parser.add_argument("--move", action="append", default=[], metavar="NAME",
                        help="Camera move from the catalog (repeatable)")
    parser.add_argument("--all", action="store_true", help="Generate every move in the catalog")
    parser.add_argument("--validated-only", action="store_true",
                        help="Generate only the empirically validated moves")
    parser.add_argument("--output", "-o", default=".",
                        help="Output directory (or a path prefix). Default: current dir")
    parser.add_argument("--slug", default="angle",
                        help="Filename prefix for outputs (default: 'angle')")
    parser.add_argument("--aspect-ratio", "-ar", default=None,
                        help="Master aspect ratio passed to gpt-image-2. Default: 2:3 (native "
                             "vertical), or 3:2 when --crop169 is requested without --crop916.")
    parser.add_argument("--crop916", action="store_true",
                        help="Also write a 9:16 reel crop (center-cropped from the master, no upscaling)")
    parser.add_argument("--crop169", action="store_true",
                        help="Also write a 16:9 landscape crop for YouTube (center-cropped, no upscaling)")
    parser.add_argument("--quality", "-q", default="high", choices=["low", "medium", "high", "auto"],
                        help="gpt-image-2 fidelity (default: high)")
    parser.add_argument("--count", "-n", type=int, default=1,
                        help="Variations per move (1-10, default: 1)")
    parser.add_argument("--retries", type=int, default=2,
                        help="Retries per generation on transient failure (default: 2)")
    parser.add_argument("--gpt-image-2-script", default=str(DEFAULT_GPT_IMAGE_SCRIPT),
                        help="Path to gpt-image-2's generate_image.py")
    parser.add_argument("--list", action="store_true", help="List the camera-move catalog and exit")
    parser.add_argument("--print-prompt", action="store_true",
                        help="Print the assembled prompt(s) and exit (no generation)")
    args = parser.parse_args()

    # Resolve the master aspect ratio. If the user did not force one, pick the
    # cleanest master for the requested crop: 3:2 for a 16:9 landscape crop,
    # 2:3 otherwise (vertical default, back-compatible with --crop916).
    if args.aspect_ratio is None:
        args.aspect_ratio = "3:2" if (args.crop169 and not args.crop916) else "2:3"

    moves, default_anchor = load_catalog()

    if args.list:
        cmd_list(moves, default_anchor)
        return

    # Resolve which moves to run.
    if args.all:
        selected = list(moves.keys())
    elif args.validated_only:
        selected = [k for k, m in moves.items() if m.get("validated")]
    else:
        selected = list(dict.fromkeys(args.move))  # de-dup, keep order
    if not selected:
        parser.error("Choose at least one --move, or use --all / --validated-only (see --list).")
    unknown = [m for m in selected if m not in moves]
    if unknown:
        parser.error(f"unknown move(s): {', '.join(unknown)}. See --list.")

    # Build the scene profile.
    overrides = {f: getattr(args, f) for f in PROFILE_FIELDS}
    try:
        profile = load_profile(args.scene_file, overrides)
    except (FileNotFoundError, ValueError) as e:
        parser.error(str(e))

    # Print-only mode.
    if args.print_prompt:
        for key in selected:
            prompt = build_prompt(profile, key, moves, default_anchor)
            print(f"\n===== {key} =====\n{prompt}")
        return

    # Generation requires references and the gpt-image-2 script.
    if not args.ref:
        parser.error("--ref is required to generate (pass the avatar reference frame).")
    gpt_script = Path(args.gpt_image_2_script)
    if not gpt_script.exists():
        parser.error(f"gpt-image-2 script not found: {gpt_script}")
    for r in args.ref:
        if not Path(r).exists():
            parser.error(f"reference image not found: {r}")

    out_arg = Path(args.output)
    out_dir = out_arg if (out_arg.is_dir() or args.output.endswith("/") or not out_arg.suffix) else out_arg.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for key in selected:
        print(f"\n[{key}] {moves[key].get('label', '')}", file=sys.stderr)
        prompt = build_prompt(profile, key, moves, default_anchor)
        master = out_dir / f"{args.slug}_{key}.png"
        try:
            files = run_one(
                prompt, args.ref, master,
                gpt_script=gpt_script, aspect_ratio=args.aspect_ratio,
                quality=args.quality, count=args.count, retries=args.retries,
            )
        except RuntimeError as e:
            print(f"  !! {e}", file=sys.stderr)
            results.append({"move": key, "error": str(e)})
            continue

        entry = {"move": key, "master": files}
        for suffix, ratio, label, out_key in (
            ("_916", 9.0 / 16.0, "9:16", "reel_916"),
            ("_169", 16.0 / 9.0, "16:9", "reel_169"),
        ):
            if not getattr(args, f"crop{suffix.lstrip('_')}"):
                continue
            crops = []
            for fp in files:
                fp = Path(fp)
                crop_path = fp.with_name(fp.stem + suffix + fp.suffix)
                dims = crop_to_ratio(fp, ratio, crop_path)
                crops.append(str(crop_path))
                print(f"  {label} crop: {crop_path} ({dims})", file=sys.stderr)
            entry[out_key] = crops
        results.append(entry)
        print(f"  done: {files}", file=sys.stderr)

    print(json.dumps({
        "references": args.ref,
        "scene_file": args.scene_file,
        "aspect_ratio": args.aspect_ratio,
        "crop916": args.crop916,
        "crop169": args.crop169,
        "quality": args.quality,
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
