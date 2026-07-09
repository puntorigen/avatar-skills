#!/usr/bin/env python3
"""Transcribe dialogue.wav into word-level timecodes (words.json).

Backends:
  replicate  WhisperX (victor-upmeet/whisperx, align_output=true, diarization=false)
  local      faster-whisper (word_timestamps=True)
  auto       replicate if a token exists, else local; falls back to local on error

Output words.json normalizes both backends to {words[], segments[]} and maps each
word to a line_index when lines.json has per-line timings.

Usage:
    python3 transcribe.py --audio audio-theater/ep/dialogue.wav \
        --script audio-theater/ep/script.json --backend auto --out audio-theater/ep
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    load_config, load_json, save_json, resolve_out_dir, get_audio_duration,
    get_replicate_token, run_replicate,
)

WHISPERX_MODEL = "victor-upmeet/whisperx"
# Known-good version, used as a fallback if dynamic resolution fails.
WHISPERX_FALLBACK_VERSION = "655845d6190ef70573c669245f245892cd039df4b880a1e3a65852c09252f5cc"


def resolve_model_ref(model, token):
    """Return 'owner/name:version'. Some replicate clients 404 on bare names."""
    import os
    import replicate
    if token:
        os.environ["REPLICATE_API_TOKEN"] = token
    try:
        versions = replicate.models.get(model).versions.list()
        if versions:
            return f"{model}:{versions[0].id}"
    except Exception as e:  # noqa: BLE001
        print(f"  (version resolve failed: {e}; using pinned fallback)", file=sys.stderr)
    return f"{model}:{WHISPERX_FALLBACK_VERSION}"


def _lang_code(language):
    if not language:
        return None
    return str(language).strip().lower()[:2] or None


def transcribe_replicate(audio_path, language, token):
    inputs = {
        "audio_file": open(str(audio_path), "rb"),
        "align_output": True,
        "diarization": False,
    }
    code = _lang_code(language)
    if code:
        inputs["language"] = code
    model_ref = resolve_model_ref(WHISPERX_MODEL, token)
    try:
        output = run_replicate(model_ref, inputs, token=token)
    finally:
        try:
            inputs["audio_file"].close()
        except Exception:  # noqa: BLE001
            pass

    if output is None:
        raise RuntimeError("WhisperX returned no output")

    segments = output.get("segments") if isinstance(output, dict) else None
    detected = output.get("detected_language") if isinstance(output, dict) else None
    if segments is None:
        raise RuntimeError(f"Unexpected WhisperX output: {type(output)}")

    norm_segments = []
    words = []
    for seg in segments:
        seg_words = []
        for w in seg.get("words", []) or []:
            ww = {
                "word": (w.get("word") or w.get("text") or "").strip(),
                "start": w.get("start"),
                "end": w.get("end"),
            }
            if ww["word"]:
                seg_words.append(ww)
                if ww["start"] is not None and ww["end"] is not None:
                    words.append(ww)
        norm_segments.append({
            "start": seg.get("start"),
            "end": seg.get("end"),
            "text": (seg.get("text") or "").strip(),
            "words": seg_words,
        })
    return words, norm_segments, detected or _lang_code(language)


def transcribe_local(audio_path, language, model_size="small"):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip3 install faster-whisper")

    print(f"  faster-whisper: loading model '{model_size}' (cpu/int8) ...", file=sys.stderr)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    code = _lang_code(language)
    seg_iter, info = model.transcribe(
        str(audio_path), word_timestamps=True, language=code)

    norm_segments = []
    words = []
    for seg in seg_iter:
        seg_words = []
        for w in (seg.words or []):
            ww = {"word": (w.word or "").strip(), "start": w.start, "end": w.end}
            if ww["word"]:
                seg_words.append(ww)
                if ww["start"] is not None and ww["end"] is not None:
                    words.append(ww)
        norm_segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": (seg.text or "").strip(),
            "words": seg_words,
        })
    return words, norm_segments, getattr(info, "language", code)


def map_words_to_lines(words, lines_data):
    """Attach line_index to each word using per-line [start,end] intervals."""
    if not lines_data:
        return
    intervals = []
    for ln in lines_data.get("lines", []):
        if ln.get("start") is not None and ln.get("end") is not None:
            intervals.append((ln["start"], ln["end"], ln["index"]))
    if not intervals:
        return
    intervals.sort()
    for w in words:
        wt = w.get("start")
        if wt is None:
            continue
        match = None
        for start, end, idx in intervals:
            if start <= wt <= end + 0.5:
                match = idx
                break
            if wt < start:
                match = idx  # falls in the pause just before this line
                break
        w["line_index"] = match


def main():
    parser = argparse.ArgumentParser(description="Transcribe with word-level timecodes")
    parser.add_argument("--audio", default=None, help="Audio file (default <out>/dialogue.wav)")
    parser.add_argument("--script", default=None, help="script.json (for language hint)")
    parser.add_argument("--out", "-o", required=True, help="Project folder")
    parser.add_argument("--backend", choices=["auto", "replicate", "local"], default=None)
    parser.add_argument("--language", "-l", default=None, help="Language hint (ISO code)")
    parser.add_argument("--local-model", default="small",
                        help="faster-whisper model size (tiny/base/small/medium/large-v3)")
    args = parser.parse_args()

    config = load_config()
    out_dir = resolve_out_dir(args.out)
    audio_path = Path(args.audio) if args.audio else out_dir / "dialogue.wav"
    if not audio_path.exists():
        print(f"Error: audio not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    backend = args.backend or config.get("default_transcribe_backend", "auto")

    language = args.language
    lines_data = None
    lines_path = out_dir / "lines.json"
    if lines_path.exists():
        lines_data = load_json(lines_path)
        language = language or lines_data.get("language")
    if not language and args.script and Path(args.script).exists():
        language = load_json(args.script).get("language")
    language = language or config.get("default_language", "es")

    token = get_replicate_token(required=False)

    words = segments = detected = None
    used_backend = None
    errors = []

    order = []
    if backend == "replicate":
        order = ["replicate"]
    elif backend == "local":
        order = ["local"]
    else:  # auto
        order = (["replicate"] if token else []) + ["local"]

    for b in order:
        try:
            if b == "replicate":
                if not token:
                    raise RuntimeError("no Replicate token")
                print("  Transcribing with WhisperX (Replicate) ...", file=sys.stderr)
                words, segments, detected = transcribe_replicate(audio_path, language, token)
            else:
                print("  Transcribing with faster-whisper (local) ...", file=sys.stderr)
                words, segments, detected = transcribe_local(
                    audio_path, language, model_size=args.local_model)
            used_backend = b
            break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{b}: {e}")
            print(f"  Backend '{b}' failed: {e}", file=sys.stderr)

    if used_backend is None:
        print("Error: all transcription backends failed:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)
        sys.exit(1)

    map_words_to_lines(words, lines_data)

    result = {
        "backend": used_backend,
        "language": detected or language,
        "duration": round(get_audio_duration(audio_path), 3),
        "word_count": len(words),
        "words": words,
        "segments": segments,
    }
    words_path = out_dir / "words.json"
    save_json(words_path, result)

    print(f"  Backend: {used_backend} | words: {len(words)} | lang: {result['language']}",
          file=sys.stderr)
    print(json.dumps({
        "words_json": str(words_path),
        "backend": used_backend,
        "word_count": len(words),
        "language": result["language"],
        "duration": result["duration"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
