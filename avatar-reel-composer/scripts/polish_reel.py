#!/usr/bin/env python3
"""Stage 4 — POLISH pass: scene-cut transition effects + short-soft SFX.

Runs ON TOP of the finished reel (final.mp4 = captions + music already burned
in), so nothing in the per-segment pipeline is touched. The pre-polish video is
preserved as ``final-without-sfx.mp4`` and the polished one replaces
``final.mp4``.

WHY this design (guided by the analyzed original reels):
  * The originals' scene transitions are hard cuts dressed with a **golden
    flash**: right at the cut the incoming frame is washed in a warm
    amber/gold (brights go yellow-white, shadows orange) that decays back to
    normal in ~0.3s (verified frame-by-frame on the reference reel's B-roll
    cuts). We reproduce exactly that with a per-frame ``eq`` envelope —
    brightness lift + warm gamma (R/G up, B down) + saturation, gated by a
    gaussian centered on the cut. It's DURATION-PRESERVING (no frames added or
    removed), so the continuous narration + captions stay in sync; a real
    crossfade is never an option — it would OVERLAP clips and shorten the
    video. ``--transition-style punch`` (a small zoom in-and-back pulse) and
    ``none`` are available for content where the golden flash doesn't fit.
  * SFX fingerprint measured on the reference reel (voice-isolate
    ``sfx_intervals`` x scene boundaries of the video-scene-analysis):
    ~1 event per ~15s, each 0.3-0.7s, mixed VERY soft (non-speech RMS is
    ~15-20% of the speech RMS), placed either (a) leading a cut into/out of
    B-roll by ~0.35s (whoosh) or (b) mid-scene under an emphasized phrase
    (soft low boom). We reproduce exactly those two placements, capped to the
    same sparse density.

SFX assets are generated once with Stable Audio 2.5 (same model as the
sound-effects skill) and cached avatar-wide in ``<avatar>/reels/_sfx_cache/``.

Usage:
    python3 polish_reel.py <reel_dir> [--no-transitions] [--no-sfx]
                           [--sfx-volume 0.18] [--punch-scale 0.05]
                           [--density 15] [--guide voice.json] [--regen-sfx]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _arc_common as C  # noqa: E402

SFX_MODEL = "stability-ai/stable-audio-2.5"

# Soft "minidrama" assets — deliberately understated (the originals' SFX sit
# far under the voice; anything punchy would read as cheap).
SFX_LIBRARY = {
    "whoosh": {
        "prompt": ("soft airy cinematic whoosh, gentle breathy swoosh transition, "
                   "smooth and subtle, quiet, no impact, no bass drop, "
                   "professional film transition sound"),
        "duration": 2,
    },
    "boom": {
        "prompt": ("soft muffled deep boom, distant low cinematic thump, gentle "
                   "warm sub impact, very quiet and subtle, emotional emphasis, "
                   "no harshness"),
        "duration": 2,
    },
}

# Fingerprint defaults measured on the analyzed reference reel.
DEFAULT_DENSITY_S = 15.0   # ~one SFX event per this many seconds
DEFAULT_LEAD_S = 0.35      # whoosh starts this long BEFORE the cut it announces
DEFAULT_SFX_VOLUME = 0.18  # ≈ the originals' non-speech/speech RMS ratio
DEFAULT_PUNCH_SCALE = 0.05  # zoom punch peak (5% in-and-back) — 'punch' style
DEFAULT_PUNCH_DUR = 0.30   # zoom punch length in seconds — 'punch' style
DEFAULT_FLASH_DUR = 0.36   # golden flash: rise+fall time on the incoming scene
DEFAULT_FLASH_GAIN = 1.0   # golden flash strength multiplier (1.0 = as measured)
MIN_GAP_S = 8.0            # never place two SFX closer than this
TRANSITION_STYLES = ("golden_flash", "white_flash", "dip_black", "punch", "none")

# Per-style eq recipes (strength s in 0..gain): the golden one is calibrated
# against the reference avatar's measured wash; white is a neutral lift;
# dip_black is a brightness drop.
FLASH_RECIPES = {
    "golden_flash": lambda s: (
        f"brightness={0.28 * s:.3f}:saturation={1 + 0.45 * s:.3f}:"
        f"gamma_r={1 + 0.55 * s:.3f}:gamma_g={1 + 0.28 * s:.3f}:"
        f"gamma_b={max(0.1, 1 - 0.32 * s):.3f}"),
    "white_flash": lambda s: (
        f"brightness={0.38 * s:.3f}:saturation={max(0.1, 1 - 0.25 * s):.3f}"),
    "dip_black": lambda s: f"brightness={-0.55 * s:.3f}",
}


# ---------------------------------------------------------------------------
# FX plan
# ---------------------------------------------------------------------------

def guide_density(guide_path) -> float:
    """Derive events-per-second density from a voice-isolate ``voice.json``
    (its ``sfx_intervals`` are the measured SFX of an ORIGINAL reel)."""
    try:
        g = C.load_json(guide_path)
        ivs = g.get("sfx_intervals") or []
        dur = float(g.get("duration") or 0)
        if ivs and dur > 0:
            return max(8.0, min(30.0, dur / len(ivs)))
    except Exception as e:  # noqa: BLE001
        print(f"  Warning: could not read guide {guide_path} ({e}); "
              f"using default density.", file=sys.stderr)
    return DEFAULT_DENSITY_S


def build_fx_plan(manifest, storyboard, total_dur, *, density_s, transitions=False,
                  sfx=True, flash_at=("broll_entry",)):
    """Decide WHERE effects go, mirroring the originals' usage:

    * ``transition`` events at talking_head <-> broll boundaries: a whoosh
      leading the cut by ~0.35s; the visual flash lands only on the boundary
      types in ``flash_at`` (measured per avatar by profile_transitions.py —
      e.g. the reference flashes 100% of B-roll ENTRIES but never exits).
      Entering B-roll outranks leaving.
    * ``emphasis`` events at the start of storyboard scenes marked
      ``emphasis: true`` (the zoom-in thesis/payoff moments): soft boom only —
      the talking-head's own zoom motion already does the visual work.

    Density is capped like the reference (~1/15s) with a hard minimum gap, and
    priorities decide who survives: broll-entry > broll-exit > emphasis.
    """
    scenes = manifest.get("scenes") or []
    sb_emph = {s.get("id"): bool(s.get("emphasis")) for s in (storyboard.get("scenes") or [])}

    candidates = []
    for prev, cur in zip(scenes, scenes[1:]):
        t = float(cur["start"])
        if t <= 0.5 or t >= total_dur - 1.0:
            continue
        p_type, c_type = prev.get("type"), cur.get("type")
        if p_type != c_type:  # talking_head <-> broll boundary
            entering = c_type == "broll"
            boundary = "broll_entry" if entering else "broll_exit"
            candidates.append({
                "t": t, "kind": "transition", "sfx": "whoosh",
                "boundary": boundary,
                "punch": transitions and boundary in flash_at,
                "priority": 3 if entering else 2,
                "why": f"{'enter' if entering else 'leave'} broll at {cur['id']}",
            })
        elif sb_emph.get(cur.get("id")):
            candidates.append({
                "t": t, "kind": "emphasis", "sfx": "boom",
                "punch": False, "priority": 1,
                "why": f"emphasis scene {cur['id']}",
            })

    if not candidates:
        return []

    target = max(2, min(8, round(total_dur / density_s)))
    chosen = []
    for cand in sorted(candidates, key=lambda c: -c["priority"]):
        if len(chosen) >= target:
            break
        if all(abs(cand["t"] - c["t"]) >= MIN_GAP_S for c in chosen):
            chosen.append(cand)
    chosen.sort(key=lambda c: c["t"])

    if not transitions:
        for c in chosen:
            c["punch"] = False
    if not sfx:
        for c in chosen:
            c["sfx"] = None
    return chosen


# ---------------------------------------------------------------------------
# SFX assets (generated once, cached avatar-wide)
# ---------------------------------------------------------------------------

def _sfx_cache_dir(reel_dir):
    d = Path(reel_dir).parent / "_sfx_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_sfx_assets(reel_dir, names, *, token, regen=False):
    """Generate (or reuse) the soft SFX clips. Returns {name: path} for the ones
    that exist; a failed generation just drops that SFX (never blocks polish)."""
    cache = _sfx_cache_dir(reel_dir)
    out = {}
    for name in sorted(set(n for n in names if n)):
        spec = SFX_LIBRARY[name]
        key = hashlib.sha1(spec["prompt"].encode()).hexdigest()[:12]
        path = cache / f"{name}_{key}.mp3"
        if path.exists() and not regen:
            print(f"  [cache] sfx '{name}' -> {path.name}", file=sys.stderr)
            out[name] = path
            continue
        try:
            import finish_reel as F
            print(f"  >>> sfx '{name}' via {SFX_MODEL}...", file=sys.stderr)
            url = F._run_replicate_polling(
                SFX_MODEL,
                {"prompt": spec["prompt"], "duration": int(spec["duration"]),
                 "steps": 8, "cfg_scale": 3.5},
                token)
            if not url:
                raise RuntimeError("no output")
            tmp = path.with_suffix(".raw.mp3")
            import urllib.request
            urllib.request.urlretrieve(url, tmp)
            # Strip lead silence so the clip starts right where it's placed,
            # and normalize tail with a fade so it never clicks.
            ok = C.run_ffmpeg(
                ["-i", str(tmp), "-af",
                 "silenceremove=start_periods=1:start_threshold=-45dB,"
                 "afade=t=out:st=1.4:d=0.5",
                 "-c:a", "libmp3lame", "-q:a", "2", str(path)],
                description=f"trim sfx '{name}'", quiet=True)
            tmp.unlink(missing_ok=True)
            if not ok or not path.exists():
                raise RuntimeError("post-process failed")
            out[name] = path
            print(f"  cached sfx '{name}' -> {cache.name}/{path.name}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  Warning: sfx '{name}' unavailable ({e}); skipping it.",
                  file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Apply (single ffmpeg pass over the finished video)
# ---------------------------------------------------------------------------

def _flash_vf(cuts, *, style, dur, gain):
    """Color-envelope transition on each cut — e.g. the golden flash measured
    on the reference reels (the wash rises right after the cut on the INCOMING
    frame, peaks ~40% in, fully back to normal by ~0.4s).

    ``eq`` does NOT re-evaluate ``t`` expressions per frame (init-only), but it
    DOES support timeline ``enable``; so the pulse is rendered as a few short
    constant-strength slices (a stepped sine), which at 30fps is
    indistinguishable from a smooth ramp.
    """
    recipe = FLASH_RECIPES[style]
    n = 6
    step = dur / n
    parts = []
    for t in cuts:
        for k in range(n):
            s = gain * math.sin(math.pi * (k + 0.5) / n)
            t0, t1 = t + k * step, t + (k + 1) * step
            parts.append(f"eq={recipe(s)}:enable='between(t,{t0:.3f},{t1:.3f})'")
    return ",".join(parts)


def _punch_vf(cuts, *, W, H, fps, scale, dur):
    """Small zoom in-and-back pulse per cut via a single ``zoompan`` (per-frame
    ``in_time`` expression; ``crop`` has no timeline/per-frame w/h support)."""
    pulses = [f"between(in_time,{t:.3f},{t + dur:.3f})"
              f"*sin(PI*(in_time-{t:.3f})/{dur:.3f})" for t in cuts]
    z = f"1+{scale:.4f}*({'+'.join(pulses)})"
    return (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={W}x{H}:fps={fps}")


def apply_fx(src, dst, plan, sfx_files, *, W, H, fps, total_dur, sfx_volume,
             transition_style, punch_scale, punch_dur, flash_dur, flash_gain):
    """One encode: the chosen duration-preserving transition effect at the cuts
    + the SFX overlay mixed at a fixed soft level under the existing audio."""
    cuts = [max(0.0, ev["t"] - 0.02) for ev in plan if ev.get("punch")]
    if cuts and transition_style in FLASH_RECIPES:
        vf = _flash_vf(cuts, style=transition_style, dur=flash_dur, gain=flash_gain)
    elif cuts and transition_style == "punch":
        vf = _punch_vf(cuts, W=W, H=H, fps=fps, scale=punch_scale, dur=punch_dur)
    else:
        vf = "null"

    placements = [(ev, sfx_files[ev["sfx"]]) for ev in plan
                  if ev.get("sfx") and ev["sfx"] in sfx_files]

    args = ["-i", str(src)]
    fc = []
    for i, (ev, f) in enumerate(placements, start=1):
        args += ["-i", str(f)]
        start = max(0.0, ev["t"] - (DEFAULT_LEAD_S if ev["kind"] == "transition" else 0.0))
        fc.append(f"[{i}:a]volume={sfx_volume:.3f},"
                  f"adelay={int(start * 1000)}:all=1[s{i}]")
    if placements:
        ins = "[0:a]" + "".join(f"[s{i}]" for i in range(1, len(placements) + 1))
        fc.append(f"{ins}amix=inputs={len(placements) + 1}:duration=first:normalize=0[a]")
        amap = "[a]"
    else:
        amap = "0:a"

    fc.insert(0, f"[0:v]{vf}[v]")
    args += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", amap,
             "-c:v", "libx264", "-crf", "18", "-preset", "medium",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(dst)]
    n_tr = len(cuts) if transition_style != "none" else 0
    return C.run_ffmpeg(args, description=f"Polish: {n_tr} {transition_style} "
                        f"transitions + {len(placements)} sfx")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def load_transition_profile(reel_dir, explicit=None):
    """Load the measured transition style of THIS avatar's originals
    (written by profile_transitions.py). Auto-discovers
    ``<avatar>/transition_style.json`` when no explicit path is given."""
    p = Path(explicit).expanduser() if explicit else (
        Path(reel_dir).resolve().parent.parent / "transition_style.json")
    if p.exists():
        prof = C.load_json(p)
        if isinstance(prof, dict):
            print(f"  Transition profile: {p} (style={prof.get('style')}, "
                  f"flash_at={prof.get('flash_at')}, dur={prof.get('flash_dur')}, "
                  f"gain={prof.get('flash_gain')})", file=sys.stderr)
            return prof
    if explicit:
        print(f"  Warning: transition profile {explicit} not found.", file=sys.stderr)
    return {}


def polish(reel_dir, *, transition_style=None, sfx=True,
           sfx_volume=DEFAULT_SFX_VOLUME,
           punch_scale=DEFAULT_PUNCH_SCALE, punch_dur=DEFAULT_PUNCH_DUR,
           flash_dur=None, flash_gain=None,
           density_s=None, guide=None, style_from=None,
           regen_sfx=False, token=None):
    """Explicit args > the avatar's measured ``transition_style.json`` profile
    > built-in defaults (which equal the reference avatar's measurements)."""
    prof = load_transition_profile(reel_dir, style_from)
    if transition_style is None:
        transition_style = prof.get("style") or "golden_flash"
    if flash_dur is None:
        flash_dur = float(prof.get("flash_dur") or DEFAULT_FLASH_DUR)
    if flash_gain is None:
        flash_gain = float(prof.get("flash_gain") or DEFAULT_FLASH_GAIN)
    flash_at = tuple(prof.get("flash_at") or ("broll_entry",))
    if transition_style not in TRANSITION_STYLES:
        raise SystemExit(f"Unknown transition style {transition_style!r}; "
                         f"choose from {TRANSITION_STYLES}")
    transitions = transition_style != "none"
    reel_dir = Path(reel_dir).expanduser().resolve()
    manifest_path = reel_dir / "reel_manifest.json"
    manifest = C.load_json(manifest_path) if manifest_path.exists() else {}
    storyboard_path = reel_dir / "storyboard.json"
    storyboard = C.load_json(storyboard_path) if storyboard_path.exists() else {}

    final = reel_dir / "final.mp4"
    clean = reel_dir / "final-without-sfx.mp4"
    if not final.exists():
        raise SystemExit(f"Missing {final} — run the finishing pass first.")

    # Idempotency: final.mp4 is already polished iff the manifest says so AND
    # the clean copy exists. In that case re-polish FROM the clean copy; a
    # fresh finish pass clears the marker, so a newly finished final.mp4 is
    # always treated as the new clean source.
    already_polished = bool(manifest.get("fx")) and clean.exists()
    if already_polished:
        src = clean
        print(f"  Re-polishing from {clean.name} (final.mp4 already has fx).",
              file=sys.stderr)
    else:
        shutil.copyfile(final, clean)
        src = clean
        print(f"  Kept pre-fx version -> {clean.name}", file=sys.stderr)

    W = int(manifest.get("width") or 1080)
    H = int(manifest.get("height") or 1920)
    fps = int(manifest.get("fps") or 30)
    total_dur = C.ffprobe_duration(src)

    if density_s is None:
        density_s = guide_density(guide) if guide else DEFAULT_DENSITY_S

    plan = build_fx_plan(manifest, storyboard, total_dur,
                         density_s=density_s, transitions=transitions, sfx=sfx,
                         flash_at=flash_at)
    if not plan:
        print("  No eligible fx points; final.mp4 left unchanged.", file=sys.stderr)
        return {"final": str(final), "fx_events": 0}

    print(f"  FX plan ({len(plan)} events, density 1/{density_s:.0f}s):", file=sys.stderr)
    for ev in plan:
        bits = [x for x in ("punch" if ev.get("punch") else None, ev.get("sfx")) if x]
        print(f"    {ev['t']:6.2f}s  {ev['kind']:10} [{'+'.join(bits)}]  {ev['why']}",
              file=sys.stderr)

    sfx_files = {}
    wanted = [ev["sfx"] for ev in plan if ev.get("sfx")]
    if wanted:
        tok = token or C.get_replicate_token()
        if tok:
            sfx_files = ensure_sfx_assets(reel_dir, wanted, token=tok, regen=regen_sfx)
        else:
            print("  Warning: no Replicate token; polishing without SFX.", file=sys.stderr)

    tmp = reel_dir / "final.fx.mp4"
    if not apply_fx(src, tmp, plan, sfx_files, W=W, H=H, fps=fps,
                    total_dur=total_dur, sfx_volume=sfx_volume,
                    transition_style=transition_style,
                    punch_scale=punch_scale, punch_dur=punch_dur,
                    flash_dur=flash_dur, flash_gain=flash_gain):
        raise SystemExit("Polish pass failed; final.mp4 untouched "
                         f"(clean copy at {clean.name}).")
    tmp.replace(final)

    import datetime as _dt
    if manifest:
        manifest["fx"] = {
            "applied_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "clean_copy": str(clean),
            "density_s": density_s,
            "sfx_volume": sfx_volume,
            "transition_style": transition_style,
            "flash_at": list(flash_at) if transition_style in FLASH_RECIPES else None,
            "profile": bool(prof) or None,
            "flash_dur": flash_dur if transition_style in FLASH_RECIPES else None,
            "flash_gain": flash_gain if transition_style in FLASH_RECIPES else None,
            "punch_scale": punch_scale if transition_style == "punch" else None,
            "transitions": transitions and any(e.get("punch") for e in plan),
            "sfx": bool(sfx_files),
            "sfx_model": SFX_MODEL if sfx_files else None,
            "events": [{k: v for k, v in ev.items()} for ev in plan],
        }
        C.save_json(manifest_path, manifest)

    print(f"\nPolished reel: {final}", file=sys.stderr)
    print(f"  clean (no fx): {clean}", file=sys.stderr)
    return {"final": str(final), "clean": str(clean), "fx_events": len(plan)}


def main():
    ap = argparse.ArgumentParser(
        description="Polish pass: duration-preserving golden-flash transitions at "
                    "scene cuts + short-soft SFX, applied OVER the finished reel "
                    "(keeps final-without-sfx.mp4).")
    ap.add_argument("reel", type=Path, help="Reel folder")
    ap.add_argument("--transition-style", choices=list(TRANSITION_STYLES),
                    default=None,
                    help="Visual effect at B-roll cuts. Default: the avatar's "
                         "measured transition_style.json (profile_transitions.py), "
                         "else golden_flash. 'white_flash'/'dip_black' for avatars "
                         "whose originals use those; 'punch' = small zoom pulse; "
                         "'none' = bare hard cuts")
    ap.add_argument("--no-transitions", dest="transition_style",
                    action="store_const", const="none",
                    help="Shortcut for --transition-style none")
    ap.add_argument("--style-from", default=None,
                    help="Explicit transition_style.json (default: auto-discover "
                         "<avatar>/transition_style.json)")
    ap.add_argument("--no-sfx", dest="sfx", action="store_false",
                    help="Skip the SFX overlay")
    ap.add_argument("--sfx-volume", type=float, default=DEFAULT_SFX_VOLUME,
                    help=f"SFX level under the voice (default {DEFAULT_SFX_VOLUME})")
    ap.add_argument("--flash-dur", type=float, default=None,
                    help=f"Flash length in s (default: profile, else {DEFAULT_FLASH_DUR})")
    ap.add_argument("--flash-gain", type=float, default=None,
                    help=f"Flash strength (default: profile, else {DEFAULT_FLASH_GAIN})")
    ap.add_argument("--punch-scale", type=float, default=DEFAULT_PUNCH_SCALE,
                    help=f"Zoom punch peak amount (default {DEFAULT_PUNCH_SCALE})")
    ap.add_argument("--punch-dur", type=float, default=DEFAULT_PUNCH_DUR,
                    help=f"Zoom punch length in s (default {DEFAULT_PUNCH_DUR})")
    ap.add_argument("--density", type=float, default=None,
                    help="Seconds per SFX event (default: from --guide, else "
                         f"{DEFAULT_DENSITY_S:.0f} as measured on the reference reel)")
    ap.add_argument("--guide", default=None,
                    help="voice-isolate voice.json of an ORIGINAL reel; its "
                         "measured sfx_intervals set the density")
    ap.add_argument("--regen-sfx", action="store_true",
                    help="Regenerate the cached SFX assets")
    args = ap.parse_args()

    res = polish(args.reel, transition_style=args.transition_style, sfx=args.sfx,
                 sfx_volume=args.sfx_volume, punch_scale=args.punch_scale,
                 punch_dur=args.punch_dur, flash_dur=args.flash_dur,
                 flash_gain=args.flash_gain, density_s=args.density,
                 guide=args.guide, style_from=args.style_from,
                 regen_sfx=args.regen_sfx)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
