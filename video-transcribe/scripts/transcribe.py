#!/usr/bin/env python3
"""Download a video by URL (yt-dlp) and/or transcribe its audio with faster-whisper.

Writes <basename>.txt, <basename>.srt and <basename>.json (full text + per-segment
timecodes) into the output folder. Works on a single Instagram reel/post URL, any
other yt-dlp-supported URL, or a local media file (mp4/mov/webm/mp3/wav).

Usage:
    # Instagram reel (download + transcribe), force Spanish
    python3 transcribe.py "https://www.instagram.com/reels/XXXX/" \
        --output-dir out/reel --language es

    # Local media file (outputs land next to it as <stem>.txt/.srt/.json)
    python3 transcribe.py path/to/clip.mp4

Notes:
    - faster-whisper decodes media via ffmpeg, so no separate audio extraction is
      needed; mp4/mov/webm/mp3/wav all work directly.
    - Default model 'small' matches the repo's voice / alignment pipeline
      (CPU, int8). Use --model large-v3 for higher accuracy (slower, big download).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MEDIA_SUFFIXES = {".txt", ".srt", ".json"}


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def download(url: str, out_dir: Path, basename: str) -> Path:
    """Download a single video with yt-dlp; return the saved media path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / f"{basename}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f",
        "mp4/bestvideo+bestaudio/best",
        "-o",
        template,
        url,
    ]
    print(f"  $ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)
    hits = [p for p in out_dir.glob(f"{basename}.*") if p.suffix.lower() not in MEDIA_SUFFIXES]
    if not hits:
        raise FileNotFoundError(f"yt-dlp produced no media file for {url}")
    return sorted(hits, key=lambda p: p.stat().st_size, reverse=True)[0]


def fmt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe(
    media: Path,
    out_dir: Path,
    basename: str,
    *,
    model_size: str,
    language: str | None,
    device: str,
    compute_type: str,
) -> dict:
    from faster_whisper import WhisperModel

    print(f"  Transcribing with faster-whisper ({model_size}, {device}/{compute_type})...", file=sys.stderr)
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(media),
        language=language,
        vad_filter=True,
        beam_size=5,
    )
    segs = list(segments)
    full_text = " ".join(s.text.strip() for s in segs).strip()

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{basename}.txt").write_text(full_text + "\n", encoding="utf-8")

    srt: list[str] = []
    for i, s in enumerate(segs, 1):
        srt += [str(i), f"{fmt_ts(s.start)} --> {fmt_ts(s.end)}", s.text.strip(), ""]
    (out_dir / f"{basename}.srt").write_text("\n".join(srt), encoding="utf-8")

    data = {
        "source": str(media),
        "language": info.language,
        "language_probability": round(info.language_probability, 4),
        "duration": round(info.duration, 3),
        "model": model_size,
        "text": full_text,
        "segments": [
            {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
            for s in segs
        ],
    }
    (out_dir / f"{basename}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Download (yt-dlp) and transcribe (faster-whisper) a single video or local file."
    )
    ap.add_argument("source", help="Video URL (Instagram reel/etc.) or local media file path")
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output folder (default: '.' for URLs, the file's own folder for local files)",
    )
    ap.add_argument(
        "--basename",
        default=None,
        help="Base name for outputs (default: 'transcript' for URLs, the file stem for local files)",
    )
    ap.add_argument(
        "--model",
        default="small",
        help="faster-whisper model size: tiny, base, small, medium, large-v3 (default: small)",
    )
    ap.add_argument("--language", default=None, help="Force a language code (e.g. es, en). Default: auto-detect")
    ap.add_argument("--device", default="cpu", help="cpu or cuda (default: cpu)")
    ap.add_argument("--compute-type", default="int8", help="ctranslate2 compute type (default: int8)")
    ap.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete the downloaded video after transcription (URL sources only)",
    )
    args = ap.parse_args()

    downloaded = False
    if is_url(args.source):
        basename = args.basename or "transcript"
        out_dir = args.output_dir or Path(".")
        media = download(args.source, out_dir, basename)
        downloaded = True
        print(f"  Downloaded: {media} ({media.stat().st_size} bytes)", file=sys.stderr)
    else:
        media = Path(args.source)
        if not media.exists():
            print(f"ERROR: local file not found: {media}", file=sys.stderr)
            return 1
        basename = args.basename or media.stem
        out_dir = args.output_dir or media.parent

    data = transcribe(
        media,
        out_dir,
        basename,
        model_size=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
    )

    if args.cleanup and downloaded:
        media.unlink(missing_ok=True)
        print(f"  Removed downloaded media: {media}", file=sys.stderr)

    print(
        f"lang={data['language']} ({data['language_probability']:.2f})  "
        f"dur={data['duration']:.1f}s  model={data['model']}",
        file=sys.stderr,
    )
    print(f"  -> {out_dir / (basename + '.txt')}", file=sys.stderr)
    print(f"  -> {out_dir / (basename + '.srt')}", file=sys.stderr)
    print(f"  -> {out_dir / (basename + '.json')}", file=sys.stderr)
    print("=" * 60)
    print(data["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
