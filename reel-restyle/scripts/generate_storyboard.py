#!/usr/bin/env python3
"""Map a reel TEMPLATE's beats onto a NEW script -> avatar-reel-composer storyboard.

Produces a composer-ready storyboard.json that preserves the template's beat
COUNT and talking-head/B-roll SEQUENCE, assigns each talking-head beat the new
avatar's matching camera-angle still, carries the per-beat motion / emphasis,
wires captions + transitions + music from the template, and splits the script
across beats proportionally to each beat's ``dur_weight``.

Two parts are inherently creative and should be reviewed/authored by the agent:
  * the exact split of the script across beats (semantic phrase boundaries), and
  * each B-roll scene's ``broll_description`` / ``broll_action`` for the NEW topic.
The auto-draft fills these mechanically (proportional split; B-roll seeded from
the template's broll_hint and flagged ``TODO``). The agent then either edits the
storyboard directly or supplies ``--segments`` (one entry per beat).

The composer's HARD RULE -- the concatenation of every scene.text (single
spaces) must equal ``script`` verbatim -- is guaranteed here: the script is
normalized to single spaces and split on word boundaries.

Usage:
    python3 generate_storyboard.py --template lolo/reel_template.json --avatar mara \
        --script script.txt -o mara/mi-reel.storyboard.json
    # provide an agent-authored split + B-roll:
    python3 generate_storyboard.py --template lolo/reel_template.json --avatar mara \
        --script script.txt --segments segments.json -o mara/mi-reel.storyboard.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _restyle_common as C  # noqa: E402

TODO_PREFIX = "TODO"


# ---------------------------------------------------------------------------
# Script split
# ---------------------------------------------------------------------------
def normalize_script(text: str) -> str:
    return " ".join((text or "").split())


def allocate(n_words: int, weights: list[float]) -> list[int] | None:
    """Split n_words across len(weights) beats by weight (each beat >= 1 word).

    Largest-remainder method. Returns None if there are fewer words than beats.
    """
    k = len(weights)
    if n_words < k:
        return None
    rem = n_words - k  # one word reserved per beat
    tot = sum(weights) or 1.0
    shares = [rem * (w / tot) for w in weights]
    add = [int(s) for s in shares]
    leftover = rem - sum(add)
    order = sorted(range(k), key=lambda i: shares[i] - add[i], reverse=True)
    for j in range(leftover):
        add[order[j % k]] += 1
    return [1 + add[i] for i in range(k)]


def merge_two(a: dict, b: dict) -> dict:
    """Merge two adjacent beats (used only when the script is shorter than beats)."""
    th = a if a.get("type") == "talking_head" else (b if b.get("type") == "talking_head" else a)
    merged = dict(th)
    merged["dur_weight"] = round((a.get("dur_weight") or 0) + (b.get("dur_weight") or 0), 4)
    merged["emphasis"] = bool(a.get("emphasis") or b.get("emphasis"))
    merged["_merged_from"] = [a.get("index"), b.get("index")]
    return merged


def fit_beats(beats: list[dict], n_words: int) -> list[dict]:
    beats = [dict(b) for b in beats]
    while len(beats) > n_words and len(beats) > 1:
        i = min(range(len(beats) - 1),
                key=lambda j: (beats[j].get("dur_weight") or 0) + (beats[j + 1].get("dur_weight") or 0))
        beats[i:i + 2] = [merge_two(beats[i], beats[i + 1])]
    return beats


# ---------------------------------------------------------------------------
# Storyboard assembly
# ---------------------------------------------------------------------------
def build_scene(beat: dict, idx: int, text: str, *, avatar_rel: str, avatar_slug: str,
                seg: dict | None, angle_suffix: str = "_916") -> dict:
    sid = f"s{idx + 1}"
    scene = {"id": sid, "type": beat["type"], "text": text}
    if beat["type"] == "talking_head":
        move = beat.get("move") or "eye_level"
        scene["image"] = f"{avatar_rel}/angles/{avatar_slug}_{move}{angle_suffix}.png"
        scene["zoom_from_previous"] = beat.get("zoom_from_previous", "none")
        scene["emphasis"] = bool(beat.get("emphasis"))
    else:
        scene["broll_camera"] = beat.get("broll_camera", "push_in")
        if seg and seg.get("broll_description"):
            scene["broll_description"] = seg["broll_description"]
            scene["broll_action"] = seg.get("broll_action") or (
                "continuous, realistic human action; no spoken dialogue")
        else:
            hint = beat.get("broll_hint") or text
            scene["broll_description"] = (
                f"{TODO_PREFIX} (B-roll): describe a supporting insert (no main presenter) "
                f"for this line. Reference beat focus: {hint}")
            scene["broll_action"] = (
                f"{TODO_PREFIX}: continuous, realistic human action reinforcing the line; "
                "no spoken dialogue")
        scene["motion"] = "none"
    return scene


def build_storyboard(template: dict, *, avatar_dir: Path, base_dir: Path, script: str,
                     slug: str, fmt: str, resolution: str, fps: int,
                     language: str | None, segments: list[dict] | None) -> tuple[dict, list[str], list[str]]:
    warnings: list[str] = []
    script = normalize_script(script)
    words = script.split()
    beats = template.get("beats") or []
    if not beats:
        raise SystemExit("template has no beats.")

    eff_beats = fit_beats(beats, len(words))
    if len(eff_beats) < len(beats):
        warnings.append(f"script has {len(words)} words but template has {len(beats)} beats; "
                        f"merged down to {len(eff_beats)} beats.")

    avatar_rel = C.rel_to(avatar_dir, base_dir)
    avatar_slug = avatar_dir.name
    angle_suffix = C.angle_suffix(fmt)

    # Resolve per-beat text.
    if segments is not None:
        if len(segments) != len(eff_beats):
            raise SystemExit(f"--segments has {len(segments)} entries but the template needs "
                             f"{len(eff_beats)} beats. Provide exactly one entry per beat.")
        texts = [normalize_script(s.get("text", "")) for s in segments]
        joined = " ".join(t for t in texts if t)
        if normalize_script(joined) != script:
            raise SystemExit("--segments text does not concatenate to the script verbatim "
                             "(single-spaced). Fix the splits and retry.")
    else:
        counts = allocate(len(words), [b.get("dur_weight") or 0 for b in eff_beats])
        if counts is None:
            raise SystemExit("script is too short for this template even after merging beats.")
        texts, cur = [], 0
        for c in counts:
            texts.append(" ".join(words[cur:cur + c]))
            cur += c

    scenes = []
    todo_ids = []
    missing_moves: list[str] = []
    for i, (beat, text) in enumerate(zip(eff_beats, texts)):
        seg = segments[i] if segments is not None else None
        scene = build_scene(beat, i, text, avatar_rel=avatar_rel, avatar_slug=avatar_slug,
                            seg=seg, angle_suffix=angle_suffix)
        if scene.get("broll_description", "").startswith(TODO_PREFIX):
            todo_ids.append(scene["id"])
        if scene["type"] == "talking_head":
            img = C.resolve_path(scene["image"], base_dir)
            move = beat.get("move") or "eye_level"
            if not img.exists() and move not in missing_moves:
                missing_moves.append(move)
        scenes.append(scene)
    if missing_moves:
        warnings.append("angle stills not generated yet for: "
                        f"{', '.join(missing_moves)} -- run scaffold_avatar.py (angles stage).")

    # Verbatim guarantee.
    rebuilt = " ".join(s["text"] for s in scenes if s.get("text"))
    if normalize_script(rebuilt) != script:
        warnings.append("internal split drifted from the script; the composer will "
                        "fall back to proportional alignment.")

    caps = template.get("captions", {}) or {}
    music = template.get("music", {}) or {}
    has_subs = (avatar_dir / "subtitle_style.json").exists()

    voice = {
        "name": None,
        "voice_id": None,
        "emotion": "calm",
        "speed": 0.95,
        "language_boost": "None",
        "sentence_gap": 0.12,
        "_note": "voice auto-resolves from <avatar>/voices/. language_boost stays 'None' "
                 "to keep the cloned accent; the agent may tune emotion/speed.",
    }

    finish = {
        "enabled": True,
        "subtitles": True,
        "music": bool(music.get("include", True)),
        "music_mood": music.get("mood", "ambient"),
        "music_prompt": music.get("prompt_hint", ""),
        "music_volume": 0.12,
        "max_words": int(music.get("words_per_caption") or caps.get("words_per_caption") or 6),
        "emphasis": True,
        "casing": "subtitle",
        "_note": "TAILOR music_prompt to THIS reel's topic + tone. transition_style is "
                 "omitted so the polish pass uses the avatar's copied transition_style.json.",
        "fx": {"enabled": True, "sfx": True, "sfx_volume": 0.18},
    }
    if has_subs:
        finish["style_from"] = f"{avatar_rel}/subtitle_style.json"

    storyboard = {
        "_comment": "Generated by reel-restyle from a reel template. Beat structure, "
                    "angles, motion, transitions and captions come from the template; "
                    "REVIEW the per-scene text split and AUTHOR every TODO B-roll "
                    "before composing.",
        "avatar_dir": avatar_rel,
        "slug": slug,
        "restyle_template": C.rel_to(Path(template.get("_template_path", "reel_template.json")), base_dir)
            if template.get("_template_path") else None,
        "reference_analysis": template.get("source", {}).get("primary_analysis"),
        "format": fmt,
        "resolution": resolution,
        "fps": fps,
        "voice": voice,
        "script": script,
        "scenes": scenes,
        "finish": finish,
    }
    if language:
        storyboard["voice"]["language_boost"] = "None"
        storyboard["_language"] = language
    return storyboard, warnings, todo_ids


def main():
    ap = argparse.ArgumentParser(
        description="Map a reel template onto a new script -> composer storyboard.json.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--template", required=True, help="reel_template.json from extract_template.py")
    ap.add_argument("--avatar", required=True, help="New (scaffolded) avatar folder")
    ap.add_argument("--script", required=True, help="Script text file, or '-' for stdin")
    ap.add_argument("--segments", default=None,
                    help="Optional JSON: [{text, broll_description?, broll_action?}, ...] (one per beat)")
    ap.add_argument("--slug", default=None, help="Reel slug (default: derived from the script)")
    ap.add_argument("--format", default="reel", choices=["reel", "post", "landscape"])
    ap.add_argument("--resolution", default="720p", choices=["720p", "1080p"])
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--language", default=None, help="Language hint (es, en, ...)")
    ap.add_argument("--base-dir", default=".", help="Base for relative paths in the storyboard")
    ap.add_argument("--output", "-o", default=None,
                    help="Storyboard path (default: <avatar>/<slug>.storyboard.json)")
    ap.add_argument("--force", action="store_true", help="Overwrite an existing storyboard")
    args = ap.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve()
    template = C.load_json(args.template)
    template["_template_path"] = str(Path(args.template).expanduser().resolve())
    avatar_dir = Path(args.avatar).expanduser().resolve()

    script = sys.stdin.read() if args.script == "-" else Path(args.script).expanduser().read_text(encoding="utf-8")
    if not script.strip():
        ap.error("script is empty.")

    slug = args.slug or _slugify(script)
    out = (Path(args.output).expanduser() if args.output
           else avatar_dir / f"{slug}.storyboard.json")
    if out.exists() and not args.force:
        print(f"  storyboard already exists: {out} (use --force to overwrite)", file=sys.stderr)
        print(json.dumps({"storyboard": str(out), "skipped": True}, ensure_ascii=False))
        return 0

    segments = None
    if args.segments:
        segments = C.load_json(args.segments)
        if not isinstance(segments, list):
            ap.error("--segments must be a JSON list of objects.")

    storyboard, warnings, todo_ids = build_storyboard(
        template, avatar_dir=avatar_dir, base_dir=base_dir, script=script,
        slug=slug, fmt=args.format, resolution=args.resolution, fps=args.fps,
        language=args.language, segments=segments,
    )
    C.save_json(out, storyboard)

    n_th = sum(1 for s in storyboard["scenes"] if s["type"] == "talking_head")
    n_br = len(storyboard["scenes"]) - n_th
    print(f"\n  Storyboard written: {out}", file=sys.stderr)
    print(f"  {len(storyboard['scenes'])} scenes ({n_th} talking-head, {n_br} B-roll)",
          file=sys.stderr)
    for w in warnings:
        print(f"  ! {w}", file=sys.stderr)
    if todo_ids:
        print(f"  ==> AUTHOR B-roll for scenes: {', '.join(todo_ids)} "
              "(edit broll_description/broll_action, removing the TODO marker).",
              file=sys.stderr)
    print(json.dumps({
        "storyboard": str(out),
        "scenes": len(storyboard["scenes"]),
        "talking_head": n_th,
        "broll": n_br,
        "todo_broll": todo_ids,
        "warnings": warnings,
    }, ensure_ascii=False))
    return 0


def _slugify(text: str, maxlen: int = 40) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:maxlen].strip("-") or "reel"


if __name__ == "__main__":
    raise SystemExit(main())
