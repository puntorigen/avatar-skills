#!/usr/bin/env python3
"""Stereo spatialization helpers for the audio-theater spatial mix.

Places a mono source on a virtual stage with a position:
- pan      in [-1, +1]  (-1 hard left, 0 center, +1 hard right)
- distance in [0, 1]    (0 = intimate/close, 1 = far)

Three perceptual cues build "distance": level (quieter when far), tone (a
low-pass mimics air absorption when far) and stereo placement (constant-power
pan). Movement (a character walking closer, a bird crossing the scene) is done
with ffmpeg's `aeval`, the only way to automate panning over time (`pan` is
static). `aeval` is slow but the clips are short, and static sources use the
fast `pan`/`volume`/`lowpass` path instead.

The output is a normal stereo stream (works on speakers and headphones); pan is
constant-power so a mono fold-down stays level-stable.
"""

import math

# ── Tunables ────────────────────────────────────────────────────────────────
MAX_ATTEN_DB = -11.0       # level drop at distance == 1
FC_NEAR = 18000.0          # low-pass cutoff (Hz) at distance == 0
FC_FAR = 2600.0            # low-pass cutoff (Hz) at distance == 1
VOICE_PAN_LIMIT = 0.5      # keep dialogue intelligible / near-center
SFX_PAN_LIMIT = 0.95       # SFX may travel almost fully L/R
VOICE_DEFAULT_DISTANCE = 0.12
NARRATION_DEFAULT_DISTANCE = 0.05
MONO_48K = "aformat=sample_fmts=fltp:channel_layouts=mono:sample_rates=48000"
STEREO_48K = "aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000"

# ln(10)/20: converts dB -> natural-log exponent for a linear gain via exp().
_DB_TO_EXP = 0.1151292546497


def clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))


def pan_gains(pan):
    """Constant-power L/R gains for a hard-positioned (collapsed) source."""
    theta = (clamp(pan, -1.0, 1.0) + 1.0) * 0.25 * math.pi  # (pan+1)/2 * pi/2
    return math.cos(theta), math.sin(theta)


def balance_gains(pan):
    """Gentle L/R balance for a *stereo bed* (keeps both channels, shifts energy)."""
    pan = clamp(pan, -1.0, 1.0)
    gl = 1.0 if pan <= 0 else (1.0 - pan)
    gr = 1.0 if pan >= 0 else (1.0 + pan)
    return gl, gr


def fc_from_distance(distance):
    d = clamp(distance, 0.0, 1.0)
    return FC_NEAR + (FC_FAR - FC_NEAR) * d


def _esc(expr):
    """Escape commas so an expression survives ffmpeg filtergraph parsing."""
    return expr.replace(",", "\\,")


def _interp_expr(keys):
    """Piecewise-linear expression in `t` (seconds) with flat clamping outside.

    keys: sorted list of (t, value). Indicator windows are mutually exclusive
    (half-open) so the terms simply sum.
    """
    if len(keys) == 1:
        return f"({keys[0][1]:.5f})"
    parts = [f"lt(t,{keys[0][0]:.5f})*{keys[0][1]:.5f}"]
    for (ta, va), (tb, vb) in zip(keys, keys[1:]):
        if tb <= ta:
            tb = ta + 0.001
        parts.append(
            f"(gte(t,{ta:.5f})*lt(t,{tb:.5f}))*"
            f"({va:.5f}+({vb:.5f}-{va:.5f})*((t-{ta:.5f})/({tb:.5f}-{ta:.5f})))"
        )
    tn, vn = keys[-1]
    parts.append(f"gte(t,{tn:.5f})*{vn:.5f}")
    return "(" + "+".join(parts) + ")"


def _static_chain(pan, distance, max_atten_db):
    gl, gr = pan_gains(pan)
    fc = fc_from_distance(distance)
    dgdb = max_atten_db * clamp(distance, 0.0, 1.0)
    return (
        f"{MONO_48K},lowpass=f={fc:.1f},volume={dgdb:.2f}dB,"
        f"pan=stereo|c0={gl:.5f}*c0|c1={gr:.5f}*c0"
    )


def _moving_chain(pan_keys, dist_keys, max_atten_db):
    mean_d = sum(d for _, d in dist_keys) / len(dist_keys)
    fc = fc_from_distance(mean_d)
    ang = f"(0.7853981634*({_interp_expr(pan_keys)}+1))"   # (pi/4)*(x+1)
    coef = _DB_TO_EXP * max_atten_db
    dg = f"exp(({coef:.8f})*{_interp_expr(dist_keys)})"
    expr_l = f"val(0)*{dg}*cos({ang})"
    expr_r = f"val(1)*{dg}*sin({ang})"
    # Duplicate mono -> stereo first so aeval always has 2 input channels.
    return (
        f"{MONO_48K},pan=stereo|c0=c0|c1=c0,lowpass=f={fc:.1f},"
        f"aeval={_esc(expr_l)}|{_esc(expr_r)}:channel_layout=stereo"
    )


def _normalize(spatial, win, default_pan, default_distance, pan_limit, min_distance):
    dpan = clamp(default_pan, -pan_limit, pan_limit)
    ddist = clamp(default_distance, min_distance, 1.0)
    if not spatial:
        return {"mode": "static", "pan": dpan, "distance": ddist}

    if "path" in spatial and spatial["path"]:
        pts = sorted(spatial["path"], key=lambda k: float(k.get("t", 0.0)))
        pan_keys, dist_keys = [], []
        for k in pts:
            t = clamp(k.get("t", 0.0), 0.0, max(win, 0.001))
            pan_keys.append((t, clamp(k.get("pan", dpan), -pan_limit, pan_limit)))
            dist_keys.append((t, clamp(k.get("distance", ddist), min_distance, 1.0)))
        if len(pan_keys) == 1:
            return {"mode": "static", "pan": pan_keys[0][1], "distance": dist_keys[0][1]}
        return {"mode": "move", "pan_keys": pan_keys, "dist_keys": dist_keys}

    if "from" in spatial and "to" in spatial:
        f, t = spatial["from"], spatial["to"]
        pan_keys = [
            (0.0, clamp(f.get("pan", dpan), -pan_limit, pan_limit)),
            (max(win, 0.001), clamp(t.get("pan", dpan), -pan_limit, pan_limit)),
        ]
        dist_keys = [
            (0.0, clamp(f.get("distance", ddist), min_distance, 1.0)),
            (max(win, 0.001), clamp(t.get("distance", ddist), min_distance, 1.0)),
        ]
        return {"mode": "move", "pan_keys": pan_keys, "dist_keys": dist_keys}

    # Plain static {pan, distance} (missing fields fall back to defaults).
    return {
        "mode": "static",
        "pan": clamp(spatial.get("pan", dpan), -pan_limit, pan_limit),
        "distance": clamp(spatial.get("distance", ddist), min_distance, 1.0),
    }


def distances_of(spatial, *, win, default_distance=VOICE_DEFAULT_DISTANCE):
    """Return the list of distance values a source will occupy (for min/max scans)."""
    norm = _normalize(spatial, win, 0.0, default_distance, 1.0, 0.0)
    if norm["mode"] == "static":
        return [norm["distance"]]
    return [d for _, d in norm["dist_keys"]]


def build_source_chain(spatial, *, win, default_pan=0.0,
                       default_distance=VOICE_DEFAULT_DISTANCE,
                       pan_limit=1.0, max_atten_db=MAX_ATTEN_DB, min_distance=0.0):
    """Return (filter_chain, is_moving) that turns a mono/stereo input into a
    positioned stereo stream. The caller appends adelay/apad and I/O labels.

    min_distance floors how close a source may render (used to keep SFX behind
    the dialogue plane so the narrator always reads as the closest source).
    """
    norm = _normalize(spatial, win, default_pan, default_distance, pan_limit, min_distance)
    if norm["mode"] == "static":
        return _static_chain(norm["pan"], norm["distance"], max_atten_db), False
    return _moving_chain(norm["pan_keys"], norm["dist_keys"], max_atten_db), True
