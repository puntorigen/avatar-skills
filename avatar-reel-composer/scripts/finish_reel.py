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

  2. MUSIC BED  -- a light instrumental track from bg-music-hq under the narration
     (no ducking), tailored to the reel's emotional tone. By default it plays at a
     FIXED low volume; with a music PLAN (or --music-structure auto) it instead
     follows a VOLUME ENVELOPE that does editing work — a hard-cut entrance, a
     lift/settle at an emotional shift, a duck under a key line, a resolve into the
     close — anchored to scene boundaries (the rule-of-six-edit `sound` axis made
     audible). See compile_music_plan / build_music_env.

Idempotent: reuses an existing music.mp3 unless --regen-music (the envelope is
recomputed cheaply at mux time, so structure changes never regenerate audio).
Re-runnable on any reel folder, so you can iterate on caption style / music
without regenerating any video.

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
        strong = bool(txt[-1] in STRONG_PUNCT) or nxt is None
        if strong or gap > max_gap:
            # Record whether this boundary is a real phrase end (strong punctuation
            # / end of narration) vs. merely a speech PAUSE. A slow or meditative
            # delivery pauses AFTER a leading connector ("Y…", "Cada…", "Pero…"),
            # which would otherwise strand it as its own lone caption.
            groups.append({"ws": cur, "strong": strong})
            cur = []
    if cur:
        groups.append({"ws": cur, "strong": True})

    # Merge a short (<=2-word) fragment that was split off by a PAUSE (not a real
    # phrase end) forward into the next phrase, so a leading connector rides with
    # the words it introduces instead of flashing alone on screen.
    merged: list[dict] = []
    i = 0
    while i < len(groups):
        g = groups[i]
        if len(g["ws"]) <= 2 and not g["strong"] and i + 1 < len(groups):
            groups[i + 1]["ws"] = g["ws"] + groups[i + 1]["ws"]
            i += 1
            continue
        merged.append(g)
        i += 1

    units = []  # each: (unit_words, ends_group)
    for g in merged:
        chunks = _subdivide_group(g["ws"], max_words)
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
    only on a breath group's completion and only when there are enough words.

    ``n_upper`` records how many leading words go on the regular SETUP line (the
    rest are the payoff): the word-by-word reveal needs this split so it can place
    each aligned word in the right line/font while keeping the full-phrase layout
    locked."""
    if emphasis and ends_group and len(ws) >= min_split:
        setup, payoff = split_unit(ws)
        if payoff:
            return {"upper": _txt(setup), "lower": _txt(payoff), "emph": True,
                    "ws": ws, "n_upper": len(setup)}
    return {"upper": None, "lower": _txt(ws), "emph": False, "ws": ws, "n_upper": 0}


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
                       "upper": ev["upper"], "lower": ev["lower"], "emph": ev["emph"],
                       "words": ws, "n_upper": ev.get("n_upper", 0)})
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


def _caption_max_w(W, H) -> int:
    """Max text width for caption wrapping. Landscape (16:9 YouTube) wraps into a
    narrower band than the very wide frame so lines stay readable; portrait/square
    keep the original 84% band."""
    return int(W * (0.70 if W > H else 0.84))


def _default_caption_y_frac(W, H) -> float:
    """Default vertical center for the caption block: a lower-third for landscape
    (16:9), the original ~two-thirds line for portrait/square."""
    return 0.85 if W > H else 0.66


def _caption_font_ref(W, H) -> int:
    """Reference dimension for caption font sizing: the SHORTER side, so a 16:9
    frame is sized like a 9:16 one instead of ballooning off the 1920px width."""
    return min(W, H)


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
    max_w = _caption_max_w(W, H)
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
# Word-by-word (karaoke) caption reveal
#
# Same phrase UNITS and setup/payoff styling as the static captions, but each
# aligned word APPEARS at the moment it's spoken, building the phrase up in
# place. The trick that keeps it from looking janky: the layout (wrap, font size,
# every word's x/y) is computed ONCE from the FULL phrase and then frozen, so a
# word lands exactly where it will sit in the finished line — nothing reflows or
# recenters as words arrive. Already-spoken words stay lit; the phrase clears
# (blank) only when the next phrase begins, exactly like the static "replace"
# progression. All the reveal states are baked into ONE transparent overlay track
# (see build_reveal_track) so compositing stays a single overlay, not ~500.
# ---------------------------------------------------------------------------
def _event_tokens(event, casing):
    """Return (tokens, times, split_at) for a caption event's word reveal.

    ``tokens`` are the per-word display strings (casing applied), one per aligned
    word, with trailing sentence punctuation stripped from the last token of the
    setup group and of the payoff group (mirroring ``_txt``). ``times`` are the
    matching spoken start times. ``split_at`` is the token index where the
    bold-italic payoff begins (0 when the event has no separate setup line).
    """
    ws = event.get("words") or []
    n_upper = int(event.get("n_upper") or 0)
    toks, times, upper_kept = [], [], 0
    for lo, hi, is_upper in ((0, n_upper, True), (n_upper, len(ws), False)):
        seg = ws[lo:hi]
        for j, w in enumerate(seg):
            raw = (w.get("word") or "").strip()
            if j == len(seg) - 1:  # social convention: no trailing .,;:… on a line
                raw = raw.rstrip(" ,;:.…")
            disp = apply_casing(raw, casing) if raw else ""
            if not disp:
                continue
            toks.append(disp)
            times.append(float(w.get("start", 0.0)))
            if is_upper:
                upper_kept += 1
    return toks, times, upper_kept


def _reveal_fit_fs(draw, tokens, split_at, emph, regular_font, emph_font,
                   fontsize, max_w, max_lines=2):
    """Pick the font size for a reveal event using the SAME fit rule as the static
    renderer (emphasis -> 1 setup line + 1 payoff line; plain -> <= max_lines),
    shrinking to a floor. Locking size here means the frozen layout matches what
    the static caption would have looked like."""
    from PIL import ImageFont

    floor = max(48, int(fontsize * 0.80))
    upper = tokens[:split_at]
    lower = tokens[split_at:]
    fs = int(fontsize)
    while True:
        reg = ImageFont.truetype(regular_font, fs)
        low_font = ImageFont.truetype(emph_font, fs) if emph else reg
        nu = len(_wrap_balanced(draw, " ".join(upper), reg, max_w)) if upper else 0
        nl = len(_wrap_balanced(draw, " ".join(lower), low_font, max_w)) if lower else 0
        ok = (nu <= 1 and nl <= 1) if (emph and upper) else ((nu + nl) <= max_lines)
        if ok or fs <= floor:
            return fs
        fs = max(floor, int(fs * 0.94))


def _positioned_tokens(draw, tokens, split_at, emph, regular_font, emph_font,
                       fs, max_w, W, H, y_frac):
    """Freeze the full-phrase layout: return a per-word list of
    ``(x, y, font, text, outline, shadow)`` in reveal order. Words are wrapped and
    centered exactly as the static caption (setup line[s] then payoff line[s]);
    each word's x is its offset inside its centered line, so drawing the first k
    words reproduces the head of the finished phrase with no shift."""
    from PIL import ImageFont

    reg = ImageFont.truetype(regular_font, fs)
    emp = ImageFont.truetype(emph_font, fs) if emph else reg
    low_font = emp if emph else reg
    upper_toks = tokens[:split_at]
    lower_toks = tokens[split_at:]
    upper_lines = _wrap_balanced(draw, " ".join(upper_toks), reg, max_w) if upper_toks else []
    lower_lines = _wrap_balanced(draw, " ".join(lower_toks), low_font, max_w) if lower_toks else []

    outline = max(2, fs // 28)
    shadow_off = max(2, round(fs * 0.06))
    gap = max(4, round(fs * 0.18))

    rows = []  # (font, [tokens on this line])
    for lines, toks, font in ((upper_lines, upper_toks, reg),
                              (lower_lines, lower_toks, low_font)):
        k = 0
        for ln in lines:
            cnt = len(ln.split())
            rows.append((font, toks[k:k + cnt]))
            k += cnt

    heights = [sum(f.getmetrics()) for f, _ in rows]
    block_h = (sum(heights) + gap * (len(rows) - 1)) if rows else 0
    y = int(H * y_frac - block_h / 2)

    positioned = []
    for (font, toks), lh in zip(rows, heights):
        line = " ".join(toks)
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=outline)
        x0 = (W - (bbox[2] - bbox[0])) / 2 - bbox[0]
        for j, t in enumerate(toks):
            prefix = " ".join(toks[:j]) + (" " if j else "")
            dx = draw.textlength(prefix, font=font) if prefix else 0.0
            positioned.append((int(round(x0 + dx)), int(y), font, t, outline, shadow_off))
        y += lh + gap
    return positioned


def render_reveal_state(positioned, reveal_count, out_path, W, H):
    """Render one reveal frame: the first ``reveal_count`` words of the frozen
    layout, drawn at full white with the same soft shadow/outline as the static
    caption; later (not-yet-spoken) words are simply absent."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, (x, y, font, txt, outline, shadow_off) in enumerate(positioned):
        if i >= reveal_count:
            break
        draw.text((x + shadow_off, y + shadow_off), txt, font=font,
                  fill=(0, 0, 0, 150), stroke_width=outline, stroke_fill=(0, 0, 0, 150))
        draw.text((x, y), txt, font=font, fill=(255, 255, 255, 255),
                  stroke_width=outline, stroke_fill=(0, 0, 0, 110))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def build_reveal_track(events, caps_dir, *, W, H, fps, regular_font, emph_font,
                       fontsize, casing, y_frac, total_dur, max_lines=2):
    """Bake all word-reveal states into ONE transparent overlay track (qtrle .mov).

    For each phrase, freeze the layout and emit a state per word (words[0..k] lit
    from that word's spoken start). States are laid on a FRAME-SNAPPED timeline
    (every boundary rounded to the fps grid, durations accumulated in whole frames)
    so the reveal never drifts against the frame-locked picture — the same
    anti-drift discipline the video assembly uses. Gaps between phrases are a
    single reused transparent frame. Returns the track path (lossless RLE keeps the
    serif edges crisp) or None if there's nothing to show."""
    from PIL import Image as _I, ImageDraw as _ID

    mdraw = _ID.Draw(_I.new("RGBA", (W, 240)))
    max_w = _caption_max_w(W, H)
    caps_dir.mkdir(parents=True, exist_ok=True)
    blank = caps_dir / "rev_blank.png"
    _I.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank)

    keys = []  # (png_path, start_s, end_s)
    idx = 0
    for ev in sorted(events, key=lambda e: float(e["in"])):
        tokens, times, split_at = _event_tokens(ev, casing)
        if not tokens:
            continue
        ev_out = float(ev["out"])
        emph = bool(ev.get("emph"))
        fs = _reveal_fit_fs(mdraw, tokens, split_at, emph, regular_font, emph_font,
                            fontsize, max_w, max_lines)
        positioned = _positioned_tokens(mdraw, tokens, split_at, emph, regular_font,
                                        emph_font, fs, max_w, W, H, y_frac)
        n = len(tokens)
        for r in range(1, n + 1):
            start = times[r - 1]
            end = times[r] if r < n else ev_out
            png = caps_dir / f"rev_{idx:04d}.png"
            render_reveal_state(positioned, r, png, W, H)
            keys.append((png, float(start), float(end)))
            idx += 1

    if not keys:
        return None
    keys.sort(key=lambda k: k[1])

    # Frame-snapped, gap-filled, strictly monotonic timeline (durations in whole
    # frames so the concat track lands exactly on the 30fps grid — no accumulation).
    total_f = int(round((total_dur or keys[-1][2]) * fps))
    segs = []  # (png, n_frames)
    f = 0
    for png, s, e in keys:
        sf, ef = int(round(s * fps)), int(round(e * fps))
        if sf < f:
            sf = f
        if ef <= sf:
            ef = sf + 1
        if sf > f:
            segs.append((blank, sf - f))
        segs.append((png, ef - sf))
        f = ef
    if total_f > f:
        segs.append((blank, total_f - f))

    listf = caps_dir / "reveal_concat.txt"
    with open(listf, "w", encoding="utf-8") as fh:
        fh.write("ffconcat version 1.0\n")
        for png, nf in segs:
            fh.write(f"file '{Path(png).resolve()}'\n")
            fh.write(f"duration {nf / fps:.6f}\n")
        fh.write(f"file '{Path(segs[-1][0]).resolve()}'\n")  # repeat last (apply its dur)

    track = caps_dir.parent / "captions_track.mov"
    ok = C.run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(listf),
         "-r", str(fps), "-vsync", "cfr", "-c:v", "qtrle", "-pix_fmt", "argb",
         str(track)],
        description=f"Assemble word-reveal caption track ({len(segs)} states, {total_f}f)",
    )
    return track if (ok and track.exists()) else None


def overlay_reveal_track(base_video, track, out, *, W, H):
    """Composite the transparent word-reveal track over the base in one overlay
    pass (its alpha does the masking; base has no audio so 0:a? maps nothing)."""
    return C.run_ffmpeg(
        ["-i", str(base_video), "-i", str(track),
         "-filter_complex",
         "[0:v][1:v]overlay=0:0:format=auto:eof_action=pass[vout]",
         "-map", "[vout]", "-map", "0:a?",
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         str(out)],
        description="Burn in word-by-word caption reveal",
    )


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


# ---------------------------------------------------------------------------
# Structured music: an automation PLAN -> a volume ENVELOPE
#
# The bed stays ONE generated track, but instead of a flat constant volume we
# apply a time-varying gain (an ffmpeg `volume` expression, eval=frame) so the
# soundtrack can do EDITING work — the moves from rule-of-six-edit's `sound`
# axis: a hard-cut ENTRANCE, a LIFT / SETTLE at an emotional shift (the
# "variation"), a DUCK under a key line, and a RESOLVE (the gentle handoff /
# outro) into the close. Times are anchored to SCENE BOUNDARIES (read from the
# reel manifest), so the plan speaks the storyboard's language ("s3 -> s4").
# Entrance rides an `adelay` (silence before + the track landing on the cut);
# the dynamics ride the volume expression. This automates the bed's PRESENCE /
# DYNAMICS — the half of the music-editing craft an un-structured track can do;
# aligning a track's own intro/verse/chorus to a frame would need a structured
# render and is left as future work.
# ---------------------------------------------------------------------------
MUSIC_GAIN_MAX = 0.6      # hard safety cap on the bed's absolute volume
_RAMP_SUSTAINED = 0.5     # seconds for a sustained lift/settle ramp
_RAMP_TRANSIENT = 0.25    # seconds for a duck's shoulders


def _clamp_gain(g):
    try:
        g = float(g)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(MUSIC_GAIN_MAX, g))


def _scene_index(scenes):
    return {str(sc.get("id", "")).strip().lower(): sc for sc in (scenes or [])}


def resolve_anchor(at, scenes, total_dur):
    """Resolve a plan anchor to seconds. Accepts a number (seconds), 'start'/'end',
    a scene id ('s3' -> its START), or a boundary 'sA -> sB' (-> scene A's END)."""
    if isinstance(at, bool):
        return None
    if isinstance(at, (int, float)):
        return max(0.0, min(float(at), total_dur))
    s = str(at or "").strip().lower()
    if s in ("", "start", "begin"):
        return 0.0
    if s == "end":
        return total_dur
    idx = _scene_index(scenes)
    if "->" in s:
        left = s.split("->")[0].strip()
        sc = idx.get(left)
        if sc is not None:
            return max(0.0, min(float(sc.get("end", 0.0)), total_dur))
    if s in idx:
        return max(0.0, min(float(idx[s].get("start", 0.0)), total_dur))
    try:
        return max(0.0, min(float(s), total_dur))
    except ValueError:
        return None


def _interp(points, tq):
    """Linear interpolation of a time-sorted [(t,g)] list at time tq."""
    if not points:
        return 0.0
    if tq <= points[0][0]:
        return points[0][1]
    if tq >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        t0, g0 = points[i]
        t1, g1 = points[i + 1]
        if t0 <= tq <= t1 and t1 > t0:
            return g0 + (g1 - g0) * (tq - t0) / (t1 - t0)
    return points[-1][1]


def _clean_keyframes(kf, total_dur):
    """Sort + clamp into [0, total_dur], collapse duplicate times (last wins), and
    guarantee anchor points at 0 and at total_dur."""
    pts = sorted(((max(0.0, min(float(t), total_dur)), _clamp_gain(g)) for t, g in kf),
                 key=lambda p: p[0])
    out = []
    for t, g in pts:
        if out and abs(t - out[-1][0]) < 1e-6:
            out[-1] = (t, g)
        else:
            out.append((t, g))
    if not out:
        return [(0.0, 0.0), (total_dur, 0.0)]
    if out[0][0] > 0:
        out.insert(0, (0.0, out[0][1]))
    if out[-1][0] < total_dur:
        out.append((total_dur, out[-1][1]))
    return out


def compile_music_plan(moves, base, total_dur, scenes):
    """Compile high-level moves into an entrance + volume-envelope keyframes.

    Move ``type`` (each carries an ``at`` anchor resolved via ``resolve_anchor``):
      enter / enter_soft   entrance point, soft (relies on the file's fade-in)
      enter_hard           entrance point, hard (silence, then the beat on the cut)
      lift                 sustained step UP   — ``amount`` (x current, def 1.35)
      settle               sustained step DOWN — ``amount`` (def 0.6)
      duck                 transient DIP over ``span:[a,b]`` (or ``at``+``dur``) — ``amount`` (def 0.45)
      accent / swell       transient BUMP at ``at`` — ``amount`` (def 1.3), ``dur`` (def 0.5)
      resolve / handoff    decrescendo from ``at`` to the end — ``amount`` (def 0.5)

    Returns {"entrance", "entrance_hard", "keyframes":[(t,g)], "notes":[...]}.
    """
    base = _clamp_gain(base)
    notes = []
    resolved = []
    for m in (moves or []):
        t = resolve_anchor(m.get("at", "start"), scenes, total_dur)
        if t is None:
            notes.append(f"unresolved anchor {m.get('at')!r} — move skipped")
            continue
        resolved.append((t, m))
    resolved.sort(key=lambda x: x[0])

    entrance, entrance_hard = 0.0, False
    kf = [(0.0, base)]
    level = base
    # pass 1: entrance + sustained level changes, in time order
    for t, m in resolved:
        typ = str(m.get("type", "")).strip().lower()
        ramp = float(m.get("ramp", _RAMP_SUSTAINED))
        if typ in ("enter", "enter_soft"):
            entrance, entrance_hard = t, False
        elif typ in ("enter_hard", "punch_in"):
            entrance, entrance_hard = t, True
        elif typ == "lift":
            new = _clamp_gain(level * float(m.get("amount", 1.35)))
            kf += [(max(0.0, t - ramp), level), (t, new)]
            level = new
        elif typ == "settle":
            new = _clamp_gain(level * float(m.get("amount", 0.6)))
            kf += [(max(0.0, t - ramp), level), (t, new)]
            level = new
        elif typ in ("resolve", "handoff", "outro"):
            new = _clamp_gain(level * float(m.get("amount", 0.5)))
            kf += [(t, level), (total_dur, new)]
            level = new
    kf.append((total_dur, level))
    sustained = sorted(kf, key=lambda p: p[0])

    # pass 2: transients (layered over the sustained curve's local level)
    for t, m in resolved:
        typ = str(m.get("type", "")).strip().lower()
        if typ == "duck":
            span = m.get("span")
            if span and len(span) == 2:
                t0 = resolve_anchor(span[0], scenes, total_dur)
                t1 = resolve_anchor(span[1], scenes, total_dur)
            else:
                t0, t1 = t, t + float(m.get("dur", 1.2))
            if t0 is None or t1 is None or t1 <= t0:
                continue
            sh = float(m.get("ramp", _RAMP_TRANSIENT))
            amt = float(m.get("amount", 0.45))
            l0, l1 = _interp(sustained, t0), _interp(sustained, t1)
            kf += [(max(0.0, t0 - sh), l0), (t0, _clamp_gain(l0 * amt)),
                   (t1, _clamp_gain(l1 * amt)), (min(total_dur, t1 + sh), l1)]
        elif typ in ("accent", "swell", "punch"):
            l0 = _interp(sustained, t)
            amt = float(m.get("amount", 1.3))
            dur = float(m.get("dur", 0.5))
            kf += [(max(0.0, t - 0.12), l0), (t, _clamp_gain(l0 * amt)),
                   (min(total_dur, t + dur), l0)]

    return {"entrance": round(entrance, 3), "entrance_hard": entrance_hard,
            "keyframes": _clean_keyframes(kf, total_dur), "notes": notes}


def volume_envelope_expr(keyframes):
    """Build an ffmpeg `volume` expression (piecewise-linear over ``keyframes``),
    for eval=frame. Returns the RAW expression (escape it before the filtergraph)."""
    pts = []
    for t, g in keyframes:
        t, g = round(float(t), 3), round(_clamp_gain(g), 4)
        if pts and t <= pts[-1][0]:
            t = round(pts[-1][0] + 0.002, 3)  # strictly increasing (no zero div)
        pts.append((t, g))
    if not pts:
        return None
    if len(pts) == 1:
        return str(pts[0][1])
    expr = f"{pts[-1][1]}"
    for i in range(len(pts) - 2, -1, -1):
        t0, g0 = pts[i]
        t1, g1 = pts[i + 1]
        seg = f"({g0}+({g1}-{g0})*(t-{t0})/({t1}-{t0}))"
        expr = f"if(lt(t,{t1}),{seg},{expr})"
    return expr


def _escape_expr(expr):
    """Escape a volume expression for embedding in a -filter_complex string."""
    return expr.replace("\\", "\\\\").replace(",", "\\,")


def auto_music_plan(scenes, *, total_dur):
    """A tasteful default envelope from the reel's scene structure: soft enter, a
    gentle duck under the hook so the opening voice punches, a small lift after the
    hook, and a resolve (handoff) over the final scene."""
    scenes = scenes or []
    moves = [{"type": "enter", "at": 0.0}]
    if scenes:
        moves.append({"type": "duck", "span": [0.0, float(scenes[0].get("end", 0.0))],
                      "amount": 0.6})
        if len(scenes) >= 3:
            moves.append({"type": "lift", "at": float(scenes[1].get("end", 0.0)),
                          "amount": 1.18})
        moves.append({"type": "resolve", "at": float(scenes[-1].get("start", total_dur)),
                      "amount": 0.55})
    return moves


# Keyword sets for mapping a rule-of-six-edit cut sheet's freeform `sound` notes.
_SND_SPLIT = ("split", "runs across", "voz cruza", "sin golpe", "no beat")
_SND_HARD = ("hard-cut", "hard cut", "punch", "beat on the", "golpe", "corte seco")
_SND_OUTRO = ("outro", "handoff", "entrega", "resolve", "resoluci", "close", "cierre")
_SND_DOWN = ("settle", "asienta", "mellow", "quiet", "baja", "calm", "down", "fast->mellow", "loud->quiet")
_SND_UP = ("variation", "variaci", "shift", "giro", "lift", "sube", "rise", "loud", "build", "up")
_SND_ENTER = ("intro", "enter", "entra", "silence", "silencio")


def music_plan_from_cutsheet(cutsheet_path, scenes):
    """Best-effort bridge: read a rule-of-six-edit ``*.cutsheet.json`` and turn each
    cut's ``sound`` note (anchored at its ``at``, e.g. 's3 -> s4') into a music move.

    This is the literal handoff from the edit plan; for precise control author a
    ``music_plan`` directly. Returns (moves, soundtrack_note)."""
    data = C.load_json(cutsheet_path)
    st = str(data.get("soundtrack") or "").strip()
    if st.lower().startswith("todo"):
        st = ""
    moves, first_enter = [], False
    for cut in data.get("cuts", []) or []:
        snd = (cut.get("sound") or "").strip()
        if not snd or snd.lower().startswith("todo"):
            continue
        at, low = cut.get("at") or "", snd.lower()
        if any(k in low for k in _SND_SPLIT):
            continue  # the running voice carries the cut — no gain move
        if any(k in low for k in _SND_HARD):
            if not first_enter and any(k in low for k in _SND_ENTER):
                moves.append({"type": "enter_hard", "at": at}); first_enter = True
            else:
                moves.append({"type": "accent", "at": at})
        elif any(k in low for k in _SND_OUTRO):
            moves.append({"type": "resolve", "at": at})
        elif any(k in low for k in _SND_DOWN):
            moves.append({"type": "settle", "at": at})
        elif any(k in low for k in _SND_UP):
            moves.append({"type": "lift", "at": at})
        # unclassified -> leave the bed flat at that cut
    return moves, st


def build_music_env(*, music_structure, music_plan, music_from_cutsheet,
                    music_volume, total_dur, scenes):
    """Resolve the music automation from (in priority) an explicit plan, a cut
    sheet, or the 'auto' structure. Returns
    {"expr": escaped_expr|None, "entrance": s, "mix": str, "source": str,
     "moves": [...], "keyframes": [...], "soundtrack": note, "notes": [...]}
    where expr=None means keep the flat fixed-volume bed."""
    flat = {"expr": None, "entrance": 0.0, "mix": "fixed_volume", "source": "flat",
            "moves": None, "keyframes": None, "soundtrack": None, "notes": []}
    moves, source, soundtrack = None, "flat", None
    if music_plan:
        moves = list(music_plan.get("moves", music_plan) if isinstance(music_plan, dict) else music_plan)
        source = "plan"
    elif music_from_cutsheet:
        moves, soundtrack = music_plan_from_cutsheet(music_from_cutsheet, scenes)
        source = "cutsheet"
    elif str(music_structure).lower() == "auto":
        moves = auto_music_plan(scenes, total_dur=total_dur)
        source = "auto"
    if not moves:
        flat["soundtrack"] = soundtrack
        return flat

    compiled = compile_music_plan(moves, music_volume, total_dur, scenes)
    raw = volume_envelope_expr(compiled["keyframes"])
    if not raw:
        flat["soundtrack"] = soundtrack
        return flat
    return {"expr": _escape_expr(raw), "entrance": compiled["entrance"],
            "mix": f"automated:{source}", "source": source, "moves": moves,
            "keyframes": compiled["keyframes"], "soundtrack": soundtrack,
            "notes": compiled["notes"]}


def mux_final(video_for_final, narration, music, out, *, music_volume,
              master_lufs=MASTER_LUFS, music_expr=None, music_entrance=0.0):
    """Mux narration onto the (silent) video, with an optional music bed.

    The bed sits under the voice with no sidechain ducking. By default it plays at
    a constant ``music_volume``; when ``music_expr`` (a pre-escaped ffmpeg volume
    expression, eval=frame) is given it instead follows a VOLUME ENVELOPE — the
    structured "soundtrack move" automation (enter / lift / settle / duck /
    resolve). ``music_entrance`` (seconds) delays the bed so it lands on a cut
    (silence before). The voice always stays clearly on top (the bed is quiet).

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
    if music_expr:
        vol_part = f"volume=eval=frame:volume={music_expr}"
        mode = "automated env"
    else:
        vol_part = f"volume={music_volume}"
        mode = f"fixed vol {music_volume}"
    delay_part = ""
    if music_entrance and music_entrance > 0.01:
        delay_part = f"adelay={int(round(music_entrance * 1000))}:all=1,"
        mode += f", enter @ {music_entrance:.2f}s"
    fc = (
        "[1:a]aresample=44100,aformat=channel_layouts=stereo[v0];"
        f"[2:a]{delay_part}{vol_part},aresample=44100,aformat=channel_layouts=stereo[m0];"
        f"[v0][m0]amix=inputs=2:duration=first:normalize=0{mix_tail}[a]"
    )
    return C.run_ffmpeg(
        ["-i", str(video_for_final), "-i", str(narration), "-i", str(music),
         "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
         "-shortest", str(out)],
        description=f"Mux narration + music ({mode}){desc_tail}",
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
           music_structure="flat", music_plan=None, music_from_cutsheet=None,
           max_words=6, emphasis=True, casing="subtitle", fontsize=None, y_frac=None,
           caption_reveal="word",
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
    video_track = Path(manifest.get("video_track") or (reel_dir / "video_track.mp4"))
    narration = Path(manifest.get("narration") or (reel_dir / "narration.mp3"))
    align_path = Path(manifest.get("align") or (reel_dir / "narration.align.json"))
    W = int(manifest.get("width") or 1080)
    H = int(manifest.get("height") or 1920)
    fps = int(manifest.get("fps") or 30)

    # Caption placement defaults follow the output geometry: a lower-third for
    # 16:9 landscape (YouTube), the original ~two-thirds line for portrait/square.
    # An explicit --y-frac wins; a profile y_frac is trusted only for
    # portrait/square (it is captured from vertical reels, so it would sit too
    # high on a wide frame).
    default_y = _default_caption_y_frac(W, H)
    if y_frac is not None:
        eff_y_frac = float(y_frac)
    elif "y_frac" in sp and W <= H:
        eff_y_frac = float(sp["y_frac"])
    else:
        eff_y_frac = default_y
    if casing in ("natural", "subtitle") and sp.get("casing") == "upper":
        casing = "upper"
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
            fs = int(fontsize or round(_caption_font_ref(W, H) * frac))
            # A measurer at the NOMINAL font: captions that wouldn't fit (and would
            # otherwise shrink) are split into sequential captions instead.
            from PIL import Image as _I, ImageDraw as _ID
            _mdraw = _ID.Draw(_I.new("RGBA", (W, 240)))
            _max_w = _caption_max_w(W, H)

            def _fit(ev):
                _r, nu, nl = _layout(_mdraw, ev, casing, reg_font, emp_font, fs, _max_w)
                if ev.get("emph") and ev.get("upper"):
                    return nu <= 1 and nl <= 1
                return (nu + nl) <= 2

            caps = build_caption_events(words, total_dur, max_words=max_words,
                                        emphasis=emphasis, fit=_fit)
            caps_dir = reel_dir / "captions"
            caps_dir.mkdir(parents=True, exist_ok=True)
            video_sub = reel_dir / "video_sub.mp4"

            if caption_reveal == "word":
                # Karaoke reveal: words appear as spoken, baked into one alpha track.
                print(f"  Rendering word-by-word reveal for {len(caps)} phrase(s) "
                      f"({Path(reg_font).name} / {Path(emp_font).name}, {fs}px, "
                      f"casing={casing}, y={eff_y_frac})...", file=sys.stderr)
                track = build_reveal_track(
                    caps, caps_dir, W=W, H=H, fps=fps, regular_font=reg_font,
                    emph_font=emp_font, fontsize=fs, casing=casing, y_frac=eff_y_frac,
                    total_dur=total_dur)
                if not track or not overlay_reveal_track(video_track, track, video_sub,
                                                         W=W, H=H):
                    raise SystemExit("Failed to burn in word-by-word caption reveal.")
            else:
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
                if not vp.overlay_titles(str(video_track), titles, str(video_sub),
                                         target_w=W, target_h=H):
                    raise SystemExit("Failed to burn in subtitles.")
            video_for_final = video_sub

    # --- Music bed (+ optional structured volume envelope) ---
    music_path = None
    env = {"expr": None, "entrance": 0.0, "mix": "fixed_volume", "source": "flat",
           "moves": None, "keyframes": None, "soundtrack": None, "notes": []}
    if music:
        tok = token or C.get_replicate_token()
        music_path = generate_music(reel_dir, total_dur, mood=music_mood,
                                    prompt=music_prompt, token=tok, regen=regen_music,
                                    vocals=music_vocals)
        if music_path:
            scenes = manifest.get("scenes") if isinstance(manifest, dict) else None
            env = build_music_env(
                music_structure=music_structure, music_plan=music_plan,
                music_from_cutsheet=music_from_cutsheet, music_volume=music_volume,
                total_dur=total_dur, scenes=scenes or [])
            if env["expr"]:
                if not scenes:
                    print("  Note: manifest has no scene list; envelope resolved numeric "
                          "anchors only (scene-boundary anchors need it).", file=sys.stderr)
                print(f"  Music envelope [{env['mix']}]: {len(env['moves'] or [])} move(s), "
                      f"{len(env['keyframes'] or [])} keyframe(s), enter @ "
                      f"{env['entrance']:.2f}s", file=sys.stderr)
                for n in env["notes"]:
                    print(f"    - {n}", file=sys.stderr)
            elif music_structure != "flat" or music_plan or music_from_cutsheet:
                print("  Music: no envelope produced (no usable moves) — flat bed.",
                      file=sys.stderr)

    # --- Final mux ---
    final_path = reel_dir / "final.mp4"
    if not mux_final(video_for_final, narration, music_path, final_path,
                     music_volume=music_volume, master_lufs=master_lufs,
                     music_expr=env["expr"], music_entrance=env["entrance"]):
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
            "caption_progression": "word_reveal" if caption_reveal == "word" else "phrase_replace",
            "caption_reveal": caption_reveal,
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
            "music_mix": env["mix"] if music_path else None,
            "music_structure_source": env["source"] if music_path else None,
            "music_plan": env["moves"] if (music_path and env["moves"]) else None,
            "music_keyframes": (
                [[round(t, 3), round(g, 4)] for t, g in env["keyframes"]]
                if (music_path and env["keyframes"]) else None),
            "music_entrance_s": env["entrance"] if (music_path and env["expr"]) else None,
            "music_soundtrack_note": env["soundtrack"] if music_path else None,
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
                    "+ bold-italic payoff, matching the analyzed reels) + a music bed "
                    "(fixed volume, or a structured volume envelope via --music-structure "
                    "auto / --music-plan / --music-from-cutsheet).",
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
    ap.add_argument("--music-structure", choices=["flat", "auto"], default="flat",
                    help="Bed dynamics: 'flat' (constant level, default) or 'auto' (a "
                         "tasteful envelope from the scene structure: duck under the hook, "
                         "lift after it, resolve on the close). Overridden by --music-plan "
                         "/ --music-from-cutsheet.")
    ap.add_argument("--music-plan", default=None,
                    help="JSON file of explicit soundtrack moves "
                         "('{\"moves\":[{\"type\":\"enter_hard\",\"at\":\"s1 -> s2\"}, ...]}') "
                         "— the precise volume envelope (see compile_music_plan for types).")
    ap.add_argument("--music-from-cutsheet", default=None,
                    help="A rule-of-six-edit *.cutsheet.json; its per-cut `sound` notes are "
                         "mapped (best-effort) to music moves at their scene boundaries.")
    ap.add_argument("--caption-reveal", choices=["word", "phrase"], default="word",
                    help="Caption progression: 'word' (default) reveals each word as it "
                         "is spoken, building the phrase up in place (layout locked to the "
                         "full phrase, no reflow); 'phrase' shows each full phrase unit at "
                         "once (the previous static behavior).")
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
                         "(default: profile's value for portrait/square, else 0.66; "
                         "0.85 lower-third for 16:9 landscape)")
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
    music_plan = C.load_json(args.music_plan) if args.music_plan else None
    res = finish(
        reel_dir, subtitles=args.subtitles, music=args.music,
        music_mood=args.music_mood, music_prompt=args.music_prompt,
        music_volume=args.music_volume, music_vocals=args.music_vocals,
        music_structure=args.music_structure, music_plan=music_plan,
        music_from_cutsheet=args.music_from_cutsheet,
        max_words=args.max_words,
        emphasis=args.emphasis,
        casing=args.casing, fontsize=args.fontsize, y_frac=args.y_frac,
        caption_reveal=args.caption_reveal,
        regular_font=args.regular_font, emph_font=args.emph_font,
        style_profile=load_style_profile(args.style_from),
        regen_music=args.regen_music, master_lufs=args.master_lufs, manifest=manifest,
    )
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
