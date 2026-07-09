#!/usr/bin/env python3
"""Generate timeline.json (the EDL) from a treatment + assets + bgm_meta.

Two-phase pipeline:

  Phase 1 — Asset matching (LLM call):
    Inputs : treatment.shots[]  +  assets.json  +  bgm_meta.json
    Outputs: a candidate timeline.json with per-shot:
             - chosen source (video clip + scene, OR image)
             - sub-clip src_in / src_out
             - transition kind + duration to the previous shot
             - Ken Burns preset (for image shots)
             - title placement (carries over from treatment)

  Phase 2 — Beat-snap (deterministic):
    For each shot boundary, find the nearest beat within tolerance and snap to
    it. Adjust adjacent shot durations to absorb the delta. Preserves total
    duration ±5%.

Usage:
    python3 generate_edl.py \\
        --treatment treatment.yaml --assets assets.json --music bgm.mp3 \\
        --music-meta bgm_meta.json -o timeline.json

    python3 generate_edl.py ... --no-beat-snap   # skip phase 2
    python3 generate_edl.py ... --beat-tolerance 0.4
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (FORMAT_PRESETS, call_llm_json, get_format_preset,
                     ffprobe_audio, load_json, save_json)

VALID_TRANSITIONS = {
    "cut", "fade", "dissolve",
    "slideleft", "slideright", "slideup", "slidedown",
    "circleopen", "circleclose",
    "wipeleft", "wiperight",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "radial",
}

KEN_BURNS_PRESETS = {"none", "zoom_center", "push_in", "push_out",
                     "drift_left", "drift_right", "drift_up", "drift_down"}

DEFAULT_TRANSITION_DUR = 0.30
MIN_SHOT_DURATION = 1.2


SYSTEM_PROMPT = """You are a senior video editor assembling an Edit Decision List (EDL) for a music-driven reel (no voiceover).

You receive:
- A TREATMENT (the shot list with desired durations and descriptions)
- An ASSET LIBRARY (videos with detected scenes, and standalone images)
- MUSIC METADATA (BPM, total duration)

Your job: pick the BEST source asset for each shot in the treatment, choose a
sub-clip range within the source, pick a transition type from the previous shot,
and pick a Ken Burns motion for image shots.

Rules:
- For each shot, choose ONE source. If it's a video, also choose a scene index
  AND src_in/src_out within that scene's [in, out] range.
  If it's an image, src_in/src_out are not used (set them to 0).
- For video sources, src_out - src_in MUST equal the shot duration EXACTLY.
- Prefer scenes with HIGH blur_score (>0.6, sharper) and matching motion_score
  (high motion for energetic shots, low motion for calm shots).
- For image shots, ALWAYS choose a Ken Burns preset (never "none"): use
  "push_in" for intimate/portrait shots, "drift_right"/"drift_left" for wide
  scenic images, "zoom_center" as a safe default.
- For video shots, set ken_burns to "none" (the source video already has motion).
- Vary transitions across the reel. Use "cut" for energetic / on-beat moments,
  "fade" or "dissolve" for emotional or calm moments, "slideleft" / "slideright"
  sparingly for narrative shifts. NEVER use the same transition more than 3
  times in a row.
- The first shot MUST have transition_in = null (no transition into the first
  shot).
- Transition duration (transition_in.dur) is between 0.15s and 0.50s. Use 0.30s
  as default. For "cut" transitions, set dur to 0.
- Carry over title from the treatment exactly (text + style). Do not invent new
  titles, but you may set title to null if a treatment shot's title is null.

Output a single JSON object with this exact shape:

{
  "video": [
    {
      "shot_index": <int>,
      "duration": <number>,
      "source": "<asset path from the library>",
      "scene_index": <int or null for images>,
      "src_in": <number>,
      "src_out": <number>,
      "ken_burns": "none|push_in|push_out|zoom_center|drift_left|drift_right|drift_up|drift_down",
      "transition_in": null | { "kind": "<transition>", "dur": <number> },
      "title": null | { "text": "<carried-over text>", "style": "<carried-over style>" }
    }
  ]
}

Output ONLY the JSON object — no commentary.
"""


def summarize_assets_for_edl(assets, *, max_videos=12, max_scenes=6, max_images=15):
    """Build a compact LLM-friendly description of the asset library."""
    videos = assets.get("videos", {})
    images = assets.get("images", {})

    sections = []
    sections.append(f"VIDEOS ({len(videos)} total):")
    for path, meta in list(videos.items())[:max_videos]:
        scenes = meta.get("scenes", [])[:max_scenes]
        sections.append(f"\n  source: {path}  (duration={meta.get('duration', 0):.1f}s)")
        for i, sc in enumerate(scenes):
            desc = (sc.get("description") or "[no description]")[:140]
            sections.append(
                f"    scene {i}: in={sc.get('in', 0):.2f}s out={sc.get('out', 0):.2f}s "
                f"(blur={sc.get('blur_score', 0):.2f} motion={sc.get('motion_score', 0):.2f}) — {desc}"
            )

    sections.append(f"\nIMAGES ({len(images)} total):")
    for path, meta in list(images.items())[:max_images]:
        desc = (meta.get("description") or "[no description]")[:140]
        sections.append(f"  source: {path}  — {desc}")

    return "\n".join(sections)


def call_llm_for_matching(treatment, assets, music_meta):
    """Phase 1 LLM call: shot list → matched timeline.video[]."""
    asset_summary = summarize_assets_for_edl(assets)
    bpm = music_meta.get("bpm") or 0
    music_dur = music_meta.get("duration") or 0
    structure = music_meta.get("structure", [])

    shots_block = json.dumps(treatment.get("shots", []), indent=2, ensure_ascii=False)

    user_prompt = (
        f"TREATMENT:\n"
        f"  goal: {treatment.get('goal', '')}\n"
        f"  tone: {treatment.get('tone', '')}\n"
        f"  language: {treatment.get('language', 'en')}\n"
        f"  format: {treatment.get('format', 'reel')}\n"
        f"  target_duration: {treatment.get('target_duration', 30)}s\n"
        f"  shots:\n{shots_block}\n\n"
        f"MUSIC:\n"
        f"  bpm: {bpm}\n"
        f"  duration: {music_dur:.2f}s\n"
        f"  structure: {json.dumps(structure)}\n\n"
        f"ASSET LIBRARY:\n{asset_summary}\n\n"
        "Now output the matched timeline as a single JSON object."
    )

    return call_llm_json(SYSTEM_PROMPT, user_prompt, temperature=0.45)


def normalize_transition(t):
    """Normalize a transition_in dict (or None) to its canonical form."""
    if t is None:
        return None
    if not isinstance(t, dict):
        return None
    kind = (t.get("kind") or "fade").lower().strip()
    if kind not in VALID_TRANSITIONS:
        kind = "fade"
    dur = float(t.get("dur", DEFAULT_TRANSITION_DUR))
    if kind == "cut":
        dur = 0.0
    dur = max(0.0, min(0.6, dur))
    return {"type": "xfade", "kind": kind, "dur": round(dur, 3)}


def build_timeline_from_match(matches, treatment, assets, music_path, music_meta, *,
                              format_, music_volume, music_fade_in_ms, music_fade_out_ms):
    """Convert raw match dicts into the canonical timeline.json structure."""
    preset = get_format_preset(format_)
    width, height = preset["width"], preset["height"]

    video_track = []
    titles_track = []
    cursor = 0.0

    treatment_shots = treatment.get("shots", [])

    for i, m in enumerate(matches):
        shot_idx = m.get("shot_index", i)
        treat_shot = treatment_shots[shot_idx] if 0 <= shot_idx < len(treatment_shots) else None

        if treat_shot is None:
            duration = float(m.get("duration", 3.0))
        else:
            duration = float(treat_shot.get("duration", m.get("duration", 3.0)))

        duration = max(MIN_SHOT_DURATION, duration)

        source = m.get("source", "")
        scene_index = m.get("scene_index")

        is_video_source = source in assets.get("videos", {})
        is_image_source = source in assets.get("images", {})

        if not is_video_source and not is_image_source:
            print(f"  Warning: source {source!r} not in library; skipping shot {shot_idx}",
                  file=sys.stderr)
            continue

        ken_burns = m.get("ken_burns", "none")
        if ken_burns not in KEN_BURNS_PRESETS:
            ken_burns = "push_in" if is_image_source else "none"
        if is_image_source and ken_burns == "none":
            ken_burns = "push_in"
        if is_video_source and ken_burns != "none":
            ken_burns = "none"

        if is_video_source:
            scenes = assets["videos"][source].get("scenes", [])
            scene_idx = scene_index if isinstance(scene_index, int) and 0 <= scene_index < len(scenes) else 0
            if not scenes:
                print(f"  Warning: video {source!r} has no scenes; skipping",
                      file=sys.stderr)
                continue
            scene = scenes[scene_idx]
            scene_in = float(scene["in"])
            scene_out = float(scene["out"])
            scene_dur = scene_out - scene_in

            src_in = float(m.get("src_in", scene_in))
            src_out = float(m.get("src_out", min(scene_out, scene_in + duration)))

            src_in = max(scene_in, src_in)
            src_out = min(scene_out, src_out)

            chosen_dur = src_out - src_in
            if abs(chosen_dur - duration) > 0.05:
                if scene_dur >= duration:
                    src_in = scene_in + (scene_dur - duration) / 2.0
                    src_out = src_in + duration
                else:
                    duration = max(MIN_SHOT_DURATION, scene_dur)
                    src_in = scene_in
                    src_out = scene_out
        else:
            src_in = 0.0
            src_out = duration
            scene_idx = None

        transition = m.get("transition_in")
        if i == 0:
            transition = None
        else:
            transition = normalize_transition(transition)

        title = m.get("title")
        if treat_shot and treat_shot.get("title"):
            title = {"text": treat_shot["title"]["text"], "style": treat_shot["title"]["style"]}
        elif title is None:
            pass

        in_at = cursor
        out_at = cursor + duration

        seg = {
            "id": f"v{i+1}",
            "in_at": round(in_at, 3),
            "out_at": round(out_at, 3),
            "duration": round(duration, 3),
            "source": source,
            "scene_index": scene_idx,
            "src_in": round(src_in, 3),
            "src_out": round(src_out, 3),
            "ken_burns": ken_burns,
            "transition_in": transition,
        }
        video_track.append(seg)

        if title:
            t_in = round(in_at + 0.3, 3)
            t_dur = compute_title_duration(title.get("style", "fullscreen"), duration)
            t_out = round(min(out_at - 0.2, t_in + t_dur), 3)
            if t_out > t_in:
                titles_track.append({
                    "id": f"t{len(titles_track)+1}",
                    "in_at": t_in,
                    "out_at": t_out,
                    "text": title["text"],
                    "style": title["style"],
                    "props": title.get("props", {}),
                    "shot_index": i,
                })

        cursor = out_at

    music = {
        "source": str(music_path) if music_path else None,
        "volume": music_volume,
        "fade_in_ms": music_fade_in_ms,
        "fade_out_ms": music_fade_out_ms,
        "bpm": music_meta.get("bpm"),
        "beat_times": music_meta.get("beat_times", []),
        "structure": music_meta.get("structure", []),
    }

    return {
        "version": 1,
        "format": format_,
        "fps": 30,
        "width": width,
        "height": height,
        "total_duration": round(cursor, 3),
        "tracks": {
            "video": video_track,
            "music": music,
            "titles": titles_track,
            "captions": None,
        },
        "metadata": {
            "beat_snapped": False,
            "treatment_hash": _short_hash(json.dumps(treatment, sort_keys=True)),
            "assets_hash": _short_hash(json.dumps(list(assets.get("videos", {}).keys()) +
                                                  list(assets.get("images", {}).keys()),
                                                  sort_keys=True)),
        },
    }


def compute_title_duration(style, shot_duration):
    """Pick a sensible default duration for a title based on its style."""
    style_durations = {
        "lower_third": 2.5,
        "kinetic_burst": 2.0,
        "fullscreen": 2.0,
        "tag_line": 3.0,
        "badge": shot_duration,
        "ticker": 3.0,
    }
    base = style_durations.get(style, 2.5)
    if style == "badge":
        return max(1.0, shot_duration - 0.5)
    return min(base, max(1.5, shot_duration - 0.5))


def _short_hash(s, n=10):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:n]


def beat_snap(timeline, *, tolerance=0.25, min_shot_duration=MIN_SHOT_DURATION):
    """Phase 2: snap shot boundaries to nearby beats.

    Adjusts adjacent shot durations to absorb the delta. Preserves total
    duration within ~5%. Skips snaps that would make a shot shorter than
    min_shot_duration.
    """
    music = timeline.get("tracks", {}).get("music", {})
    beats = music.get("beat_times", [])
    video = timeline.get("tracks", {}).get("video", [])

    if not beats or len(video) < 2:
        timeline["metadata"]["beat_snapped"] = False
        return timeline

    boundaries = []
    cursor = 0.0
    for seg in video:
        cursor = round(seg["out_at"], 6)
        boundaries.append(cursor)

    snapped = []
    snap_count = 0

    for i in range(len(boundaries) - 1):
        b = boundaries[i]
        nearest = min(beats, key=lambda x: abs(x - b))
        if abs(nearest - b) <= tolerance:
            new_b = nearest
            left_dur = (new_b - (boundaries[i - 1] if i > 0 else 0.0))
            right_dur = boundaries[i + 1] - new_b
            if left_dur >= min_shot_duration and right_dur >= min_shot_duration:
                boundaries[i] = round(new_b, 3)
                snapped.append({"shot": i, "from": b, "to": new_b})
                snap_count += 1

    cursor = 0.0
    for i, seg in enumerate(video):
        seg["in_at"] = round(cursor, 3)
        end_at = boundaries[i] if i < len(boundaries) else seg["out_at"]
        seg["out_at"] = round(end_at, 3)
        seg["duration"] = round(seg["out_at"] - seg["in_at"], 3)

        if seg.get("scene_index") is not None and seg.get("source"):
            new_dur = seg["duration"]
            old_dur = seg["src_out"] - seg["src_in"]
            if abs(new_dur - old_dur) > 0.02:
                center = (seg["src_in"] + seg["src_out"]) / 2.0
                seg["src_in"] = round(center - new_dur / 2.0, 3)
                seg["src_out"] = round(center + new_dur / 2.0, 3)
        elif seg.get("scene_index") is None:
            seg["src_in"] = 0.0
            seg["src_out"] = seg["duration"]

        cursor = seg["out_at"]

    titles = timeline.get("tracks", {}).get("titles", []) or []
    for t in titles:
        si = t.get("shot_index")
        if si is None or si >= len(video):
            continue
        seg = video[si]
        t["in_at"] = round(seg["in_at"] + 0.3, 3)
        t_dur = t.get("out_at", 0) - t.get("in_at", 0)
        if t_dur <= 0:
            t_dur = compute_title_duration(t.get("style", "fullscreen"), seg["duration"])
        t["out_at"] = round(min(seg["out_at"] - 0.2, t["in_at"] + t_dur), 3)

    timeline["total_duration"] = round(video[-1]["out_at"], 3) if video else 0.0
    timeline["metadata"]["beat_snapped"] = snap_count > 0
    timeline["metadata"]["beat_snap_count"] = snap_count
    timeline["metadata"]["beat_snap_log"] = snapped

    return timeline


def main():
    parser = argparse.ArgumentParser(description="Generate timeline.json (the EDL)")
    parser.add_argument("--treatment", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--music", required=True, help="Path to bgm.mp3")
    parser.add_argument("--music-meta", required=True, help="Path to bgm_meta.json")
    parser.add_argument("--format", default="reel", choices=sorted(FORMAT_PRESETS.keys()))
    parser.add_argument("--music-volume", type=float, default=0.7)
    parser.add_argument("--music-fade-in-ms", type=int, default=500)
    parser.add_argument("--music-fade-out-ms", type=int, default=2000)
    parser.add_argument("--no-beat-snap", action="store_true")
    parser.add_argument("--beat-tolerance", type=float, default=0.25)
    parser.add_argument("--min-shot-duration", type=float, default=MIN_SHOT_DURATION)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    try:
        import yaml
        with open(args.treatment, encoding="utf-8") as f:
            treatment = yaml.safe_load(f)
    except ImportError:
        print("Error: PyYAML not installed.", file=sys.stderr)
        sys.exit(1)

    assets = load_json(args.assets)
    music_meta = load_json(args.music_meta)

    print(f"Generating EDL for {len(treatment.get('shots', []))} shots...", file=sys.stderr)
    matched = call_llm_for_matching(treatment, assets, music_meta)
    if not matched or "video" not in matched:
        print("Error: LLM did not return a valid match. Re-run.", file=sys.stderr)
        sys.exit(2)

    timeline = build_timeline_from_match(
        matched["video"], treatment, assets,
        music_path=args.music, music_meta=music_meta,
        format_=args.format,
        music_volume=args.music_volume,
        music_fade_in_ms=args.music_fade_in_ms,
        music_fade_out_ms=args.music_fade_out_ms,
    )

    if not args.no_beat_snap:
        timeline = beat_snap(
            timeline,
            tolerance=args.beat_tolerance,
            min_shot_duration=args.min_shot_duration,
        )

    save_json(args.output, timeline)

    print(json.dumps({
        "output": str(Path(args.output).resolve()),
        "shots": len(timeline["tracks"]["video"]),
        "titles": len(timeline["tracks"]["titles"]),
        "duration": timeline["total_duration"],
        "beat_snapped": timeline["metadata"].get("beat_snapped", False),
        "beat_snap_count": timeline["metadata"].get("beat_snap_count", 0),
    }, indent=2))


if __name__ == "__main__":
    main()
