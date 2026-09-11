#!/usr/bin/env python3
"""Map a video MOLD (blueprint.json) + authored content.json -> composer storyboard.

Produces an avatar-reel-composer ``storyboard.json`` that reuses the mold's beat
COUNT and talking-head/B-roll SEQUENCE, assigns each talking-head beat the
avatar's matching camera-angle still (default look or a per-scene location),
carries the per-beat motion / emphasis, wires captions + music (+ the measured
ducking envelope) + transitions from the mold, and splits the script across
beats — either from the agent's per-beat ``text`` or proportionally by
``dur_weight``.

Multi-speaker molds: any beat whose ``speaker`` maps to a NON-host avatar becomes
a ``type: "guest"`` scene, and a sibling ``<slug>.narration_plan.json`` is emitted
for avatar-reel-composer's ``assemble_narration.py`` (host ``tts`` runs + ``guest``
segments in scene order). ``remix.py`` runs that plan, patches each guest scene's
``broll_clip`` and composes with the pre-built narration.

The composer's HARD RULE — the concatenation of every scene.text (single spaces)
must equal ``script`` verbatim — is enforced here.

Usage:
  python3 build_storyboard.py --blueprint runs/x/blueprint.json --content runs/x/content.json \
      -o runs/x/reel.storyboard.json --base-dir .
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

TODO_PREFIX = "TODO"
FORMAT_SUFFIX = {"reel": "_916", "post": "_916", "landscape": "_169"}


# ---------------------------------------------------------------------------
# Script split (verbatim guarantee) — mirrors reel-restyle
# ---------------------------------------------------------------------------
def normalize_script(text: str) -> str:
    return " ".join((text or "").split())


def allocate(n_words: int, weights: list[float]) -> list[int] | None:
    k = len(weights)
    if n_words < k:
        return None
    rem = n_words - k
    tot = sum(weights) or 1.0
    shares = [rem * (w / tot) for w in weights]
    add = [int(s) for s in shares]
    leftover = rem - sum(add)
    order = sorted(range(k), key=lambda i: shares[i] - add[i], reverse=True)
    for j in range(leftover):
        add[order[j % k]] += 1
    return [1 + add[i] for i in range(k)]


# ---------------------------------------------------------------------------
# Avatar / role resolution
# ---------------------------------------------------------------------------
def resolve_avatars(content: dict, base_dir: Path) -> tuple[dict, str]:
    """role -> {dir, rel, slug, voice_id} + the host role."""
    avatars = content.get("avatars") or []
    if not avatars:
        raise SystemExit("content.avatars is empty — resolve avatars first (remix.py stage 'avatars').")
    resolved: dict = {}
    host_role = None
    for a in avatars:
        role = a.get("role") or "host"
        use = a.get("use")
        if not use:
            raise SystemExit(f"avatar role '{role}' has no resolved `use` path "
                             "(remix.py must invent/pick it before building the storyboard).")
        adir = C.resolve_path(use, base_dir)
        resolved[role] = {
            "dir": adir,
            "rel": C.rel_to(adir, base_dir),
            "slug": adir.name,
            "voice_id": a.get("voice_id"),
        }
        if host_role is None or role == "host":
            host_role = role if role == "host" else host_role or role
    if host_role is None:
        host_role = avatars[0].get("role", "host")
    return resolved, host_role


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------
def _angle_image(av: dict, move: str, suffix: str, location: str | None) -> tuple[dict, str | None]:
    """Return storyboard image/angle fields. Uses a per-scene location when given."""
    if location and location not in ("default", ""):
        return ({"angle": move, "location": location}, None)
    img = f"{av['rel']}/angles/{av['slug']}_{move}{suffix}.png"
    return ({"image": img}, img)


def build_scene(beat_bp: dict, beat_ct: dict, idx: int, text: str, *,
                avatars: dict, host_role: str, suffix: str) -> tuple[dict, dict | None]:
    """Return (scene, guest_segment_or_None)."""
    sid = f"s{idx + 1}"
    btype = beat_bp.get("type", "broll")
    speaker = beat_ct.get("speaker") or beat_bp.get("speaker") or host_role
    location = beat_ct.get("location") or None

    if btype == "broll":
        scene = {"id": sid, "type": "broll", "text": text,
                 "broll_camera": beat_bp.get("broll_camera", "push_in"), "motion": "none"}
        desc = (beat_ct.get("broll_description") or "").strip()
        if desc and not desc.startswith(TODO_PREFIX):
            scene["broll_description"] = desc
            scene["broll_action"] = (beat_ct.get("broll_action") or "").strip() or \
                "continuous, realistic human action; no spoken dialogue"
        else:
            hint = beat_bp.get("broll_hint") or text
            scene["broll_description"] = (f"{TODO_PREFIX} (B-roll): supporting insert (no main "
                                          f"presenter) for this line. Mold hint: {hint}")
            scene["broll_action"] = f"{TODO_PREFIX}: continuous, realistic human action; no dialogue"
        return scene, None

    # talking_head — host or guest
    move = beat_bp.get("move") or "eye_level"
    if speaker == host_role or speaker not in avatars:
        av = avatars[host_role]
        fields, _img = _angle_image(av, move, suffix, location)
        scene = {"id": sid, "type": "talking_head", "text": text,
                 "zoom_from_previous": beat_bp.get("zoom_from_previous", "none"),
                 "emphasis": bool(beat_bp.get("emphasis"))}
        scene.update(fields)
        return scene, None

    # guest speaker
    av = avatars[speaker]
    fields, img = _angle_image(av, move, suffix, location)
    guest_img = img or f"{av['rel']}/angles/{av['slug']}_{move}{suffix}.png"
    scene = {"id": sid, "type": "guest", "text": text, "broll_clip": None,
             "motion": "none", "emphasis": bool(beat_bp.get("emphasis")),
             "_guest_avatar_dir": av["rel"], "_guest_image": guest_img,
             "_guest_voice_id": av.get("voice_id"), "_guest_slug": f"{av['slug']}_{sid}"}
    seg = {"kind": "guest", "slug": f"{av['slug']}_{sid}", "avatar_dir": av["rel"],
           "image": guest_img, "text": text}
    if av.get("voice_id"):
        seg["voice_id"] = av["voice_id"]
    return scene, seg


# ---------------------------------------------------------------------------
# Finish block (captions + music + ducking + fx) from the mold
# ---------------------------------------------------------------------------
def build_finish(blueprint: dict, content: dict, base_dir: Path) -> dict:
    music_ct = content.get("music", {}) or {}
    caps_ct = content.get("captions", {}) or {}
    audio = blueprint.get("audio", {}) or {}
    music_bp = audio.get("music", {}) or {}
    tr = (blueprint.get("transitions", {}) or {}).get("style", "")

    music_on = bool(music_ct.get("enabled", music_bp.get("present", True)))
    prompt = (music_ct.get("prompt") or "").strip() or (
        f"instrumental bed, {audio.get('music_mood', 'calm, unobtrusive')}, light, no drums, no vocals")
    finish = {
        "enabled": True,
        "subtitles": bool(caps_ct.get("present", True)) if "present" in caps_ct else True,
        "music": music_on,
        "music_mood": music_ct.get("mood", "ambient"),
        "music_prompt": prompt,
        "music_volume": float(music_ct.get("volume", music_bp.get("base_volume", 0.12))),
        "music_structure": music_ct.get("structure", music_bp.get("structure", "flat")),
        "max_words": int(caps_ct.get("max_words") or 6),
        "emphasis": True,
        "casing": caps_ct.get("casing", "subtitle"),
        "caption_reveal": caps_ct.get("reveal", "word"),
        "_note": "captions + music tailored from the video mold; music_structure reproduces the "
                 "measured voice-vs-music ducking (auto = duck under the hook, lift after, resolve on close).",
        "fx": {"enabled": True, "sfx": True, "sfx_volume": 0.18},
    }
    style_from = (caps_ct.get("style_from") or "").strip()
    if style_from:
        finish["style_from"] = style_from
    tr_map = {"golden_flash": "golden_flash", "white_flash": "white_flash",
              "dip_black": "dip_black", "punch": "punch", "hard_cut": "none", "none": "none"}
    if tr in tr_map:
        finish["fx"]["transition_style"] = tr_map[tr]
    return finish


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def build(blueprint: dict, content: dict, *, base_dir: Path, slug: str, fmt: str,
          resolution: str, fps: int, language: str | None) -> tuple[dict, dict | None, list, list]:
    warnings: list[str] = []
    beats_bp = blueprint.get("beats") or []
    beats_ct = content.get("beats") or []
    if not beats_bp:
        raise SystemExit("blueprint has no beats.")
    if beats_ct and len(beats_ct) != len(beats_bp):
        warnings.append(f"content has {len(beats_ct)} beats but the mold has {len(beats_bp)}; "
                        "using the mold's beat structure and matching by index.")
    ct_by_index = {b.get("index", i): b for i, b in enumerate(beats_ct)}

    avatars, host_role = resolve_avatars(content, base_dir)
    suffix = FORMAT_SUFFIX.get(fmt, "_916")

    # Resolve the per-beat text split.
    script_full = normalize_script(content.get("script", ""))
    authored = [normalize_script((ct_by_index.get(i) or {}).get("text", "")) for i in range(len(beats_bp))]
    if all(authored):
        texts = authored
        joined = normalize_script(" ".join(t for t in texts if t))
        if script_full and joined != script_full:
            warnings.append("per-beat text does not match content.script verbatim; "
                            "using the per-beat split as the script.")
        script_full = joined
    elif script_full:
        counts = allocate(len(script_full.split()), [b.get("dur_weight") or 0 for b in beats_bp])
        if counts is None:
            raise SystemExit("script is too short for the mold's beat count; shorten the mold or lengthen the script.")
        words, texts, cur = script_full.split(), [], 0
        for c in counts:
            texts.append(" ".join(words[cur:cur + c]))
            cur += c
        warnings.append("beat text auto-split proportionally from content.script; review phrase boundaries.")
    else:
        raise SystemExit("Nothing to narrate: fill content.script or per-beat text.")

    scenes, guest_segs, todo_ids, missing = [], [], [], []
    prev_was_host = False
    for i, beat_bp in enumerate(beats_bp):
        beat_ct = ct_by_index.get(i, {})
        scene, guest_seg = build_scene(beat_bp, beat_ct, i, texts[i],
                                       avatars=avatars, host_role=host_role, suffix=suffix)
        if scene.get("broll_description", "").startswith(TODO_PREFIX):
            todo_ids.append(scene["id"])
        if scene["type"] == "talking_head" and scene.get("image"):
            img = C.resolve_path(scene["image"], base_dir)
            if not img.exists() and scene["image"] not in missing:
                missing.append(scene["image"])
        scenes.append(scene)
        if guest_seg is not None:
            guest_segs.append((i, guest_seg))

    # Verbatim guarantee.
    rebuilt = normalize_script(" ".join(s["text"] for s in scenes if s.get("text")))
    if rebuilt != script_full:
        warnings.append("internal split drifted from the script; the composer will fall back to proportional alignment.")

    if missing:
        warnings.append("angle stills not generated yet: " + ", ".join(missing[:6]) +
                        (" ..." if len(missing) > 6 else "") + " (remix.py generates them via avatar-invent/location).")

    voice = {
        "name": None, "voice_id": avatars[host_role].get("voice_id"),
        "emotion": "calm", "speed": 0.95, "language_boost": "None", "sentence_gap": 0.12,
        "_note": "host voice auto-resolves from <avatar>/voices/; language_boost stays 'None' to keep the cloned accent.",
    }
    storyboard = {
        "_comment": "Generated by video-remix from a video mold. Beat structure, angles, motion, "
                    "captions, music + ducking and transitions come from the mold; REVIEW the per-scene "
                    "text split and AUTHOR every TODO B-roll before composing.",
        "avatar_dir": avatars[host_role]["rel"],
        "slug": slug,
        "reference_video": blueprint.get("source_video"),
        "format": fmt,
        "resolution": resolution,
        "fps": fps,
        "voice": voice,
        "script": script_full,
        "scenes": scenes,
        "finish": build_finish(blueprint, content, base_dir),
    }
    if language:
        storyboard["_language"] = language

    # Multi-avatar: emit a narration plan (host tts runs + guest segments in scene order).
    plan = None
    if guest_segs:
        guest_indices = {i for i, _ in guest_segs}
        guest_seg_by_index = {i: seg for i, seg in guest_segs}
        segments: list[dict] = []
        host_run: list[str] = []

        def _flush_host():
            if host_run:
                segments.append({"kind": "tts", "avatar_dir": avatars[host_role]["rel"],
                                 "text": " ".join(host_run),
                                 "voice": {"voice_id": avatars[host_role].get("voice_id"),
                                           "emotion": "auto", "language_boost": "None"}})
                host_run.clear()

        for i, s in enumerate(scenes):
            if i in guest_indices:
                _flush_host()
                segments.append(guest_seg_by_index[i])
            else:
                if s.get("text"):
                    host_run.append(s["text"])
        _flush_host()
        plan = {
            "out_dir": ".",   # remix.py overrides with the reel dir
            "gap": 0.0,
            "language": language or content.get("meta", {}).get("language", "es"),
            "whisper_model": "small",
            "resolution": resolution,
            "script": script_full,
            "segments": segments,
        }
    return storyboard, plan, warnings, todo_ids


def main() -> int:
    ap = argparse.ArgumentParser(description="Build an avatar-reel-composer storyboard from a video mold + content.")
    ap.add_argument("--blueprint", required=True, help="blueprint.json from analyze_video.py")
    ap.add_argument("--content", required=True, help="content.json authored from content_template.json")
    ap.add_argument("--output", "-o", default=None, help="Storyboard path (default: <blueprint dir>/<slug>.storyboard.json)")
    ap.add_argument("--base-dir", default=".", help="Base for relative paths in the storyboard")
    ap.add_argument("--slug", default=None, help="Reel slug (default: content.meta.slug or derived)")
    ap.add_argument("--format", default=None, choices=["reel", "post", "landscape"],
                    help="Override output format (default: content.meta.format or the mold's)")
    ap.add_argument("--resolution", default="720p", choices=["720p", "1080p"])
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--force", action="store_true", help="Overwrite an existing storyboard")
    args = ap.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve()
    blueprint = C.load_json(args.blueprint)
    content = C.load_json(args.content)
    meta = content.get("meta", {}) or {}
    fmt = args.format or meta.get("format") or blueprint.get("geometry", {}).get("format", "reel")
    if fmt not in FORMAT_SUFFIX:
        fmt = "reel"
    language = meta.get("language")
    slug = args.slug or meta.get("slug") or C.slugify(meta.get("topic") or Path(args.blueprint).parent.name)

    out = (Path(args.output).expanduser() if args.output
           else Path(args.blueprint).parent / f"{slug}.storyboard.json")
    if out.exists() and not args.force:
        print(f"  storyboard exists: {out} (use --force to overwrite)", file=sys.stderr)
        print(json.dumps({"storyboard": str(out), "skipped": True}, ensure_ascii=False))
        return 0

    storyboard, plan, warnings, todo_ids = build(
        blueprint, content, base_dir=base_dir, slug=slug, fmt=fmt,
        resolution=args.resolution, fps=args.fps, language=language)
    C.save_json(out, storyboard)
    plan_path = None
    if plan is not None:
        base = out.name[:-len(".storyboard.json")] if out.name.endswith(".storyboard.json") else out.stem
        plan_path = out.parent / f"{base}.narration_plan.json"
        C.save_json(plan_path, plan)

    n_th = sum(1 for s in storyboard["scenes"] if s["type"] == "talking_head")
    n_g = sum(1 for s in storyboard["scenes"] if s["type"] == "guest")
    n_br = sum(1 for s in storyboard["scenes"] if s["type"] == "broll")
    print(f"\n  Storyboard written: {out}", file=sys.stderr)
    print(f"  {len(storyboard['scenes'])} scenes ({n_th} talking-head, {n_g} guest, {n_br} B-roll), format={storyboard['format']}",
          file=sys.stderr)
    for w in warnings:
        print(f"  ! {w}", file=sys.stderr)
    if todo_ids:
        print(f"  ==> AUTHOR B-roll for: {', '.join(todo_ids)} (edit broll_description/broll_action).", file=sys.stderr)
    print(json.dumps({
        "storyboard": str(out),
        "narration_plan": str(plan_path) if plan_path else None,
        "multi_avatar": plan is not None,
        "scenes": len(storyboard["scenes"]),
        "talking_head": n_th, "guest": n_g, "broll": n_br,
        "format": storyboard["format"],
        "todo_broll": todo_ids,
        "warnings": warnings,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
