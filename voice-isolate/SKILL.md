---
name: voice-isolate
description: >-
  Extracts clean voice samples from a video. Separates the vocal stem with
  Demucs, gets speech timecodes with faster-whisper, detects the recurring
  percussive "taka" SFX by its high-frequency signature in the accompaniment
  stem, drops the whole word under each detected SFX, and exports the remaining
  clean spoken phrases as individual sample clips plus a concatenated track. Use
  when the user gives a video and wants the narrator's voice isolated, clean
  voice samples for cloning/TTS, a voice-only audio track, background music/SFX
  removed from speech, or mentions "solo la voz", "aislar la voz", "voz limpia",
  "muestras de voz", "quitar SFX/música", "canal de voz", isolate/extract voice,
  voice samples, narrator voice, or vocal stem from a video or reel.
---

# Voice Isolate

Given a video, produce **clean voice samples of the narrator**: the recurring
percussive SFX (a short broadband "taka"/"tk" that bleeds over the voice) is
detected and the word it lands on is dropped, so the remaining phrases are clean.
The goal is good-quality voice samples (for cloning/TTS), not preserving every
word — contaminated words are discarded on purpose.

## Pipeline

1. **ffmpeg** extracts the audio from the video.
2. **Demucs** (`htdemucs`) splits it into the voice stem and the accompaniment
   stem (everything that is not voice: music + SFX).
3. **faster-whisper** transcribes on the clean voice stem → segments + per-word
   timecodes (more accurate than transcribing the original mix).
4. **Taka detection (auto)**: the SFX is a short broadband transient whose energy
   spikes in the **high band (>5 kHz)**, while the voice body lives below ~4 kHz.
   In the accompaniment stem (voice already removed) those transients stand out.
   The HF energy envelope is peak-picked with an auto-relative threshold, so only
   prominent taka are flagged — not the near-silent floor.
5. **Word drop**: each detected taka is expanded to the **whole word(s)** it
   overlaps and those words are removed from the speech.
6. The remaining clean phrases (≥ `--min-sample-len`) are exported as individual
   `samples/sample_NNN.wav` clips and as one concatenated `voice_concat`.

## Requirements

- `ffmpeg` on PATH.
- Python deps: `pip3 install -r requirements.txt` (no librosa/torch beyond Demucs;
  detection uses `scipy.signal`).
- **torch and torchaudio MUST match versions** (e.g. `torch==2.5.1` +
  `torchaudio==2.5.1`). A mismatch makes torchaudio fail to load and Demucs
  cannot run. Fix with `pip3 install "torchaudio==$(python3 -c 'import torch;print(torch.__version__.split("+")[0])')"`.
- First Demucs run downloads model weights (~80MB), cached afterwards.

## Quick start

Everything is automatic — taka removal and sample export are **on by default**:

```bash
python3 scripts/extract_voice.py <video> --mp3
```

- Output goes to `<video>_voice/` next to the video (override with `-o <dir>`).
- The deliverable is the **`samples/`** folder (clean clips) plus
  **`voice_concat.mp3`** (all clean phrases concatenated).
- `accompaniment.wav` is kept by default so re-runs can reuse the stems (Tuning).
- Add `--language es` (or `en`, …) to skip auto-detection.

Report the final stats printed by the script (taka detected, seconds removed,
number of clean samples) and the path to `samples/` and `voice_concat.mp3`.

## Outputs (in `<video>_voice/`)

| File | What it is |
|------|------------|
| `samples/sample_NNN.wav` / `.mp3` | **Main deliverable**: each clean spoken phrase as an individual sample clip |
| `voice_concat.mp3` / `.wav` | All clean phrases concatenated (taka + their words removed) |
| `voice_gated.wav` | Voice aligned to the original timeline (taka silenced in place) — with `--mode both` |
| `vocals_full.wav` | Full Demucs voice stem (whole timeline) |
| `accompaniment.wav` | Non-voice stem (where the taka is detected) |
| `voice.json` | Language, segments, per-word timecodes, `sfx_detection`, `sfx_intervals`, kept `intervals` |
| `voice.srt` | Narrator speech subtitles |

## Auto-relative threshold (default, no per-video tuning)

The taka is sparse and sits over a near-silent high-frequency floor, so a
fixed threshold — or a MAD-based one — collapses and over-triggers. Instead the
threshold uses a robust **upper** spread of the accompaniment's >5 kHz envelope:

```
threshold = max(--sfx-min-abs, median + k · (p95 − median))
```

Only **prominent peaks** above it (with a minimum spacing) are taken as taka.
The script prints the computed threshold and count each run
(`Umbral auto (taka >5000Hz): median … + k*(p95-median) … = …`) and stores it in
`voice.json` (`sfx_detection`). This is fully per-video and needs no tuning.

## Tuning (fast, no re-separation)

Re-running Demucs is the slow part. After a first run (accompaniment is saved by
default), use `--reuse-stems` to re-cut in ~5s from the saved
`vocals_full.wav` + `accompaniment.wav` + `voice.json`:

```bash
# More taka removed → lower k; keep more voice → raise k:
python3 scripts/extract_voice.py <video> --reuse-stems --mp3 --sfx-k 3
```

Key knobs:

- `--sfx-k` (default `4.0`): sensitivity. **Lower = more taka removed** (cleaner
  remainder, less voice kept); higher = fewer. `k≈4` removes only the clear taka;
  drop to `3`/`2` if some are still audible, raise to `5` if too much is cut.
- `--sfx-hf-hz` (default `5000`): the high band where the taka lives. Lower it if
  the SFX is more midrange; the voice body is below ~4 kHz.
- `--sfx-min-distance` (default `0.20`): minimum spacing (s) between taka peaks.
- `--sfx-half-width` (default `0.06`): half-window (s) around each peak before
  snapping to the word.
- `--min-sample-len` (default `0.4`): drop clean chunks shorter than this (keeps
  only usable samples).
- `--sfx-word-pad` (default `0.04`): extra margin when expanding a peak to a word.
- `--no-snap-words`: cut exactly the peak instead of the whole word (may leave a
  half-word; usually not wanted for samples).
- `--no-samples`: skip the individual-clip export (keep only the concat).
- `--no-remove-sfx`: disable taka detection entirely (raw Demucs voice).

## Notes / limitations

- Demucs isolates **all** vocals, not a specific speaker. With multiple speakers,
  all voices stay in the stem (no diarization).
- The taka detector targets **discrete transient SFX**. A **continuous music
  bed** under the voice is not removed by dropping words (it overlaps every word);
  for a cleaner stem re-separate with the fine-tuned model
  `--demucs-model htdemucs_ft` (≈4× slower, CPU only — MPS is unsupported for it).
- `--no-demucs` skips separation and just trims the original audio by speech VAD
  (no taka removal).
