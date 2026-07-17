#!/usr/bin/env python3
"""Stage 2 (core) of avatar-reel-composer: turn a storyboard into a finished reel.

Given a storyboard.json (see examples/storyboard.example.json) and an existing
avatar, this:
  1. Narrates the full script as ONE continuous cloned-voice take + aligns it
     word-by-word (delegates to narrate.py / faster-whisper). Idempotent.
  2. Maps each scene.text to a [start, end] range in the narration by aligning
     the script words to the narration words, snapping each cut to the midpoint
     of the silence between words (clean cuts). Scene ranges TILE the whole
     narration with no gaps/overlaps.
  3. Slices narration.mp3 into scenes/chunk_<id>.mp3.
  4. Generates each scene:
       talking_head -> avatar-talking-video (--audio chunk, lip-synced)
       broll        -> broll-generator (silent, --duration ceil(chunk))
  5. Normalizes each clip (video-only): trim to the exact chunk duration
     (clone-pad if short) -> scale/pad to the reel format -> Ken Burns / zoom.
  6. Concatenates with HARD CUTS (sum of durations == narration length).
  7. Muxes narration.mp3 back on as the single master track -> final.mp4.
  8. Writes reel_manifest.json.

Because every chunk is cut from the same narration and we assemble with hard
cuts (no xfade that would shorten the timeline), re-laying the full narration on
top lands perfectly in sync.

Usage:
    python3 compose_reel.py path/to/storyboard.json
    python3 compose_reel.py storyboard.json --dry-run     # narrate+align+slice only
    python3 compose_reel.py storyboard.json --regen       # regenerate scene clips
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _arc_common as C  # noqa: E402
import narrate as narrate_mod  # noqa: E402

MIN_SCENE_GAP = 0.20  # seconds; keep scene boundaries strictly increasing
BROLL_FPS = 24        # p-video supports {24, 48}; we re-time in normalization


# ---------------------------------------------------------------------------
# Text / alignment helpers
# ---------------------------------------------------------------------------
def norm_word(w: str) -> str:
    w = unicodedata.normalize("NFKD", w or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", w.lower())


def tokens(text: str) -> list[str]:
    """Normalized word tokens (drops punctuation / empties)."""
    raw = re.findall(r"\w+", text or "", flags=re.UNICODE)
    return [t for t in (norm_word(r) for r in raw) if t]


def compute_boundaries(scenes, align, total_dur) -> list[float]:
    """Return N+1 boundary times that tile [0, total_dur] for N scenes.

    Aligns the concatenated scene texts to the narration words (difflib) and
    places each inter-scene cut at the midpoint of the silence around the
    narration word that starts the next scene. Falls back to proportional
    splitting (by word count) when alignment is too weak.
    """
    n = len(scenes)
    if n == 1:
        return [0.0, total_dur]

    narr_words = [w for w in align.get("words", []) if norm_word(w.get("word", ""))]
    narr_norm = [norm_word(w["word"]) for w in narr_words]

    scene_tok = [tokens(s.get("text", "")) for s in scenes]
    script_norm = [t for toks in scene_tok for t in toks]

    # Cumulative script-word index where each new scene begins (n-1 split points).
    cum = []
    run = 0
    for toks in scene_tok[:-1]:
        run += len(toks)
        cum.append(run)

    # Map script word index -> narration word index for matched runs.
    s2n: dict[int, int] = {}
    if script_norm and narr_norm:
        sm = difflib.SequenceMatcher(None, script_norm, narr_norm, autojunk=False)
        for a, b, size in sm.get_matching_blocks():
            for k in range(size):
                s2n[a + k] = b + k

    match_ratio = (len(s2n) / len(script_norm)) if script_norm else 0.0

    def split_time_for(script_idx: int) -> float:
        # Find the narration word index aligned at/after this script boundary.
        j = None
        for cand in range(script_idx, len(script_norm)):
            if cand in s2n:
                j = s2n[cand]
                break
        if j is None:
            for cand in range(script_idx - 1, -1, -1):
                if cand in s2n:
                    j = s2n[cand] + 1
                    break
        if j is None or j <= 0 or j >= len(narr_words):
            if total_dur and script_norm:
                return total_dur * (script_idx / len(script_norm))
            return -1.0
        prev_end = float(narr_words[j - 1]["end"])
        nxt_start = float(narr_words[j]["start"])
        return (prev_end + nxt_start) / 2.0 if nxt_start >= prev_end else nxt_start

    use_proportional = match_ratio < 0.5
    if use_proportional:
        print(f"  Warning: weak script<->narration alignment ({match_ratio:.0%}); "
              "using proportional scene splitting.", file=sys.stderr)

    splits = []
    for idx in cum:
        if use_proportional:
            t = total_dur * (idx / len(script_norm)) if script_norm else 0.0
        else:
            t = split_time_for(idx)
            if t < 0:
                t = total_dur * (idx / len(script_norm)) if script_norm else 0.0
        splits.append(t)

    # Clamp + enforce strictly increasing with a minimum gap.
    bounds = [0.0]
    for t in splits:
        t = max(bounds[-1] + MIN_SCENE_GAP, min(t, total_dur - MIN_SCENE_GAP))
        bounds.append(t)
    bounds.append(total_dur)
    # Final safety: ensure monotonic (can drift if many tiny scenes).
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = min(bounds[i - 1] + MIN_SCENE_GAP, total_dur)
    return bounds


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def resolve_path(raw, base_dir: Path) -> Path:
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (base_dir / p).resolve()


# Pacing heuristics (derived from the analyzed reels: short hook + frequent cuts).
HOOK_MAX = 4.0        # opening scene should be a ~2-3s hook
SCENE_MAX = 8.0       # no shot should linger past ~8s
SLOW_RATIO = 1.6      # warn if our median scene is >1.6x the reference median


def pacing_report(scenes, bounds, total_dur, reference_analysis):
    """Print a non-fatal pacing report comparing the storyboard to the reference.

    Warns on a long opening hook, over-long shots, and cutting more slowly than
    the analyzed reel — the levers that make short-form reels feel engaging.
    """
    import statistics as _st
    durs = [bounds[i + 1] - bounds[i] for i in range(len(scenes))]
    med = _st.median(durs) if durs else 0.0

    ref_med = ref_hook = ref_scenes = None
    if reference_analysis and Path(reference_analysis).exists():
        try:
            ref = C.load_json(reference_analysis)
            rsc = ref.get("scenes", [])
            rdurs = [s.get("duration", 0) for s in rsc if s.get("duration")]
            if rdurs:
                ref_med = _st.median(rdurs)
                ref_hook = rdurs[0]
                ref_scenes = len(rdurs)
        except (OSError, ValueError):
            pass

    print("\n  Pacing report:", file=sys.stderr)
    print(f"    scenes={len(scenes)}  median_shot={med:.1f}s  hook={durs[0]:.1f}s  total={total_dur:.1f}s",
          file=sys.stderr)
    if ref_med:
        suggested = max(1, round(total_dur / ref_med))
        print(f"    reference: median_shot={ref_med:.1f}s  hook={ref_hook:.1f}s  "
              f"scenes={ref_scenes}  -> suggests ~{suggested} scenes for {total_dur:.0f}s",
              file=sys.stderr)

    warns = []
    if durs and durs[0] > HOOK_MAX:
        warns.append(f"opening hook is {durs[0]:.1f}s (aim ~2-3s; split the first line "
                     "or move the back half to B-roll).")
    long_shots = [(s["id"], d) for s, d in zip(scenes, durs)
                  if d > SCENE_MAX and not (s is scenes[-1] and s["type"] == "broll")]
    for sid, d in long_shots:
        warns.append(f"scene {sid} is {d:.1f}s (>{SCENE_MAX:.0f}s); split it or vary the framing/zoom.")
    if ref_med and med > SLOW_RATIO * ref_med:
        warns.append(f"median shot {med:.1f}s is much slower than the reference "
                     f"{ref_med:.1f}s; cut more often (more, shorter scenes).")
    for w in warns:
        print(f"    \u26a0 {w}", file=sys.stderr)
    if not warns:
        print("    \u2713 pacing looks consistent with the reference.", file=sys.stderr)


def camera_report(reference_analysis):
    """Print the reference reel's camera/zoom fingerprint to guide angle choices.

    The talking-head shots reuse a few pre-rendered angle crops + digital zoom,
    so the main lever we replicate is the zoom-transition vocabulary and the
    framing tendency (which framings are used for the base vs. for emphasis).
    """
    if not reference_analysis or not Path(reference_analysis).exists():
        return
    import collections
    try:
        rsc = C.load_json(reference_analysis).get("scenes", [])
    except (OSError, ValueError):
        return
    if not rsc:
        return
    th = [s for s in rsc if s.get("scene_type") == "main_character_solo"]
    ang = collections.Counter(s.get("camera", {}).get("angle") for s in th)
    frm = collections.Counter(s.get("camera", {}).get("framing") for s in th)
    zoom = collections.Counter(s.get("zoom_from_previous", {}).get("type") for s in rsc)

    def top(counter):
        return ", ".join(f"{k}×{v}" for k, v in counter.most_common() if k)

    print("  Reference camera fingerprint (match angles/zoom to this):", file=sys.stderr)
    print(f"    talking-head angle  : {top(ang)}", file=sys.stderr)
    print(f"    talking-head framing: {top(frm)}", file=sys.stderr)
    print(f"    zoom transitions    : {top(zoom)}", file=sys.stderr)


def scene_location(scene, default_location=None) -> str:
    """The effective LOCATION (look) for a scene: per-scene override, else the
    reel default, else 'default' (the avatar's top-level scene.json/angles)."""
    return (scene.get("location") or default_location or "default")


def resolve_image(scene, avatar_dir: Path, base_dir: Path, default_location=None,
                  aspect="9:16") -> Path | None:
    img = scene.get("image")
    if img:
        return resolve_path(img, base_dir)  # explicit path always wins
    angle = scene.get("angle")
    if not angle:
        return None
    # A scene may pick a LOCATION (a look) for the avatar -- per-scene override,
    # else the reel default. "default"/unset => the top-level angles/. When a
    # location lacks the requested angle, fall back to the default look so the
    # reel still renders (with a warning), rather than failing hard.
    loc = scene.get("location") or default_location
    roots = []
    if loc and loc != "default":
        roots.append((loc, avatar_dir / "locations" / loc / "angles"))
    roots.append((None, avatar_dir / "angles"))
    # Prefer the still cropped for THIS output format (``_169`` for 16:9
    # landscape, ``_916`` for 9:16 reels), then any ``_916`` (back-compat), then
    # any still for the angle.
    suffix = "_" + str(aspect).replace(":", "")  # _916 / _169
    pats = list(dict.fromkeys(
        [f"**/*{angle}*{suffix}.png", f"**/*{angle}*_916.png", f"**/*{angle}*.png"]))
    for loc_name, root in roots:
        for pat in pats:
            matches = sorted(root.glob(pat))
            if matches:
                if loc_name is None and loc and loc != "default":
                    print(f"  ! location '{loc}' has no '{angle}' angle; using the "
                          f"default look for scene {scene.get('id', '?')}.", file=sys.stderr)
                return matches[0]
    return None


# Map the analysis's zoom_from_previous vocabulary -> a Ken Burns motion, so a
# scene can transcribe the analyzed camera sequence verbatim (set on the scene as
# "zoom_from_previous"). hard_cut == a clean static reframe (no Ken Burns).
ZOOM_TO_MOTION = {"zoom_in": "push_in", "zoom_out": "push_out",
                  "hard_cut": "none", "none": None}


def resolve_motion(scene) -> tuple[str, str]:
    m = scene.get("motion")
    if m is None:
        if scene.get("type") == "broll":
            m = "none"  # B-roll already carries its own camera move
        else:
            z = scene.get("zoom_from_previous")
            if z is not None:
                mapped = ZOOM_TO_MOTION.get(z, "__")
                m = mapped if mapped != "__" else None
            if m is None:
                m = "zoom_center"
    emphasis = bool(scene.get("emphasis"))
    intensity = "medium" if emphasis else "subtle"
    if emphasis and (m is None or m == "none"):
        m = "push_in"
    return m, intensity


# ---------------------------------------------------------------------------
# Scene generation (delegates to sibling skills)
# ---------------------------------------------------------------------------
def _audio_fingerprint(path) -> str:
    """Short hash of the audio chunk so the talking-head cache invalidates when
    the spoken audio changes (e.g. after re-narration / a re-rolled sentence),
    instead of reusing a clip whose lip-sync no longer matches."""
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:8]


def gen_talking_head(scene, chunk_path, image_path, avatar_dir, resolution, slug):
    out_name = f"reel_{slug}_{scene['id']}_{_audio_fingerprint(chunk_path)}"
    cached = avatar_dir / "generated-videos" / f"{out_name}.mp4"
    if cached.exists():
        print(f"  [cache] talking-head {scene['id']} -> {cached.name}", file=sys.stderr)
        return cached
    cmd = [sys.executable, str(C.TALKING_VIDEO_SCRIPT),
           "--audio", str(chunk_path),
           "--image", str(image_path),
           "--avatar-dir", str(avatar_dir),
           "--resolution", resolution,
           "--out-name", out_name]
    if scene.get("video_prompt"):
        cmd += ["--video-prompt", scene["video_prompt"]]
    if scene.get("negative_prompt"):
        cmd += ["--negative-prompt", scene["negative_prompt"]]
    res = C.run_cli_json(cmd, desc=f"talking-head {scene['id']}")
    if not res or not res.get("video"):
        raise RuntimeError(f"avatar-talking-video returned no video for {scene['id']}")
    return Path(res["video"])


def use_existing_broll(scene, chunk_dur, avatar_dir, base_dir, slug):
    """Use a pre-existing B-roll clip (e.g. found real footage from broll-finder)
    instead of generating synthetic B-roll.

    Resolves ``scene['broll_clip']`` (absolute, or relative to base_dir / the
    avatar folder / CWD). Because silent B-roll has nothing to sync to and we
    never freeze-pad, a found clip shorter than its slot is LOOPED to fully cover
    the scene; normalize_scene then trims it back to the exact slot length.
    """
    raw = scene.get("broll_clip")
    if not raw:
        raise SystemExit(f"Scene {scene['id']}: broll_source 'existing' needs 'broll_clip'.")
    clip = Path(raw).expanduser()
    cands = [clip] if clip.is_absolute() else [base_dir / clip, avatar_dir / clip, Path.cwd() / clip]
    found = next((c for c in cands if c.exists()), None)
    if not found:
        raise SystemExit(f"Scene {scene['id']}: broll_clip not found (looked in "
                         f"{', '.join(str(c) for c in cands)}).")
    cdur = C.ffprobe_duration(found)
    if cdur + 0.04 >= chunk_dur:
        print(f"  [existing] broll {scene['id']} -> {found.name} "
              f"({cdur:.2f}s ≥ {chunk_dur:.2f}s slot)", file=sys.stderr)
        return found
    looped = avatar_dir / "broll" / "found" / f"reel_{slug}_{scene['id']}_loop.mp4"
    looped.parent.mkdir(parents=True, exist_ok=True)
    ok = C.run_ffmpeg(
        ["-stream_loop", "-1", "-i", str(found), "-t", f"{chunk_dur + 0.1:.3f}",
         "-an", "-c:v", "libx264", "-crf", "20", "-preset", "medium",
         "-pix_fmt", "yuv420p", str(looped)],
        description=f"Loop existing broll {scene['id']} to cover {chunk_dur:.2f}s slot")
    if not ok or not looped.exists():
        print(f"  Warning: could not loop {found.name}; using as-is (may fall short).",
              file=sys.stderr)
        return found
    return looped


def _find_clip(clip, avatar_dir: Path, base_dir: Path) -> Path | None:
    """Locate a clip path given as absolute / base-dir / avatar / repo-root relative."""
    if not clip:
        return None
    p = Path(str(clip)).expanduser()
    candidates = [p] if p.is_absolute() else [base_dir / p, avatar_dir / p, avatar_dir.parent / p]
    return next((c for c in candidates if c.exists()), None)


def resolve_guest_clip(scene, avatar_dir, base_dir):
    """A 'guest' scene is a pre-made talking clip from a DIFFERENT avatar that keeps
    its OWN voice (already woven into the master narration by assemble_narration.py).

    Unlike existing-broll, it is NEVER looped or freeze-padded: the clip is used
    exactly as-is and its boundary is pinned to its real duration, so the next scene
    starts the instant the guest stops talking (no hold, no stutter, no drift)."""
    src = _find_clip(scene.get("broll_clip"), avatar_dir, base_dir)
    if src is None:
        raise SystemExit(f"Scene {scene['id']}: guest broll_clip not found: "
                         f"{scene.get('broll_clip')}")
    print(f"  [guest] {scene['id']} -> {src.name} "
          f"({C.ffprobe_duration(src):.2f}s, used as-is — no pad/loop)", file=sys.stderr)
    return src


def gen_broll(scene, chunk_dur, avatar_dir, resolution, slug, aspect="9:16"):
    out_name = f"reel_{slug}_{scene['id']}"
    cached = avatar_dir / "broll" / f"{out_name}.mp4"
    duration = max(1, min(20, C.ceil_int(chunk_dur)))
    if cached.exists():
        cdur = C.ffprobe_duration(cached)
        # Reuse only if the cached clip fully COVERS its slot (we trim, never
        # expand/freeze a silent B-roll). Regenerate if it falls short — e.g.
        # after re-narration lengthened the scene.
        if cdur + 0.04 >= chunk_dur:
            print(f"  [cache] broll {scene['id']} -> {cached.name} "
                  f"({cdur:.2f}s ≥ {chunk_dur:.2f}s slot)", file=sys.stderr)
            return cached
        print(f"  broll {scene['id']} cached clip too short "
              f"({cdur:.2f}s < {chunk_dur:.2f}s slot); regenerating at {duration}s.",
              file=sys.stderr)
    cmd = [sys.executable, str(C.BROLL_SCRIPT),
           scene.get("broll_description", scene.get("text", "")),
           "--duration", str(duration),
           "--aspect-ratio", aspect,
           "--resolution", resolution,
           "--fps", str(BROLL_FPS),
           "--avatar-dir", str(avatar_dir),
           "--out-name", out_name]
    if scene.get("broll_camera"):
        cmd += ["--camera", scene["broll_camera"]]
    if scene.get("broll_action"):
        cmd += ["--action", scene["broll_action"]]
    res = C.run_cli_json(cmd, desc=f"broll {scene['id']} ({duration}s)")
    if not res or not res.get("video"):
        raise RuntimeError(f"broll-generator returned no video for {scene['id']}")
    return Path(res["video"])


# ---------------------------------------------------------------------------
# Normalization + assembly
# ---------------------------------------------------------------------------
def _conform_to_frames(path: Path, n_frames: int, fps: int, W: int, H: int) -> None:
    """Force ``path`` to EXACTLY ``n_frames`` frames (CFR ``fps``).

    A clip shorter than its slot is padded by CLONING its last frame (tpad); a
    longer one is trimmed. This is what keeps the picture frame-locked to the
    continuously-laid narration: talking-head takes from p-video can come back a
    few frames short of their audio chunk, and slot durations rarely land on an
    exact frame — left unconformed, those per-scene shortfalls ACCUMULATE and
    push the picture ahead of the voice (the drift that reads as lip-sync
    slipping, worst near the end). Cloning <=~0.1s of a tail frame is
    imperceptible and holds every later scene in sync."""
    n_frames = max(1, int(n_frames))
    tmp = path.with_name(path.stem + ".fix.mp4")
    ok = C.run_ffmpeg(
        ["-i", str(path),
         # tpad appends cloned copies of the last frame (generous 2s) so a short
         # clip can reach n_frames; -frames:v then caps to EXACTLY n_frames
         # (also trimming a clip that runs long).
         "-vf", f"tpad=stop_mode=clone:stop_duration=2,fps={fps},"
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1",
         "-frames:v", str(n_frames), "-an", "-r", str(fps),
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         str(tmp)],
        description=f"Conform {path.stem} to {n_frames}f ({n_frames/fps:.3f}s)",
    )
    if ok and tmp.exists():
        tmp.replace(path)
    else:
        tmp.unlink(missing_ok=True)
        print(f"  Warning: could not conform {path.name} to {n_frames} frames; "
              "leaving as-is (may drift).", file=sys.stderr)


def normalize_scene(src, out, W, H, target_dur, motion, intensity, fps, vp,
                    *, target_frames=None):
    """Scale/crop to WxH, apply Ken Burns, strip audio, and conform to an EXACT
    frame count so the clip fully covers (and never overruns) its audio slot.

    ``target_frames`` (from the frame-aligned scene grid) pins the output length
    to the frame; when omitted it falls back to ``round(target_dur*fps)``. Short
    clips are padded by cloning the last frame (see ``_conform_to_frames``) rather
    than left short — the invariant the assembly relies on is clip_len == slot_len
    for every scene, so re-laying the whole narration stays in lip-sync."""
    if target_frames is None:
        target_frames = max(1, int(round(target_dur * fps)))
    base = out.with_name(out.stem + ".base.mp4")
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},setsar=1")
    ok = C.run_ffmpeg(
        ["-i", str(src), "-vf", vf, "-an", "-t", f"{target_dur + 0.5:.3f}", "-r", str(fps),
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         str(base)],
        description=f"Normalize base {out.stem} ({target_dur:.2f}s)",
    )
    if not ok:
        raise RuntimeError(f"Failed to normalize base clip for {out.name}")

    if motion in (None, "none"):
        base.replace(out)
    else:
        applied = vp.apply_camera_motion(str(base), str(out), W, H, motion,
                                         intensity=intensity, fps=fps)
        if not applied or not out.exists():
            print(f"  Warning: motion '{motion}' failed for {out.name}; using static base.",
                  file=sys.stderr)
            base.replace(out)
        else:
            base.unlink(missing_ok=True)
    _conform_to_frames(out, target_frames, fps, W, H)
    return out


def concat_video_only(clips, out, W, H, fps):
    """Filter-based video-only concat (robust to per-clip encoder differences)."""
    if not clips:
        return False
    if len(clips) == 1:
        return C.run_ffmpeg(
            ["-i", str(clips[0]), "-an",
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H},setsar=1,fps={fps}",
             "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
             str(out)],
            description="Single-clip video track",
        )
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    parts = "".join(
        f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1,fps={fps}[v{i}];"
        for i in range(len(clips))
    )
    concat = "".join(f"[v{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[v]"
    return C.run_ffmpeg(
        inputs + ["-filter_complex", parts + concat, "-map", "[v]", "-an",
                  "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                  "-pix_fmt", "yuv420p", "-r", str(fps), str(out)],
        description=f"Concat {len(clips)} scene clips (hard cuts)",
    )


def mux_narration(video_track, narration, out):
    return C.run_ffmpeg(
        ["-i", str(video_track), "-i", str(narration),
         "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
         "-shortest", str(out)],
        description="Mux narration as master track",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Compose a finished reel (9:16, 1:1 or 16:9) from a storyboard + an existing avatar.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("storyboard", type=Path, help="Path to storyboard.json")
    ap.add_argument("--base-dir", type=Path, default=None,
                    help="Base for resolving relative paths (default: CWD)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Reel output folder (default: <avatar>/reels/<NNN>_<slug>)")
    ap.add_argument("--whisper-model", default="small", help="faster-whisper model size")
    ap.add_argument("--language", default=None, help="Language hint for alignment (e.g. es)")
    ap.add_argument("--force-narrate", action="store_true",
                    help="Re-narrate even if narration.mp3 exists (reuses unchanged "
                         "per-sentence takes from cache)")
    ap.add_argument("--reroll", type=int, nargs="+", default=None, metavar="N",
                    help="Re-roll a fresh take of these 1-based sentence indices "
                         "(e.g. a mispronounced segment); rest reused from cache. "
                         "Talking-heads whose audio changed are regenerated automatically.")
    ap.add_argument("--regen", action="store_true",
                    help="Regenerate scene clips even if a cached clip exists")
    ap.add_argument("--dry-run", action="store_true",
                    help="Narrate + align + compute boundaries + slice, then stop "
                         "(no video generation; cheap alignment check)")
    ap.add_argument("--finish", action="store_true",
                    help="Run the finishing pass (burned-in subtitles + ducked music) "
                         "after assembly. Also enabled by a storyboard 'finish' block.")
    ap.add_argument("--no-music", dest="music", action="store_false",
                    help="With --finish: skip the music bed")
    ap.add_argument("--no-subtitles", dest="subtitles", action="store_false",
                    help="With --finish: skip burned-in captions")
    ap.add_argument("--music-mood", default=None,
                    help="With --finish: bg-music-hq mood preset")
    args = ap.parse_args()

    base_dir = (args.base_dir or Path.cwd()).expanduser().resolve()
    sb = C.load_json(args.storyboard)

    avatar_dir = resolve_path(sb["avatar_dir"], base_dir)
    if not avatar_dir.is_dir():
        ap.error(f"Avatar folder not found: {avatar_dir}")

    scenes = sb.get("scenes", [])
    if not scenes:
        ap.error("Storyboard has no scenes.")
    # Optional LOCATION (a look for the avatar): reel default + per-scene override.
    # "default"/unset == the avatar's top-level scene.json/angles (today's behavior).
    reel_location = sb.get("location")
    used_locs = {scene_location(s, reel_location) for s in scenes} - {"default"}
    for loc in sorted(used_locs):
        if not (avatar_dir / "locations" / loc / "angles").is_dir():
            print(f"  ! storyboard references location '{loc}' but "
                  f"{avatar_dir / 'locations' / loc / 'angles'} is missing; "
                  f"scenes will fall back to the default look. "
                  f"(create it: avatar-location/create_location.py {avatar_dir.name} {loc})",
                  file=sys.stderr)
    if reel_location and reel_location != "default":
        print(f"  Reel location (default look): {reel_location}", file=sys.stderr)
    for i, s in enumerate(scenes):
        s.setdefault("id", f"s{i+1}")
        if s.get("type") not in ("talking_head", "broll", "guest"):
            ap.error(f"Scene {s['id']}: type must be talking_head, broll or guest.")
        if s.get("type") == "broll" and s.get("broll_source") == "existing" \
                and not s.get("broll_clip"):
            ap.error(f"Scene {s['id']}: broll_source 'existing' requires 'broll_clip' "
                     "(path to a found-footage clip, e.g. from broll-finder).")
        if s.get("type") == "guest" and not s.get("broll_clip"):
            ap.error(f"Scene {s['id']}: type 'guest' requires 'broll_clip' "
                     f"(a pre-made talking clip with its OWN voice; build it + the "
                     f"master narration with assemble_narration.py).")

    script = sb.get("script") or " ".join(s.get("text", "") for s in scenes)
    script = script.strip()
    if not script:
        ap.error("Storyboard has no script / scene texts.")

    vp, vc = C.get_video_pipeline()
    preset = vc.get_format_preset(sb.get("format", "reel"))
    W, H = preset["width"], preset["height"]
    fps = int(sb.get("fps", 30))
    resolution = sb.get("resolution", "720p")
    slug = sb.get("slug") or C.slugify(script[:40])

    # Reel output folder.
    if args.out_dir:
        reel_dir = args.out_dir.expanduser().resolve()
    else:
        reels_root = avatar_dir / "reels"
        idx = C.next_reel_index(reels_root)
        reel_dir = reels_root / f"{idx:03d}_{slug}"
    scenes_dir = reel_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nReel folder: {reel_dir}", file=sys.stderr)

    # --- Stage 1: narrate + align ---
    voice = sb.get("voice", {}) or {}
    narr = narrate_mod.narrate(
        script, avatar_dir, reel_dir, slug=slug,
        whisper_model=args.whisper_model, language=args.language,
        force=args.force_narrate,
        sentence_gap=float(voice.get("sentence_gap", narrate_mod.DEFAULT_SENTENCE_GAP)),
        sentences_per_call=int(voice.get("sentences_per_call", 1)),
        max_chars=int(voice.get("tts_max_chars", narrate_mod.DEFAULT_MAX_CHARS)),
        reroll=args.reroll,
        engine=voice.get("engine", "minimax"),
        voice_name=voice.get("name"), voice_id=voice.get("voice_id"),
        source=voice.get("source"), emotion=voice.get("emotion", "auto"),
        language_boost=voice.get("language_boost", "None"),
        speed=float(voice.get("speed", 1.0)), volume=float(voice.get("volume", 1.0)),
        pitch=int(voice.get("pitch", 0)),
        el_stability=float(voice.get("el_stability", 0.5)),
        el_similarity=float(voice.get("el_similarity", 0.75)),
        el_style=float(voice.get("el_style", 0.0)),
        el_model=voice.get("el_model", "eleven_multilingual_v2"),
    )
    narration_path = Path(narr["narration"])
    align = C.load_json(narr["align"])
    total_dur = float(narr["duration"] or align.get("duration") or 0.0)
    if total_dur <= 0:
        total_dur = C.ffprobe_duration(narration_path)
    print(f"  Narration duration: {total_dur:.2f}s", file=sys.stderr)

    # --- Alignment -> boundaries -> slice ---
    bounds = compute_boundaries(scenes, align, total_dur)
    # Guest scenes carry their OWN voice in a pre-made clip. Pin their boundaries
    # (overriding the silence-midpoint snap) so the next scene starts the instant
    # the guest stops — no freeze pad, no loop, and no downstream drift. Works at
    # ANY position (hook, middle or end), not just the opening scene.
    #   * If assemble_narration recorded this clip's exact [start,end] in the master
    #     narration (assemble_narration.out.json), pin BOTH in + out to those offsets
    #     → frame-exact even for a mid-reel guest.
    #   * Otherwise fall back to pinning the OUT point to start + clip duration.
    guest_offsets = {}
    off_file = reel_dir / "assemble_narration.out.json"
    if off_file.exists():
        try:
            for seg in C.load_json(off_file).get("segments", []):
                clip = seg.get("clip")
                if clip and seg.get("start") is not None and seg.get("end") is not None:
                    found = _find_clip(clip, avatar_dir, base_dir) or Path(clip)
                    guest_offsets[str(found.resolve())] = (float(seg["start"]), float(seg["end"]))
        except Exception as exc:
            print(f"  Warning: could not read {off_file.name}: {exc}", file=sys.stderr)
    # When the master narration was assembled by assemble_narration.py with a 1:1
    # scene<->segment correspondence, its recorded segment offsets ARE the exact
    # audio boundaries. Pin EVERY scene to them so the VIDEO tiles the timeline
    # identically to the AUDIO. (compute_boundaries' word-snap is only approximate;
    # for a multi-segment narration it drifts the picture against the dialogue,
    # which shows up as the spoken segments slipping out of lip-sync.) Requires the
    # plan to use gap=0 so each scene's clip == its audio segment exactly.
    seg_starts = None
    assembled_gap = 0.0
    if off_file.exists():
        try:
            _adata = C.load_json(off_file)
            _segs = _adata.get("segments", [])
            assembled_gap = float(_adata.get("gap", 0.0) or 0.0)
            if len(_segs) == len(scenes) and all(s.get("start") is not None for s in _segs):
                seg_starts = [float(s["start"]) for s in _segs]
        except Exception:
            seg_starts = None
    if seg_starts is not None:
        if assembled_gap > 0 and any(s.get("type") == "guest" for s in scenes):
            print(f"  Warning: narration was assembled with gap={assembled_gap:.2f}s. Guest clips "
                  "carry no trailing pad, so each will fall short by that gap and the picture will "
                  "drift ahead of the audio. Re-assemble the plan with gap=0 for frame-exact "
                  "guest lip-sync.", file=sys.stderr)
        for i, st0 in enumerate(seg_starts):
            bounds[i] = st0
        bounds[len(scenes)] = total_dur
        for i in range(1, len(bounds)):
            if bounds[i] <= bounds[i - 1]:
                bounds[i] = min(bounds[i - 1] + MIN_SCENE_GAP, total_dur)
        print("  Boundaries pinned to assemble_narration offsets "
              "(exact A/V tiling; word-snap bypassed).", file=sys.stderr)
    else:
        for i, s in enumerate(scenes):
            if s.get("type") != "guest":
                continue
            gsrc = _find_clip(s.get("broll_clip"), avatar_dir, base_dir)
            if gsrc is None:
                print(f"  Warning: guest {s['id']} clip not found yet; using aligned boundary.",
                      file=sys.stderr)
                continue
            hi = (bounds[i + 2] - MIN_SCENE_GAP) if (i + 2) < len(bounds) else total_dur
            off = guest_offsets.get(str(gsrc.resolve()))
            if off:
                gst, gen = off
                gst = 0.0 if i == 0 else max(gst, bounds[i - 1] + MIN_SCENE_GAP)
                gen = max(gst + MIN_SCENE_GAP, min(gen, hi))
                gst = min(gst, gen - MIN_SCENE_GAP)
                bounds[i] = gst
                bounds[i + 1] = gen
            else:
                cdur = C.ffprobe_duration(gsrc)
                bounds[i + 1] = max(bounds[i] + MIN_SCENE_GAP, min(bounds[i] + cdur, hi))
    # Frame-aligned assembly grid: pin every scene boundary to an integer frame so
    # each clip is an exact number of frames and scene i occupies frames
    # [grid[i], grid[i+1]). Because these positions are ABSOLUTE (not a cumulative
    # sum of per-scene rounding), the picture tracks the audio within <=0.5 frame
    # with NO accumulation — this is what kills the slow lip-sync drift. Audio
    # chunks are still sliced at the real (sub-frame) bounds below, so the
    # talking-head cache (keyed by chunk audio) is untouched.
    frame_grid = [int(round(b * fps)) for b in bounds]
    for i in range(1, len(frame_grid)):
        if frame_grid[i] <= frame_grid[i - 1]:
            frame_grid[i] = frame_grid[i - 1] + 1
    print("  Scene boundaries (s):", file=sys.stderr)
    for i, s in enumerate(scenes):
        st, en = bounds[i], bounds[i + 1]
        print(f"    {s['id']:>4} [{s['type']:>12}] {st:6.2f} -> {en:6.2f}  ({en-st:4.2f}s)  "
              f"{s.get('text','')[:54]}", file=sys.stderr)

    ref_analysis = sb.get("reference_analysis")
    ref_path = resolve_path(ref_analysis, base_dir) if ref_analysis else None
    pacing_report(scenes, bounds, total_dur, ref_path)
    camera_report(ref_path)

    scene_records = []
    for i, s in enumerate(scenes):
        st, en = bounds[i], bounds[i + 1]
        chunk = scenes_dir / f"chunk_{s['id']}.mp3"
        C.slice_audio(narration_path, st, en, chunk)
        rec = {"id": s["id"], "type": s["type"], "text": s.get("text", ""),
               "start": round(st, 3), "end": round(en, 3),
               "duration": round(en - st, 3), "chunk": str(chunk)}
        # Resolve the talking-head angle now (a cheap glob, no spend) so a dry-run
        # confirms the avatar + LOCATION look before any paid generation.
        if s["type"] == "talking_head":
            loc = scene_location(s, reel_location)
            rec["location"] = loc
            img = resolve_image(s, avatar_dir, base_dir, reel_location, aspect=preset["aspect"])
            rec["image"] = str(img) if img else None
            tag = "" if loc == "default" else f" @ {loc}"
            if img:
                print(f"    {s['id']:>4} angle -> {img.name}{tag}", file=sys.stderr)
            else:
                print(f"    {s['id']:>4} ! NO angle image resolved{tag} "
                      f"(angle={s.get('angle')!r}, image={s.get('image')!r})", file=sys.stderr)
        scene_records.append(rec)

    if args.dry_run:
        C.save_json(reel_dir / "boundaries.json",
                    {"total_duration": total_dur, "scenes": scene_records})
        print("\n[dry-run] Narration, alignment, boundaries and audio chunks ready.", file=sys.stderr)
        print(json.dumps({"reel_dir": str(reel_dir), "narration": str(narration_path),
                          "scenes": scene_records, "dry_run": True}, ensure_ascii=False))
        return

    # --- Per-scene generation + normalization ---
    norm_clips = []
    for i, (rec, s) in enumerate(zip(scene_records, scenes)):
        sid = s["id"]
        target_dur = rec["duration"]
        target_frames = frame_grid[i + 1] - frame_grid[i]
        chunk = Path(rec["chunk"])
        norm_path = scenes_dir / f"{sid}.norm.mp4"

        if s["type"] == "talking_head":
            image_path = resolve_image(s, avatar_dir, base_dir, reel_location, aspect=preset["aspect"])
            if not image_path or not image_path.exists():
                raise SystemExit(f"Scene {sid}: talking-head image not found "
                                 f"(set 'image' to a valid angle PNG, or check the "
                                 f"location '{scene_location(s, reel_location)}'). Got: {image_path}")
            if args.regen:
                (avatar_dir / "generated-videos" / f"reel_{slug}_{sid}.mp4").unlink(missing_ok=True)
            raw = gen_talking_head(s, chunk, image_path, avatar_dir, resolution, slug)
            rec["image"] = str(image_path)
            rec["location"] = scene_location(s, reel_location)
        elif s["type"] == "guest":
            raw = resolve_guest_clip(s, avatar_dir, base_dir)
            rec["broll_clip"] = str(raw)
            rec["guest"] = True
        else:
            if s.get("broll_source") == "existing" or s.get("broll_clip"):
                raw = use_existing_broll(s, target_dur, avatar_dir, base_dir, slug)
                rec["broll_source"] = "existing"
                rec["broll_clip"] = s.get("broll_clip")
            else:
                if args.regen:
                    (avatar_dir / "broll" / f"reel_{slug}_{sid}.mp4").unlink(missing_ok=True)
                raw = gen_broll(s, target_dur, avatar_dir, resolution, slug, aspect=preset["aspect"])
            rec["broll_description"] = s.get("broll_description")
            rec["broll_camera"] = s.get("broll_camera")
            rec["broll_action"] = s.get("broll_action")

        motion, intensity = resolve_motion(s)
        rec["raw_clip"] = str(raw)
        rec["motion"] = motion
        rec["intensity"] = intensity
        rec["emphasis"] = bool(s.get("emphasis"))

        normalize_scene(raw, norm_path, W, H, target_dur, motion, intensity, fps, vp,
                        target_frames=target_frames)
        rec["norm_clip"] = str(norm_path)
        rec["norm_duration"] = round(C.ffprobe_duration(norm_path), 3)
        rec["target_frames"] = target_frames
        norm_clips.append(norm_path)

    # --- Assemble: hard-cut concat -> mux narration ---
    video_track = reel_dir / "video_track.mp4"
    if not concat_video_only(norm_clips, video_track, W, H, fps):
        raise SystemExit("Failed to assemble the video track.")
    final_path = reel_dir / "final.mp4"
    if not mux_narration(video_track, narration_path, final_path):
        raise SystemExit("Failed to mux narration onto the video track.")

    final_info = vc.ffprobe_video(final_path)

    # --- Manifest ---
    manifest = {
        "version": 1,
        "created_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "avatar_dir": str(avatar_dir),
        "reel_dir": str(reel_dir),
        "slug": slug,
        "script": script,
        "reference_analysis": sb.get("reference_analysis"),
        "format": sb.get("format", "reel"),
        "width": W, "height": H, "fps": fps,
        "resolution": resolution,
        "voice": voice,
        "models": {
            "tts": "minimax/speech-2.8-hd (via voice-clone)",
            "talking_head": "prunaai/p-video-avatar (via avatar-talking-video)",
            "broll": "prunaai/p-video (via broll-generator)",
            "alignment": f"faster-whisper {args.whisper_model}",
        },
        "narration": str(narration_path),
        "align": narr["align"],
        "narration_duration": round(total_dur, 3),
        "video_track": str(video_track),
        "final": str(final_path),
        "final_info": final_info,
        "scenes": scene_records,
    }
    C.save_json(reel_dir / "storyboard.json", sb)
    C.save_json(reel_dir / "reel_manifest.json", manifest)

    # --- Optional finishing pass: subtitles + ducked music ---
    fin = sb.get("finish") or {}
    if args.finish or fin.get("enabled"):
        import finish_reel  # noqa: E402  (lazy: pulls in Pillow only when finishing)
        do_music = args.music and fin.get("music", True)
        do_subs = args.subtitles and fin.get("subtitles", True)
        print("\n  Finishing pass (subtitles + music)...", file=sys.stderr)
        style_profile = None
        if fin.get("style_from"):
            style_profile = finish_reel.load_style_profile(
                resolve_path(fin["style_from"], base_dir))
        mfc = fin.get("music_from_cutsheet")
        finish_reel.finish(
            reel_dir, subtitles=do_subs, music=do_music,
            music_mood=args.music_mood or fin.get("music_mood", finish_reel.DEFAULT_MUSIC_MOOD),
            music_prompt=fin.get("music_prompt", finish_reel.DEFAULT_MUSIC_PROMPT),
            music_volume=float(fin.get("music_volume", 0.12)),
            music_vocals=fin.get("music_vocals", "wordless"),
            music_structure=fin.get("music_structure", "flat"),
            music_plan=fin.get("music_plan"),
            music_from_cutsheet=resolve_path(mfc, base_dir) if mfc else None,
            max_words=int(fin.get("max_words", 6)),
            emphasis=bool(fin.get("emphasis", True)),
            casing=fin.get("casing", "subtitle"),
            caption_reveal=fin.get("caption_reveal", "word"),
            fontsize=fin.get("fontsize"),
            y_frac=fin.get("y_frac"),
            regular_font=fin.get("regular_font"),
            emph_font=fin.get("emph_font"),
            style_profile=style_profile,
            regen_music=bool(fin.get("regen_music", False)),
            master_lufs=fin.get("master_lufs", finish_reel.MASTER_LUFS),
            manifest=manifest,
        )
        manifest = C.load_json(reel_dir / "reel_manifest.json")
        final_info = manifest.get("final_info", final_info)

        # Optional polish pass (stage 4): zoom-punch transitions + soft SFX
        # applied OVER the finished video; keeps final-without-sfx.mp4.
        fx = fin.get("fx") or {}
        if fx.get("enabled"):
            import polish_reel  # noqa: E402
            print("\n  Polish pass (transitions + sfx)...", file=sys.stderr)
            guide = fx.get("guide")
            sfrom = fx.get("style_from")
            polish_reel.polish(
                reel_dir,
                # None = defer to the avatar's measured transition_style.json
                transition_style=fx.get("transition_style"),
                sfx=bool(fx.get("sfx", True)),
                sfx_volume=float(fx.get("sfx_volume", polish_reel.DEFAULT_SFX_VOLUME)),
                flash_dur=fx.get("flash_dur"),
                flash_gain=fx.get("flash_gain"),
                punch_scale=float(fx.get("punch_scale", polish_reel.DEFAULT_PUNCH_SCALE)),
                punch_dur=float(fx.get("punch_dur", polish_reel.DEFAULT_PUNCH_DUR)),
                density_s=fx.get("density"),
                guide=resolve_path(guide, base_dir) if guide else None,
                style_from=resolve_path(sfrom, base_dir) if sfrom else None,
                regen_sfx=bool(fx.get("regen_sfx", False)),
            )
            manifest = C.load_json(reel_dir / "reel_manifest.json")
            final_info = manifest.get("final_info", final_info)

    print(f"\nDone — reel: {final_path}", file=sys.stderr)
    print(f"  {final_info.get('width')}x{final_info.get('height')} @ "
          f"{final_info.get('fps')}fps  |  {final_info.get('duration'):.2f}s  |  "
          f"{len(scenes)} scenes", file=sys.stderr)
    print(f"  Manifest: {reel_dir / 'reel_manifest.json'}", file=sys.stderr)
    print(json.dumps({
        "final": str(final_path),
        "reel_dir": str(reel_dir),
        "duration": final_info.get("duration"),
        "scenes": len(scenes),
        "manifest": str(reel_dir / "reel_manifest.json"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
