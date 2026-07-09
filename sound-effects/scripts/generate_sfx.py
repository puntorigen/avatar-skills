#!/usr/bin/env python3
"""Generate sound effects using Stable Audio 2.5 on Replicate.

Usage:
    python3 generate_sfx.py "button click" --category ui --duration 1 --output click.mp3
    python3 generate_sfx.py "success chime" -c notification -d 2 -n 3 -o success.mp3
    python3 generate_sfx.py --list-categories
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"
CATEGORIES_FILE = SCRIPT_DIR / "categories.json"

FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
]

MODEL = "stability-ai/stable-audio-2.5"


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def load_categories():
    if CATEGORIES_FILE.exists():
        return json.loads(CATEGORIES_FILE.read_text(encoding="utf-8"))
    return {}


def get_replicate_token():
    token = os.environ.get("REPLICATE_API_TOKEN")
    if token:
        return token

    config = load_config()
    token = config.get("replicate_api_token", "")
    if token:
        return token

    for path in FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                t = cfg.get("replicate_api_token", "")
                if t:
                    return t
            except (json.JSONDecodeError, KeyError):
                continue

    print("Error: No Replicate API token found.", file=sys.stderr)
    print(f"Run: python3 {SCRIPT_DIR}/setup_key.py YOUR_REPLICATE_API_TOKEN", file=sys.stderr)
    sys.exit(1)


def enhance_prompt(description, category_key, categories):
    """Enhance a natural-language description into an optimized audio prompt."""
    cat = categories.get(category_key, categories.get("generic", {}))
    style_keywords = cat.get("style_keywords", "clean, professional, high-fidelity")
    prompt_suffix = cat.get("prompt_suffix", "sound effect, professional quality")

    enhanced = f"{description}, {style_keywords}, {prompt_suffix}"
    return enhanced


def download_file(url, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading: {output_path.name} ...", file=sys.stderr)
    urllib.request.urlretrieve(str(url), str(output_path))
    return str(output_path)


def generate_sound(prompt, *, duration=3, steps=8, cfg_scale=3.5, seed=None, token=None):
    """Call Stable Audio 2.5 on Replicate and return the output URL."""
    import replicate

    if token:
        os.environ["REPLICATE_API_TOKEN"] = token
    elif "REPLICATE_API_TOKEN" not in os.environ:
        os.environ["REPLICATE_API_TOKEN"] = get_replicate_token()

    inputs = {
        "prompt": prompt,
        "duration": int(duration),
        "steps": int(steps),
        "cfg_scale": float(cfg_scale),
    }
    if seed is not None:
        inputs["seed"] = int(seed)

    print(f"  Model: {MODEL}", file=sys.stderr)
    print(f"  Prompt: {prompt}", file=sys.stderr)
    print(f"  Duration: {duration}s | Steps: {steps} | CFG: {cfg_scale}", file=sys.stderr)
    if seed is not None:
        print(f"  Seed: {seed}", file=sys.stderr)
    print(f"  Generating...", file=sys.stderr)

    output = replicate.run(MODEL, input=inputs)
    return output


def resolve_output_path(output_arg, description, variation_index=None):
    """Build the output file path."""
    if output_arg:
        p = Path(output_arg)
        if variation_index is not None:
            stem = p.stem
            suffix = p.suffix or ".mp3"
            return p.parent / f"{stem}_{variation_index}{suffix}"
        if not p.suffix:
            p = p.with_suffix(".mp3")
        return p

    slug = description.lower()
    for ch in " ,.'\"!?;:()[]{}":
        slug = slug.replace(ch, "_")
    slug = "_".join(part for part in slug.split("_") if part)[:40]

    if variation_index is not None:
        return Path(f"{slug}_{variation_index}.mp3")
    return Path(f"{slug}.mp3")


def trim_silence(file_path, *, threshold_db=-35, pad_ms=10, fade_out_ms=20):
    """Trim leading/trailing silence from an audio file in-place."""
    trim_script = SCRIPT_DIR / "trim_silence.py"
    if not trim_script.exists():
        print(f"  Warning: trim_silence.py not found, skipping trim.", file=sys.stderr)
        return str(file_path)

    cmd = [
        sys.executable, str(trim_script),
        str(file_path),
        "--in-place",
        "--threshold", str(threshold_db),
        "--pad", str(pad_ms),
        "--fade-out", str(fade_out_ms),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: trim failed: {result.stderr.strip()[-200:]}", file=sys.stderr)
        return str(file_path)

    try:
        info = json.loads(result.stdout)
        orig = info.get("original_duration", 0)
        trimmed = info.get("trimmed_duration", 0)
        if orig > 0 and trimmed < orig:
            print(f"  Trimmed: {orig:.3f}s → {trimmed:.3f}s ({(orig - trimmed) * 1000:.0f}ms silence removed)",
                  file=sys.stderr)
        return info.get("file", str(file_path))
    except (json.JSONDecodeError, KeyError):
        return str(file_path)


def list_categories(categories):
    print("\nAvailable sound categories:\n")
    print(f"  {'Category':<14} {'Label':<16} {'Default Dur.':<14} Description")
    print(f"  {'─' * 14} {'─' * 16} {'─' * 14} {'─' * 40}")
    for key, cat in sorted(categories.items()):
        label = cat.get("label", key)
        dur = cat.get("default_duration", "?")
        desc = cat.get("description", "")
        print(f"  {key:<14} {label:<16} {str(dur) + 's':<14} {desc}")
    print()


def main():
    categories = load_categories()
    config = load_config()

    parser = argparse.ArgumentParser(
        description="Generate sound effects using Stable Audio 2.5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("description", nargs="?", help="Natural-language description of the sound")
    parser.add_argument("--category", "-c", default=config.get("default_category", "generic"),
                        help="Sound category preset (default: generic)")
    parser.add_argument("--duration", "-d", type=float,
                        help="Duration in seconds (1-90)")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--variations", "-n", type=int, default=1,
                        help="Number of variations (1-5, default: 1)")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    parser.add_argument("--steps", type=int, default=config.get("default_steps", 8),
                        help="Diffusion steps (default: 8)")
    parser.add_argument("--cfg-scale", type=float, default=config.get("default_cfg_scale", 3.5),
                        help="Guidance scale (default: 3.5, higher = stricter prompt adherence)")
    parser.add_argument("--raw-prompt", action="store_true",
                        help="Use prompt as-is without enhancement")
    parser.add_argument("--trim", action="store_true", default=True,
                        help="Trim leading/trailing silence (default: on)")
    parser.add_argument("--no-trim", dest="trim", action="store_false",
                        help="Disable silence trimming")
    parser.add_argument("--trim-threshold", type=float, default=-35,
                        help="Silence threshold in dB for trimming (default: -35)")
    parser.add_argument("--fade-out", type=float, default=20,
                        help="Fade-out in ms applied after trim (default: 20)")
    parser.add_argument("--list-categories", action="store_true",
                        help="Show available categories")

    args = parser.parse_args()

    if args.list_categories:
        list_categories(categories)
        sys.exit(0)

    if not args.description:
        parser.error("description is required (or use --list-categories)")

    cat_key = args.category
    if cat_key not in categories:
        print(f"Warning: Unknown category '{cat_key}', using 'generic'.", file=sys.stderr)
        cat_key = "generic"

    cat = categories.get(cat_key, {})
    duration = args.duration or cat.get("default_duration", config.get("default_duration", 3))
    duration = max(1, min(90, int(duration)))

    if args.raw_prompt:
        prompt = args.description
    else:
        prompt = enhance_prompt(args.description, cat_key, categories)

    token = get_replicate_token()
    variations = max(1, min(5, args.variations))

    results = []
    for i in range(variations):
        seed = (args.seed + i) if args.seed is not None else None
        var_idx = (i + 1) if variations > 1 else None

        output_url = generate_sound(
            prompt,
            duration=duration,
            steps=args.steps,
            cfg_scale=args.cfg_scale,
            seed=seed,
            token=token,
        )

        if not output_url:
            print(f"  Error: No output returned for variation {i + 1}", file=sys.stderr)
            continue

        url = str(output_url)
        out_path = resolve_output_path(args.output, args.description, var_idx)
        saved = download_file(url, out_path)

        if args.trim:
            saved = trim_silence(
                saved,
                threshold_db=args.trim_threshold,
                fade_out_ms=args.fade_out,
            )

        results.append(str(saved))
        print(f"  Saved: {saved}", file=sys.stderr)

    output_json = {
        "files": results,
        "prompt": prompt,
        "raw_description": args.description,
        "category": cat_key,
        "duration": duration,
        "trimmed": args.trim,
        "steps": args.steps,
        "cfg_scale": args.cfg_scale,
    }
    if args.seed is not None:
        output_json["seed"] = args.seed

    print(json.dumps(output_json, indent=2))


if __name__ == "__main__":
    main()
