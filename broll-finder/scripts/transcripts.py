#!/usr/bin/env python3
"""Fetch TIMECODED transcripts for candidate videos so the agent can pick the
relevant [start,end] windows BEFORE downloading anything.

Cheap by design: it pulls YouTube's own captions (auto or manual) via
youtube-transcript-api, falling back to yt-dlp VTT — no video download, no ASR.
For a video with no captions, pass --whisper to download the audio and
transcribe with faster-whisper (slower; reuses the video-transcribe approach).

For each video it writes:
  * transcripts/<video_id>.json  — [{start, dur, text}, ...] (seconds)
  * transcripts/<video_id>.md    — agent-readable, one line per ~6s block with
                                   [mm:ss] markers (skim this to choose windows)

Standalone:
    python3 transcripts.py --ids dQw4w9WgXcQ abc12345678 -o ./work --lang en es
    python3 transcripts.py --candidates ./work/candidates.json -o ./work --max 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def _whisper_transcript(url: str, languages: list[str], cookies: str | None) -> list[dict] | None:
    """Download audio + faster-whisper word/segment timings (fallback only)."""
    import tempfile
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        print("[transcripts] faster-whisper not installed; cannot --whisper.", file=sys.stderr)
        return None
    import subprocess
    tmp = Path(tempfile.mkdtemp(prefix="bf_aud_"))
    audio = tmp / "audio.m4a"
    cmd = ["yt-dlp", "-f", "bestaudio", "-o", str(audio.with_suffix(".%(ext)s")), url]
    if cookies:
        cmd[1:1] = ["--cookies-from-browser", cookies]
    subprocess.run(cmd, capture_output=True, text=True)
    got = next((p for p in tmp.glob("audio.*")), None)
    if not got:
        return None
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    lang = languages[0] if languages else None
    segments, _ = model.transcribe(str(got), language=lang, vad_filter=True)
    return [{"start": round(s.start, 2), "dur": round(s.end - s.start, 2),
             "text": s.text.strip()} for s in segments if s.text.strip()]


def _to_blocks(cues: list[dict], block_s: float = 6.0) -> list[dict]:
    """Group fine caption cues into ~block_s windows for a skimmable transcript."""
    blocks: list[dict] = []
    cur = None
    for c in cues:
        if cur is None or c["start"] - cur["start"] >= block_s:
            if cur:
                blocks.append(cur)
            cur = {"start": c["start"], "text": c["text"]}
        else:
            cur["text"] += " " + c["text"]
    if cur:
        blocks.append(cur)
    return blocks


def write_transcript(video_id: str, url: str, cues: list[dict], out_dir: Path,
                     title: str = "") -> tuple[Path, Path]:
    tdir = out_dir / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)
    js = tdir / f"{video_id}.json"
    md = tdir / f"{video_id}.md"
    C.write_manifest(js, {"video_id": video_id, "url": url, "title": title,
                          "cue_count": len(cues), "cues": cues})
    lines = [f"# {title or video_id}", f"<{url}>", "",
             "_Pick [start,end] windows (mm:ss) and put them in selection.json._", ""]
    for b in _to_blocks(cues):
        lines.append(f"[{C.fmt_ts(b['start'])}] {b['text']}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return js, md


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch timecoded transcripts for candidate videos.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ids", nargs="+", help="One or more YouTube URLs or 11-char video IDs.")
    g.add_argument("--candidates", help="Path to a candidates.json from search.py.")
    ap.add_argument("--max", type=int, default=8, help="Max videos to transcribe (default 8).")
    ap.add_argument("--lang", nargs="+", default=["en", "es"],
                    help="Preferred caption languages in order (default en es).")
    ap.add_argument("--whisper", action="store_true",
                    help="If a video has no captions, download audio + faster-whisper (slow).")
    ap.add_argument("--cookies-from-browser", help="Browser for cookies on bot-gated videos (e.g. firefox).")
    ap.add_argument("-o", "--out-dir", default=".", help="Working directory (transcripts/ created inside).")
    args = ap.parse_args()

    targets: list[dict] = []
    if args.candidates:
        data = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
        for r in data.get("candidates", [])[:args.max]:
            targets.append({"video_id": r.get("video_id") or C.extract_video_id(r["url"]),
                            "url": r["url"], "title": r.get("title", "")})
    else:
        for raw in args.ids[:args.max]:
            vid = C.extract_video_id(raw) or raw
            url = raw if raw.startswith("http") else f"https://www.youtube.com/watch?v={vid}"
            targets.append({"video_id": vid, "url": url, "title": ""})

    out_dir = Path(args.out_dir).expanduser().resolve()
    results = []
    for t in targets:
        vid, url = t["video_id"], t["url"]
        print(f"[transcripts] {vid} ...", file=sys.stderr)
        cues = C.fetch_timed_transcript(url, args.lang, args.cookies_from_browser)
        if not cues and args.whisper:
            print(f"[transcripts] no captions for {vid}; trying faster-whisper", file=sys.stderr)
            cues = _whisper_transcript(url, args.lang, args.cookies_from_browser)
        if not cues:
            print(f"[transcripts] no transcript for {vid} (skipping)", file=sys.stderr)
            results.append({"video_id": vid, "url": url, "ok": False})
            continue
        js, md = write_transcript(vid, url, cues, out_dir, t.get("title", ""))
        results.append({"video_id": vid, "url": url, "ok": True,
                        "json": str(js), "md": str(md), "cues": len(cues)})

    print(json.dumps({"count": sum(1 for r in results if r["ok"]),
                      "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
