#!/usr/bin/env python3
"""Distill a script-agnostic reel TEMPLATE from a reference avatar's analysis.

Reads one or more enriched ``*.analysis.json`` files (produced + vision-enriched
by the video-scene-analysis skill) plus the avatar's measured style files
(``transition_style.json``, ``subtitle_style.json``, ``talking_profile.json``)
and writes a compact ``reel_template.json`` -- the reusable "DNA" of the reel:

  * a per-scene BEAT sequence (talking-head vs B-roll pattern),
  * per-beat camera angle (mapped to an avatar-camera-angles move) + framing,
  * the cut/transition vocabulary (zoom_from_previous per beat),
  * SFX placement style + density,
  * caption style, proportional pacing (dur_weight per beat) and a delivery seed.

It contains NO script-specific content, so generate_storyboard.py / apply_template.py
can re-apply it to a DIFFERENT avatar + voice + script. Scene DURATIONS are not
copied verbatim (a new script has its own rhythm); the template carries the
proportional pacing and structure, and the composer derives real durations from
the new narration's word alignment.

The beat STRUCTURE comes from a single representative reel (``--primary``, else
the analysis with the most scenes). Avatar-level style (transitions, captions)
is read from the measured style files, which are already aggregated across reels.

Usage:
    python3 extract_template.py lolo/videos/2026-06-08_15-02-03.analysis.json
    python3 extract_template.py lolo/videos/*.analysis.json --avatar-dir lolo \
        -o lolo/reel_template.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _restyle_common as C  # noqa: E402
from _angle_map import move_for_angle, needed_moves  # noqa: E402

TALKING_TYPES = {"main_character_solo", "multi_person"}

# Coarse call-to-action hints (es/en) used only to label the narrative arc.
CTA_HINTS = (
    "escr", "llama", "mensaje", "sígue", "sigue", "link", "comenta", "guarda",
    "comparte", "agenda", "reserva", "contact", "message", "follow", "subscribe",
    "comment", "save", "share", "dm", "book", "sign up",
)

DEFAULT_TRANSITIONS = {
    "style": "golden_flash",
    "flash_at": ["broll_entry"],
    "flash_dur": 0.4,
    "flash_gain": 0.99,
    "_note": "Default transition style (no measured transition_style.json found).",
}

DEFAULT_MUSIC_PROMPT = (
    "sparse, intimate instrumental bed under a voice-over; soft and unobtrusive, "
    "no drums, no beat, no vocals -- TAILOR this to the new reel's topic + tone"
)


# ---------------------------------------------------------------------------
# Beat helpers
# ---------------------------------------------------------------------------
def beat_type(scene) -> str:
    return "talking_head" if scene.get("scene_type") in TALKING_TYPES else "broll"


def derive_role(i: int, n: int, focus: str | None) -> str:
    if i == 0:
        return "hook"
    if i == n - 1:
        return "cta" if (focus and any(h in focus.lower() for h in CTA_HINTS)) else "close"
    return "body"


def broll_camera_for(zoom: str | None) -> str:
    return {"zoom_in": "push_in", "zoom_out": "pull_out"}.get(zoom or "", "handheld")


def beat_emphasis(scene) -> bool:
    zoom = (scene.get("zoom_from_previous") or {}).get("type")
    framing = (scene.get("camera") or {}).get("framing")
    if zoom == "zoom_in":
        return True
    return framing in ("close_up", "extreme_close_up")


def cut_rhythm(avg: float) -> str:
    if avg < 3.0:
        return "fast"
    if avg < 5.0:
        return "medium"
    return "slow"


# ---------------------------------------------------------------------------
# Selection / discovery
# ---------------------------------------------------------------------------
def enriched_score(data: dict) -> int:
    """How many talking-head scenes carry a real camera angle (enrichment)."""
    score = 0
    for s in data.get("scenes", []):
        if beat_type(s) == "talking_head" and (s.get("camera") or {}).get("angle"):
            score += 1
    return score


def pick_primary(analyses: list[tuple[Path, dict]], explicit: Path | None):
    if explicit:
        for p, d in analyses:
            if p.resolve() == explicit.resolve():
                return p, d
        raise SystemExit(f"--primary {explicit} is not among the provided analyses.")
    # Prefer the richest enriched structure; tie-break by scene count, then duration.
    def key(item):
        _p, d = item
        scenes = d.get("scenes", [])
        dur = sum(float(s.get("duration") or 0) for s in scenes)
        return (enriched_score(d), len(scenes), dur)

    return max(analyses, key=key)


def find_style_file(avatar_dir: Path | None, explicit, name: str) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    if avatar_dir and (avatar_dir / name).exists():
        return avatar_dir / name
    return None


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------
def build_template(args) -> dict:
    base = Path(args.base_dir).expanduser().resolve()
    paths = [Path(p).expanduser() for p in args.analysis]
    analyses: list[tuple[Path, dict]] = []
    for p in paths:
        if not p.exists():
            print(f"  ! skipping missing analysis: {p}", file=sys.stderr)
            continue
        d = C.try_load_json(p)
        if d is None or not d.get("scenes"):
            print(f"  ! skipping analysis without scenes: {p}", file=sys.stderr)
            continue
        analyses.append((p, d))
    if not analyses:
        raise SystemExit("No usable *.analysis.json with scenes was provided.")

    primary_path, primary = pick_primary(analyses, args.primary)
    scenes = primary.get("scenes", [])
    if enriched_score(primary) == 0:
        print("  ! WARNING: the primary analysis has no enriched camera angles. "
              "Run the video-scene-analysis agent vision pass first for accurate "
              "angles; falling back to eye_level where missing.", file=sys.stderr)

    # Avatar dir + measured style files.
    avatar_dir = (Path(args.avatar_dir).expanduser().resolve()
                  if args.avatar_dir else C.infer_avatar_dir(primary_path))
    trans_path = find_style_file(avatar_dir, args.transition_style, "transition_style.json")
    subs_path = find_style_file(avatar_dir, args.subtitle_style, "subtitle_style.json")
    prof_path = find_style_file(avatar_dir, args.talking_profile, "talking_profile.json")

    transitions = C.try_load_json(trans_path) if trans_path else None
    subtitle_style = C.try_load_json(subs_path) if subs_path else None
    talking_profile = C.try_load_json(prof_path) if prof_path else None

    # ---- Beats from the primary reel ----
    total = sum(float(s.get("duration") or 0) for s in scenes) or 1.0
    n = len(scenes)
    beats = []
    sfx_count = 0
    has_music = False
    for i, s in enumerate(scenes):
        btype = beat_type(s)
        cam = s.get("camera") or {}
        audio = s.get("audio") or {}
        summ = s.get("summary") or {}
        zoom = (s.get("zoom_from_previous") or {}).get("type") or "none"
        sfx_count += int(audio.get("sfx_event_count") or 0)
        has_music = has_music or bool(audio.get("has_music_bed"))
        beat = {
            "index": i,
            "role": derive_role(i, n, summ.get("focus")),
            "type": btype,
            "dur_weight": round(float(s.get("duration") or 0) / total, 4),
            "zoom_from_previous": zoom,
            "emphasis": beat_emphasis(s),
            "has_sfx": bool(audio.get("has_sfx")),
            "audio_profile": audio.get("audio_profile"),
            "focus": summ.get("focus"),
        }
        if btype == "talking_head":
            angle = cam.get("angle") or "eye_level"
            if angle == "none":
                angle = "eye_level"
            beat["camera_angle"] = angle
            beat["framing"] = cam.get("framing")
            beat["move"] = move_for_angle(angle)
        else:
            beat["camera_angle"] = None
            beat["broll_camera"] = broll_camera_for(zoom)
            # A generic seed only; B-roll content MUST be re-authored per script.
            beat["broll_hint"] = summ.get("focus") or (s.get("transcript") or "").strip()[:160]
        beats.append(beat)

    th = sum(1 for b in beats if b["type"] == "talking_head")
    broll = n - th
    avg = total / n
    angles = needed_moves([b["camera_angle"] for b in beats if b["type"] == "talking_head"])

    # ---- SFX density ----
    sfx_density = round(total / sfx_count, 1) if sfx_count > 0 else 15.0

    # ---- Captions ----
    captions = {
        "style_from": C.rel_to(subs_path, base) if subs_path else None,
        "subtitle_style": subtitle_style,  # embedded copy so the template is portable
    }
    words_per_caption = (subtitle_style or {}).get("words_per_caption", 6) or 6

    # ---- Transitions (embed measured profile, else default) ----
    if transitions:
        transitions = dict(transitions)
        transitions["_style_from"] = C.rel_to(trans_path, base) if trans_path else None
    else:
        transitions = dict(DEFAULT_TRANSITIONS)

    # ---- Delivery seed (STYLE only, not identity) ----
    delivery_seed = None
    if talking_profile:
        delivery_seed = talking_profile.get("mannerisms_summary") or talking_profile.get("video_prompt")

    template = {
        "version": 1,
        "_comment": (
            "Script-agnostic reel template extracted by reel-restyle. Re-apply it "
            "to a NEW avatar + voice + script with apply_template.py. Structure "
            "(beats/angles/transitions/SFX/captions/pacing) transfers; scene "
            "DURATIONS do not -- the composer derives them from the new narration."
        ),
        "extracted_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": {
            "avatar": avatar_dir.name if avatar_dir else None,
            "primary_analysis": C.rel_to(primary_path, base),
            "analyses": [C.rel_to(p, base) for p, _ in analyses],
            "transition_style": C.rel_to(trans_path, base) if trans_path else None,
            "subtitle_style": C.rel_to(subs_path, base) if subs_path else None,
            "talking_profile": C.rel_to(prof_path, base) if prof_path else None,
        },
        "summary": {
            "total_scenes": n,
            "talking_head": th,
            "broll": broll,
            "total_duration": round(total, 2),
            "avg_scene_dur": round(avg, 2),
            "cut_rhythm": cut_rhythm(avg),
            "narrative_arc": [b["role"] for b in beats],
        },
        "angles_needed": angles,
        "beats": beats,
        "transitions": transitions,
        "sfx": {
            "density_sec": sfx_density,
            "events": ["whoosh_before_broll", "boom_on_emphasis"],
            "_note": "Soft whoosh leading each B-roll cut + soft low boom on emphasis "
                     "scenes; density measured from the reference reel.",
        },
        "captions": captions,
        "music": {
            "mood": "ambient",
            "include": True,
            "detected_music_bed": bool(has_music),
            "prompt_hint": DEFAULT_MUSIC_PROMPT,
            "words_per_caption": words_per_caption,
        },
        "delivery_style_seed": delivery_seed,
    }
    return template


def main():
    ap = argparse.ArgumentParser(
        description="Distill a reusable reel template from a reference avatar's analysis.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("analysis", nargs="+", help="One or more enriched *.analysis.json files")
    ap.add_argument("--primary", type=Path, default=None,
                    help="Which analysis defines the beat structure (default: richest/longest)")
    ap.add_argument("--avatar-dir", default=None,
                    help="Reference avatar folder (auto-inferred from the analysis path)")
    ap.add_argument("--transition-style", default=None, help="Override transition_style.json path")
    ap.add_argument("--subtitle-style", default=None, help="Override subtitle_style.json path")
    ap.add_argument("--talking-profile", default=None, help="Override talking_profile.json path")
    ap.add_argument("--base-dir", default=".", help="Base for relative paths stored in the template")
    ap.add_argument("--output", "-o", default=None,
                    help="Where to write reel_template.json (default: <avatar>/reel_template.json or ./reel_template.json)")
    args = ap.parse_args()

    template = build_template(args)

    base = Path(args.base_dir).expanduser().resolve()
    if args.output:
        out = Path(args.output).expanduser()
    else:
        avatar = template["source"]["avatar"]
        avatar_dir = (Path(args.avatar_dir).expanduser() if args.avatar_dir
                      else (base / avatar) if avatar else base)
        out = Path(avatar_dir) / "reel_template.json"
    C.save_json(out, template)

    s = template["summary"]
    print(f"\n  Reel template written: {out}", file=sys.stderr)
    print(f"  {s['total_scenes']} beats ({s['talking_head']} talking-head, "
          f"{s['broll']} B-roll) | {s['total_duration']}s | avg {s['avg_scene_dur']}s "
          f"({s['cut_rhythm']}) | angles: {', '.join(template['angles_needed']) or 'none'}",
          file=sys.stderr)
    print(json.dumps({
        "template": str(out),
        "avatar": template["source"]["avatar"],
        "beats": s["total_scenes"],
        "angles_needed": template["angles_needed"],
        "narrative_arc": s["narrative_arc"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
