#!/usr/bin/env python3
"""Stage 3 (finishing pass) of avatar-reel-composer.

Takes a reel produced by ``compose_reel.py`` (a folder with video_track.mp4,
narration.mp3, narration.align.json and reel_manifest.json) and adds the
"published" layer that the bare cut is missing:

  1. SUBTITLES  -- burned-in, word-timed captions that match the analyzed reels'
     style: one self-contained PHRASE UNIT at a time (it REPLACES the previous one
     -- no stale already-spoken text stacked under a new line), set in an elegant
     serif. When a phrase is long enough, it shows a regular SETUP line + a
     bold-italic PAYOFF line (the breath-ending / key words), mirroring how the
     originals emphasize the completion of each phrase. Rendered as transparent
     PNGs with Pillow (full styling control) and composited with video-compose's
     overlay_titles primitive -- no dependency on a libass-enabled ffmpeg build.

  2. MUSIC BED  -- a light instrumental track from bg-music-hq at a FIXED low
     volume under the narration (no ducking), tailored to the reel's emotional
     tone so it stays in the background without distracting.

Idempotent: reuses an existing music.mp3 unless --regen-music. Re-runnable on any
reel folder, so you can iterate on caption style / music without regenerating any
video.

Usage:
    python3 finish_reel.py <reel_dir | reel_manifest.json>
    python3 finish_reel.py <reel_dir> --no-music                 # captions only
    python3 finish_reel.py <reel_dir> --music-mood inspiring
    python3 finish_reel.py <reel_dir> --no-subtitles             # music only
    python3 finish_reel.py <reel_dir> --max-words 6 --no-emphasis
    python3 finish_reel.py <reel_dir> --style-from lolo/subtitle_style.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _arc_common as C  # noqa: E402

# A barely-there bed for an intimate spoken reflection: emotional but un-busy so
# it never competes with the voice. The agent should TAILOR this to the reel's
# emotional tone (read from the script + the B-roll), passing --music-prompt or a
# storyboard finish.music_prompt; this is the calm default if none is given.
DEFAULT_MUSIC_PROMPT = (
    "sparse, intimate solo piano underscore for an emotional, reflective moment, "
    "soft and tender with a touch of melancholy turning hopeful, very minimal, "
    "slow, lots of space, sustained ambient pad underneath, no drums, no "
    "percussion, no beat, no vocals, quiet unobtrusive background bed"
)
DEFAULT_MUSIC_MOOD = "ambient"

# --- Master loudness ---------------------------------------------------------
# The final mux is loudness-normalized to a broadcast/social spoken-word target.
# Without this the master sits at the TTS narration's NATIVE level (our Gemini /
# voice-clone narrations land around -24 LUFS), which plays back as a near-whisper
# locally and leaves the voice fighting any music/ambient bed. -16 LUFS is the
# spoken-word standard; TP -1.5 dBTP keeps true-peak headroom; LRA 11 preserves a
# natural dynamic range. The music bed (fixed low volume) and any polish SFX are
# scaled BEFORE this, so normalizing the mix keeps the voice clearly on top.
# Pass master_lufs=None to disable (e.g. to preserve a pre-mastered source level).
MASTER_LUFS = -16.0
MASTER_TP = -1.5
MASTER_LRA = 11


def _loudnorm_filter(master_lufs):
    """Single-pass loudnorm filter string for the final master, or None to skip."""
    if master_lufs is None:
        return None
    return f"loudnorm=I={float(master_lufs)}:TP={MASTER_TP}:LRA={MASTER_LRA}"

# Caption style matches the analyzed reels: an elegant SERIF, natural casing,
# white with a soft drop shadow (no heavy outline). One self-contained phrase unit
# at a time (it replaces the previous), shown as a regular SETUP line + a BOLD
# ITALIC PAYOFF line (the breath-ending / key words).
SERIF_REGULAR_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/Supplemental/Charter.ttc",
]
SERIF_EMPH_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Georgia Bold Italic.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

# Strong punctuation / pause -> ends a phrase UNIT. Soft punctuation -> a good
# place to split a unit into its setup (regular) and payoff (highlighted) parts.
STRONG_PUNCT = ".?!…"
SOFT_SPLIT = ",;:"


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------
def _pick(cands, label):
    for f in cands:
        if Path(f).exists():
            return f
    raise SystemExit(f"No {label} font found (looked for {', '.join(cands)}).")


def pick_fonts(regular=None, emph=None):
    """Return (regular_font_path, emphasis_font_path)."""
    reg = regular if (regular and Path(regular).exists()) else _pick(SERIF_REGULAR_CANDIDATES, "serif")
    emp = emph if (emph and Path(emph).exists()) else _pick(SERIF_EMPH_CANDIDATES, "bold-italic serif")
    return reg, emp


_CASE_STRIP = "¿¡.,;:!?…\"'()-«»\u201c\u201d"


def _subtitle_token(tok):
    """Lowercase a token, but keep INTENTIONAL all-caps words (acronyms/emphasis:
    REPE, NO). Accents survive .lower() (Á→á). A lone capital (sentence-start
    'Eso', 'Y') is just normal writing, so it's lowercased."""
    core = tok.strip(_CASE_STRIP)
    if core and core.isupper() and sum(c.isalpha() for c in core) >= 2:
        return tok
    return tok.lower()


def apply_casing(text, casing):
    if casing == "lower":
        return text.lower()
    if casing == "upper":
        return text.upper()
    if casing == "subtitle":
        # Match the analyzed reels: lowercase presentation (no sentence-initial
        # capitals) EXCEPT intentional all-caps words, which stay shouted.
        return " ".join(_subtitle_token(w) for w in text.split())
    return text  # "natural" = preserve as-is


# Spanish proclitics / connectors that lean on the FOLLOWING word — a line should
# never end on one of these (it strands the reader), so breaks are nudged off them.
PROCLITICS = set(
    "a ante bajo cabe con contra de del desde durante en entre hacia hasta mediante "
    "para por segun sin so sobre tras "
    "el la los las un una unos unas lo al "
    "y e o u ni que como si pero mas aunque porque cuando donde mientras "
    "su sus tu tus mi mis me te se le les nos os "
    "no muy tan ya".split()
)


def _txt(ws):
    # Social-subtitle convention: no trailing sentence punctuation (the dot/ellipsis/
    # comma at the end of a caption). Keep '?'/'!' — they carry tone.
    return " ".join((w.get("word") or "").strip() for w in ws).strip().rstrip(" ,;:.…")


def _norm(t):
    return (t or "").strip().strip("¿¡.,;:!?…\"'").lower()


def _good_split(texts, target, lo, hi):
    """Pick a split index (setup = texts[:idx]) near ``target`` within [lo, hi]
    such that the setup does NOT end on a proclitic. Prefer the closest candidate.
    """
    lo = max(1, lo)
    hi = min(len(texts) - 1, hi)
    if lo > hi:
        return max(1, min(len(texts) - 1, target))
    # Closest to target wins (target is the balanced midpoint); deterministic on ties.
    for i in sorted(range(lo, hi + 1), key=lambda i: (abs(i - target), i)):
        if _norm(texts[i - 1]) not in PROCLITICS:
            return i
    return max(lo, min(hi, target))


def _comma_near(texts, target, lo, hi):
    """If a word ends with soft punctuation near ``target``, split right after it."""
    for j in (target, target - 1, target + 1, target - 2, target + 2):
        if lo <= j <= hi and texts[j - 1].strip().endswith((",", ";", ":")):
            return j
    return None


def _subdivide_group(g, max_words):
    """Recursively split a breath group so EVERY chunk has <= max_words words.

    Splits near the balanced midpoint, preferring a comma and never ending a chunk
    on a proclitic. Recursion guarantees no oversized leftover chunk (the bug a
    single ceil-based split can leave behind).
    """
    n = len(g)
    if n <= max_words:
        return [g]
    texts = [(w.get("word") or "").strip() for w in g]
    target = round(n / 2)
    idx = _comma_near(texts, target, 1, n - 1) or _good_split(texts, target, 1, n - 1)
    idx = max(1, min(n - 1, idx))
    return _subdivide_group(g[:idx], max_words) + _subdivide_group(g[idx:], max_words)


def build_units(words, *, max_words=6, max_gap=0.30):
    """Segment aligned words into self-contained caption UNITS (breath groups).

    Primary boundaries are natural: strong punctuation and speech pauses. A breath
    group longer than ``max_words`` is subdivided (recursively, balanced) so every
    unit stays short enough to read on ~2 lines. Units are shown one at a time and
    REPLACE each other — never rolled/accumulated — so the viewer never reads stale
    already-spoken text stacked under a new line. Only the final unit of a breath
    group is flagged ``ends_group`` (that's where the payoff emphasis lands).
    """
    groups, cur = [], []
    for i, w in enumerate(words):
        txt = (w.get("word") or "").strip()
        if not txt:
            continue
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (float(nxt["start"]) - float(w["end"])) if nxt else 0.0
        if txt[-1] in STRONG_PUNCT or nxt is None or gap > max_gap:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    units = []  # each: (unit_words, ends_group)
    for g in groups:
        chunks = _subdivide_group(g, max_words)
        for j, chunk in enumerate(chunks):
            units.append((chunk, j == len(chunks) - 1))
    return units


def split_unit(unit, *, min_split=4):
    """Split a displayed unit into (setup, payoff). The payoff is the breath-ending
    / key words shown highlighted (bold-italic, second line) — like the originals.

    Reasoning mirrors the analyzed reels: emphasize the *completion* of the phrase.
    Prefer the span after the last internal comma; else the trailing ~half. Never
    end the setup on a proclitic. Units shorter than ``min_split`` stay on one
    regular line (no highlight) — short phrases aren't emphasized in the originals.
    """
    n = len(unit)
    if n < min_split:
        return unit, []
    texts = [(w.get("word") or "").strip() for w in unit]
    split_idx = None
    for i in range(1, n):  # split before i; payoff stays non-empty
        if texts[i - 1].endswith((",", ";", ":")):
            split_idx = i
    if not split_idx:
        target = round(n / 2)  # balanced: setup ~ payoff (both ~1 line)
        split_idx = _good_split(texts, target, 1, n - 1)
    return unit[:split_idx], unit[split_idx:]


def _split_index(ws):
    texts = [(w.get("word") or "").strip() for w in ws]
    n = len(ws)
    target = round(n / 2)
    # Keep both sides >= 2 words when possible, so a split never strands a lone word.
    lo, hi = (2, n - 2) if n >= 4 else (1, n - 1)
    return _comma_near(texts, target, lo, hi) or _good_split(texts, target, lo, hi)


def _event_for(ws, ends_group, emphasis, min_split=4):
    """Build a render event for a word span. Emphasis (setup + bold-italic payoff)
    only on a breath group's completion and only when there are enough words."""
    if emphasis and ends_group and len(ws) >= min_split:
        setup, payoff = split_unit(ws)
        if payoff:
            return {"upper": _txt(setup), "lower": _txt(payoff), "emph": True, "ws": ws}
    return {"upper": None, "lower": _txt(ws), "emph": False, "ws": ws}


def build_caption_events(words, total_dur, *, max_words=6, max_gap=0.30, emphasis=True,
                         fit=None, pause_clear=0.40, pause_tail=0.30):
    """Build caption render events.

    Captions REPLACE each other (no rolling). A breath group's completion gets the
    bold-italic payoff. Two readability rules the analyzed reels follow:

    * **Split, don't shrink.** If a caption wouldn't fit at the nominal font (``fit``
      returns False), it's split into SEQUENTIAL captions (each shown for its own
      words) rather than crammed into a tiny 2-line block — lower cognitive load,
      full-size text.
    * **Track speech.** Each caption is bounded to its spoken words; when a long
      pause follows (sentence boundary), it clears shortly after the last word
      instead of lingering with not-yet-spoken text on screen.
    """
    units = build_units(words, max_words=max_words, max_gap=max_gap)

    raw = []  # ordered events, each carrying its word span in "ws"

    def emit(ws, ends):
        ev = _event_for(ws, ends, emphasis)
        if len(ws) <= 2 or fit is None or fit(ev):
            raw.append(ev)
            return
        idx = max(1, min(len(ws) - 1, _split_index(ws)))
        emit(ws[:idx], False)
        emit(ws[idx:], ends)

    for ws, ends in units:
        emit(ws, ends)

    events = []
    for i, ev in enumerate(raw):
        ws = ev["ws"]
        start = float(ws[0]["start"])
        last_end = float(ws[-1]["end"])
        if i + 1 < len(raw):
            nxt = float(raw[i + 1]["ws"][0]["start"])
            gap = nxt - last_end
            out = nxt if gap <= pause_clear else (last_end + pause_tail)
        else:
            out = total_dur or (last_end + pause_tail)
        events.append({"in": start, "out": max(start + 0.20, out),
                       "upper": ev["upper"], "lower": ev["lower"], "emph": ev["emph"]})
    return events


def _line_w(draw, s, font):
    bb = draw.textbbox((0, 0), s, font=font)
    return bb[2] - bb[0]


def _wrap_balanced(draw, text, font, max_width):
    """Wrap into the fewest lines that fit ``max_width``, then BALANCE them so no
    line is left with an orphan single word (which looks broken). Uses a small DP
    that minimizes the widest line for that line count.
    """
    words = text.split()
    if not words:
        return []
    # Fewest lines via greedy.
    greedy, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if not cur or _line_w(draw, trial, font) <= max_width:
            cur = trial
        else:
            greedy.append(cur)
            cur = w
    if cur:
        greedy.append(cur)
    L = len(greedy)
    if L <= 1:
        return greedy

    n = len(words)
    space = _line_w(draw, "x x", font) - 2 * _line_w(draw, "x", font)
    wj = [_line_w(draw, w, font) for w in words]

    def line_w(i, j):
        return sum(wj[i:j]) + space * (j - i - 1)

    import functools

    @functools.lru_cache(maxsize=None)
    def best(i, lines_left):
        if lines_left == 1:
            return (line_w(i, n), (n,))
        out = None
        for j in range(i + 1, n - lines_left + 2):
            sub_cost, sub_cut = best(j, lines_left - 1)
            cost = max(line_w(i, j), sub_cost)
            if out is None or cost < out[0]:
                out = (cost, (j,) + sub_cut)
        return out

    cuts = best(0, L)[1]
    lines, start = [], 0
    for c in cuts:
        lines.append(" ".join(words[start:c]))
        start = c
    return lines


def _layout(draw, event, casing, regular_font, emph_font, fs, max_w):
    """Return wrapped rows [(text, font)] and the (upper_lines, lower_lines) counts
    for the given font size."""
    from PIL import ImageFont

    reg = ImageFont.truetype(regular_font, fs)
    emp = ImageFont.truetype(emph_font, fs)
    rows, u_lines = [], []
    if event.get("upper"):
        u_lines = _wrap_balanced(draw, apply_casing(event["upper"], casing), reg, max_w)
        rows += [(ln, reg) for ln in u_lines]
    lower_font = emp if event.get("emph") else reg
    l_lines = _wrap_balanced(draw, apply_casing(event["lower"], casing), lower_font, max_w)
    rows += [(ln, lower_font) for ln in l_lines]
    return rows, len(u_lines), len(l_lines)


def render_caption_png(event, out_path, *, W, H, regular_font, emph_font,
                       fontsize, y_frac=0.66, casing="natural", max_lines=2):
    """Render one caption event as a full-frame transparent PNG.

    Elegant serif, white fill, soft drop shadow + a thin subtle outline. Upper line
    regular; lower line bold-italic when ``emph``. Centered, block centered at
    ``y_frac``. The font AUTO-FITS: it shrinks (to a floor) so a caption stays at
    ~2 lines like the analyzed reels — an emphasis unit targets a 1-line setup + a
    1-line payoff; a plain unit targets <= ``max_lines`` — instead of degrading into
    a stack of orphan single-word lines at a fixed large size.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    max_w = int(W * 0.84)
    # Captions are pre-split to fit at nominal size, so only a gentle shrink floor
    # is needed for the rare residual overflow (keeps text big and consistent).
    floor = max(48, int(fontsize * 0.80))

    fs = int(fontsize)
    rows, nu, nl = _layout(draw, event, casing, regular_font, emph_font, fs, max_w)
    while fs > floor:
        if event.get("emph") and event.get("upper"):
            ok = nu <= 1 and nl <= 1
        else:
            ok = (nu + nl) <= max_lines
        if ok:
            break
        fs = max(floor, int(fs * 0.94))
        rows, nu, nl = _layout(draw, event, casing, regular_font, emph_font, fs, max_w)

    outline = max(2, fs // 28)
    shadow_off = max(2, round(fs * 0.06))
    gap = max(4, round(fs * 0.18))

    heights = [sum(f.getmetrics()) for _, f in rows]
    block_h = sum(heights) + gap * (len(rows) - 1)
    y = int(H * y_frac - block_h / 2)

    for (ln, font), lh in zip(rows, heights):
        bbox = draw.textbbox((0, 0), ln, font=font, stroke_width=outline)
        x = (W - (bbox[2] - bbox[0])) // 2 - bbox[0]
        draw.text((x + shadow_off, y + shadow_off), ln, font=font,
                  fill=(0, 0, 0, 150), stroke_width=outline, stroke_fill=(0, 0, 0, 150))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255),
                  stroke_width=outline, stroke_fill=(0, 0, 0, 110))
        y += lh + gap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# Music bed (reuses bg-music-hq's instrumental prompt builders, but drives the
# model with prediction POLLING so a slow render never trips the client's HTTP
# read timeout — the failure mode of a blocking replicate.run long-poll).
# ---------------------------------------------------------------------------
MUSIC_MODEL = "minimax/music-2.5"

# minimax/music-2.5 SINGS whatever text sits in the `lyrics` field — including
# the parenthetical stage directions in a mood's structure template (e.g.
# "(Simple piano, hopeful)"). That's why an un-stripped template makes the model
# literally sing the instructions. The model has no is_instrumental flag, so we
# shape the vocals ourselves through the lyrics:
#   - we ALWAYS strip the stage directions (the model must never sing the
#     instructions), and then
#   - for a non-distracting bed we use soft WORDLESS vocalizations (gentle
#     oohs/aahs) under the singable sections — a warm sung quality that doesn't
#     compete with the spoken narration — or no vocals at all ("none").
# The musical/instrument intent still rides in the PROMPT (its proper field).
_STRUCT_TAG_RE = __import__("re").compile(r"^\[[^\]]+\]$")

# Sections that stay purely instrumental (no vocal line) vs. singable ones.
_INSTRUMENTAL_SECTIONS = {"inst", "solo", "break", "interlude", "transition", "build up"}
# Gentle, airy wordless lines (vowels only — never real words / instructions).
_WORDLESS_LINES = ["Ooh, ooh, ah", "Mmm, ooh", "Aah, ah, ooh", "Ooh, mmm, ah", "Aah, ooh"]


def _section_name(tag: str) -> str:
    return tag.strip().strip("[]").strip().lower()


def _bed_lyrics(raw: str, vocals: str = "wordless") -> str:
    """Build a non-distracting bed's lyrics from a mood structure template.

    Always drops the stage-direction parentheticals so the model never sings the
    instructions. ``vocals="wordless"`` adds a soft vowel-only line under each
    singable section (warm humming, no real words); ``vocals="none"`` returns
    bare structure tags (purely instrumental).
    """
    tags = [ln.strip() for ln in (raw or "").splitlines()
            if _STRUCT_TAG_RE.match(ln.strip())]
    if not tags:
        tags = ["[Intro]", "[Verse]", "[Inst]", "[Chorus]", "[Outro]"]
    if vocals == "none":
        return "\n".join(tags)
    out, vi = [], 0
    for tag in tags:
        out.append(tag)
        if _section_name(tag) not in _INSTRUMENTAL_SECTIONS:
            out.append(_WORDLESS_LINES[vi % len(_WORDLESS_LINES)])
            vi += 1
    return "\n".join(out)


def _bed_prompt(style_prompt: str, vocals: str = "wordless") -> str:
    """Reinforce the desired vocal treatment (wordless & unobtrusive, or none)."""
    if vocals == "none":
        suffix = ("purely instrumental, instrumental only, no vocals, no voice, "
                  "no singing, no lyrics, no spoken word, no choir")
    else:
        suffix = ("soft wordless background vocals only — gentle airy oohs and "
                  "aahs, warm and atmospheric, mixed low and unobtrusive, never "
                  "overpowering, no real words, no spoken word, no rap, no narration")
    sp = (style_prompt or "").strip()
    return f"{sp}, {suffix}" if sp else suffix


def _load_bgm_module():
    p = str(C.HOME_SKILLS / "bg-music-hq/scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    import generate_bgm_hq as bgm  # noqa: E402
    return bgm


def _run_replicate_polling(model, inputs, token, *, timeout=480, interval=4):
    """Create a prediction and poll until it settles. Returns the output URL."""
    import time

    import httpx
    import replicate

    client = replicate.Client(api_token=token, timeout=httpx.Timeout(60.0))
    pred = client.predictions.create(model=model, input=inputs)
    start = time.time()
    while pred.status not in ("succeeded", "failed", "canceled"):
        if time.time() - start > timeout:
            print(f"  Warning: music render exceeded {timeout}s; giving up.", file=sys.stderr)
            try:
                pred.cancel()
            except Exception:  # noqa: BLE001
                pass
            return None
        time.sleep(interval)
        try:
            pred.reload()
        except Exception as e:  # noqa: BLE001  (transient network blips while polling)
            print(f"  (poll retry: {e})", file=sys.stderr)
    if pred.status != "succeeded":
        print(f"  Warning: music render {pred.status}: {getattr(pred, 'error', '')}",
              file=sys.stderr)
        return None
    out = pred.output
    if isinstance(out, (list, tuple)):
        out = out[0] if out else None
    return str(out) if out else None


def _loop_to_length(path, target_seconds):
    """Loop an audio file (seamless re-encode) until it covers target_seconds.

    Background beds from the model are often shorter than the reel; without this
    the fixed-volume mix (duration=first) would drop the bed partway through.
    A short crossfade between repeats hides the loop seam.
    """
    p = Path(path)
    cur = C.ffprobe_duration(p)
    if cur <= 0 or cur >= target_seconds - 0.1:
        return str(p)
    reps = int(target_seconds // cur) + 2
    xf = min(1.5, max(0.3, cur * 0.1))  # short crossfade to mask the seam
    tmp = p.with_name(p.stem + ".loop.mp3")
    # Build an acrossfade chain across `reps` copies of the same input.
    inputs = []
    for _ in range(reps):
        inputs += ["-i", str(p)]
    if reps >= 2:
        parts, prev = [], "[0:a]"
        for i in range(1, reps):
            out = f"[a{i}]"
            parts.append(f"{prev}[{i}:a]acrossfade=d={xf:.3f}:c1=tri:c2=tri{out}")
            prev = out
        fc = ";".join(parts)
        args = inputs + ["-filter_complex", fc, "-map", prev,
                         "-t", f"{target_seconds:.3f}",
                         "-c:a", "libmp3lame", "-q:a", "2", "-ar", "44100", str(tmp)]
    else:
        args = ["-stream_loop", "-1", "-i", str(p), "-t", f"{target_seconds:.3f}",
                "-c:a", "libmp3lame", "-q:a", "2", "-ar", "44100", str(tmp)]
    if C.run_ffmpeg(args, description=f"Loop music to {target_seconds:.1f}s") and tmp.exists():
        tmp.replace(p)
    return str(p)


def _bgm_cache_dir(reel_dir):
    """Avatar-scoped shared cache for RAW (un-trimmed) music beds, so a track is
    generated once and reused across reel attempts / versions of that avatar."""
    d = reel_dir.parent / "_bgm_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bgm_key(prompt, mood_key, vocals):
    """Stable key for a bed: same prompt + mood + vocals ⇒ same track (reused).
    Change any of them and you get a fresh generation (and a new cache entry)."""
    import hashlib
    raw = f"{mood_key}|{vocals}|{(prompt or '').strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _finalize_bed(raw_src, dst, duration, bgm):
    """Fit a RAW cached track to THIS reel: copy -> loop -> trim -> fade.

    The cache holds the full-length raw track (duration-agnostic); each reel
    derives its own bed from it, so different-length reels reuse the same source.
    """
    import shutil
    shutil.copyfile(raw_src, dst)
    _loop_to_length(dst, int(duration) + 1)
    bgm.trim_duration(str(dst), int(duration) + 1)
    bgm.apply_fades(str(dst), fade_in_ms=800, fade_out_ms=2000)
    return dst if Path(dst).exists() else None


def generate_music(reel_dir, duration, *, mood, prompt, token, regen=False, vocals="wordless"):
    music = reel_dir / "music.mp3"
    if music.exists() and not regen:
        print(f"  [cache] music bed -> {music.name}", file=sys.stderr)
        return music
    try:
        bgm = _load_bgm_module()
    except Exception as e:  # noqa: BLE001
        print(f"  Warning: could not load bg-music-hq ({e}); skipping music.", file=sys.stderr)
        return None

    moods = bgm.load_moods()
    mood_key = mood if mood in moods else "generic"
    cache = _bgm_cache_dir(reel_dir)
    key = _bgm_key(prompt, mood_key, vocals)
    raw = cache / f"{key}.mp3"

    # Shared cache hit: a good track for this prompt/mood/vocals already exists —
    # reuse it (just re-fit to this reel's length) instead of paying to regenerate.
    if raw.exists() and not regen:
        print(f"  [cache] reusing shared bgm {key} (mood={mood_key}, vocals={vocals}) "
              f"<- {cache.name}/{raw.name}", file=sys.stderr)
        return _finalize_bed(raw, music, duration, bgm)

    # Style/instrumentation goes in the PROMPT; the lyrics field carries only
    # structure tags + (optionally) soft wordless vocals — never the stage
    # directions, so the model can't sing the instructions (see note above).
    style_prompt = _bed_prompt(bgm.build_prompt(prompt, mood_key, moods), vocals)
    lyrics = _bed_lyrics(bgm.build_lyrics_from_mood(mood_key, moods), vocals)
    inputs = {"lyrics": lyrics, "prompt": style_prompt,
              "sample_rate": 44100, "bitrate": 256000, "audio_format": "mp3"}

    print(f"\n  >>> music bed ({mood_key}) via {MUSIC_MODEL} (this may take 1-3 min)...",
          file=sys.stderr)
    print(f"      prompt: {style_prompt[:110]}...", file=sys.stderr)
    url = _run_replicate_polling(MUSIC_MODEL, inputs, token)
    if not url:
        print("  Warning: music generation failed; finishing without music.", file=sys.stderr)
        return None

    # Cache the RAW (full-length, un-trimmed) track + metadata, then fit a copy to
    # this reel. MiniMax returns a variable-length clip; _finalize_bed loops it to
    # cover the whole narration so the fixed-volume mix never drops out.
    bgm.download_file(url, raw)
    C.save_json(cache / f"{key}.json", {
        "key": key, "mood": mood_key, "vocals": vocals, "prompt": prompt,
        "style_prompt": style_prompt, "model": MUSIC_MODEL,
    })
    print(f"  cached shared bgm {key} -> {cache.name}/{raw.name}", file=sys.stderr)
    return _finalize_bed(raw, music, duration, bgm)


def mux_final(video_for_final, narration, music, out, *, music_volume,
              master_lufs=MASTER_LUFS):
    """Mux narration onto the (silent) video, with an optional FIXED-volume bed.

    The music sits at a constant low level under the voice (no sidechain ducking,
    so it never pumps up and down with the speech) — the voice stays clearly on
    top because the bed is quiet and instrumental.

    The mixed audio is loudness-normalized to ``master_lufs`` (default -16 LUFS,
    the spoken-word standard) so the voice plays at a proper level instead of the
    TTS narration's quiet native level (~-24 LUFS). Pass ``master_lufs=None`` to
    keep the source level untouched.
    """
    ln = _loudnorm_filter(master_lufs)
    desc_tail = f" [master {master_lufs} LUFS]" if ln else ""
    if not music:
        # Single audio input -> a plain -af chain is enough.
        af = ln or "anull"
        return C.run_ffmpeg(
            ["-i", str(video_for_final), "-i", str(narration),
             "-map", "0:v", "-map", "1:a", "-af", af,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
             "-shortest", str(out)],
            description=f"Mux narration (no music){desc_tail}",
        )
    mix_tail = f",{ln}" if ln else ""
    fc = (
        "[1:a]aresample=44100,aformat=channel_layouts=stereo[v0];"
        f"[2:a]volume={music_volume},aresample=44100,aformat=channel_layouts=stereo[m0];"
        f"[v0][m0]amix=inputs=2:duration=first:normalize=0{mix_tail}[a]"
    )
    return C.run_ffmpeg(
        ["-i", str(video_for_final), "-i", str(narration), "-i", str(music),
         "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
         "-shortest", str(out)],
        description=f"Mux narration + fixed-volume music (vol {music_volume}){desc_tail}",
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def resolve_reel(arg: Path):
    """Return (reel_dir, manifest_dict). ``arg`` may be a dir or a manifest path."""
    p = Path(arg).expanduser().resolve()
    if p.is_file():
        return p.parent, C.load_json(p)
    manifest = p / "reel_manifest.json"
    if manifest.exists():
        return p, C.load_json(manifest)
    return p, {}


def finish(reel_dir, *, subtitles=True, music=True, music_mood=DEFAULT_MUSIC_MOOD,
           music_prompt=DEFAULT_MUSIC_PROMPT, music_volume=0.12, music_vocals="wordless",
           max_words=6, emphasis=True, casing="subtitle", fontsize=None, y_frac=None,
           regular_font=None, emph_font=None, style_profile=None, regen_music=False,
           master_lufs=MASTER_LUFS, manifest=None, token=None):
    reel_dir = Path(reel_dir).expanduser().resolve()
    manifest = manifest if manifest is not None else (
        C.load_json(reel_dir / "reel_manifest.json")
        if (reel_dir / "reel_manifest.json").exists() else {}
    )

    # A subtitle-style profile (e.g. captured by avatar-frames from the analyzed
    # reels) seeds the measurable params; explicit args still win. NOTE: only
    # "upper" casing is trusted from the profile — OCR lowercases its output, so a
    # reported "lower" is unreliable; we keep natural casing in that case.
    sp = style_profile or {}
    eff_y_frac = float(y_frac) if y_frac is not None else float(sp.get("y_frac", 0.66))
    if casing in ("natural", "subtitle") and sp.get("casing") == "upper":
        casing = "upper"

    video_track = Path(manifest.get("video_track") or (reel_dir / "video_track.mp4"))
    narration = Path(manifest.get("narration") or (reel_dir / "narration.mp3"))
    align_path = Path(manifest.get("align") or (reel_dir / "narration.align.json"))
    W = int(manifest.get("width") or 1080)
    H = int(manifest.get("height") or 1920)
    fps = int(manifest.get("fps") or 30)
    for label, pth in [("video_track", video_track), ("narration", narration)]:
        if not pth.exists():
            raise SystemExit(f"Missing {label}: {pth}")

    total_dur = float(manifest.get("narration_duration") or 0.0) or C.ffprobe_duration(narration)
    vp, vc = C.get_video_pipeline()

    # --- Subtitles: render PNGs, burn via overlay_titles ---
    video_for_final = video_track
    caps = []
    reg_font = emp_font = None
    fs = 0
    if subtitles:
        if not align_path.exists():
            print(f"  Warning: no alignment at {align_path}; skipping subtitles.", file=sys.stderr)
        else:
            align = C.load_json(align_path)
            words = align.get("words") or []
            reg_font, emp_font = pick_fonts(regular_font, emph_font)
            frac = min(0.085, max(0.05, float(sp.get("fontsize_frac", 0.072))))
            fs = int(fontsize or round(W * frac))
            # A measurer at the NOMINAL font: captions that wouldn't fit (and would
            # otherwise shrink) are split into sequential captions instead.
            from PIL import Image as _I, ImageDraw as _ID
            _mdraw = _ID.Draw(_I.new("RGBA", (W, 240)))
            _max_w = int(W * 0.84)

            def _fit(ev):
                _r, nu, nl = _layout(_mdraw, ev, casing, reg_font, emp_font, fs, _max_w)
                if ev.get("emph") and ev.get("upper"):
                    return nu <= 1 and nl <= 1
                return (nu + nl) <= 2

            caps = build_caption_events(words, total_dur, max_words=max_words,
                                        emphasis=emphasis, fit=_fit)
            caps_dir = reel_dir / "captions"
            caps_dir.mkdir(parents=True, exist_ok=True)
            print(f"  Rendering {len(caps)} captions "
                  f"({Path(reg_font).name} / {Path(emp_font).name}, {fs}px, "
                  f"casing={casing}, y={eff_y_frac})...", file=sys.stderr)
            titles = []
            for i, ev in enumerate(caps):
                png = caps_dir / f"cap_{i:03d}.png"
                render_caption_png(ev, png, W=W, H=H, regular_font=reg_font,
                                   emph_font=emp_font, fontsize=fs,
                                   y_frac=eff_y_frac, casing=casing)
                titles.append({"path": str(png), "in_at": ev["in"], "out_at": ev["out"]})
            video_sub = reel_dir / "video_sub.mp4"
            if not vp.overlay_titles(str(video_track), titles, str(video_sub),
                                     target_w=W, target_h=H):
                raise SystemExit("Failed to burn in subtitles.")
            video_for_final = video_sub

    # --- Music bed ---
    music_path = None
    if music:
        tok = token or C.get_replicate_token()
        music_path = generate_music(reel_dir, total_dur, mood=music_mood,
                                    prompt=music_prompt, token=tok, regen=regen_music,
                                    vocals=music_vocals)

    # --- Final mux ---
    final_path = reel_dir / "final.mp4"
    if not mux_final(video_for_final, narration, music_path, final_path,
                     music_volume=music_volume, master_lufs=master_lufs):
        raise SystemExit("Failed to mux the finished reel.")

    final_info = vc.ffprobe_video(final_path)

    # --- Update manifest ---
    if manifest:
        # A fresh finish overwrites final.mp4, so any previous polish (fx) pass
        # no longer applies — clear the marker so polish_reel treats this
        # final.mp4 as the new clean source.
        manifest.pop("fx", None)
        manifest["final"] = str(final_path)
        manifest["final_info"] = final_info
        manifest["finish"] = {
            "applied_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "subtitles": bool(subtitles and caps),
            "caption_count": len(caps),
            "caption_unit_max_words": max_words,
            "caption_style": "serif_phrase_setup_payoff",
            "caption_progression": "phrase_replace",
            "caption_emphasis": "payoff_bold_italic" if emphasis else "none",
            "caption_font": Path(reg_font).name if reg_font else None,
            "caption_emph_font": Path(emp_font).name if emp_font else None,
            "caption_fontsize": fs or None,
            "caption_casing": casing,
            "caption_y_frac": eff_y_frac,
            "music": bool(music_path),
            "music_path": str(music_path) if music_path else None,
            "music_mood": music_mood if music_path else None,
            "music_volume": music_volume if music_path else None,
            "music_vocals": music_vocals if music_path else None,
            "music_mix": "fixed_volume" if music_path else None,
            "music_model": "minimax/music-2.5 (via bg-music-hq)" if music_path else None,
            "master_lufs": float(master_lufs) if master_lufs is not None else None,
            "master_tp": MASTER_TP if master_lufs is not None else None,
            "master_lra": MASTER_LRA if master_lufs is not None else None,
        }
        C.save_json(reel_dir / "reel_manifest.json", manifest)

    print(f"\nFinished reel: {final_path}", file=sys.stderr)
    print(f"  {final_info.get('width')}x{final_info.get('height')} @ "
          f"{final_info.get('fps')}fps  |  {final_info.get('duration'):.2f}s  |  "
          f"captions={len(caps)}  music={'yes' if music_path else 'no'}", file=sys.stderr)
    return {
        "final": str(final_path),
        "reel_dir": str(reel_dir),
        "duration": final_info.get("duration"),
        "captions": len(caps),
        "music": str(music_path) if music_path else None,
    }


def load_style_profile(path):
    """Load a subtitle-style profile from a JSON file. Accepts either a bare
    profile or a wrapper that contains a ``subtitle_style`` block (e.g. an
    avatar-frames manifest.json)."""
    if not path:
        return None
    data = C.load_json(path)
    return data.get("subtitle_style", data) if isinstance(data, dict) else None


def main():
    ap = argparse.ArgumentParser(
        description="Finishing pass: burn in phrase-unit subtitles (serif setup line "
                    "+ bold-italic payoff, matching the analyzed reels) + a fixed-volume music bed.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("reel", type=Path, help="Reel folder (or its reel_manifest.json)")
    ap.add_argument("--no-subtitles", dest="subtitles", action="store_false",
                    help="Skip burned-in captions")
    ap.add_argument("--no-music", dest="music", action="store_false",
                    help="Skip the background music bed")
    ap.add_argument("--music-mood", default=DEFAULT_MUSIC_MOOD,
                    help=f"bg-music-hq mood preset (default: {DEFAULT_MUSIC_MOOD})")
    ap.add_argument("--music-prompt", default=DEFAULT_MUSIC_PROMPT,
                    help="Music style description (TAILOR to the reel's emotional tone)")
    ap.add_argument("--music-volume", type=float, default=0.12,
                    help="FIXED music level under the voice (0-1, default 0.12)")
    ap.add_argument("--music-vocals", choices=["none", "wordless"], default="wordless",
                    help="Bed vocals: 'wordless' soft oohs/aahs (default, non-distracting) "
                         "or 'none' (purely instrumental). Stage directions are never sung.")
    ap.add_argument("--regen-music", action="store_true",
                    help="Regenerate music.mp3 even if it exists")
    ap.add_argument("--max-words", type=int, default=6,
                    help="Max words per caption phrase unit (default 6)")
    ap.add_argument("--no-emphasis", dest="emphasis", action="store_false",
                    help="Disable the bold-italic payoff highlight (plain single-line phrases)")
    ap.add_argument("--casing", choices=["subtitle", "natural", "lower", "upper"],
                    default="subtitle",
                    help="Caption casing (default: subtitle — lowercase like the analyzed "
                         "reels, but intentional ALL-CAPS words like REPE/NO stay shouted; "
                         "'natural' preserves the ASR/script casing verbatim)")
    ap.add_argument("--fontsize", type=int, default=None,
                    help="Caption font size in px (default ~6.3%% of width)")
    ap.add_argument("--y-frac", type=float, default=None,
                    help="Vertical center of captions as a fraction of height "
                         "(default: profile's value, else 0.66)")
    ap.add_argument("--regular-font", default=None, help="Override the regular caption font (TTF)")
    ap.add_argument("--emph-font", default=None, help="Override the emphasis (bold-italic) font (TTF)")
    ap.add_argument("--style-from", default=None,
                    help="JSON with a subtitle-style profile (e.g. an avatar-frames "
                         "manifest) to seed position/size/casing from the analyzed reels")
    ap.add_argument("--master-lufs", type=float, default=MASTER_LUFS,
                    help=f"Master loudness target for the final mux in LUFS "
                         f"(default {MASTER_LUFS}, the spoken-word standard; "
                         f"TP {MASTER_TP} dBTP, LRA {MASTER_LRA}). The TTS narration is "
                         f"quiet (~-24 LUFS) on its own, so this keeps the voice audible.")
    ap.add_argument("--no-master", dest="master_lufs", action="store_const", const=None,
                    help="Disable master loudness normalization (keep the source level, "
                         "e.g. for an already-mastered narration)")
    args = ap.parse_args()

    reel_dir, manifest = resolve_reel(args.reel)
    res = finish(
        reel_dir, subtitles=args.subtitles, music=args.music,
        music_mood=args.music_mood, music_prompt=args.music_prompt,
        music_volume=args.music_volume, music_vocals=args.music_vocals,
        max_words=args.max_words,
        emphasis=args.emphasis,
        casing=args.casing, fontsize=args.fontsize, y_frac=args.y_frac,
        regular_font=args.regular_font, emph_font=args.emph_font,
        style_profile=load_style_profile(args.style_from),
        regen_music=args.regen_music, master_lufs=args.master_lufs, manifest=manifest,
    )
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
