#!/usr/bin/env python3
"""Profile the VISUAL TRANSITION style of an avatar's ORIGINAL reels.

For every scene boundary in a ``*.analysis.json`` (video-scene-analysis), this
samples low-res frames around the cut in the original video and measures how
the picture deviates from its surroundings: a brightness lift + warm color
shift = the "golden flash" seen on some creators' reels; a neutral lift =
white flash; a brightness drop = dip-to-black; no significant deviation =
bare hard cuts.

The aggregated result is written to ``<avatar>/transition_style.json`` —
consumed by ``polish_reel.py`` the same way ``finish_reel.py`` consumes
``subtitle_style.json`` — so NEW avatars automatically get THEIR OWN measured
transition look (style, duration, strength) instead of another avatar's
defaults.

Measurement details:
  * Frames are sampled at ~15fps in a ±0.6s window around each cut, at 48px
    wide (mean channel statistics only — no detail needed).
  * The baseline is taken 0.8-1.2s away on BOTH sides of the cut; the flash
    metric is the peak deviation of brightness/warmth inside the window vs the
    nearer baseline. PySceneDetect often reports a flashed cut slightly LATE
    (the wash confuses it), which is why the window spans both sides.
  * Flash duration = the contiguous span around the peak where the deviation
    stays above 30% of the peak.

Usage:
    python3 profile_transitions.py <video.analysis.json> [more.analysis.json …]
        [--out <avatar>/transition_style.json] [--min-scene-gap 1.6]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _arc_common as C  # noqa: E402

import numpy as np  # noqa: E402

SAMPLE_W = 48          # analysis frame width (stats only)
WIN_S = 0.6            # window sampled on each side of the cut
BASE_NEAR, BASE_FAR = 0.8, 1.2  # baseline band distance from the cut
FPS = 15               # sampling rate inside the window
# Peak thresholds (0-255 scale) for calling a flash:
TH_BRIGHT = 14.0       # brightness deviation
TH_WARMTH = 16.0       # (R-B) deviation
# Reference gain: the reference avatar's measured golden flash peaks at a mean
# brightness delta of ~110 (0-255); profiles are normalized so that == gain 1.0.
GAIN_REF_BRIGHT = 110.0


def _video_dims(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True).stdout.strip()
    w, h = (int(x) for x in out.split(",")[:2])
    return w, h


def _sample_band(video, t0, t1, sample_h):
    """Decode [t0, t1) at FPS as tiny RGB frames; return (times, Nx3 means)."""
    if t0 < 0:
        t0 = 0.0
    dur = max(0.0, t1 - t0)
    if dur <= 0:
        return np.zeros(0), np.zeros((0, 3))
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", str(video),
           "-t", f"{dur:.3f}", "-vf", f"fps={FPS},scale={SAMPLE_W}:{sample_h}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
    except subprocess.TimeoutExpired:
        return np.zeros(0), np.zeros((0, 3))
    frame_bytes = SAMPLE_W * sample_h * 3
    n = len(raw) // frame_bytes
    if n == 0:
        return np.zeros(0), np.zeros((0, 3))
    arr = np.frombuffer(raw[: n * frame_bytes], dtype=np.uint8)
    arr = arr.reshape(n, sample_h, SAMPLE_W, 3).astype(np.float32)
    means = arr.mean(axis=(1, 2))  # (n, 3) mean R,G,B per frame
    times = t0 + (np.arange(n) + 0.5) / FPS
    return times, means


def _stats(means):
    """brightness Y, warmth (R-B) per frame."""
    if len(means) == 0:
        return np.zeros(0), np.zeros(0)
    y = 0.299 * means[:, 0] + 0.587 * means[:, 1] + 0.114 * means[:, 2]
    warmth = means[:, 0] - means[:, 2]
    return y, warmth


def profile_cut(video, t_cut, *, total_dur, sample_h):
    """Measure one boundary. Returns a dict or None if unmeasurable."""
    lo = max(0.0, t_cut - BASE_FAR)
    hi = min(total_dur, t_cut + BASE_FAR)
    if hi - lo < 1.0:
        return None
    times, means = _sample_band(video, lo, hi, sample_h)
    if len(times) < 8:
        return None
    y, warmth = _stats(means)
    rel = times - t_cut

    base_mask = (np.abs(rel) >= BASE_NEAR)
    win_mask = (np.abs(rel) <= WIN_S)
    if base_mask.sum() < 3 or win_mask.sum() < 3:
        return None
    # Baseline per side (scene content differs across the cut), take the
    # nearer side's baseline for each window sample.
    def _side_base(arr):
        pre = arr[base_mask & (rel < 0)]
        post = arr[base_mask & (rel > 0)]
        pre_v = float(np.median(pre)) if len(pre) else float(np.median(arr[base_mask]))
        post_v = float(np.median(post)) if len(post) else float(np.median(arr[base_mask]))
        return pre_v, post_v

    yb_pre, yb_post = _side_base(y)
    wb_pre, wb_post = _side_base(warmth)
    dy = np.where(rel < 0, y - yb_pre, y - yb_post)
    dw = np.where(rel < 0, warmth - wb_pre, warmth - wb_post)
    dy_w, dw_w, rel_w = dy[win_mask], dw[win_mask], rel[win_mask]
    mean_w = means[win_mask]

    k = int(np.argmax(0.6 * dy_w + 0.4 * dw_w))
    peak_dy, peak_dw = float(dy_w[k]), float(dw_w[k])
    is_flash = peak_dy > TH_BRIGHT or peak_dw > TH_WARMTH
    is_dip = (not is_flash) and float(-dy_w.min()) > 2 * TH_BRIGHT

    out = {
        "t": round(float(t_cut), 3),
        "peak_dy": round(peak_dy, 1),
        "peak_dw": round(peak_dw, 1),
        "kind": "flash" if is_flash else ("dip" if is_dip else "none"),
    }
    if is_flash:
        # duration: contiguous span around the peak above 30% of the peak metric
        metric = 0.6 * dy_w + 0.4 * dw_w
        th = 0.3 * metric[k]
        i = k
        while i > 0 and metric[i - 1] > th:
            i -= 1
        j = k
        while j < len(metric) - 1 and metric[j + 1] > th:
            j += 1
        out["dur"] = round(float(rel_w[j] - rel_w[i]) + 1.0 / FPS, 3)
        out["peak_offset"] = round(float(rel_w[k]), 3)
        # channel deltas at the peak vs that side's baseline -> hue class
        base_rgb = (means[base_mask & (rel < 0)] if rel_w[k] < 0
                    else means[base_mask & (rel > 0)])
        if len(base_rgb) == 0:
            base_rgb = means[base_mask]
        d_rgb = mean_w[k] - np.median(base_rgb, axis=0)
        out["d_rgb"] = [round(float(v), 1) for v in d_rgb]
        dr, dg, db = d_rgb
        out["hue"] = ("golden" if (dr > dg > db or (dr > 0 and db < 0.3 * dr))
                      else "white")
    return out


def _rate(cuts, kind):
    return round(sum(1 for c in cuts if c["kind"] == kind) / len(cuts), 2) if cuts else 0.0


def aggregate(per_cut, sources):
    """Boundary-type-aware aggregation. The originals don't dress EVERY cut —
    e.g. lolo flashes 100% of B-roll ENTRIES but 0% of exits and almost no
    talking-head cuts — so rates are computed per boundary type and the style
    is declared for the type(s) that actually use it (``flash_at``)."""
    measured = [c for c in per_cut if c]
    n = len(measured)
    by_type = {bt: [c for c in measured if c.get("boundary") == bt]
               for bt in ("broll_entry", "broll_exit", "th_th")}
    profile = {
        "version": 1,
        "sources": sources,
        "boundaries_measured": n,
        "flash_rate": _rate(measured, "flash"),
        "flash_rate_by_boundary": {bt: _rate(cs, "flash") for bt, cs in by_type.items() if cs},
        "dip_rate": _rate(measured, "dip"),
        "per_cut": measured,
    }

    # Which boundary types use the flash? (>= 50% of that type's cuts)
    flash_at = [bt for bt, cs in by_type.items() if cs and _rate(cs, "flash") >= 0.5]
    flashes = [c for c in measured if c["kind"] == "flash"
               and (not flash_at or c.get("boundary") in flash_at)]
    if not flash_at and _rate(measured, "flash") >= 0.3:
        flash_at = ["broll_entry", "broll_exit", "th_th"]  # used loosely everywhere
        flashes = [c for c in measured if c["kind"] == "flash"]

    if flash_at and flashes:
        golden = sum(1 for c in flashes if c.get("hue") == "golden")
        durs = sorted(c["dur"] for c in flashes)
        peaks = sorted(c["peak_dy"] for c in flashes)
        profile.update({
            "style": "golden_flash" if golden >= len(flashes) / 2 else "white_flash",
            "flash_at": flash_at,
            "flash_dur": round(min(0.6, max(0.2, durs[len(durs) // 2])), 2),
            "flash_gain": round(min(1.6, max(0.4, peaks[len(peaks) // 2] / GAIN_REF_BRIGHT)), 2),
        })
    elif _rate(measured, "dip") >= 0.3:
        profile["style"] = "dip_black"
    else:
        profile["style"] = "none"
    return profile


def profile_videos(analysis_paths, *, min_scene_gap=1.6):
    per_cut, sources = [], []
    for ap in analysis_paths:
        a = C.load_json(ap)
        video = a.get("video_path") or ""
        vp = Path(video)
        if not vp.exists():  # try relative to the analysis file
            vp = Path(ap).parent / Path(video).name
        if not vp.exists():
            print(f"  Warning: video for {ap} not found; skipping.", file=sys.stderr)
            continue
        scenes = a.get("scenes") or []
        total = max((float(s.get("end") or 0) for s in scenes), default=0.0)

        def _is_broll(s):
            return (s.get("scene_type") or "") == "supplementary_material"

        cuts = []
        for prev, cur in zip(scenes, scenes[1:]):
            t = float(cur.get("start") or 0)
            if t - float(prev.get("start") or 0) < min_scene_gap or total - t < 1.0:
                continue
            if _is_broll(cur) and not _is_broll(prev):
                btype = "broll_entry"
            elif _is_broll(prev) and not _is_broll(cur):
                btype = "broll_exit"
            else:
                btype = "th_th"
            cuts.append((t, btype))
        w, h = _video_dims(vp)
        sample_h = max(2, round(h * SAMPLE_W / w / 2) * 2)
        print(f"  {vp.name}: {len(cuts)} boundaries", file=sys.stderr)
        sources.append(str(vp))
        for t, btype in cuts:
            r = profile_cut(vp, t, total_dur=total, sample_h=sample_h)
            if r:
                r["video"] = vp.name
                r["boundary"] = btype
                per_cut.append(r)
                print(f"    {t:7.2f}s  {btype:11} {r['kind']:5}  dy={r['peak_dy']:+6.1f} "
                      f"dw={r['peak_dw']:+6.1f}"
                      + (f"  dur={r['dur']:.2f}s hue={r['hue']}" if r["kind"] == "flash" else ""),
                      file=sys.stderr)
    return aggregate(per_cut, sources)


def main():
    ap = argparse.ArgumentParser(description="Measure the original reels' visual "
                                 "transition style -> transition_style.json")
    ap.add_argument("analysis", nargs="+", type=Path,
                    help="*.analysis.json files (video-scene-analysis output)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output path (default: <avatar>/transition_style.json "
                         "next to the first video's avatar folder, else CWD)")
    ap.add_argument("--min-scene-gap", type=float, default=1.6)
    args = ap.parse_args()

    profile = profile_videos(args.analysis, min_scene_gap=args.min_scene_gap)

    out = args.out
    if out is None:
        # <avatar>/videos/<file>.mp4 -> <avatar>/transition_style.json
        try:
            v0 = Path(profile["sources"][0])
            avatar = v0.parent.parent if v0.parent.name == "videos" else Path.cwd()
            out = avatar / "transition_style.json"
        except (IndexError, KeyError):
            out = Path.cwd() / "transition_style.json"
    C.save_json(out, profile)
    print(f"\nTransition style profile -> {out}", file=sys.stderr)
    print(json.dumps({k: v for k, v in profile.items() if k != "per_cut"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
