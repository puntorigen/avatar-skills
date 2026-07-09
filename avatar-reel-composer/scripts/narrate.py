#!/usr/bin/env python3
"""Stage 1 of avatar-reel-composer: narrate the script + align it.

1. Synthesize the FULL script (verbatim) in the avatar's cloned voice by
   delegating to the voice-clone skill (generate_speech.py), one MiniMax call
   PER SENTENCE, then joining the takes with a small silence gap. Per-sentence
   synthesis avoids the audio-quality degradation speech-2.8-hd shows on long
   single takes and the sentence-boundary gaps help the caption engine.
2. Transcribe the resulting narration.mp3 with faster-whisper
   (word_timestamps=True, vad_filter=True), producing word-level timings used
   later to cut the narration per scene.

Outputs (in --out-dir): narration.mp3 + narration.align.json
Prints a JSON summary to stdout for the orchestrator.

Usage (standalone):
    python3 narrate.py --avatar-dir lolo --out-dir lolo/reels/001_demo \
        --text-file script.txt --emotion neutral --speed 0.95
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _arc_common as C  # noqa: E402

# MiniMax speech-2.8-hd degrades on very long single takes (the model's own docs
# recommend short sentences for smoother delivery), so we synthesize ONE call per
# sentence and join the takes. ``DEFAULT_MAX_CHARS`` is only a safety cap to
# hard-split a pathological run-on sentence.
DEFAULT_MAX_CHARS = 2800
# Short silence inserted between sentence takes: keeps independently generated
# sentences from running together and gives the caption engine clean pauses at
# sentence boundaries (it clears captions on pauses > ~0.4s).
DEFAULT_SENTENCE_GAP = 0.12

# Common Spanish/English abbreviations whose trailing period is NOT a sentence end.
_ABBREV = {
    "sr", "sra", "srta", "dr", "dra", "prof", "ing", "lic", "arq", "gral",
    "etc", "ej", "vs", "ud", "uds", "núm", "no", "pág", "av", "avda", "ph", "d",
    "mr", "mrs", "ms", "st", "vol", "fig",
}
_ENDERS = ".!?…"


def split_into_sentences(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Split text into individual sentences, keeping terminal punctuation.

    Decimal-aware ("3.14" stays one token) and abbreviation-aware ("Dr." does
    not end a sentence). A sentence longer than ``max_chars`` (a rare run-on) is
    hard-split at word boundaries as a safety net so no single TTS call is huge.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []

    sents: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        buf.append(ch)
        if ch in _ENDERS:
            # Consume a run of terminators (e.g. "?!", "…", "...").
            while i + 1 < n and text[i + 1] in _ENDERS:
                i += 1
                buf.append(text[i])
            nxt = text[i + 1] if i + 1 < n else ""
            prev = buf[-2] if len(buf) >= 2 else ""
            cur = "".join(buf)
            last_word = cur.rsplit(" ", 1)[-1].rstrip(_ENDERS).lower()
            is_decimal = ch == "." and prev.isdigit() and nxt.isdigit()
            is_abbrev = ch == "." and last_word in _ABBREV
            if not is_decimal and not is_abbrev and nxt in ("", " "):
                s = cur.strip()
                if s:
                    sents.append(s)
                buf = []
        i += 1
    tail = "".join(buf).strip()
    if tail:
        sents.append(tail)

    out: list[str] = []
    for s in sents:
        if len(s) <= max_chars:
            out.append(s)
            continue
        word_buf = ""
        for w in s.split():
            if len(word_buf) + len(w) + 1 <= max_chars:
                word_buf = f"{word_buf} {w}".strip()
            else:
                if word_buf:
                    out.append(word_buf)
                word_buf = w
        if word_buf:
            out.append(word_buf)
    return out or [text]


def _norm_for_match(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


# MiniMax pause markers ("<#0.5#>" / "<#3#>") drive the TTS pauses but must NEVER
# reach the caption alignment: a marker tokenizes to a bare digit ("<#5#>" -> "5")
# and, during the long silence it creates, faster-whisper frequently emits a
# matching spurious token (often that same digit). The raw script contains the
# markers, so a naive forced-speller treats those digits as correct and they leak
# into captions — and, glued (gap ~0) to the next word, they bridge a phrase
# boundary so a next-sentence word lands on the previous caption.
PAUSE_MARKER_RE = re.compile(r"<#[^#>]*#>")


def strip_pause_markers(text: str) -> str:
    """Remove ``<#...#>`` pause markers (keep them in the TTS text, never in the
    text used to align/spell captions)."""
    return PAUSE_MARKER_RE.sub(" ", text or "")


_CORE_RE = re.compile(r"^\W*(.*?)\W*$", re.UNICODE)


def _split_affixes(tok: str):
    """Return (lead_punct, core_letters, trail_punct). Core keeps internal accents."""
    m = _CORE_RE.match(tok or "")
    core = m.group(1) if m else (tok or "")
    if not core:
        return "", "", tok or ""
    i = tok.find(core)
    return tok[:i], core, tok[i + len(core):]


def _intentional_upper(core: str) -> bool:
    """True for ALL-CAPS words that denote intent (acronyms / emphasis: REPE, NO).
    A single uppercase letter (sentence-start 'Y', 'O', 'A') is NOT intentional."""
    return bool(core) and core.isupper() and sum(c.isalpha() for c in core) >= 2


def _mirror_case(new_core: str, ref_core: str) -> str:
    """Render ``new_core`` (the script's correct letters) using the case STYLE of
    ``ref_core`` (the ASR word) — so we keep natural subtitle casing instead of
    importing the script's sentence-capitalization."""
    if ref_core.isupper() and sum(c.isalpha() for c in ref_core) >= 2:
        return new_core.upper()
    if ref_core[:1].isupper():
        return new_core[:1].upper() + new_core[1:].lower()
    return new_core.lower()


def correct_words_against_script(words: list[dict], script: str) -> list[dict]:
    """Fix ASR word *spelling* against the SCRIPT (the source of truth for TEXT)
    while keeping normal subtitle conventions for casing and punctuation.

    faster-whisper transcribes phonetically, so it mis-spells acronyms / proper
    nouns ('REPE' -> 'rape'). We align ASR words to the script and, for each match:

    * keep the ASR word AS-IS when it's the same word ignoring case AND accents
      ('Sólo' == 'sólo' == 'solo'): the script's sentence-capitalization and
      punctuation are NOT imposed, and we do NOT strip the ASR's accents — captions
      follow normal subtitle orthography, which whisper already produces well;
    * force UPPERCASE when the script wrote the word ALL-CAPS (>=2 letters), since
      that denotes intentionality (acronyms/emphasis: 'NO', 'REPE');
    * adopt the script's letters only when the base spelling genuinely differs
      (e.g. an acronym whisper heard wrong: 'rape' -> 'REPE'), rendered in the ASR
      word's own case style so we don't introduce mid-sentence capitals.

    Mutates ``words`` in place (start/end untouched) and returns it.
    """
    if not script or not words:
        return words
    import difflib
    script_tokens = script.split()
    s_norm = [_norm_for_match(t) for t in script_tokens]
    w_norm = [_norm_for_match(w.get("word", "")) for w in words]
    n_fixed = 0
    sm = difflib.SequenceMatcher(None, s_norm, w_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag not in ("equal", "replace"):
            continue  # 'insert' = ASR has no script word (keep); 'delete' = ASR missed it
        for k in range(min(i2 - i1, j2 - j1)):
            asr = words[j1 + k].get("word", "")
            _, s_core, _ = _split_affixes(script_tokens[i1 + k])
            lead, a_core, trail = _split_affixes(asr)
            if not s_core or not a_core:
                continue
            # Fold BOTH case and accents: 'Sólo'/'sólo'/'solo' are the same word,
            # so we never overwrite the ASR's casing OR strip its accents.
            same_word = _norm_for_match(s_core) == _norm_for_match(a_core)
            if same_word and not _intentional_upper(s_core):
                continue  # keep the ASR word verbatim (its case + accents + punct)
            if _intentional_upper(s_core):
                new_core = s_core.upper()          # 'NO', 'REPE' — intentional caps
            else:
                new_core = _mirror_case(s_core, a_core)  # source spelling, ASR casing
            new_word = f"{lead}{new_core}{trail}"  # keep the ASR's own punctuation
            if new_word != asr:
                words[j1 + k]["asr_word"] = asr
                words[j1 + k]["word"] = new_word
                n_fixed += 1
    if n_fixed:
        print(f"  Caption text: corrected {n_fixed} ASR word(s) to the script "
              f"spelling (acronyms/intentional caps like REPE, NO).", file=sys.stderr)
    return words


def reconcile_words_to_script(words: list[dict], script: str) -> list[dict]:
    """Return a NEW caption word list whose TEXT comes from the SCRIPT (the source
    of truth, with ``<#N#>`` pause markers stripped) and whose TIMINGS come from
    the ASR alignment.

    This supersedes the conservative spelling-only fix when a full script is
    available, because it also removes the artifacts the pause markers cause:

    * matched words   -> the script's exact spelling + punctuation, ASR timing;
    * ASR-only tokens -> dropped (the spurious pause-pause digits whisper
      hallucinates, and stray inserted connectors like 'entrena' -> 'entrena en');
    * a script word the ASR missed/misheard -> taken from the script, with the
      mis-heard ASR token's timing (e.g. whisper's '5' -> the script's 'Va'),
      or an interpolated timing when the ASR produced nothing there.

    Because the caption text and its punctuation now follow the script, phrase
    breaks land on the real sentence ends and a next-sentence word can never leak
    onto the previous caption.
    """
    if not script or not words:
        return words
    import difflib
    script_toks = strip_pause_markers(script).split()
    if not script_toks:
        return words
    s_norm = [_norm_for_match(t) for t in script_toks]
    w_norm = [_norm_for_match(w.get("word", "")) for w in words]
    sm = difflib.SequenceMatcher(None, s_norm, w_norm, autojunk=False)

    out: list[dict] = []
    n_from_asr = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal", "replace"):
            npair = min(i2 - i1, j2 - j1)
            for k in range(npair):
                a = words[j1 + k]
                out.append({"word": script_toks[i1 + k],
                            "start": float(a["start"]), "end": float(a["end"])})
                n_from_asr += 1
            for k in range(npair, i2 - i1):       # extra SCRIPT tokens (ASR had fewer)
                out.append({"word": script_toks[i1 + k], "start": None, "end": None})
            # extra ASR tokens on the replace's j-side are dropped
        elif tag == "delete":                      # script words the ASR missed
            for k in range(i2 - i1):
                out.append({"word": script_toks[i1 + k], "start": None, "end": None})
        # tag == "insert": ASR-only tokens (pause-marker artifacts) -> dropped

    # Fill unknown timings by linear interpolation between known neighbours.
    n = len(out)
    i = 0
    while i < n:
        if out[i]["start"] is None:
            j = i
            while j < n and out[j]["start"] is None:
                j += 1
            left = out[i - 1]["end"] if i > 0 else 0.0
            right = out[j]["start"] if j < n else left + 0.3 * (j - i)
            step = max(0.0, right - left) / (j - i + 1)
            for k in range(i, j):
                st = round(left + step * (k - i + 1), 3)
                out[k]["start"] = st
                out[k]["end"] = round(min(right, st + max(step, 0.12)), 3)
            i = j
        else:
            i += 1
    for k in range(n):                             # enforce monotonic, non-degenerate
        if k and out[k]["start"] < out[k - 1]["start"]:
            out[k]["start"] = out[k - 1]["start"]
        if out[k]["end"] < out[k]["start"]:
            out[k]["end"] = round(out[k]["start"] + 0.08, 3)

    print(f"  Caption text: reconciled to the script — {len(out)} caption words "
          f"({len(words) - n_from_asr} ASR-only artifact(s) dropped, "
          f"e.g. pause-marker digits).", file=sys.stderr)
    return out


def _segments_from_words(words: list[dict], *, max_gap: float = 0.6) -> list[dict]:
    """Group a flat word list back into coarse segments (by sentence-ending
    punctuation or a speech pause) so the alignment file stays self-consistent
    after the words are reconciled to the script."""
    segs, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (float(nxt["start"]) - float(w["end"])) if nxt else 0.0
        last = (w.get("word") or "").strip()[-1:]
        if nxt is None or gap > max_gap or last in ".?!…":
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return [{"start": s[0]["start"], "end": s[-1]["end"],
             "text": " ".join((x.get("word") or "") for x in s), "words": s}
            for s in segs]


def group_sentences(sentences: list[str], per_call: int = 1,
                    max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Group consecutive sentences into TTS calls (default: one per call).

    ``per_call`` > 1 packs that many sentences per call (never exceeding
    ``max_chars``), trading a little prosody continuity for fewer API calls.
    """
    per_call = max(1, int(per_call))
    if per_call == 1:
        return list(sentences)
    groups: list[str] = []
    buf, count = "", 0
    for s in sentences:
        if count and (count >= per_call or len(buf) + len(s) + 1 > max_chars):
            groups.append(buf)
            buf, count = "", 0
        buf = f"{buf} {s}".strip()
        count += 1
    if buf:
        groups.append(buf)
    return groups or list(sentences)


def _tts_chunk(text: str, avatar_dir: Path, out_name: str, *,
               voice_name=None, voice_id=None, source=None, emotion="auto",
               language_boost="None", speed=1.0, volume=1.0, pitch=0) -> Path:
    """Run voice-clone generate_speech.py for one chunk; return the mp3 path."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        tf = f.name
    try:
        cmd = [sys.executable, str(C.VOICE_CLONE_SCRIPT),
               "--text-file", tf,
               "--avatar-dir", str(avatar_dir),
               "--emotion", emotion,
               "--language-boost", language_boost,
               "--speed", str(speed),
               "--volume", str(volume),
               "--pitch", str(pitch),
               "--audio-format", "mp3",
               "--out-name", out_name]
        if voice_name:
            cmd += ["--name", voice_name]
        if voice_id:
            cmd += ["--voice-id", voice_id]
        if source:
            cmd += ["--source", source]
        result = C.run_cli_json(cmd, desc=f"TTS chunk -> {out_name}.mp3")
    finally:
        Path(tf).unlink(missing_ok=True)
    if not result or not result.get("audio"):
        raise RuntimeError("voice-clone returned no audio path.")
    audio = Path(result["audio"])
    if not audio.exists():
        raise RuntimeError(f"voice-clone audio not found: {audio}")
    return audio


def _part_key(text: str, voice_kw: dict) -> str:
    """Stable cache key for one sentence take: its text + the voice params that
    actually change the audio. Two runs with the same text+params reuse the clip;
    changing the voice / emotion / language_boost / speed / … misses the cache."""
    relevant = {
        "text": text,
        "voice": voice_kw.get("voice_id") or voice_kw.get("voice_name"),
        "emotion": voice_kw.get("emotion"),
        "language_boost": voice_kw.get("language_boost"),
        "speed": voice_kw.get("speed"),
        "volume": voice_kw.get("volume"),
        "pitch": voice_kw.get("pitch"),
    }
    raw = json.dumps(relevant, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def synthesize(script: str, avatar_dir: Path, out_path: Path, *, slug="reel",
               max_chars=DEFAULT_MAX_CHARS, sentence_gap=DEFAULT_SENTENCE_GAP,
               sentences_per_call=1, reroll=None, **voice_kw) -> Path:
    """Synthesize the full script (verbatim) into out_path (mp3).

    One MiniMax call per sentence (default), joined with a small silence gap.
    Per-sentence synthesis avoids the quality degradation speech-2.8-hd shows on
    long single takes and keeps prosody crisp.

    Each sentence take is CACHED in ``<out_dir>/narration_parts/`` keyed by its
    text + voice params, so re-narrating only regenerates what actually changed.
    ``reroll`` is a set/list of 1-based sentence indices to force a fresh take of
    (e.g. when one segment is mispronounced) — the rest are reused from cache.
    """
    sentences = split_into_sentences(script, max_chars)
    calls = group_sentences(sentences, sentences_per_call, max_chars)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = out_path.parent / "narration_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    reroll = {int(x) for x in (reroll or [])}

    n = len(calls)
    print(f"  Narrating {len(sentences)} sentence(s) in {n} TTS call(s) "
          f"(gap {sentence_gap:.2f}s, language_boost={voice_kw.get('language_boost')}) ...",
          file=sys.stderr)
    parts, index = [], []
    n_gen = n_cache = 0
    for i, ch in enumerate(calls, 1):
        key = _part_key(ch, voice_kw)
        cached = parts_dir / f"part_{key}.mp3"
        if i in reroll and cached.exists():
            cached.unlink()  # force a fresh take of this sentence
        if cached.exists():
            n_cache += 1
            tag = "cache"
        else:
            audio = _tts_chunk(ch, avatar_dir, f"{slug}_narr_s{i:02d}", **voice_kw)
            shutil.copyfile(audio, cached)
            n_gen += 1
            tag = "tts"
        preview = (ch[:54] + "…") if len(ch) > 55 else ch
        print(f"    [{tag:>5}] sentence {i:>2}/{n}: {preview}", file=sys.stderr)
        parts.append(cached)
        index.append({"i": i, "key": key, "file": cached.name, "text": ch})

    C.save_json(parts_dir / "index.json", {
        "parts": index,
        "language_boost": voice_kw.get("language_boost"),
        "emotion": voice_kw.get("emotion"),
        "speed": voice_kw.get("speed"),
        "_note": "Per-sentence TTS cache. Re-roll a bad sentence i with "
                 "compose_reel.py --reroll i (or narrate.py --reroll i).",
    })

    if len(parts) == 1:
        shutil.copyfile(parts[0], out_path)
    elif not C.concat_audio(parts, out_path, gap=sentence_gap):
        raise RuntimeError("Failed to concatenate sentence takes.")
    print(f"  Narration ready ({n_gen} generated, {n_cache} reused): {out_path}",
          file=sys.stderr)
    return out_path


def align(narration_path: Path, out_path: Path, *, whisper_model="small",
          language=None, script=None) -> dict:
    """Transcribe narration with faster-whisper -> word-level align JSON.

    When ``script`` is given, ASR word strings are relabeled with the script's
    canonical spelling/casing (forced alignment) so captions never show
    mis-transcribed acronyms/proper nouns; timings stay from the ASR.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip3 install faster-whisper"
        ) from exc

    print(f"  Aligning narration with faster-whisper ({whisper_model}) ...", file=sys.stderr)
    model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
    lang = (language or "").strip().lower()[:2] or None
    segments_iter, info = model.transcribe(
        str(narration_path),
        word_timestamps=True,
        language=lang,
        vad_filter=True,
    )

    segments, words = [], []
    for seg in segments_iter:
        seg_words = []
        for w in seg.words or []:
            ww = {"word": (w.word or "").strip(),
                  "start": round(w.start, 3), "end": round(w.end, 3)}
            if ww["word"]:
                seg_words.append(ww)
                words.append(ww)
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": (seg.text or "").strip(),
            "words": seg_words,
        })

    if script:
        # Drive the caption TEXT from the script (source of truth) with ASR
        # TIMINGS: strips the ``<#N#>`` pause markers and the artifacts they cause
        # (hallucinated digits, stray inserted connectors, cross-sentence leaks).
        # Rebuild the segments so the file stays consistent with the new words.
        words = reconcile_words_to_script(words, script)
        segments = _segments_from_words(words)

    data = {
        "language": getattr(info, "language", lang),
        "duration": round(getattr(info, "duration", 0) or 0, 3),
        "audio_duration": round(C.ffprobe_duration(narration_path), 3),
        "segments": segments,
        "words": words,
    }
    C.save_json(out_path, data)
    print(f"  Alignment: {out_path}  ({len(words)} words, {data['duration']:.2f}s)", file=sys.stderr)
    return data


def narrate(script: str, avatar_dir: Path, out_dir: Path, *, slug="reel",
            whisper_model="small", language=None, force=False,
            max_chars=DEFAULT_MAX_CHARS, sentence_gap=DEFAULT_SENTENCE_GAP,
            sentences_per_call=1, reroll=None, **voice_kw) -> dict:
    """Full stage 1: produce narration.mp3 + narration.align.json in out_dir.

    Idempotent: if both already exist and not force, reuse them. ``force`` or a
    ``reroll`` request rebuilds the narration (reusing the unchanged per-sentence
    takes from cache), then re-aligns.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    narration_path = out_dir / "narration.mp3"
    align_path = out_dir / "narration.align.json"
    reroll = {int(x) for x in (reroll or [])}

    if narration_path.exists() and align_path.exists() and not force and not reroll:
        print(f"  Narration already exists (reusing): {narration_path}", file=sys.stderr)
        data = C.load_json(align_path)
    else:
        synthesize(script, avatar_dir, narration_path, slug=slug,
                   max_chars=max_chars, sentence_gap=sentence_gap,
                   sentences_per_call=sentences_per_call, reroll=reroll, **voice_kw)
        data = align(narration_path, align_path,
                     whisper_model=whisper_model, language=language, script=script)

    return {
        "narration": str(narration_path),
        "align": str(align_path),
        "duration": data.get("audio_duration") or data.get("duration"),
        "words": len(data.get("words", [])),
    }


def main():
    ap = argparse.ArgumentParser(
        description="Narrate a script in a cloned voice and align it word-by-word.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("text", nargs="?", default=None, help="Script text (or use --text-file)")
    ap.add_argument("--text-file", type=Path, default=None, help="Read the script from a file")
    ap.add_argument("--avatar-dir", type=Path, required=True, help="Avatar folder")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Where to write narration.mp3 + narration.align.json")
    ap.add_argument("--slug", default="reel", help="Filename stem for the voice-clone outputs")
    # Voice options forwarded to voice-clone.
    ap.add_argument("--name", default=None, help="Trained voice name to use (auto if omitted)")
    ap.add_argument("--voice-id", default=None, help="MiniMax voice_id to use directly")
    ap.add_argument("--source", default=None, help="Audio/video to TRAIN the voice if none exists")
    ap.add_argument("--emotion", default="auto", help="TTS delivery style (auto/neutral/calm/...)")
    ap.add_argument("--language-boost", default="None",
                    help="'None' (no boost; keeps the cloned voice's own accent — recommended), "
                         "'detect', or a MiniMax locale (e.g. Spanish)")
    ap.add_argument("--speed", type=float, default=1.0, help="TTS speed (0.5-2.0)")
    ap.add_argument("--volume", type=float, default=1.0, help="TTS volume (0-10)")
    ap.add_argument("--pitch", type=int, default=0, help="TTS pitch in semitones (-12..12)")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                    help="Safety cap per TTS call; a longer single sentence is hard-split")
    ap.add_argument("--sentence-gap", type=float, default=DEFAULT_SENTENCE_GAP,
                    help="Silence (s) inserted between sentence takes (0 to disable)")
    ap.add_argument("--sentences-per-call", type=int, default=1,
                    help="Sentences per TTS call (1 = one per sentence; higher = fewer calls)")
    ap.add_argument("--reroll", type=int, nargs="+", default=None, metavar="N",
                    help="Force a fresh take of these 1-based sentence indices "
                         "(reuses the rest from the per-sentence cache)")
    # Alignment options.
    ap.add_argument("--whisper-model", default="small", help="faster-whisper model size")
    ap.add_argument("--language", default=None, help="Language hint for whisper (e.g. es)")
    ap.add_argument("--force", action="store_true", help="Re-narrate even if outputs exist")
    args = ap.parse_args()

    if args.text_file:
        script = args.text_file.expanduser().read_text(encoding="utf-8").strip()
    elif args.text:
        script = args.text.strip()
    else:
        ap.error("Provide the script text (positional or --text-file).")
    if not script:
        ap.error("The script is empty.")

    avatar_dir = args.avatar_dir.expanduser().resolve()
    if not avatar_dir.is_dir():
        ap.error(f"Avatar folder not found: {avatar_dir}")

    result = narrate(
        script, avatar_dir, args.out_dir.expanduser().resolve(),
        slug=args.slug, whisper_model=args.whisper_model, language=args.language,
        force=args.force, max_chars=args.max_chars,
        sentence_gap=args.sentence_gap, sentences_per_call=args.sentences_per_call,
        reroll=args.reroll,
        voice_name=args.name, voice_id=args.voice_id, source=args.source,
        emotion=args.emotion, language_boost=args.language_boost,
        speed=args.speed, volume=args.volume, pitch=args.pitch,
    )

    import json
    print(f"\nNarration ready — {result['narration']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
