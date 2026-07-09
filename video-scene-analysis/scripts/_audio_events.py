"""Per-scene audio event detection: speech vs SFX vs music bed (local heuristics)."""

from __future__ import annotations

import numpy as np

AUDIO_PROFILES = {
    "silent": "Sin audio relevante",
    "speech_only": "Solo voz",
    "speech_with_sfx": "Voz + efectos de sonido (SFX)",
    "speech_with_music": "Voz + música/ambiente continuo",
    "speech_mixed": "Voz + SFX + música/ambiente",
    "sfx_only": "Solo efectos (sin voz)",
    "music_only": "Solo música/ambiente (sin voz)",
    "ambient": "Ambiente/noise de fondo",
}


def load_wav_mono(path) -> tuple[np.ndarray, int]:
    try:
        from scipy.io import wavfile
    except ImportError as exc:
        raise RuntimeError("scipy required for audio analysis. pip3 install scipy") from exc

    sr, data = wavfile.read(str(path))
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.dtype == np.int16:
        samples = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        samples = data.astype(np.float32) / 2147483648.0
    else:
        samples = data.astype(np.float32)
    return samples, int(sr)


def _speech_intervals_in_window(
    words: list[dict],
    start: float,
    end: float,
    *,
    pad: float = 0.12,
) -> list[tuple[float, float]]:
    intervals = []
    for w in words:
        ws, we = w.get("start"), w.get("end")
        if ws is None or we is None:
            continue
        if we <= start or ws >= end:
            continue
        intervals.append((max(start, ws - pad), min(end, we + pad)))
    if not intervals:
        return []
    intervals.sort()
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def _mask_from_intervals(length: int, sr: int, start: float, intervals: list[tuple[float, float]]) -> np.ndarray:
    mask = np.zeros(length, dtype=bool)
    base = int(start * sr)
    for s, e in intervals:
        i0 = max(0, int(s * sr) - base)
        i1 = min(length, int(e * sr) - base)
        if i1 > i0:
            mask[i0:i1] = True
    return mask


def _frame_rms(samples: np.ndarray, sr: int, *, frame_ms: float = 25.0, hop_ms: float = 10.0):
    frame = max(1, int(sr * frame_ms / 1000))
    hop = max(1, int(sr * hop_ms / 1000))
    if len(samples) < frame:
        return np.array([float(np.sqrt(np.mean(samples ** 2)))] if len(samples) else [0.0])
    rms = []
    for i in range(0, len(samples) - frame + 1, hop):
        chunk = samples[i : i + frame]
        rms.append(float(np.sqrt(np.mean(chunk ** 2))))
    return np.array(rms, dtype=np.float32)


def _detect_transient_peaks(
    rms: np.ndarray,
    *,
    min_strength: float,
    hop_sec: float,
    min_gap_sec: float = 0.18,
) -> list[dict]:
    if len(rms) < 3:
        return []
    diff = np.diff(rms)
    candidates = []
    for i in range(1, len(rms) - 1):
        if rms[i] < min_strength:
            continue
        if diff[i - 1] > 0 and diff[i] <= 0 and rms[i] >= rms[i - 1]:
            strength = float(rms[i])
            if strength >= min_strength * 1.6:
                candidates.append({"frame": i, "strength": round(strength, 4)})

    if not candidates:
        return []

    min_gap_frames = max(1, int(min_gap_sec / hop_sec))
    peaks = [candidates[0]]
    for cand in candidates[1:]:
        if cand["frame"] - peaks[-1]["frame"] >= min_gap_frames:
            peaks.append(cand)
    return peaks


def analyze_scene_audio(
    samples: np.ndarray,
    sr: int,
    start: float,
    end: float,
    words: list[dict],
    *,
    hop_ms: float = 10.0,
) -> dict:
    i0 = max(0, int(start * sr))
    i1 = min(len(samples), int(end * sr))
    segment = samples[i0:i1]
    duration = max(0.0, end - start)

    if len(segment) == 0 or duration <= 0.05:
        return {
            "audio_profile": "silent",
            "has_speech": False,
            "has_sfx": False,
            "has_music_bed": False,
            "non_speech_ratio": 0.0,
            "sfx_event_count": 0,
            "sfx_events": [],
        }

    speech_intervals = _speech_intervals_in_window(words, start, end)
    speech_mask = _mask_from_intervals(len(segment), sr, start, speech_intervals)
    speech_samples = segment[speech_mask] if speech_mask.any() else segment[:0]
    non_speech_samples = segment[~speech_mask] if (~speech_mask).any() else segment[:0]

    full_rms = float(np.sqrt(np.mean(segment ** 2)))
    speech_rms = float(np.sqrt(np.mean(speech_samples ** 2))) if len(speech_samples) else 0.0
    non_speech_rms = float(np.sqrt(np.mean(non_speech_samples ** 2))) if len(non_speech_samples) else 0.0

    noise_floor = max(0.008, float(np.percentile(np.abs(segment), 20)))
    min_peak = max(noise_floor * 3, 0.02)

    non_speech_rms_series = _frame_rms(non_speech_samples, sr, hop_ms=hop_ms) if len(non_speech_samples) else np.array([])
    speech_rms_series = _frame_rms(speech_samples, sr, hop_ms=hop_ms) if len(speech_samples) else np.array([])

    hop_sec = hop_ms / 1000.0
    peaks = _detect_transient_peaks(
        non_speech_rms_series, min_strength=min_peak, hop_sec=hop_sec,
    )
    sfx_event_count = len(peaks)
    peak_density = sfx_event_count / max(1, len(non_speech_rms_series))

    non_speech_ratio = float((~speech_mask).sum() / max(1, len(speech_mask)))
    has_speech = len(speech_intervals) > 0 and speech_rms > noise_floor * 1.5

    # Music bed: sustained non-speech energy, or rhythmic density (beats ≠ discrete SFX)
    if len(non_speech_rms_series) >= 5:
        sustained = float(np.mean(non_speech_rms_series > noise_floor * 2.5))
        has_music_bed = (
            (sustained > 0.35 and non_speech_rms > noise_floor * 2)
            or (peak_density > 0.12 and non_speech_rms > noise_floor * 2.5)
        )
    else:
        has_music_bed = False

    if has_speech and len(speech_rms_series) >= 3:
        full_series = _frame_rms(segment, sr, hop_ms=hop_ms)
        bed_under_voice = float(np.mean(full_series > (speech_rms * 0.55 + noise_floor))) > 0.5
        has_music_bed = has_music_bed or (bed_under_voice and non_speech_rms > noise_floor)

    # SFX: sparse, isolated transients — not a rhythmic bed
    has_sfx = (
        sfx_event_count >= 1
        and non_speech_rms > noise_floor * 2
        and peak_density < 0.12
    )

    if not has_speech and full_rms <= noise_floor * 1.5:
        profile = "silent"
    elif not has_speech and has_sfx and not has_music_bed:
        profile = "sfx_only"
    elif not has_speech and has_music_bed:
        profile = "music_only"
    elif not has_speech:
        profile = "ambient" if full_rms > noise_floor else "silent"
    elif has_speech and has_sfx and has_music_bed:
        profile = "speech_mixed"
    elif has_speech and has_sfx:
        profile = "speech_with_sfx"
    elif has_speech and has_music_bed:
        profile = "speech_with_music"
    else:
        profile = "speech_only"

    hop_sec = hop_ms / 1000.0
    sfx_events = []
    for p in peaks[:8]:
        rel_start = round(p["frame"] * hop_sec, 3)
        sfx_events.append({
            "start": round(start + rel_start, 3),
            "end": round(start + rel_start + 0.25, 3),
            "strength": p["strength"],
        })

    return {
        "audio_profile": profile,
        "has_speech": has_speech,
        "has_sfx": has_sfx,
        "has_music_bed": has_music_bed,
        "non_speech_ratio": round(non_speech_ratio, 3),
        "sfx_event_count": sfx_event_count,
        "sfx_events": sfx_events,
        "levels": {
            "full_rms": round(full_rms, 4),
            "speech_rms": round(speech_rms, 4),
            "non_speech_rms": round(non_speech_rms, 4),
        },
    }


def analyze_all_scenes(
    wav_path,
    scenes: list[dict],
    words: list[dict],
) -> list[dict]:
    samples, sr = load_wav_mono(wav_path)
    return [
        analyze_scene_audio(samples, sr, s["start"], s["end"], words)
        for s in scenes
    ]
