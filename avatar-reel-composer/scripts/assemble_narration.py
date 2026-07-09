#!/usr/bin/env python3
"""assemble_narration.py — build ONE master narration.mp3 + word-level alignment
from an ORDERED list of heterogeneous segments, so a reel can mix voices / avatars
on a single continuous narration track.

Why this exists
---------------
``compose_reel.py`` muxes ONE master narration over the whole timeline, and
``narrate.py`` synthesizes that narration in a SINGLE voice. To put a *guest*
avatar (a different person, with their own cloned voice) inside a host avatar's
reel — e.g. a human-looking presenter who opens the hook before cutting to the
host — the master narration has to be stitched from more than one source. This
script does exactly that and hands ``compose_reel.py`` a ready narration.mp3 +
narration.align.json (which it reuses idempotently).

Segment kinds
-------------
  guest : a DIFFERENT avatar speaks in its OWN voice. Generates a lip-synced
          talking clip via avatar-talking-video and uses that clip's audio as the
          segment. Emits the clip path + duration so the storyboard can drop it in
          as a ``type: "guest"`` scene. The guest segment's audio is matched to the
          clip's exact VIDEO duration (with inaudible trailing silence, NEVER a
          visible freeze frame) so the composer can cut precisely at the clip's end
          and the next (host) scene starts immediately — no pad, no loop, no drift.
  audio : an existing audio file used as-is (e.g. an audio-theater dialogue.wav for
          the host avatar, or any pre-rendered narration).
  tts   : host text synthesized with the host avatar's MiniMax voice via narrate.py
          (for avatars that narrate through voice-clone rather than audio-theater).

Segments are concatenated with gap=0 by default (the host picks up the instant the
guest stops), normalized to 44.1 kHz mono, then aligned word-by-word against the
combined script.

Plan file (JSON)
----------------
{
  "out_dir": "doki-monster/reels/00X_slug",   // where narration.mp3 + align go
  "gap": 0.0,                                   // silence between segments (s)
  "language": "es",
  "whisper_model": "small",
  "resolution": "720p",                         // for guest clip generation
  "script": null,                               // optional; else join segment texts
  "segments": [
    {"kind": "guest", "slug": "nora_hook", "avatar_dir": "nora",
     "image": "nora/angles/nora_push_in_916.png", "voice_id": "R8_LO9IT937",
     "emotion": "auto", "language_boost": "None",
     "text": "Llevas veinte segundos mirándome a los ojos... y no soy una persona real."},
    {"kind": "audio", "file": "doki-monster/reels/00X/narration_src/dialogue.wav",
     "text": "<the full host text exactly as spoken>"}
  ]
}
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _arc_common as C  # noqa: E402
import narrate as narrate_mod  # noqa: E402


def resolve_path(raw, base_dir: Path) -> Path:
    p = Path(str(raw)).expanduser()
    return p if p.is_absolute() else (base_dir / p).resolve()


def _normalize_audio(src: Path, out: Path, *, target_dur: float | None = None) -> bool:
    """Decode any audio/video into 44.1 kHz mono mp3. If ``target_dur`` is given,
    pad/trim the audio to exactly that many seconds with trailing silence — used to
    match a guest segment to its clip's VIDEO duration (inaudible; never a freeze)."""
    af = "aresample=44100"
    args = ["-i", str(src), "-vn", "-ac", "1", "-ar", "44100"]
    if target_dur and target_dur > 0:
        # pad first (in case audio is short), then hard-trim to the exact length
        af = f"aresample=44100,apad=whole_dur={target_dur:.3f},atrim=0:{target_dur:.3f}"
    args += ["-af", af, "-c:a", "libmp3lame", "-q:a", "2", str(out)]
    return C.run_ffmpeg(args, description=f"normalize segment -> {out.name}")


def gen_guest_clip(seg: dict, base_dir: Path, resolution: str, force: bool) -> Path:
    """Generate (or reuse) the guest avatar's lip-synced talking clip."""
    avatar_dir = resolve_path(seg["avatar_dir"], base_dir)
    if not avatar_dir.is_dir():
        raise SystemExit(f"guest segment: avatar_dir not found: {avatar_dir}")
    slug = seg.get("slug") or C.slugify(seg.get("text", "guest"))
    out_name = f"guest_{slug}"
    cached = avatar_dir / "generated-videos" / f"{out_name}.mp4"
    if cached.exists() and not force:
        print(f"  [cache] guest clip {slug} -> {cached.name}", file=sys.stderr)
        return cached

    text = seg.get("text", "").strip()
    if not text:
        raise SystemExit(f"guest segment {slug}: missing 'text'.")
    tf = Path(tempfile.mktemp(suffix=".txt"))
    tf.write_text(text + "\n", encoding="utf-8")

    cmd = [sys.executable, str(C.TALKING_VIDEO_SCRIPT),
           "--text-file", str(tf),
           "--avatar-dir", str(avatar_dir),
           "--resolution", resolution,
           "--out-name", out_name]
    if seg.get("image"):
        cmd += ["--image", str(resolve_path(seg["image"], base_dir))]
    if seg.get("voice_id"):
        cmd += ["--voice-id", str(seg["voice_id"])]
    if seg.get("name"):
        cmd += ["--name", str(seg["name"])]
    if seg.get("emotion"):
        cmd += ["--emotion", str(seg["emotion"])]
    if seg.get("language_boost"):
        cmd += ["--language-boost", str(seg["language_boost"])]
    res = C.run_cli_json(cmd, desc=f"guest clip {slug} ({avatar_dir.name})")
    tf.unlink(missing_ok=True)
    if not res or not res.get("video"):
        raise RuntimeError(f"avatar-talking-video returned no video for guest {slug}")
    return Path(res["video"])


def main():
    ap = argparse.ArgumentParser(description="Assemble a multi-source master narration + alignment.")
    ap.add_argument("plan", help="Path to the narration plan JSON.")
    ap.add_argument("--base-dir", type=Path, default=Path.cwd(),
                    help="Base for resolving relative paths (default: CWD).")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Output folder (overrides plan.out_dir).")
    ap.add_argument("--resolution", default=None, help="Guest clip resolution (default: plan or 720p).")
    ap.add_argument("--whisper-model", default=None, help="faster-whisper model size.")
    ap.add_argument("--language", default=None, help="Alignment language hint (e.g. es).")
    ap.add_argument("--force", action="store_true", help="Regenerate guest clips even if cached.")
    args = ap.parse_args()

    base_dir = args.base_dir.expanduser().resolve()
    plan = C.load_json(args.plan)
    out_dir = (args.out_dir or Path(plan["out_dir"])).expanduser()
    out_dir = out_dir if out_dir.is_absolute() else (base_dir / out_dir)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "narration_src" / "_assemble"
    work.mkdir(parents=True, exist_ok=True)

    gap = float(plan.get("gap", 0.0))
    resolution = args.resolution or plan.get("resolution", "720p")
    whisper_model = args.whisper_model or plan.get("whisper_model", "small")
    language = args.language or plan.get("language", "es")

    segments = plan.get("segments", [])
    if not segments:
        ap.error("plan has no segments.")

    parts: list[Path] = []
    records: list[dict] = []
    texts: list[str] = []
    print(f"\nAssembling narration from {len(segments)} segment(s) (gap={gap:.2f}s) -> {out_dir}",
          file=sys.stderr)

    for i, seg in enumerate(segments):
        kind = seg.get("kind")
        sid = seg.get("slug") or f"seg{i}"
        seg_mp3 = work / f"seg_{i:02d}_{sid}.mp3"
        rec: dict = {"index": i, "kind": kind, "slug": sid, "text": seg.get("text", "")}

        if kind == "guest":
            clip = gen_guest_clip(seg, base_dir, resolution, args.force)
            clip_dur = C.ffprobe_duration(clip)
            # Match the guest AUDIO segment to the clip's exact VIDEO duration so the
            # composer can pin the cut to the clip end with zero drift (inaudible
            # trailing silence — NOT a visible freeze frame).
            if not _normalize_audio(clip, seg_mp3, target_dur=clip_dur):
                raise RuntimeError(f"Failed to extract guest audio for {sid}")
            rec["clip"] = str(clip)
            rec["clip_duration"] = round(clip_dur, 3)

        elif kind == "audio":
            src = resolve_path(seg["file"], base_dir)
            if not src.exists():
                raise SystemExit(f"audio segment {sid}: file not found: {src}")
            if not _normalize_audio(src, seg_mp3):
                raise RuntimeError(f"Failed to normalize audio segment {sid}")

        elif kind == "tts":
            # Host MiniMax voice via narrate.py (for voice-clone avatars).
            avatar_dir = resolve_path(seg["avatar_dir"], base_dir)
            voice = seg.get("voice", {}) or {}
            sub = narrate_mod.narrate(
                seg.get("text", ""), avatar_dir, work / f"tts_{i:02d}", slug=sid,
                whisper_model=whisper_model, language=language,
                voice_name=voice.get("name"), voice_id=voice.get("voice_id"),
                source=voice.get("source"), emotion=voice.get("emotion", "auto"),
                language_boost=voice.get("language_boost", "None"),
            )
            if not _normalize_audio(Path(sub["narration"]), seg_mp3):
                raise RuntimeError(f"Failed to normalize tts segment {sid}")
        else:
            ap.error(f"segment {i}: unknown kind {kind!r} (use guest|audio|tts).")

        dur = C.ffprobe_duration(seg_mp3)
        rec["audio"] = str(seg_mp3)
        rec["audio_duration"] = round(dur, 3)
        parts.append(seg_mp3)
        records.append(rec)
        if seg.get("text"):
            texts.append(seg["text"].strip())

    # Concatenate -> master narration.
    narration = out_dir / "narration.mp3"
    if not C.concat_audio(parts, narration, gap=gap):
        raise SystemExit("Failed to concatenate narration segments.")
    total = C.ffprobe_duration(narration)

    # Cumulative offsets (each segment's [start, end] in the master narration).
    t = 0.0
    for rec in records:
        rec["start"] = round(t, 3)
        t += rec["audio_duration"] + (gap if rec is not records[-1] else 0.0)
        rec["end"] = round(t - (gap if rec is not records[-1] else 0.0), 3)

    # Word-level alignment against the combined script.
    script = (plan.get("script") or " ".join(texts)).strip()
    align_path = out_dir / "narration.align.json"
    adata = narrate_mod.align(narration, align_path, whisper_model=whisper_model,
                              language=language, script=script)

    out = {
        "narration": str(narration),
        "align": str(align_path),
        "duration": round(total, 3),
        "words": len(adata.get("words", [])),
        "gap": gap,
        "segments": records,
    }
    C.save_json(out_dir / "assemble_narration.out.json", out)

    # Print ready-to-paste storyboard stubs for the guest scenes.
    stubs = []
    for rec in records:
        if rec["kind"] == "guest":
            stubs.append({
                "id": f"s_{rec['slug']}", "type": "guest", "text": rec["text"],
                "broll_clip": rec["clip"], "motion": "none", "emphasis": True,
            })
    print(f"\n  narration: {narration}  ({total:.2f}s, {out['words']} words)", file=sys.stderr)
    if stubs:
        print("  guest scene stub(s) for the storyboard:", file=sys.stderr)
        print(json.dumps(stubs, ensure_ascii=False, indent=2), file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
