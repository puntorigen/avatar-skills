#!/usr/bin/env python3
"""Clone a voice with MiniMax voice-cloning on Replicate.

Takes a clean voice file (e.g. voice_concat.mp3 from the voice-isolate skill),
trains a MiniMax TTS voice and stores the resulting voice_id in the avatar
folder, keyed to the source recording's name.

Usage:
    python3 clone_voice.py <voice_file> [--avatar-dir DIR] [--name NAME]
    python3 clone_voice.py lolo/videos/clip_voice/voice_concat.mp3
    python3 clone_voice.py voice_concat.mp3 --model speech-2.6-hd

Output: <avatar-dir>/voices/<name>.json holding the voice_id (+ a preview clip
and an index.json registry of all cloned voices for that avatar).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import shutil  # noqa: E402

from _common import (  # noqa: E402
    NoTunnel,
    download_file,
    get_replicate_token,
    run_replicate,
    serve_public,
    to_url,
    upload_to_public_host,
)

MODEL = "minimax/voice-cloning"
# TTS model to train. speech-2.6-hd is the current HD model (may run on a newer
# HD engine server-side). Enum per the Replicate schema.
MODELS = ["speech-2.6-hd", "speech-2.6-turbo", "speech-02-hd", "speech-02-turbo"]
MAX_MB = 20.0


def infer_name(voice_path: Path) -> str:
    """Source recording name: '<stem>_voice/voice_concat.mp3' -> '<stem>'."""
    parent = voice_path.parent
    if parent.name.endswith("_voice"):
        return parent.name[: -len("_voice")]
    return voice_path.stem


def infer_avatar_dir(voice_path: Path) -> Path:
    """Avatar root = the folder that contains a 'videos/' dir, else the file's dir."""
    for p in voice_path.parents:
        if p.name == "videos":
            return p.parent
    return voice_path.parent


def extract(output, key):
    if isinstance(output, dict):
        return output.get(key)
    return getattr(output, key, None)


# --------------------------------------------------------------------------
# Voice registry: look up / reuse a trained voice for an avatar.
# --------------------------------------------------------------------------
class AmbiguousVoice(Exception):
    """Several trained voices exist for an avatar and none was specified."""

    def __init__(self, names):
        self.names = names
        super().__init__("multiple trained voices: " + ", ".join(names))


def load_voice_index(avatar_dir: Path) -> dict:
    index_path = Path(avatar_dir) / "voices" / "index.json"
    if index_path.exists():
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def find_voice(avatar_dir: Path, name: str | None = None) -> dict | None:
    """Return {'name','voice_id','model'} for a trained voice, or None.

    With a name: looks up <avatar>/voices/<name>.json then the index.
    Without a name: returns the sole trained voice, raises AmbiguousVoice if
    several exist, or None if none exist.
    """
    voices_dir = Path(avatar_dir) / "voices"
    if name:
        rec = voices_dir / f"{name}.json"
        if rec.exists():
            try:
                r = json.loads(rec.read_text(encoding="utf-8"))
                if r.get("voice_id"):
                    return {"name": name, "voice_id": r["voice_id"], "model": r.get("model")}
            except json.JSONDecodeError:
                pass
        index = load_voice_index(avatar_dir)
        if name in index and index[name].get("voice_id"):
            e = index[name]
            return {"name": name, "voice_id": e["voice_id"], "model": e.get("model")}
        return None

    index = load_voice_index(avatar_dir)
    valid = {n: e for n, e in index.items() if e.get("voice_id")}
    if not valid:
        return None
    if len(valid) == 1:
        n, e = next(iter(valid.items()))
        return {"name": n, "voice_id": e["voice_id"], "model": e.get("model")}
    raise AmbiguousVoice(sorted(valid))


def clone(
    vf: Path,
    *,
    avatar_dir: Path,
    name: str,
    model: str = "speech-2.6-hd",
    accuracy: float = 0.7,
    noise_reduction: bool = False,
    volume_normalization: bool = False,
    download_preview: bool = True,
    token: str | None = None,
    verbose: bool = True,
) -> dict:
    """Train a MiniMax voice from a clean voice file; save + return the record."""
    vf = Path(vf).expanduser().resolve()
    if not vf.exists():
        raise FileNotFoundError(f"No existe el archivo de voz: {vf}")
    size_mb = vf.stat().st_size / 1e6
    if size_mb > MAX_MB:
        raise ValueError(
            f"El archivo pesa {size_mb:.1f}MB; el máximo de MiniMax es {MAX_MB:.0f}MB."
        )
    if vf.suffix.lower() not in (".mp3", ".m4a", ".wav") and verbose:
        print(f"Aviso: formato {vf.suffix} no estándar; MiniMax acepta MP3/M4A/WAV.", file=sys.stderr)

    avatar_dir = Path(avatar_dir)
    voices_dir = avatar_dir / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    token = token or get_replicate_token()

    if verbose:
        print(f"  Voz fuente: {vf} ({size_mb:.1f}MB)", file=sys.stderr)
        print(f"  Avatar: {avatar_dir}  |  nombre: {name}  |  modelo: {model}", file=sys.stderr)
        print("  Entrenando la voz (puede tardar ~1-2 min)...", file=sys.stderr)

    def do_run(voice_url):
        inputs = {
            "voice_file": voice_url,
            "model": model,
            "accuracy": accuracy,
            "need_noise_reduction": noise_reduction,
            "need_volume_normalization": volume_normalization,
        }
        return run_replicate(MODEL, inputs, token=token)

    # MiniMax re-fetches the file from its own servers, so it needs a PUBLIC URL
    # with a real extension. Prefer serving it from this machine via a local
    # tunnel; fall back to a temporary public host only if no tunnel exists.
    if shutil.which("cloudflared") or shutil.which("ngrok"):
        if verbose:
            print("  Sirviendo la voz por túnel local (no sale de tu máquina)...", file=sys.stderr)
        with serve_public(vf) as voice_url:
            output = do_run(voice_url)
    else:
        if verbose:
            print("  Sin túnel (cloudflared/ngrok); subiendo a host público temporal...", file=sys.stderr)
        output = do_run(upload_to_public_host(vf))

    voice_id = extract(output, "voice_id")
    if not voice_id:
        raise RuntimeError(f"La respuesta no incluyó voice_id. Respuesta: {output!r}")
    used_model = extract(output, "model") or model
    preview_url = to_url(extract(output, "preview"))

    preview_file = None
    if preview_url and download_preview:
        preview_file = f"{name}_preview.mp3"
        try:
            download_file(preview_url, voices_dir / preview_file)
        except Exception as e:  # noqa: BLE001
            print(f"  Aviso: no se pudo descargar el preview: {e}", file=sys.stderr)
            preview_file = None

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    record = {
        "name": name,
        "voice_id": voice_id,
        "model": used_model,
        "provider": "minimax/voice-cloning",
        "source": str(vf),
        "accuracy": accuracy,
        "need_noise_reduction": noise_reduction,
        "need_volume_normalization": volume_normalization,
        "preview_url": preview_url,
        "preview_file": preview_file,
        "created_at": now,
    }
    (voices_dir / f"{name}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    index_path = voices_dir / "index.json"
    index = load_voice_index(avatar_dir)
    index[name] = {"voice_id": voice_id, "model": used_model, "source": str(vf), "updated_at": now}
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return record


def main():
    ap = argparse.ArgumentParser(
        description="Clona una voz (MiniMax voice-cloning en Replicate) y guarda el voice_id.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("voice_file", type=Path,
                    help="Audio de voz limpia (MP3/M4A/WAV, 10s-5min, <20MB), p.ej. voice_concat.mp3")
    ap.add_argument("--avatar-dir", type=Path, default=None,
                    help="Carpeta del avatar donde guardar el voice_id (auto si se omite)")
    ap.add_argument("--name", default=None,
                    help="Nombre de la grabación fuente (auto desde el archivo si se omite)")
    ap.add_argument("--model", default="speech-2.6-hd", choices=MODELS,
                    help="Modelo TTS a entrenar")
    ap.add_argument("--accuracy", type=float, default=0.7,
                    help="Umbral de exactitud de validación de texto (0-1)")
    ap.add_argument("--noise-reduction", action="store_true",
                    help="Activa reducción de ruido (solo si el audio tiene ruido de fondo)")
    ap.add_argument("--volume-normalization", action="store_true",
                    help="Activa normalización de volumen")
    ap.add_argument("--no-preview", action="store_true",
                    help="No descargar el clip de preview de la voz clonada")
    args = ap.parse_args()

    vf = args.voice_file.expanduser().resolve()
    if not vf.exists():
        ap.error(f"No existe el archivo de voz: {vf}")

    name = args.name or infer_name(vf)
    avatar_dir = (args.avatar_dir.expanduser().resolve()
                  if args.avatar_dir else infer_avatar_dir(vf))

    try:
        record = clone(
            vf,
            avatar_dir=avatar_dir,
            name=name,
            model=args.model,
            accuracy=args.accuracy,
            noise_reduction=args.noise_reduction,
            volume_normalization=args.volume_normalization,
            download_preview=not args.no_preview,
            token=get_replicate_token(),
        )
    except NoTunnel:
        ap.error("No hay forma de exponer el archivo (instala cloudflared o ngrok).")
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        ap.error(str(e))

    voices_dir = avatar_dir / "voices"
    record_path = voices_dir / f"{name}.json"
    preview_file = record.get("preview_file")
    print(f"\nListo — voice_id: {record['voice_id']}", file=sys.stderr)
    print(f"  Guardado en: {record_path}", file=sys.stderr)
    if preview_file:
        print(f"  Preview: {voices_dir / preview_file}", file=sys.stderr)
    print(json.dumps({
        "voice_id": record["voice_id"],
        "model": record["model"],
        "record": str(record_path),
        "preview": str(voices_dir / preview_file) if preview_file else None,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
