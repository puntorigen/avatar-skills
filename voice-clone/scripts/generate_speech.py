#!/usr/bin/env python3
"""Generate speech in a cloned voice with MiniMax speech-2.8-hd on Replicate.

Reuses a voice already trained for the avatar (see clone_voice.py); if none
exists yet it trains one from a source recording. Detects the language of the
text and passes it as MiniMax's `language_boost` for better pronunciation.

Usage:
    python3 generate_speech.py "Hola, soy Lolo" --avatar-dir lolo
    python3 generate_speech.py "Hello there" --source lolo/videos/clip_voice/voice_concat.mp3
    python3 generate_speech.py --text-file script.txt --avatar-dir lolo --emotion happy

Output: <avatar>/generated-audios/<NNN>_<slug>.<ext> plus a manifest.json
mapping each generated file -> text + voice_id used.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _common import (  # noqa: E402
    NoTunnel,
    download_file,
    get_replicate_token,
    run_replicate,
    to_url,
)
from clone_voice import (  # noqa: E402
    AmbiguousVoice,
    clone,
    find_voice,
    infer_avatar_dir,
    infer_name,
)

MODEL = "minimax/speech-2.8-hd"
EMOTIONS = ["auto", "happy", "sad", "angry", "fearful", "disgusted",
            "surprised", "calm", "fluent", "neutral"]
LANGUAGE_BOOSTS = [
    "None", "Automatic", "Chinese", "Chinese,Yue", "Cantonese", "English",
    "Arabic", "Russian", "Spanish", "French", "Portuguese", "German", "Turkish",
    "Dutch", "Ukrainian", "Vietnamese", "Indonesian", "Japanese", "Italian",
    "Korean", "Thai", "Polish", "Romanian", "Greek", "Czech", "Finnish",
    "Hindi", "Bulgarian", "Danish", "Hebrew", "Malay", "Persian", "Slovak",
    "Swedish", "Croatian", "Filipino", "Hungarian", "Norwegian", "Slovenian",
    "Catalan", "Nynorsk", "Tamil", "Afrikaans",
]
AUDIO_FORMATS = ["mp3", "wav", "flac", "pcm"]
SAMPLE_RATES = [8000, 16000, 22050, 24000, 32000, 44100]
BITRATES = [32000, 64000, 128000, 256000]
CHANNELS = ["mono", "stereo"]
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

# Expressive interjections recognized by MiniMax speech-2.8-hd. Write them inline
# in the text — e.g. "Lo logramos (laughs)" — and the model renders the sound
# naturally. The model recognizes 20+; this is the common, reliably-rendered set.
# (Not exhaustive; unknown parenthesized tokens may be read literally.)
INTERJECTIONS = [
    "laughs", "laughs softly", "chuckles", "giggles", "sighs", "gasps",
    "coughs", "clears throat", "sneezes", "sniffs", "groans", "yawns",
    "whistles", "humming", "hums", "exhales", "inhales", "breathes",
    "gulps", "crying", "sobs", "screams", "applause",
]
_INTERJECTION_SET = {s.lower() for s in INTERJECTIONS}
_PAREN_RE = re.compile(r"\(([^)]+)\)")
# Manual pause marker MiniMax honours: <#x#> = x seconds of silence (0.01–99.99).
_PAUSE_RE = re.compile(r"<#\s*(\d+(?:\.\d+)?)\s*#>")


def scan_interjections(text: str) -> tuple[list[str], list[str]]:
    """Return (recognized, unknown) parenthesized tokens found in the text."""
    recognized, unknown = [], []
    for raw in _PAREN_RE.findall(text):
        tok = " ".join(raw.split()).lower()
        if tok in _INTERJECTION_SET:
            recognized.append(tok)
        else:
            unknown.append(tok)
    return recognized, unknown

# langid ISO 639-1 code -> MiniMax language_boost value.
ISO_TO_BOOST = {
    "en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French",
    "de": "German", "it": "Italian", "nl": "Dutch", "pl": "Polish",
    "ro": "Romanian", "tr": "Turkish", "vi": "Vietnamese", "id": "Indonesian",
    "cs": "Czech", "da": "Danish", "fi": "Finnish", "hu": "Hungarian",
    "no": "Norwegian", "sv": "Swedish", "hr": "Croatian", "sk": "Slovak",
    "sl": "Slovenian", "ca": "Catalan", "af": "Afrikaans", "ms": "Malay",
    "tl": "Filipino",
    # non-Latin (script detection handles these first, kept as a safety net)
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ru": "Russian",
    "uk": "Ukrainian", "bg": "Bulgarian", "ar": "Arabic", "fa": "Persian",
    "he": "Hebrew", "el": "Greek", "th": "Thai", "hi": "Hindi", "ta": "Tamil",
}
# Restrict langid to Latin-script languages MiniMax supports (sharper picks).
LATIN_LANGID = ["en", "es", "pt", "fr", "de", "it", "nl", "pl", "ro", "tr",
                "vi", "id", "cs", "da", "fi", "hu", "no", "sv", "hr", "sk",
                "sl", "ca", "af", "ms", "tl"]


def _script_language(text: str) -> str | None:
    """Reliable language hint from the dominant Unicode script (non-Latin)."""
    counts: dict[str, int] = {}
    has_hira = has_kata = has_hangul = has_han = False
    for ch in text:
        o = ord(ch)
        if 0x3040 <= o <= 0x309F:
            has_hira = True
        elif 0x30A0 <= o <= 0x30FF:
            has_kata = True
        elif 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            has_hangul = True
        elif 0x4E00 <= o <= 0x9FFF:
            has_han = True
        elif 0x0400 <= o <= 0x04FF:
            counts["cyr"] = counts.get("cyr", 0) + 1
        elif 0x0600 <= o <= 0x06FF:
            counts["arab"] = counts.get("arab", 0) + 1
        elif 0x0590 <= o <= 0x05FF:
            counts["hebrew"] = counts.get("hebrew", 0) + 1
        elif 0x0370 <= o <= 0x03FF:
            counts["greek"] = counts.get("greek", 0) + 1
        elif 0x0E00 <= o <= 0x0E7F:
            counts["thai"] = counts.get("thai", 0) + 1
        elif 0x0900 <= o <= 0x097F:
            counts["deva"] = counts.get("deva", 0) + 1
        elif 0x0B80 <= o <= 0x0BFF:
            counts["tamil"] = counts.get("tamil", 0) + 1
    if has_hira or has_kata:
        return "Japanese"
    if has_hangul:
        return "Korean"
    if has_han:
        return "Chinese"
    if not counts:
        return None
    top = max(counts, key=counts.get)
    if top == "cyr":
        return "Ukrainian" if any(c in text for c in "іїєґІЇЄҐ") else "Russian"
    if top == "arab":
        return "Persian" if any(c in text for c in "پچژگ") else "Arabic"
    return {"hebrew": "Hebrew", "greek": "Greek", "thai": "Thai",
            "deva": "Hindi", "tamil": "Tamil"}.get(top)


def detect_language_boost(text: str) -> str:
    """Best-effort language_boost for the text; 'Automatic' when unsure."""
    scripted = _script_language(text)
    if scripted:
        return scripted
    txt = text.strip()
    if len(txt) < 3:
        return "Automatic"
    try:
        import langid
        langid.set_languages(LATIN_LANGID)
        code, _ = langid.classify(txt)
    except Exception:  # noqa: BLE001
        return "Automatic"
    return ISO_TO_BOOST.get(code, "Automatic")


def slugify(text: str, maxlen: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return (t[:maxlen].strip("-") or "audio")


def resolve_source(raw: str) -> Path:
    """Resolve a training source: a voice file, or a video -> its _voice/voice_concat.mp3."""
    p = Path(raw).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"No existe la fuente: {p}")
    if p.suffix.lower() in VIDEO_EXTS:
        cand = p.parent / f"{p.stem}_voice" / "voice_concat.mp3"
        if cand.exists():
            return cand
        raise ValueError(
            f"La fuente es un video sin voz aislada. Ejecuta primero el skill "
            f"voice-isolate para generar {cand}, y pásalo como --source."
        )
    return p


def next_index(items: list, gen_dir: Path) -> int:
    nums = []
    for it in items:
        m = re.match(r"(\d+)_", str(it.get("file", "")))
        if m:
            nums.append(int(m.group(1)))
    for f in gen_dir.glob("[0-9][0-9][0-9]_*"):
        m = re.match(r"(\d+)_", f.name)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def main():
    ap = argparse.ArgumentParser(
        description="Genera audio TTS con una voz clonada (MiniMax speech-2.8-hd en Replicate).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("text", nargs="?", default=None, help="Texto a sintetizar (o usa --text-file)")
    ap.add_argument("--text-file", type=Path, default=None, help="Lee el texto desde un archivo")
    ap.add_argument("--avatar-dir", type=Path, default=None,
                    help="Carpeta del avatar (auto desde --source si se omite)")
    ap.add_argument("--name", default=None,
                    help="Nombre de la voz entrenada a usar/crear (auto si se omite)")
    ap.add_argument("--voice-id", default=None,
                    help="Usar este voice_id directamente (omite búsqueda/entrenamiento)")
    ap.add_argument("--source", default=None,
                    help="Audio/voz o video para ENTRENAR si el avatar no tiene voz aún")
    ap.add_argument("--emotion", default="auto", choices=EMOTIONS,
                    help="Estilo de entrega; 'auto' deja que MiniMax elija")
    ap.add_argument("--language-boost", default="None",
                    help="'None' (sin boost; preserva el acento de la voz clonada — recomendado), "
                         "'detect' (auto-detecta el idioma) o uno de: " + ", ".join(LANGUAGE_BOOSTS))
    ap.add_argument("--speed", type=float, default=1.0, help="Velocidad (0.5-2.0)")
    ap.add_argument("--volume", type=float, default=1.0, help="Volumen relativo (0-10)")
    ap.add_argument("--pitch", type=int, default=0, help="Semitonos (-12 a +12)")
    ap.add_argument("--audio-format", default="mp3", choices=AUDIO_FORMATS)
    ap.add_argument("--sample-rate", type=int, default=32000, choices=SAMPLE_RATES)
    ap.add_argument("--bitrate", type=int, default=128000, choices=BITRATES)
    ap.add_argument("--channel", default="mono", choices=CHANNELS)
    ap.add_argument("--english-normalization", action="store_true",
                    help="Mejora lectura de números/fechas en inglés (algo más lento)")
    ap.add_argument("--out-name", default=None, help="Nombre de archivo de salida (sin extensión)")
    ap.add_argument("--list-interjections", action="store_true",
                    help="Lista las interjecciones expresivas reconocidas y termina")
    args = ap.parse_args()

    if args.list_interjections:
        print("Interjecciones expresivas reconocidas por MiniMax speech-2.8-hd")
        print("(escríbelas en el texto, p.ej. \"Lo logramos (laughs)\"):\n")
        for s in INTERJECTIONS:
            print(f"  ({s})")
        print("\nPausa manual: <#x#>  ->  x segundos de silencio (0.01–99.99). "
              "Ej.: \"Respira <#0.6#> y continúa.\"")
        return

    # --- Resolve text ---
    if args.text_file:
        text = args.text_file.expanduser().read_text(encoding="utf-8").strip()
    elif args.text:
        text = args.text.strip()
    else:
        ap.error("Falta el texto: pásalo como argumento o con --text-file.")
    if not text:
        ap.error("El texto está vacío.")

    # --- Expressive interjections / pause markers (informational) ---
    interjections, unknown_parens = scan_interjections(text)
    if interjections:
        print(f"  Interjecciones expresivas: {', '.join(f'({i})' for i in interjections)}",
              file=sys.stderr)
    if unknown_parens:
        print(f"  Aviso: texto entre paréntesis no reconocido como interjección "
              f"(podría leerse literal): {', '.join(f'({u})' for u in unknown_parens)}. "
              f"Usa --list-interjections para ver las soportadas.", file=sys.stderr)
    pauses = _PAUSE_RE.findall(text)
    if pauses:
        print(f"  Pausas manuales <#x#>: {', '.join(p + 's' for p in pauses)}", file=sys.stderr)

    # --- Resolve avatar dir ---
    if args.avatar_dir:
        avatar_dir = args.avatar_dir.expanduser().resolve()
    elif args.source:
        avatar_dir = infer_avatar_dir(Path(args.source).expanduser().resolve())
    else:
        ap.error("Indica --avatar-dir (o --source para inferirlo).")

    token = get_replicate_token()

    # --- Resolve / reuse / train voice ---
    if args.voice_id:
        voice_id, voice_name, voice_model = args.voice_id, (args.name or "custom"), None
        print(f"  Usando voice_id explícito: {voice_id}", file=sys.stderr)
    else:
        try:
            found = find_voice(avatar_dir, args.name)
        except AmbiguousVoice as e:
            ap.error("Hay varias voces entrenadas para este avatar "
                     f"({', '.join(e.names)}). Especifica --name.")
        if found:
            voice_id, voice_name, voice_model = found["voice_id"], found["name"], found.get("model")
            print(f"  Reutilizando voz entrenada '{voice_name}' (voice_id: {voice_id})", file=sys.stderr)
        else:
            if not args.source:
                ap.error("No hay voz entrenada para este avatar. Pasa --source "
                         "<voice_concat.mp3 o video> para entrenarla, o usa --voice-id.")
            try:
                src = resolve_source(args.source)
            except (FileNotFoundError, ValueError) as e:
                ap.error(str(e))
            train_name = args.name or infer_name(src)
            print(f"  Sin voz previa; entrenando '{train_name}' desde {src} ...", file=sys.stderr)
            try:
                rec = clone(src, avatar_dir=avatar_dir, name=train_name, token=token)
            except NoTunnel:
                ap.error("No hay forma de exponer el audio para entrenar (instala cloudflared o ngrok).")
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                ap.error(str(e))
            voice_id, voice_name, voice_model = rec["voice_id"], train_name, rec["model"]

    # --- Language boost ---
    if str(args.language_boost).lower() in ("detect", "auto"):
        language_boost = detect_language_boost(text)
        print(f"  Idioma detectado -> language_boost: {language_boost}", file=sys.stderr)
    else:
        if args.language_boost not in LANGUAGE_BOOSTS:
            ap.error(f"language_boost inválido: {args.language_boost}. "
                     f"Usa 'detect' o uno de: {', '.join(LANGUAGE_BOOSTS)}")
        language_boost = args.language_boost

    # --- Synthesize ---
    inputs = {
        "text": text,
        "voice_id": voice_id,
        "emotion": args.emotion,
        "language_boost": language_boost,
        "speed": args.speed,
        "volume": args.volume,
        "pitch": args.pitch,
        "audio_format": args.audio_format,
        "sample_rate": args.sample_rate,
        "bitrate": args.bitrate,
        "channel": args.channel,
        "english_normalization": args.english_normalization,
    }
    print(f"  Generando audio (emotion={args.emotion}) ...", file=sys.stderr)
    output = run_replicate(MODEL, inputs, token=token)
    if isinstance(output, (list, tuple)) and output:
        output = output[0]
    audio_url = to_url(output)
    if not audio_url:
        print(f"Error: la respuesta no incluyó audio. Respuesta: {output!r}", file=sys.stderr)
        sys.exit(1)

    # --- Save + manifest ---
    gen_dir = avatar_dir / "generated-audios"
    gen_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = gen_dir / "manifest.json"
    manifest = {"items": []}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
                manifest = loaded
        except json.JSONDecodeError:
            pass

    idx = next_index(manifest["items"], gen_dir)
    ext = args.audio_format
    base = args.out_name or f"{idx:03d}_{slugify(text)}"
    fname = f"{base}.{ext}"
    download_file(audio_url, gen_dir / fname)

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    entry = {
        "file": fname,
        "text": text,
        "voice_id": voice_id,
        "voice_name": voice_name,
        "model": MODEL,
        "voice_train_model": voice_model,
        "emotion": args.emotion,
        "language_boost": language_boost,
        "speed": args.speed,
        "volume": args.volume,
        "pitch": args.pitch,
        "audio_format": args.audio_format,
        "sample_rate": args.sample_rate,
        "bitrate": args.bitrate,
        "channel": args.channel,
        "english_normalization": args.english_normalization,
        "interjections": interjections,
        "source_url": audio_url,
        "created_at": now,
    }
    manifest["items"].append(entry)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out_path = gen_dir / fname
    print(f"\nListo — audio: {out_path}", file=sys.stderr)
    print(f"  voice_id: {voice_id}  |  emotion: {args.emotion}  |  language_boost: {language_boost}", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)
    print(json.dumps({
        "audio": str(out_path),
        "voice_id": voice_id,
        "emotion": args.emotion,
        "language_boost": language_boost,
        "manifest": str(manifest_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
