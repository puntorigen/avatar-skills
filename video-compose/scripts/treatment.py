#!/usr/bin/env python3
"""Treatment / shot-list generator and validator.

The treatment is the structural script for the reel — without a voiceover, it
defines the timing, narrative beats, and title placement.

Three subcommands:

    draft     Generate a treatment.yaml from a brief + analyzed asset library.
              The LLM writes a shot list whose total duration matches the target.

    validate  Validate a treatment.yaml against the v0.1 schema.
              Exits non-zero on schema violations; emits a machine-readable
              JSON report on stdout.

    print     Pretty-print a treatment.yaml as a human-readable summary.

Schema (treatment.yaml):
    goal: string
    tone: string
    language: string (ISO 639-1, e.g. en, es, fr)
    format: reel | post | landscape
    target_duration: number (seconds)
    shots:
      - duration: number
        description: string (what should happen, what to look for in the assets)
        title: { text: string, style: string } | null

Title styles:
    lower_third | kinetic_burst | fullscreen | tag_line | badge | ticker

Usage:
    python3 treatment.py draft --brief "..." --assets assets.json \
        --format reel --target-duration 30 --language en --tone "warm, uplifting" \
        -o treatment.yaml

    python3 treatment.py validate treatment.yaml
    python3 treatment.py print    treatment.yaml
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import call_llm_json, load_json

VALID_FORMATS = {"reel", "post", "landscape"}
VALID_TITLE_STYLES = {"lower_third", "kinetic_burst", "fullscreen", "tag_line", "badge", "ticker"}
SUPPORTED_LANGUAGES = {"en", "es", "pt", "fr", "de", "it", "ja", "ko", "zh"}

DEFAULT_TARGET_DURATION = 30
MIN_SHOT_DURATION = 1.2
MAX_SHOT_DURATION = 8.0


SYSTEM_PROMPT = """You are a senior video editor who specializes in social-media reels and short-form storytelling.

You are drafting a "treatment" — a structural shot list that turns a creative brief
into a sequence of clearly described shots, each with a duration and an optional
on-screen title. The reel has NO voiceover; music is the only audio. So the shot
descriptions must carry the narrative on their own.

Style guidelines:
- Each shot description is one sentence that says what should happen visually.
  Be specific about subject, action, mood — not vague ("happy moment").
- Total duration must equal the requested target_duration (within ±2 seconds).
- Each shot is between 1.2 and 8.0 seconds. Most shots are 2-5 seconds.
- 3-7 shots is ideal for 20-40s reels. Up to 10 shots for longer reels.
- 2-4 of the shots should have on-screen titles (text + style). The rest have title: null.
- Use varied title styles across the reel (don't repeat the same style every shot).
- Keep title TEXT short — under 5 words, ideally 1-3 words. They are graphic accents.
- Match the language (titles in the reel's language).
- Match the asset library — describe shots that the available footage can actually deliver.

Output a single JSON object with this exact shape:
{
  "goal": "...",
  "tone": "...",
  "language": "...",
  "format": "...",
  "target_duration": <number>,
  "shots": [
    { "duration": <number>, "description": "...", "title": null },
    { "duration": <number>, "description": "...", "title": { "text": "...", "style": "..." } }
  ]
}

Title styles available:
- "lower_third"   — slides in from left, primary text + optional subtitle (intros, names)
- "kinetic_burst" — word-by-word springs, dramatic, scale + rotate (energy, big reveals)
- "fullscreen"   — large centered text, subtle scale-in, stays bold (hero statements)
- "tag_line"     — bottom-center, slow fade, light weight, elegant (closing taglines)
- "badge"        — small pill in top-right, brand-card style (chapter labels, dates)
- "ticker"       — horizontal scroll for stats / facts / dates

NEVER include a "subtitle" key inside title. Only "text" and "style".
"""


def summarize_assets_for_prompt(assets, *, max_videos=10, max_scenes_per_video=4,
                                max_images=10):
    """Build a compact textual summary of the asset library for the LLM prompt."""
    videos = assets.get("videos", {})
    images = assets.get("images", {})

    lines = []
    lines.append(f"VIDEOS ({len(videos)}):")
    for path, meta in list(videos.items())[:max_videos]:
        dur = meta.get("duration", 0)
        scenes = meta.get("scenes", [])[:max_scenes_per_video]
        lines.append(f"- {path}  ({dur:.1f}s, {len(scenes)} scenes)")
        for i, sc in enumerate(scenes):
            desc = sc.get("description") or "[no description]"
            blur = sc.get("blur_score", 0)
            motion = sc.get("motion_score", 0)
            lines.append(
                f"    scene {i}: {sc.get('in', 0):.1f}-{sc.get('out', 0):.1f}s "
                f"(blur={blur:.2f} motion={motion:.2f})  {desc}"
            )
    if len(videos) > max_videos:
        lines.append(f"  ... and {len(videos) - max_videos} more videos")

    lines.append(f"\nIMAGES ({len(images)}):")
    for path, meta in list(images.items())[:max_images]:
        desc = meta.get("description") or "[no description]"
        lines.append(f"- {path}  {desc}")
    if len(images) > max_images:
        lines.append(f"  ... and {len(images) - max_images} more images")

    return "\n".join(lines)


def draft_treatment(brief, assets, *, format_, target_duration, language, tone, max_shots=None):
    """Call the LLM to draft a treatment from a brief + asset library."""
    asset_summary = summarize_assets_for_prompt(assets)

    target_shots = max_shots or max(3, min(10, round(target_duration / 4)))

    user_prompt = (
        f"BRIEF:\n{brief.strip()}\n\n"
        f"FORMAT: {format_}\n"
        f"TARGET DURATION: {target_duration} seconds\n"
        f"LANGUAGE: {language}\n"
        f"TONE: {tone}\n"
        f"TARGET SHOT COUNT: ~{target_shots} shots\n\n"
        f"ASSET LIBRARY:\n{asset_summary}\n\n"
        "Now write the treatment as a JSON object matching the schema."
    )

    return call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.6)


def validate_treatment(treatment):
    """Validate a treatment dict against the schema. Returns (ok, errors)."""
    errors = []

    if not isinstance(treatment, dict):
        return False, ["treatment must be an object"]

    for key in ("goal", "tone", "language", "format", "target_duration", "shots"):
        if key not in treatment:
            errors.append(f"missing key: {key}")

    fmt = treatment.get("format")
    if fmt not in VALID_FORMATS:
        errors.append(f"format must be one of {sorted(VALID_FORMATS)}, got {fmt!r}")

    target = treatment.get("target_duration", 0)
    if not isinstance(target, (int, float)) or target <= 0:
        errors.append("target_duration must be a positive number")

    lang = treatment.get("language", "")
    if not isinstance(lang, str) or len(lang) < 2:
        errors.append(f"language must be an ISO 639-1 code, got {lang!r}")

    shots = treatment.get("shots")
    if not isinstance(shots, list) or not shots:
        errors.append("shots must be a non-empty array")
        return False, errors

    total = 0.0
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict):
            errors.append(f"shot {i}: must be an object")
            continue
        dur = shot.get("duration")
        if not isinstance(dur, (int, float)) or dur <= 0:
            errors.append(f"shot {i}: duration must be a positive number")
        else:
            if dur < MIN_SHOT_DURATION:
                errors.append(
                    f"shot {i}: duration {dur:.2f}s is below minimum "
                    f"({MIN_SHOT_DURATION}s)"
                )
            if dur > MAX_SHOT_DURATION:
                errors.append(
                    f"shot {i}: duration {dur:.2f}s exceeds maximum "
                    f"({MAX_SHOT_DURATION}s)"
                )
            total += dur

        desc = shot.get("description")
        if not isinstance(desc, str) or len(desc.strip()) < 5:
            errors.append(f"shot {i}: description must be a non-empty string")

        title = shot.get("title", None)
        if title is not None:
            if not isinstance(title, dict):
                errors.append(f"shot {i}: title must be null or an object")
            else:
                t_text = title.get("text", "")
                t_style = title.get("style", "")
                if not isinstance(t_text, str) or not t_text.strip():
                    errors.append(f"shot {i}: title.text must be a non-empty string")
                if t_style not in VALID_TITLE_STYLES:
                    errors.append(
                        f"shot {i}: title.style must be one of "
                        f"{sorted(VALID_TITLE_STYLES)}, got {t_style!r}"
                    )

    if isinstance(target, (int, float)) and abs(total - target) > max(2.0, target * 0.1):
        errors.append(
            f"sum of shot durations ({total:.2f}s) deviates from target "
            f"({target:.2f}s) by more than 10% / 2s"
        )

    return len(errors) == 0, errors


def yaml_dump(treatment):
    """Dump treatment as YAML using PyYAML if available, falling back to a manual writer."""
    try:
        import yaml
        return yaml.safe_dump(treatment, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except ImportError:
        lines = []
        for key in ("goal", "tone", "language", "format", "target_duration"):
            if key in treatment:
                v = treatment[key]
                if isinstance(v, str):
                    lines.append(f"{key}: \"{v}\"")
                else:
                    lines.append(f"{key}: {v}")
        lines.append("shots:")
        for shot in treatment.get("shots", []):
            lines.append(f"  - duration: {shot.get('duration')}")
            desc = (shot.get("description", "") or "").replace('"', '\\"')
            lines.append(f"    description: \"{desc}\"")
            title = shot.get("title")
            if title is None:
                lines.append("    title: null")
            else:
                t_text = (title.get("text", "") or "").replace('"', '\\"')
                t_style = title.get("style", "")
                lines.append(f"    title: {{ text: \"{t_text}\", style: \"{t_style}\" }}")
        return "\n".join(lines) + "\n"


def yaml_load(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        print("Error: PyYAML not installed. pip install PyYAML", file=sys.stderr)
        sys.exit(1)


def cmd_draft(args):
    if not Path(args.assets).exists():
        print(f"Error: assets file not found: {args.assets}", file=sys.stderr)
        sys.exit(1)

    assets = load_json(args.assets)
    treatment = draft_treatment(
        args.brief,
        assets,
        format_=args.format,
        target_duration=args.target_duration,
        language=args.language,
        tone=args.tone,
        max_shots=args.max_shots,
    )

    if not treatment:
        print("Error: LLM did not return a valid treatment", file=sys.stderr)
        sys.exit(2)

    treatment.setdefault("format", args.format)
    treatment.setdefault("language", args.language)
    treatment.setdefault("target_duration", args.target_duration)

    ok, errs = validate_treatment(treatment)
    if not ok:
        print("Warning: drafted treatment has validation issues:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_dump(treatment), encoding="utf-8")

    n_shots = len(treatment.get("shots", []))
    total = sum(s.get("duration", 0) for s in treatment.get("shots", []))
    print(json.dumps({
        "output": str(output_path),
        "shots": n_shots,
        "total_duration": round(total, 2),
        "valid": ok,
        "errors": errs,
    }, indent=2))


def cmd_validate(args):
    treatment = yaml_load(args.path)
    ok, errs = validate_treatment(treatment)
    print(json.dumps({"valid": ok, "errors": errs}, indent=2))
    sys.exit(0 if ok else 1)


def cmd_print(args):
    treatment = yaml_load(args.path)
    print(f"Goal:     {treatment.get('goal', '')}")
    print(f"Tone:     {treatment.get('tone', '')}")
    print(f"Language: {treatment.get('language', '')}")
    print(f"Format:   {treatment.get('format', '')}")
    print(f"Target:   {treatment.get('target_duration', 0)}s")
    print()
    print("Shots:")
    for i, shot in enumerate(treatment.get("shots", []), start=1):
        title = shot.get("title")
        title_str = ""
        if title:
            title_str = f"  [{title.get('style', '?')}] {title.get('text', '')!r}"
        print(f"  {i}. ({shot.get('duration', 0):.1f}s) {shot.get('description', '')}{title_str}")
    total = sum(s.get("duration", 0) for s in treatment.get("shots", []))
    print(f"\nTotal: {total:.1f}s ({len(treatment.get('shots', []))} shots)")


def main():
    parser = argparse.ArgumentParser(description="Treatment generator/validator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_draft = sub.add_parser("draft", help="Draft a treatment.yaml")
    p_draft.add_argument("--brief", required=True, help="Creative brief (paragraph)")
    p_draft.add_argument("--assets", required=True, help="Path to assets.json")
    p_draft.add_argument("--format", default="reel", choices=sorted(VALID_FORMATS))
    p_draft.add_argument("--target-duration", type=float, default=DEFAULT_TARGET_DURATION)
    p_draft.add_argument("--language", default="en")
    p_draft.add_argument("--tone", default="warm, uplifting")
    p_draft.add_argument("--max-shots", type=int, default=None)
    p_draft.add_argument("-o", "--output", required=True)
    p_draft.set_defaults(func=cmd_draft)

    p_val = sub.add_parser("validate", help="Validate treatment.yaml against schema")
    p_val.add_argument("path")
    p_val.set_defaults(func=cmd_validate)

    p_print = sub.add_parser("print", help="Pretty-print treatment.yaml")
    p_print.add_argument("path")
    p_print.set_defaults(func=cmd_print)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
