#!/usr/bin/env python3
"""Generate one clean Gemini TTS clip per line, concatenate into dialogue.wav.

Default (per-line): each line -> lines/line-NNN.wav (one voice per character),
concatenated with pause_after silence into dialogue.wav. lines.json carries
exact start/end/duration per line. The clean per-line clips double as lipsync
reference for seedance-2.

--two-speaker: for exactly two characters, render the conversation with Gemini
multi-speaker TTS in chunks (a single natural take). Per-line timing is then
approximate (use transcribe.py for word-level timecodes).

Usage:
    python3 generate_voices.py --script audio-theater/ep/script.json --out audio-theater/ep
    python3 generate_voices.py --script ... --out ... --two-speaker
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    get_gemini_api_key, load_config, load_json, save_json, resolve_out_dir,
    pcm_to_wav, get_audio_duration, run_ffmpeg, DEFAULT_TTS_MODEL, MAX_CLIP_SECONDS,
)

MAX_RETRIES = 4
RETRY_DELAY = 6.0
TTS_RATE = 24000
MULTISPEAKER_CHUNK_LINES = 8

# Default BCP-47 locale per 2-letter language. Gemini TTS otherwise auto-detects,
# which for Spanish tends to render Castilian (es-ES); LATAM-neutral (es-US) is a
# better default for this skill. Override per project via script.json
# "language_code" or the --language-code flag.
DEFAULT_LOCALE = {
    "es": "es-US",
    "en": "en-US",
    "pt": "pt-BR",
    "fr": "fr-FR",
    "de": "de-DE",
    "it": "it-IT",
}


def resolve_locale(language, explicit=None):
    """explicit (CLI/script) > full BCP-47 in `language` (has '-') > mapped default."""
    if explicit:
        return explicit
    lang = (language or "").strip()
    if not lang:
        return None
    if "-" in lang:
        return lang
    return DEFAULT_LOCALE.get(lang.lower())


def weave_tags(text, tags):
    """Prefix inline audio tags ([tag]) that aren't already present in text."""
    prefix = ""
    for t in tags or []:
        t = str(t).strip().strip("[]")
        if t and f"[{t}]" not in text:
            prefix += f"[{t}] "
    return (prefix + text).strip()


def build_line_prompt(text_with_tags, persona):
    """Build a single-speaker TTS prompt with a classifier-safe preamble.

    Per Gemini TTS docs: add a clear preamble instructing synthesis and label
    where the spoken transcript begins, so director's notes are not read aloud.
    """
    style = f" Perform it as: {persona}." if persona else ""
    return (
        "Synthesize speech. Read aloud ONLY the line after 'LINE:'. "
        f"Do not read these instructions or any labels aloud.{style}\n\n"
        f"LINE: {text_with_tags}"
    )


def extract_audio_bytes(response):
    """Pull PCM bytes from a TTS response, or None if the model returned text."""
    try:
        parts = response.candidates[0].content.parts
    except (AttributeError, IndexError, TypeError):
        return None
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is not None and getattr(inline, "data", None):
            return inline.data
    return None


def tts_single(client, types, model, prompt, voice_name, language_code=None):
    speech_kwargs = {
        "voice_config": types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
        )
    }
    if language_code:
        speech_kwargs["language_code"] = language_code
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(**speech_kwargs),
    )
    return client.models.generate_content(model=model, contents=prompt, config=config)


def tts_multi(client, types, model, prompt, speaker_voice_map, language_code=None):
    speaker_configs = [
        types.SpeakerVoiceConfig(
            speaker=name,
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            ),
        )
        for name, voice in speaker_voice_map.items()
    ]
    speech_kwargs = {
        "multi_speaker_voice_config": types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=speaker_configs
        )
    }
    if language_code:
        speech_kwargs["language_code"] = language_code
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(**speech_kwargs),
    )
    return client.models.generate_content(model=model, contents=prompt, config=config)


def with_retries(fn, *, label="tts"):
    """Call fn() with retries; the TTS model randomly returns text/500 errors."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = fn()
            if data:
                return data
            last_err = "no audio returned (text tokens)"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        if attempt < MAX_RETRIES:
            print(f"    {label}: attempt {attempt} failed ({last_err}); retrying...",
                  file=sys.stderr)
            time.sleep(RETRY_DELAY)
    print(f"  Error: {label} failed after {MAX_RETRIES} attempts: {last_err}", file=sys.stderr)
    return None


def pad_clip(clip_path, pause_after, out_path):
    """Re-encode a clip to fixed format with trailing silence (pcm_s16le/24k/mono)."""
    af = f"apad=pad_dur={max(0.0, float(pause_after)):.3f}" if pause_after else "anull"
    ok = run_ffmpeg([
        "-i", str(clip_path), "-af", af,
        "-ar", str(TTS_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(out_path),
    ])
    return ok


def concat_wavs(wav_paths, out_path):
    """Concatenate identically-formatted WAVs via the concat demuxer (-c copy)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        listfile = f.name
        for p in wav_paths:
            f.write(f"file '{Path(p).resolve()}'\n")
    try:
        ok = run_ffmpeg([
            "-f", "concat", "-safe", "0", "-i", listfile,
            "-c", "copy", str(out_path),
        ], description=f"concat {len(wav_paths)} clips")
    finally:
        Path(listfile).unlink(missing_ok=True)
    return ok


def generate_per_line(client, types, model, script, out_dir, max_clip_seconds,
                      language_code=None):
    lines = script["lines"]
    char_voice = {c["name"]: c.get("voice", "Charon") for c in script["characters"]}
    lines_dir = out_dir / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)

    padded_dir = out_dir / ".padded"
    padded_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    padded_paths = []
    cumulative = 0.0
    warnings = []

    for ln in lines:
        idx = ln["index"]
        text = (ln.get("text") or "").strip()
        if not text:
            continue
        voice = char_voice.get(ln["speaker"], "Charon")
        persona = next((c.get("persona", "") for c in script["characters"]
                        if c["name"] == ln["speaker"]), "")
        text_with_tags = weave_tags(text, ln.get("tags"))
        prompt = build_line_prompt(text_with_tags, persona)

        print(f"  Line {idx:03d} [{ln['speaker']}/{voice}]: {text[:48]}", file=sys.stderr)
        data = with_retries(
            lambda: extract_audio_bytes(
                tts_single(client, types, model, prompt, voice, language_code)),
            label=f"line {idx}",
        )
        if data is None and ln.get("tags"):
            # Some style tags (e.g. [whispers]) make the model emit text instead
            # of audio. Retry the bare line so we never drop it over a style note.
            print(f"    line {idx}: retrying without style tags {ln.get('tags')} ...",
                  file=sys.stderr)
            plain_prompt = build_line_prompt(text, persona)
            data = with_retries(
                lambda: extract_audio_bytes(
                    tts_single(client, types, model, plain_prompt, voice, language_code)),
                label=f"line {idx} (no tags)",
            )
        if data is None:
            print(f"  Skipping line {idx} (TTS failed)", file=sys.stderr)
            continue

        clip_path = lines_dir / f"line-{idx:03d}.wav"
        pcm_to_wav(data, clip_path, rate=TTS_RATE)
        clip_dur = get_audio_duration(clip_path)

        if clip_dur > max_clip_seconds:
            warnings.append(idx)
            print(f"    Warning: clip {idx} is {clip_dur:.1f}s > {max_clip_seconds}s "
                  f"(too long for seedance lipsync; consider splitting the line)",
                  file=sys.stderr)

        pause_after = float(ln.get("pause_after", 0.3) or 0.0)
        padded_path = padded_dir / f"pad-{idx:03d}.wav"
        if not pad_clip(clip_path, pause_after, padded_path):
            print(f"  Error: failed to pad clip {idx}", file=sys.stderr)
            continue
        padded_dur = get_audio_duration(padded_path)
        padded_paths.append(padded_path)

        entries.append({
            "index": idx,
            "speaker": ln["speaker"],
            "voice": voice,
            "text": text,
            "tags": ln.get("tags", []),
            "file": str(clip_path.relative_to(out_dir)),
            "start": round(cumulative, 3),
            "end": round(cumulative + clip_dur, 3),
            "duration": round(clip_dur, 3),
            "pause_after": pause_after,
        })
        cumulative += padded_dur

    if not padded_paths:
        print("Error: no audio was generated.", file=sys.stderr)
        sys.exit(1)

    dialogue_path = out_dir / "dialogue.wav"
    if not concat_wavs(padded_paths, dialogue_path):
        sys.exit(1)

    # Clean up padded temporaries.
    for p in padded_paths:
        Path(p).unlink(missing_ok=True)
    try:
        padded_dir.rmdir()
    except OSError:
        pass

    return entries, dialogue_path, warnings


def generate_two_speaker(client, types, model, script, out_dir, max_clip_seconds,
                         language_code=None):
    chars = script["characters"]
    if len(chars) != 2:
        print(f"Error: --two-speaker requires exactly 2 characters (found {len(chars)}).",
              file=sys.stderr)
        print("  Use per-line mode (omit --two-speaker) for more speakers.", file=sys.stderr)
        sys.exit(1)

    speaker_voice = {c["name"]: c.get("voice", "Charon") for c in chars}
    lines = [ln for ln in script["lines"] if (ln.get("text") or "").strip()]
    chunks_dir = out_dir / ".chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunk_paths = []
    entries = []
    for ln in lines:
        entries.append({
            "index": ln["index"],
            "speaker": ln["speaker"],
            "voice": speaker_voice.get(ln["speaker"], "Charon"),
            "text": ln["text"].strip(),
            "tags": ln.get("tags", []),
            "file": None,
            "start": None,
            "end": None,
            "duration": None,
            "pause_after": float(ln.get("pause_after", 0.3) or 0.0),
        })

    for ci in range(0, len(lines), MULTISPEAKER_CHUNK_LINES):
        group = lines[ci:ci + MULTISPEAKER_CHUNK_LINES]
        convo = "\n".join(f"{ln['speaker']}: {weave_tags(ln['text'].strip(), ln.get('tags'))}"
                          for ln in group)
        prompt = (
            "Synthesize speech for the following two-person conversation. Speak only "
            "the dialogue; do not read the speaker names aloud.\n\n" + convo
        )
        print(f"  Multi-speaker chunk {ci // MULTISPEAKER_CHUNK_LINES} "
              f"({len(group)} lines) ...", file=sys.stderr)
        data = with_retries(
            lambda: extract_audio_bytes(
                tts_multi(client, types, model, prompt, speaker_voice, language_code)),
            label=f"chunk {ci // MULTISPEAKER_CHUNK_LINES}",
        )
        if data is None and any(ln.get("tags") for ln in group):
            # Retry the chunk without style tags (a single tag can make the model
            # return text instead of audio and drop the whole chunk).
            plain_convo = "\n".join(f"{ln['speaker']}: {ln['text'].strip()}" for ln in group)
            plain_prompt = (
                "Synthesize speech for the following two-person conversation. Speak only "
                "the dialogue; do not read the speaker names aloud.\n\n" + plain_convo
            )
            print(f"    chunk {ci // MULTISPEAKER_CHUNK_LINES}: retrying without style tags ...",
                  file=sys.stderr)
            data = with_retries(
                lambda: extract_audio_bytes(
                    tts_multi(client, types, model, plain_prompt, speaker_voice, language_code)),
                label=f"chunk {ci // MULTISPEAKER_CHUNK_LINES} (no tags)",
            )
        if data is None:
            continue
        chunk_path = chunks_dir / f"chunk-{ci // MULTISPEAKER_CHUNK_LINES:03d}.wav"
        pcm_to_wav(data, chunk_path, rate=TTS_RATE)
        # Re-encode to fixed format for clean concat.
        fixed = chunks_dir / f"fixed-{ci // MULTISPEAKER_CHUNK_LINES:03d}.wav"
        run_ffmpeg(["-i", str(chunk_path), "-ar", str(TTS_RATE), "-ac", "1",
                    "-c:a", "pcm_s16le", str(fixed)])
        chunk_paths.append(fixed)

    if not chunk_paths:
        print("Error: no audio was generated.", file=sys.stderr)
        sys.exit(1)

    dialogue_path = out_dir / "dialogue.wav"
    if len(chunk_paths) == 1:
        run_ffmpeg(["-i", str(chunk_paths[0]), "-c", "copy", str(dialogue_path)])
    else:
        concat_wavs(chunk_paths, dialogue_path)

    for p in chunks_dir.glob("*"):
        p.unlink(missing_ok=True)
    try:
        chunks_dir.rmdir()
    except OSError:
        pass

    return entries, dialogue_path, []


def main():
    parser = argparse.ArgumentParser(description="Generate per-line Gemini TTS voices")
    parser.add_argument("--script", required=True, help="Path to script.json")
    parser.add_argument("--out", "-o", required=True, help="Output project folder")
    parser.add_argument("--two-speaker", action="store_true",
                        help="Render as one multi-speaker take (exactly 2 characters)")
    parser.add_argument("--model", default=None, help="Gemini TTS model")
    parser.add_argument("--language-code", default=None,
                        help="BCP-47 TTS locale/accent, e.g. es-US (LATAM), es-ES "
                             "(Castilian), pt-BR, en-US. Default: script.json "
                             "language_code, else mapped from `language` (es -> es-US).")
    parser.add_argument("--max-clip-seconds", type=float, default=None,
                        help="Warn when a clip exceeds this (default 15, seedance limit)")
    args = parser.parse_args()

    config = load_config()
    model = args.model or config.get("default_tts_model", DEFAULT_TTS_MODEL)
    max_clip = args.max_clip_seconds or config.get("max_clip_seconds", MAX_CLIP_SECONDS)

    script = load_json(args.script)
    out_dir = resolve_out_dir(args.out)
    language_code = resolve_locale(
        script.get("language"),
        args.language_code or script.get("language_code") or config.get("default_language_code"))

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=get_gemini_api_key())

    print(f"  TTS model: {model}", file=sys.stderr)
    if language_code:
        print(f"  TTS locale: {language_code}", file=sys.stderr)
    if args.two_speaker:
        entries, dialogue_path, warnings = generate_two_speaker(
            client, types, model, script, out_dir, max_clip, language_code)
        mode_used = "two_speaker"
    else:
        entries, dialogue_path, warnings = generate_per_line(
            client, types, model, script, out_dir, max_clip, language_code)
        mode_used = "per_line"

    total_dur = get_audio_duration(dialogue_path)
    lines_data = {
        "title": script.get("title"),
        "language": script.get("language"),
        "language_code": language_code,
        "mode": script.get("mode"),
        "tts_mode": mode_used,
        "tts_model": model,
        "dialogue": str(Path(dialogue_path).relative_to(out_dir)),
        "duration": round(total_dur, 3),
        "max_clip_seconds": max_clip,
        "lines": entries,
    }
    lines_json = out_dir / "lines.json"
    save_json(lines_json, lines_data)

    print(f"\n  dialogue.wav: {total_dur:.2f}s ({len(entries)} lines)", file=sys.stderr)
    if warnings:
        print(f"  {len(warnings)} clip(s) exceed {max_clip}s: {warnings}", file=sys.stderr)
    print(json.dumps({
        "dialogue": str(dialogue_path),
        "lines_json": str(lines_json),
        "tts_mode": mode_used,
        "line_count": len(entries),
        "duration": round(total_dur, 3),
        "clips_over_limit": warnings,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
