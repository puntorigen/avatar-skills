#!/usr/bin/env python3
"""Aísla el canal de voz del narrador de un video.

Pipeline:
  1. ffmpeg      -> extrae el audio del video a WAV.
  2. Demucs      -> separa el stem de voz (vocals) del resto (música/SFX/ambiente).
  3. faster-whisper -> detecta dónde habla el narrador (segmentos + timecodes, VAD).
  4. timecodes   -> recorta el stem de voz para conservar SOLO donde se habla.

Salidas (en <video>_voice/ por defecto):
  samples/sample_NNN.wav — cada tramo de voz LIMPIO como clip individual (para
                           clonado/TTS). Es el entregable principal.
  voice_concat.wav  — todos los tramos limpios concatenados (sin huecos ni taka)
  voice_gated.wav   — voz limpia, alineada con el video (silencio donde no se habla)
  vocals_full.wav   — stem de voz completo de Demucs (timeline entero), opcional
  accompaniment.wav — stem de no-voz (música/SFX); usado para detectar el taka
  voice.json        — segmentos, timecodes e intervalos usados para el recorte
  voice.srt         — subtítulos del habla del narrador (para verificar timecodes)

Omitir el 'taka' (SFX percusivo sobre la voz) — ACTIVADO por defecto:
  El objetivo es obtener MUESTRAS de voz de buena calidad. Un SFX transitorio de
  banda ancha (un 'tk' breve, agudo) se cuela sobre la voz. Se detecta por su
  firma de ALTA FRECUENCIA en el stem de acompañamiento (donde la voz ya no está):
  se toma la envolvente >~5 kHz y se eligen sus PICOS prominentes con umbral
  AUTO-relativo (median + k*(p95-median)). Cada pico se ajusta a la PALABRA
  completa que toca y esa palabra se descarta, de modo que las muestras que quedan
  están limpias. Usa --no-remove-sfx para desactivarlo.

Uso:
    python3 scripts/extract_voice.py lolo/videos/clip.mp4              # todo auto
    python3 scripts/extract_voice.py lolo/videos/clip.mp4 -l es --mp3
    # re-recortar rápido probando sensibilidad (reutiliza stems, sin re-correr Demucs):
    python3 scripts/extract_voice.py lolo/videos/clip.mp4 --reuse-stems --sfx-k 3
    python3 scripts/extract_voice.py lolo/videos/clip.mp4 --no-remove-sfx  # sin quitar taka
    python3 scripts/extract_voice.py lolo/videos/clip.mp4 --no-demucs      # solo recorte por VAD

Notas:
  - Demucs aísla TODA la voz cantada/hablada, no separa locutores. Si el video tiene
    varios hablantes, todos quedan en el stem de voz. La diarización (separar por
    persona) requiere otra herramienta (p.ej. pyannote) y queda fuera de este script.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent


def _frame_rms(
    samples: np.ndarray, sr: int, *, frame_ms: float = 25.0, hop_ms: float = 10.0
) -> np.ndarray:
    """RMS por ventana deslizante (frame_ms / hop_ms)."""
    frame = max(1, int(sr * frame_ms / 1000))
    hop = max(1, int(sr * hop_ms / 1000))
    if len(samples) < frame:
        return np.array(
            [float(np.sqrt(np.mean(samples ** 2)))] if len(samples) else [0.0],
            dtype=np.float32,
        )
    rms = []
    for i in range(0, len(samples) - frame + 1, hop):
        chunk = samples[i : i + frame]
        rms.append(float(np.sqrt(np.mean(chunk ** 2))))
    return np.array(rms, dtype=np.float32)


# --------------------------------------------------------------------------- #
# Audio extraction
# --------------------------------------------------------------------------- #
def extract_audio_wav(video_path: Path, wav_path: Path, sample_rate: int) -> bool:
    """Extrae audio del video a WAV estéreo PCM 16-bit al sample rate pedido."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", str(sample_rate), "-ac", "2",
        str(wav_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr[-800:], file=sys.stderr)
    return proc.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 0


# --------------------------------------------------------------------------- #
# Demucs vocal separation
# --------------------------------------------------------------------------- #
def separate_vocals(
    audio_path: Path,
    *,
    model_name: str,
    device: str,
    shifts: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Separa el audio con Demucs.

    Devuelve (vocals, accompaniment, samplerate), ambos arrays [samples, channels]
    float32. ``accompaniment`` es la suma de los stems que NO son voz
    (drums + bass + other), o sea todo el SFX/música/ambiente.
    """
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.audio import AudioFile, convert_audio
        from demucs.pretrained import get_model
    except ImportError as exc:
        raise RuntimeError(
            "Demucs/torch no instalados. Ejecuta: pip3 install demucs soundfile"
        ) from exc

    print(f"  Separando voz con Demucs ({model_name}, device={device})...", file=sys.stderr)
    model = get_model(model_name)
    model.to(device)
    model.eval()

    if "vocals" not in model.sources:
        raise RuntimeError(
            f"El modelo {model_name} no tiene stem 'vocals' (tiene {model.sources})."
        )
    vocals_idx = model.sources.index("vocals")
    other_idx = [i for i in range(len(model.sources)) if i != vocals_idx]

    wav = AudioFile(audio_path).read(
        streams=0, samplerate=model.samplerate, channels=model.audio_channels
    )
    wav = convert_audio(wav, model.samplerate, model.samplerate, model.audio_channels)

    # Normalización idéntica a demucs.separate para niveles de salida correctos.
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std()
    wav = (wav - mean) / (std + 1e-8)

    with torch.no_grad():
        out = apply_model(
            model,
            wav[None],
            device=device,
            shifts=shifts,
            split=True,
            overlap=0.25,
            progress=True,
        )[0]
    out = out * std + mean

    vocals = out[vocals_idx].cpu().numpy().T.astype(np.float32)  # (samples, channels)
    accompaniment = out[other_idx].sum(0).cpu().numpy().T.astype(np.float32)
    return vocals, accompaniment, int(model.samplerate)


# --------------------------------------------------------------------------- #
# Whisper transcription
# --------------------------------------------------------------------------- #
def transcribe(
    audio_path: Path,
    *,
    language: str | None,
    model_size: str,
) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper no instalado. Ejecuta: pip3 install faster-whisper"
        ) from exc

    print(f"  Transcribiendo con faster-whisper ({model_size})...", file=sys.stderr)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    lang = (language or "").strip().lower()[:2] or None
    segments_iter, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        language=lang,
        vad_filter=True,
    )

    segments, words = [], []
    for seg in segments_iter:
        seg_words = []
        for w in seg.words or []:
            ww = {"word": (w.word or "").strip(), "start": w.start, "end": w.end}
            if ww["word"] and ww["start"] is not None and ww["end"] is not None:
                seg_words.append(ww)
                words.append(ww)
        segments.append({
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": (seg.text or "").strip(),
            "words": seg_words,
        })

    return {
        "language": getattr(info, "language", lang),
        "duration": round(float(getattr(info, "duration", 0) or 0), 3),
        "segments": segments,
        "words": words,
    }


# --------------------------------------------------------------------------- #
# Interval building + audio gating
# --------------------------------------------------------------------------- #
def build_intervals(
    units: list[dict],
    duration: float,
    *,
    pad: float,
    gap: float,
    min_seg: float,
) -> list[list[float]]:
    """Construye intervalos [inicio, fin] de habla a partir de segmentos o palabras."""
    raw = []
    for u in units:
        s, e = u.get("start"), u.get("end")
        if s is None or e is None:
            continue
        a = max(0.0, float(s) - pad)
        b = float(e) + pad
        if duration > 0:
            b = min(duration, b)
        if b > a:
            raw.append([a, b])
    raw.sort()

    merged: list[list[float]] = []
    for a, b in raw:
        if merged and a <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    return [iv for iv in merged if (iv[1] - iv[0]) >= min_seg]


def detect_sfx_intervals(
    accompaniment: np.ndarray,
    sr: int,
    *,
    k: float,
    hf_hz: float = 5000.0,
    min_distance: float = 0.20,
    half_width: float = 0.06,
    min_abs: float = 0.0,
    n_fft: int = 1024,
    hop: int = 256,
) -> tuple[list[list[float]], dict]:
    """Detecta los 'taka' (SFX percusivo/transitorio) por su firma de ALTA FRECUENCIA.

    El SFX distintivo que se cuela sobre la voz es un transitorio de banda ancha
    (un 'tk' breve) cuya energía sube en AGUDOS, mientras que el cuerpo de la voz
    vive por debajo de ~4 kHz. En el stem de acompañamiento (donde la voz ya fue
    removida) esos transitorios resaltan limpiamente. Tomamos la envolvente de
    energía por encima de ``hf_hz`` y elegimos solo sus PICOS prominentes:

        threshold = max(min_abs, median + k * (p95 - median))

    ``p95 - median`` es una dispersión robusta hacia arriba. A diferencia del MAD,
    NO colapsa cuando los agudos están casi en silencio la mayor parte del tiempo
    (que es justo el caso: el taka es escaso sobre un piso casi mudo). Se exige
    prominencia para no disparar con el piso de ruido. Cada pico se expande
    ±``half_width`` y luego (fuera de aquí) se ajusta a la palabra completa.

    Todo es AUTO-relativo a la distribución de CADA video; no hay umbral fijo.
    """
    mono = accompaniment.mean(axis=1) if accompaniment.ndim > 1 else accompaniment
    meta = {
        "method": "hf_peaks", "median": 0.0, "p95": 0.0, "spread": 0.0,
        "threshold": 0.0, "k": k, "hf_hz": hf_hz, "count": 0,
    }
    if len(mono) < n_fft:
        return [], meta

    from scipy.signal import stft, find_peaks

    freqs, times, Z = stft(
        mono, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, boundary=None, padded=False,
    )
    if Z.shape[1] < 3:
        return [], meta
    mag = np.abs(Z)
    band = freqs >= hf_hz
    if not band.any():  # sr demasiado bajo: usa la mitad superior del espectro
        band = freqs >= (freqs[-1] * 0.5)
    env = mag[band].mean(axis=0)

    median = float(np.median(env))
    p95 = float(np.percentile(env, 95))
    spread = max(p95 - median, 1e-9)
    threshold = max(min_abs, median + k * spread)
    fps = sr / hop
    peaks, _ = find_peaks(
        env,
        height=threshold,
        distance=max(1, int(min_distance * fps)),
        prominence=spread * k * 0.6,
    )
    meta = {
        "method": "hf_peaks",
        "median": round(median, 6),
        "p95": round(p95, 6),
        "spread": round(spread, 6),
        "threshold": round(threshold, 6),
        "k": k,
        "hf_hz": hf_hz,
        "count": int(len(peaks)),
    }
    windows = [
        [max(0.0, float(times[p]) - half_width), float(times[p]) + half_width]
        for p in peaks
    ]
    windows.sort()
    merged: list[list[float]] = []
    for a, b in windows:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged, meta


def expand_intervals_to_words(
    intervals: list[list[float]],
    words: list[dict],
    *,
    pad: float = 0.05,
) -> list[list[float]]:
    """Expande cada ventana para abarcar por completo las palabras que toca.

    Si un pico cae a mitad de una palabra, recortar solo el pico dejaría media
    palabra (un "vacío" en medio). Expandiendo la ventana a los límites de las
    palabras solapadas, se omite la palabra entera y el corte queda limpio.
    """
    if not words:
        return [list(iv) for iv in intervals]

    expanded: list[list[float]] = []
    for a, b in intervals:
        lo, hi = a, b
        for w in words:
            ws, we = w.get("start"), w.get("end")
            if ws is None or we is None:
                continue
            if we <= a or ws >= b:  # sin solape con el pico
                continue
            lo = min(lo, float(ws) - pad)
            hi = max(hi, float(we) + pad)
        expanded.append([max(0.0, lo), hi])

    expanded.sort()
    merged: list[list[float]] = []
    for a, b in expanded:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def subtract_intervals(
    base: list[list[float]], cut: list[list[float]]
) -> list[list[float]]:
    """Devuelve ``base`` quitando las regiones que se solapan con ``cut``."""
    if not cut:
        return [list(iv) for iv in base]
    cut = sorted(cut)
    result: list[list[float]] = []
    for a, b in base:
        segments = [[a, b]]
        for ca, cb in cut:
            new_segments = []
            for s, e in segments:
                if cb <= s or ca >= e:
                    new_segments.append([s, e])
                    continue
                if ca > s:
                    new_segments.append([s, min(ca, e)])
                if cb < e:
                    new_segments.append([max(cb, s), e])
            segments = new_segments
        result.extend(segments)
    return [iv for iv in result if iv[1] > iv[0]]


def apply_gate(audio: np.ndarray, sr: int, intervals: list[list[float]], fade_ms: float) -> np.ndarray:
    """Silencia todo lo que esté fuera de los intervalos, con fades para evitar clicks."""
    n = audio.shape[0]
    env = np.zeros(n, dtype=np.float32)
    fade = int(sr * fade_ms / 1000.0)
    for a, b in intervals:
        i0 = max(0, int(round(a * sr)))
        i1 = min(n, int(round(b * sr)))
        if i1 <= i0:
            continue
        env[i0:i1] = 1.0
        f = min(fade, (i1 - i0) // 2)
        if f > 0:
            env[i0:i0 + f] = np.linspace(0.0, 1.0, f, endpoint=False, dtype=np.float32)
            env[i1 - f:i1] = np.linspace(1.0, 0.0, f, endpoint=False, dtype=np.float32)
    return (audio * env[:, None]).astype(np.float32)


def apply_concat(audio: np.ndarray, sr: int, intervals: list[list[float]], fade_ms: float) -> np.ndarray:
    """Concatena solo los tramos hablados (elimina los huecos), con micro-fades."""
    fade = int(sr * fade_ms / 1000.0)
    chunks = []
    for a, b in intervals:
        i0 = max(0, int(round(a * sr)))
        i1 = min(len(audio), int(round(b * sr)))
        if i1 <= i0:
            continue
        chunk = audio[i0:i1].copy()
        f = min(fade, len(chunk) // 2)
        if f > 0:
            ramp = np.linspace(0.0, 1.0, f, endpoint=False, dtype=np.float32)
            chunk[:f] *= ramp[:, None]
            chunk[-f:] *= ramp[::-1][:, None]
        chunks.append(chunk)
    if not chunks:
        return np.zeros((0, audio.shape[1]), dtype=np.float32)
    return np.concatenate(chunks, axis=0).astype(np.float32)


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    import soundfile as sf

    sf.write(str(path), np.clip(audio, -1.0, 1.0), sr, subtype="PCM_16")


def encode_mp3(wav_path: Path, mp3_path: Path) -> bool:
    cmd = [
        "ffmpeg", "-y", "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-q:a", "2", str(mp3_path),
    ]
    return subprocess.run(cmd, capture_output=True, text=True).returncode == 0


def srt_timestamp(seconds: float) -> str:
    td = timedelta(seconds=max(0.0, seconds))
    total_ms = int(td.total_seconds() * 1000)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: Path, segments: list[dict]) -> None:
    lines = []
    idx = 1
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{srt_timestamp(seg['start'])} --> {srt_timestamp(seg['end'])}")
        lines.append(text)
        lines.append("")
        idx += 1
    path.write_text("\n".join(lines), encoding="utf-8")


def pick_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run(
    video_path: Path,
    out_dir: Path,
    *,
    language: str | None,
    whisper_model: str,
    demucs_model: str,
    device: str,
    shifts: int,
    mode: str,
    pad: float,
    gap: float,
    min_seg: float,
    fade_ms: float,
    word_level: bool,
    use_demucs: bool,
    keep_stem: bool,
    sample_rate: int,
    make_mp3: bool,
    remove_sfx: bool,
    sfx_k: float,
    sfx_min_abs: float = 0.0,
    sfx_hf_hz: float = 5000.0,
    sfx_min_distance: float = 0.20,
    sfx_half_width: float = 0.06,
    snap_words: bool = True,
    sfx_word_pad: float = 0.04,
    min_sample_len: float = 0.4,
    split_samples: bool = True,
    keep_accompaniment: bool = True,
    reuse_stems: bool = False,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    accompaniment = None
    voc_path = out_dir / "vocals_full.wav"
    acc_path = out_dir / "accompaniment.wav"
    can_reuse = reuse_stems and use_demucs and voc_path.exists()

    if can_reuse:
        import soundfile as sf

        print("[1-3/4] Reutilizando stems existentes (se omite Demucs)...", file=sys.stderr)
        voice_audio, sr = sf.read(str(voc_path), dtype="float32", always_2d=True)
        if acc_path.exists():
            accompaniment, _ = sf.read(str(acc_path), dtype="float32", always_2d=True)
        elif remove_sfx:
            print(
                "  AVISO: no existe accompaniment.wav para reutilizar; "
                "no se podrán omitir SFX. Re-ejecuta sin --reuse-stems.",
                file=sys.stderr,
            )
        need_words = word_level or (remove_sfx and snap_words)
        transcript = None
        prev_json = out_dir / "voice.json"
        if prev_json.exists():
            try:
                prev = json.loads(prev_json.read_text(encoding="utf-8"))
                has_words = bool(prev.get("words"))
                if prev.get("segments") and (not need_words or has_words):
                    transcript = {
                        "language": prev.get("language"),
                        "duration": prev.get("duration", 0),
                        "segments": prev["segments"],
                        "words": prev.get("words", []),
                    }
                    print("  Reutilizando transcripción de voice.json.", file=sys.stderr)
            except Exception:
                transcript = None
        if transcript is None:
            transcript = transcribe(voc_path, language=language, model_size=whisper_model)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            full_wav = tmp_dir / "audio.wav"

            print(f"[1/4] Extrayendo audio de {video_path.name}...", file=sys.stderr)
            if not extract_audio_wav(video_path, full_wav, sample_rate):
                raise RuntimeError("ffmpeg no pudo extraer el audio del video.")

            if use_demucs:
                print("[2/4] Separando stem de voz...", file=sys.stderr)
                voice_audio, accompaniment, sr = separate_vocals(
                    full_wav, model_name=demucs_model, device=device, shifts=shifts,
                )
                stem_wav = tmp_dir / "vocals.wav"
                write_wav(stem_wav, voice_audio, sr)
                transcribe_src = stem_wav  # transcribir sobre la voz limpia = más preciso
            else:
                print("[2/4] (saltando Demucs, se usa el audio original)", file=sys.stderr)
                import soundfile as sf

                data, sr = sf.read(str(full_wav), dtype="float32", always_2d=True)
                voice_audio = data
                transcribe_src = full_wav

            print("[3/4] Detectando habla del narrador...", file=sys.stderr)
            transcript = transcribe(transcribe_src, language=language, model_size=whisper_model)

    print("[4/4] Recortando por timecodes...", file=sys.stderr)
    duration = len(voice_audio) / sr
    units = transcript["words"] if word_level else transcript["segments"]
    intervals = build_intervals(units, duration, pad=pad, gap=gap, min_seg=min_seg)

    sfx_intervals: list[list[float]] = []
    sfx_meta: dict | None = None
    speech_before = sum(b - a for a, b in intervals)
    if remove_sfx:
        if accompaniment is None:
            print(
                "  AVISO: --remove-sfx requiere el stem de acompañamiento (Demucs); se ignora.",
                file=sys.stderr,
            )
        else:
            sfx_intervals, sfx_meta = detect_sfx_intervals(
                accompaniment, sr,
                k=sfx_k,
                min_abs=sfx_min_abs,
                hf_hz=sfx_hf_hz,
                min_distance=sfx_min_distance,
                half_width=sfx_half_width,
            )
            if snap_words and transcript.get("words"):
                sfx_intervals = expand_intervals_to_words(
                    sfx_intervals, transcript["words"], pad=sfx_word_pad,
                )
            elif snap_words and not transcript.get("words"):
                print(
                    "  AVISO: no hay timecodes por palabra; no se pudo ajustar a palabras.",
                    file=sys.stderr,
                )
            intervals = subtract_intervals(intervals, sfx_intervals)
            # Para muestras de voz: descarta los trozos limpios demasiado cortos.
            min_frag = max(min_sample_len, min_seg, 2 * fade_ms / 1000.0)
            intervals = [iv for iv in intervals if (iv[1] - iv[0]) >= min_frag]
            removed = speech_before - sum(b - a for a, b in intervals)
            preview = ", ".join(f"{a:.1f}-{b:.1f}" for a, b in sfx_intervals[:8])
            print(
                f"  Umbral auto (taka >{sfx_meta['hf_hz']:g}Hz): median "
                f"{sfx_meta['median']:.2e} + {sfx_meta['k']:g}*(p95-median) "
                f"{sfx_meta['spread']:.2e} = {sfx_meta['threshold']:.2e}",
                file=sys.stderr,
            )
            print(
                f"  Taka detectados: {sfx_meta['count']} picos -> {len(sfx_intervals)} "
                f"ventanas de palabra [{preview}{' ...' if len(sfx_intervals) > 8 else ''}]; "
                f"se omitieron {removed:.2f}s de voz.",
                file=sys.stderr,
            )

    outputs: dict[str, str] = {}

    if keep_accompaniment and accompaniment is not None:
        p = out_dir / "accompaniment.wav"
        write_wav(p, accompaniment, sr)
        outputs["accompaniment"] = str(p)

    if keep_stem and use_demucs:
        write_wav(voc_path, voice_audio, sr)
        outputs["vocals_full"] = str(voc_path)
        if make_mp3 and encode_mp3(voc_path, voc_path.with_suffix(".mp3")):
            outputs["vocals_full_mp3"] = str(voc_path.with_suffix(".mp3"))

    if mode in ("gated", "both"):
        gated = apply_gate(voice_audio, sr, intervals, fade_ms)
        p = out_dir / "voice_gated.wav"
        write_wav(p, gated, sr)
        outputs["voice_gated"] = str(p)
        if make_mp3 and encode_mp3(p, p.with_suffix(".mp3")):
            outputs["voice_gated_mp3"] = str(p.with_suffix(".mp3"))

    if mode in ("concat", "both"):
        concat = apply_concat(voice_audio, sr, intervals, fade_ms)
        p = out_dir / "voice_concat.wav"
        write_wav(p, concat, sr)
        outputs["voice_concat"] = str(p)
        if make_mp3 and encode_mp3(p, p.with_suffix(".mp3")):
            outputs["voice_concat_mp3"] = str(p.with_suffix(".mp3"))

    # Muestras de voz: cada tramo limpio como clip individual (para clonado/TTS).
    if split_samples and intervals:
        samples_dir = out_dir / "samples"
        samples_dir.mkdir(parents=True, exist_ok=True)
        for old in samples_dir.glob("sample_*.wav"):
            old.unlink()
        for old in samples_dir.glob("sample_*.mp3"):
            old.unlink()
        sample_paths: list[str] = []
        fade = int(sr * fade_ms / 1000.0)
        for idx, (a, b) in enumerate(intervals, start=1):
            i0 = max(0, int(round(a * sr)))
            i1 = min(len(voice_audio), int(round(b * sr)))
            if i1 <= i0:
                continue
            clip = voice_audio[i0:i1].copy()
            f = min(fade, len(clip) // 2)
            if f > 0:
                ramp = np.linspace(0.0, 1.0, f, endpoint=False, dtype=np.float32)
                shape = (f,) + (1,) * (clip.ndim - 1)
                clip[:f] *= ramp.reshape(shape)
                clip[-f:] *= ramp[::-1].reshape(shape)
            sp = samples_dir / f"sample_{idx:03d}.wav"
            write_wav(sp, clip, sr)
            sample_paths.append(str(sp))
            if make_mp3:
                encode_mp3(sp, sp.with_suffix(".mp3"))
        outputs["samples_dir"] = str(samples_dir)
        outputs["sample_count"] = len(sample_paths)
        print(
            f"  Muestras de voz: {len(sample_paths)} clips limpios en {samples_dir}/",
            file=sys.stderr,
        )

    speech_total = round(sum(b - a for a, b in intervals), 3)
    result = {
        "video": str(video_path),
        "duration": round(duration, 3),
        "language": transcript["language"],
        "whisper_model": whisper_model,
        "demucs_model": demucs_model if use_demucs else None,
        "sample_rate": sr,
        "mode": mode,
        "interval_source": "words" if word_level else "segments",
        "params": {"pad": pad, "gap": gap, "min_seg": min_seg, "fade_ms": fade_ms},
        "remove_sfx": remove_sfx and accompaniment is not None,
        "sfx_detection": sfx_meta,
        "sfx_snap_words": bool(remove_sfx and snap_words and transcript.get("words")),
        "sfx_interval_count": len(sfx_intervals),
        "sfx_seconds": round(sum(b - a for a, b in sfx_intervals), 3),
        "sfx_intervals": [[round(a, 3), round(b, 3)] for a, b in sfx_intervals],
        "speech_seconds": speech_total,
        "speech_ratio": round(speech_total / duration, 3) if duration else 0.0,
        "interval_count": len(intervals),
        "intervals": [[round(a, 3), round(b, 3)] for a, b in intervals],
        "segments": [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in transcript["segments"]
        ],
        "words": [
            {"word": w["word"], "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
            for w in transcript.get("words", [])
            if w.get("start") is not None and w.get("end") is not None
        ],
        "outputs": outputs,
        "elapsed_seconds": round(time.time() - t0, 1),
    }

    (out_dir / "voice.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_srt(out_dir / "voice.srt", transcript["segments"])

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Aísla el canal de voz del narrador de un video (Demucs + faster-whisper).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("video", type=Path, help="Ruta al video de entrada")
    parser.add_argument(
        "-o", "--out-dir", type=Path, default=None,
        help="Carpeta de salida (por defecto: <video>_voice/ junto al video)",
    )
    parser.add_argument("-l", "--language", default=None, help="Idioma (es, en, ...); auto si se omite")
    parser.add_argument(
        "--whisper-model", default="small",
        help="Tamaño del modelo faster-whisper (tiny, base, small, medium, large-v3)",
    )
    parser.add_argument("--demucs-model", default="htdemucs", help="Modelo Demucs")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"],
                        help="Dispositivo para Demucs")
    parser.add_argument("--shifts", type=int, default=1,
                        help="Demucs shifts (más = mejor calidad y más lento)")
    parser.add_argument("--mode", default="both", choices=["gated", "concat", "both"],
                        help="gated=alineado al video; concat=solo habla; both=ambos")
    parser.add_argument("--pad", type=float, default=0.15, help="Padding (s) a cada lado de cada tramo")
    parser.add_argument("--gap", type=float, default=0.35, help="Une tramos separados por menos de este hueco (s)")
    parser.add_argument("--min-seg", type=float, default=0.0, help="Descarta tramos más cortos que esto (s)")
    parser.add_argument("--fade-ms", type=float, default=15.0, help="Fade in/out (ms) en los bordes de cada tramo")
    parser.add_argument("--word-level", action="store_true",
                        help="Usa timecodes por palabra (más ajustado, puede sonar cortado)")
    parser.add_argument("--no-demucs", action="store_true",
                        help="No separar stem; recortar el audio original por VAD")
    parser.add_argument("--no-keep-stem", action="store_true",
                        help="No guardar vocals_full.wav (stem completo)")
    parser.add_argument("--sample-rate", type=int, default=44100, help="Sample rate de extracción/salida")
    parser.add_argument("--mp3", action="store_true", help="Generar también versiones .mp3")

    sfx = parser.add_argument_group(
        "Omitir el 'taka' (SFX percusivo/transitorio sobre la voz) — ON por defecto"
    )
    sfx.add_argument("--no-remove-sfx", dest="remove_sfx", action="store_false",
                     help="No detectar/omitir el taka (deja la voz tal cual sale de Demucs)")
    sfx.add_argument("--sfx-k", type=float, default=4.0,
                     help="Sensibilidad AUTO: umbral = median + k*(p95-median) de los agudos. "
                          "Más BAJO = más picos detectados (quita más); más alto = menos")
    sfx.add_argument("--sfx-hf-hz", type=float, default=5000.0,
                     help="Banda de agudos (Hz) donde vive el taka; la voz va por debajo de ~4 kHz")
    sfx.add_argument("--sfx-min-distance", type=float, default=0.20,
                     help="Separación mínima (s) entre picos de taka")
    sfx.add_argument("--sfx-half-width", type=float, default=0.06,
                     help="Mitad de ventana (s) alrededor de cada pico antes de ajustar a palabra")
    sfx.add_argument("--sfx-min-abs", type=float, default=0.0,
                     help="Piso de seguridad opcional para el umbral (0 = sin piso)")
    sfx.add_argument("--no-snap-words", action="store_true",
                     help="No ajustar a palabras completas (recorta exactamente el pico)")
    sfx.add_argument("--sfx-word-pad", type=float, default=0.04,
                     help="Margen (s) extra al expandir el pico a la palabra completa")
    sfx.add_argument("--min-sample-len", type=float, default=0.4,
                     help="Descarta los trozos limpios más cortos que esto (s) — muestras usables")
    sfx.add_argument("--no-samples", dest="split_samples", action="store_false",
                     help="No exportar cada trozo limpio como clip individual en samples/")
    sfx.add_argument("--no-keep-accompaniment", dest="keep_accompaniment", action="store_false",
                     help="No guardar accompaniment.wav (impide re-recortar con --reuse-stems)")
    sfx.add_argument("--reuse-stems", action="store_true",
                     help="Reutiliza vocals_full.wav/accompaniment.wav existentes (omite Demucs) para re-recortar rápido")
    parser.set_defaults(remove_sfx=True, keep_accompaniment=True, split_samples=True)
    args = parser.parse_args()

    video_path = args.video.expanduser().resolve()
    if not video_path.exists():
        parser.error(f"No existe el video: {video_path}")

    out_dir = args.out_dir or (video_path.parent / f"{video_path.stem}_voice")
    out_dir = out_dir.expanduser().resolve()

    device = pick_device(args.device)

    result = run(
        video_path,
        out_dir,
        language=args.language,
        whisper_model=args.whisper_model,
        demucs_model=args.demucs_model,
        device=device,
        shifts=args.shifts,
        mode=args.mode,
        pad=args.pad,
        gap=args.gap,
        min_seg=args.min_seg,
        fade_ms=args.fade_ms,
        word_level=args.word_level,
        use_demucs=not args.no_demucs,
        keep_stem=not args.no_keep_stem,
        sample_rate=args.sample_rate,
        make_mp3=args.mp3,
        remove_sfx=args.remove_sfx,
        sfx_k=args.sfx_k,
        sfx_min_abs=args.sfx_min_abs,
        sfx_hf_hz=args.sfx_hf_hz,
        sfx_min_distance=args.sfx_min_distance,
        sfx_half_width=args.sfx_half_width,
        snap_words=not args.no_snap_words,
        sfx_word_pad=args.sfx_word_pad,
        min_sample_len=args.min_sample_len,
        split_samples=args.split_samples,
        keep_accompaniment=args.keep_accompaniment,
        reuse_stems=args.reuse_stems,
    )

    sfx_note = ""
    if result.get("remove_sfx"):
        sfx_note = (
            f" Se omitieron {result['sfx_interval_count']} 'taka' "
            f"({result['sfx_seconds']}s)."
        )
    samples_note = ""
    if result["outputs"].get("sample_count"):
        samples_note = f" {result['outputs']['sample_count']} muestras en samples/."
    print(
        f"\nListo en {result['elapsed_seconds']}s — "
        f"{result['interval_count']} tramos de voz, "
        f"{result['speech_seconds']}s de habla "
        f"({result['speech_ratio'] * 100:.0f}% del video).{sfx_note}{samples_note}",
        file=sys.stderr,
    )
    print(f"Salida: {out_dir}", file=sys.stderr)
    print(json.dumps(result["outputs"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
