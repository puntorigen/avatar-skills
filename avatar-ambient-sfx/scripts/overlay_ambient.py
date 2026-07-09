#!/usr/bin/env python3
"""Overlay a spatial ambient SFX layer onto a finished reel, ducked under the narration.

Takes a finished reel (`final.mp4`, already has narration + music + burned captions +
fade-to-black) and a spatial ambient layer (`ambient/ambient_spatial.mp3`, built with
audio-theater's mix_spatial.py from cues.json) and produces `final-espacial.mp4`:

  final-espacial = final.mp4 video (copied, untouched)
                 + [ original final.mp4 audio
                     + ambient_spatial ducked under narration.mp3 (sidechaincompress) ]
                   loudnorm'd, with a final audio fade matching the video's fade-to-black.

It NEVER overwrites final.mp4. The narration track is used as the sidechain KEY so the
ambient only dips under the voice (not under music/SFX), keeping the bed present in the gaps.

Usage (typical — everything auto-discovered from the reel folder):

    python3 overlay_ambient.py --reel-dir antiguo/reels/008_leccion-de-vida-5-libre

Explicit paths:

    python3 overlay_ambient.py \
      --final  REEL/final.mp4 \
      --ambient REEL/ambient/ambient_spatial.mp3 \
      --narration REEL/narration.mp3 \
      --out REEL/final-espacial.mp4

Fade: by default the script reads the last spoken word from narration.align.json and starts
the audio fade at last_word_end + 0.15s so the ambient fades out exactly with the
fade-to-black (never cutting the last word). Override with --fade-start / --fade-dur, or
disable with --no-fade.
"""
import argparse
import json
import os
import subprocess
import sys


def ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise SystemExit(f"Could not read duration of {path}:\n{out.stderr}")


def measure_integrated_lufs(path: str):
    """Return the integrated loudness (LUFS) of a file's audio, or None."""
    out = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "loudnorm=print_format=summary", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in (out.stderr or "").splitlines():
        if "Input Integrated" in line:
            try:
                return float(line.split(":")[1].strip().split()[0])
            except (IndexError, ValueError):
                return None
    return None


def _mean_volume(path: str, pre_filter: str = "") -> float | None:
    """mean_volume (dBFS) of a file, optionally after a pre-filter (e.g. a highpass)."""
    af = (pre_filter + "," if pre_filter else "") + "volumedetect"
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", af, "-f", "null", "-"],
                         capture_output=True, text=True)
    for line in (out.stderr or "").splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().split()[0])
            except (IndexError, ValueError):
                return None
    return None


def warn_if_noise_wash(path: str) -> None:
    """Flag an ambient bed dominated by broadband hiss. ElevenLabs renders quiet/abstract
    prompts ('room tone', 'airy shimmer', 'hush') as noise: its energy above 8kHz sits within
    a few dB of the full-band level (real foley drops 7-20 dB up there). If so, the bed will
    sound like 'annoying background noise' once amplified -> re-author with concrete foley."""
    full = _mean_volume(path)
    hi = _mean_volume(path, "highpass=f=8000")
    if full is None or hi is None:
        return
    gap = full - hi  # how far below the full level the >8kHz band sits
    tag = "  [bed-QA]"
    if gap < 3.0:
        print(f"{tag} ⚠ NOISE WASH: >8kHz is only {gap:.1f}dB below full ({full:.1f}/{hi:.1f}). "
              f"This bed is broadband hiss, not foley — it will sound like noise when boosted. "
              f"Re-author with CONCRETE discrete sounds (clock tick, candle pop, page turn, a "
              f"single soft gust) + one-shots in speech gaps; reject continuous abstract textures.",
              file=sys.stderr)
    else:
        print(f"{tag} ok: >8kHz {gap:.1f}dB below full (structured, not a noise wash).",
              file=sys.stderr)


def last_word_end(align_path: str):
    """Return the end time (s) of the last aligned word, or None."""
    try:
        with open(align_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    words = data.get("words") or data.get("segments") or []
    # faster-whisper / whisperx style: list of {word/text, start, end} or segments with words.
    ends = []
    for w in words:
        if isinstance(w, dict):
            if "end" in w:
                ends.append(w["end"])
            for sub in (w.get("words") or []):
                if isinstance(sub, dict) and "end" in sub:
                    ends.append(sub["end"])
    return max(ends) if ends else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reel-dir", help="Reel folder; auto-discovers final.mp4, ambient/ambient_spatial.mp3, narration.mp3, narration.align.json")
    ap.add_argument("--final", help="Finished reel mp4 (default: REEL/final.mp4)")
    ap.add_argument("--ambient", help="Spatial ambient layer mp3 (default: REEL/ambient/ambient_spatial.mp3)")
    ap.add_argument("--narration", help="Narration-only mp3 used as sidechain key (default: REEL/narration.mp3)")
    ap.add_argument("--align", help="narration.align.json for fade timing (default: REEL/narration.align.json)")
    ap.add_argument("--out", help="Output mp4 (default: REEL/final-espacial.mp4)")
    ap.add_argument("--ambient-gain-db", type=float, default=-4.0,
                    help="Level offset on the ambient layer before ducking (default -4). Lower = more subtle.")
    ap.add_argument("--duck", default="threshold=0.04:ratio=3:attack=20:release=350",
                    help="sidechaincompress params (ambient ducked under narration).")
    # --- bed cleanup (anti ElevenLabs broadband-hiss; see SKILL.md "noise wash" lesson) ---
    # Quiet/abstract ambiences ("room tone", "airy shimmer", "hush") render as low-level
    # broadband NOISE; boosting them makes a hiss wash. A gentle lowpass (these ambiences
    # have nothing above ~12kHz) + light FFT denoise tames it. ON by default.
    ap.add_argument("--no-clean", action="store_true",
                    help="Disable the bed cleanup (lowpass + light denoise). Use for rich, "
                         "loud outdoor foley that does not need it.")
    ap.add_argument("--clean-lowpass", type=int, default=12000,
                    help="Lowpass cutoff (Hz) on the ambient bed (default 12000; kills the "
                         "ElevenLabs brick-wall hiss above the useful band).")
    ap.add_argument("--clean-highpass", type=int, default=35,
                    help="Highpass cutoff (Hz) on the ambient bed (default 35; removes sub-rumble).")
    ap.add_argument("--clean-nr", type=float, default=10.0,
                    help="afftdn noise-reduction amount in dB (default 10; gentle. Higher = more "
                         "aggressive but risks 'musical noise' warble).")
    ap.add_argument("--loudnorm", default=None,
                    help="Final loudnorm target. Default: MATCH final.mp4's own integrated loudness "
                         "(so the only audible change is the ambient bed). Pass e.g. 'I=-16:TP=-1.5:LRA=11' "
                         "to force a fixed target instead.")
    ap.add_argument("--beat", type=float, default=0.15,
                    help="Pause (s) after the last word before the fade starts (default 0.15).")
    ap.add_argument("--fade-start", type=float, help="Audio fade-out start (s). Overrides auto-detection.")
    ap.add_argument("--fade-dur", type=float, default=0.7, help="Audio fade-out duration (s). Default 0.7.")
    ap.add_argument("--no-fade", action="store_true", help="Do not apply a final audio fade.")
    ap.add_argument("--dry-run", action="store_true", help="Print the ffmpeg command and exit.")
    args = ap.parse_args()

    reel = args.reel_dir
    final = args.final or (os.path.join(reel, "final.mp4") if reel else None)
    ambient = args.ambient or (os.path.join(reel, "ambient", "ambient_spatial.mp3") if reel else None)
    narration = args.narration or (os.path.join(reel, "narration.mp3") if reel else None)
    align = args.align or (os.path.join(reel, "narration.align.json") if reel else None)
    out = args.out or (os.path.join(reel, "final-espacial.mp4") if reel else None)

    for label, p in [("final", final), ("ambient", ambient), ("narration", narration), ("out", out)]:
        if not p:
            raise SystemExit(f"Missing --{label} (or pass --reel-dir to auto-discover).")
    for label, p in [("final", final), ("ambient", ambient), ("narration", narration)]:
        if not os.path.isfile(p):
            raise SystemExit(f"Not found: {label} = {p}")

    dur = ffprobe_duration(final)

    # Sanity: warn if the ambient bed is a broadband-noise wash (the "ruido raro" failure).
    warn_if_noise_wash(ambient)

    # Bed cleanup chain (lowpass + light FFT denoise) — tames ElevenLabs broadband hiss.
    if args.no_clean:
        clean = ""
    else:
        clean = (f",highpass=f={args.clean_highpass},lowpass=f={args.clean_lowpass}"
                 f",afftdn=nr={args.clean_nr}")
        print(f"[clean] bed cleanup: highpass {args.clean_highpass}Hz + lowpass "
              f"{args.clean_lowpass}Hz + afftdn nr={args.clean_nr} (use --no-clean to disable)")

    # Loudnorm target: by default MATCH the source final.mp4 loudness, so the only audible
    # change is the ambient bed (our series masters sit ~-21..-24 LUFS, not -16; forcing a
    # fixed -16 would boost the whole mix several dB and muddy the A/B vs final.mp4).
    loudnorm = args.loudnorm
    if loudnorm is None:
        measured = measure_integrated_lufs(final)
        target = measured if measured is not None else -16.0
        loudnorm = f"I={target:.1f}:TP=-1.5:LRA=11"
        print(f"[loudnorm] source={measured} LUFS -> match target {loudnorm}")

    # Fade timing
    fade_filter = ""
    if not args.no_fade:
        if args.fade_start is not None:
            fstart = args.fade_start
        else:
            lw = last_word_end(align) if align and os.path.isfile(align) else None
            fstart = (lw + args.beat) if lw is not None else max(0.0, dur - args.fade_dur)
        fdur = max(0.2, min(args.fade_dur, max(0.2, dur - fstart)))
        fade_filter = f",afade=t=out:st={fstart:.3f}:d={fdur:.3f}"
        print(f"[fade] video_dur={dur:.2f}s  fade_start={fstart:.2f}s  fade_dur={fdur:.2f}s")

    # Filter graph:
    #  [1] ambient -> gain -> resample
    #  [2] narration (key) -> resample
    #  sidechaincompress(ambient, narration) -> ducked ambient
    #  amix(original audio, ducked ambient) -> loudnorm -> fade
    fc = (
        f"[1:a]aresample=48000{clean},volume={args.ambient_gain_db}dB[amb];"
        f"[2:a]aresample=48000[key];"
        f"[amb][key]sidechaincompress={args.duck}[duck];"
        f"[0:a]aresample=48000[base];"
        f"[base][duck]amix=inputs=2:normalize=0:dropout_transition=0,"
        f"loudnorm={loudnorm}{fade_filter}[a]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", final,
        "-i", ambient,
        "-i", narration,
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", out,
    ]

    if args.dry_run:
        print(" ".join(f"'{c}'" if " " in c else c for c in cmd))
        return

    print(f"[overlay] {os.path.basename(final)} + ambient (ducked under narration) -> {os.path.basename(out)}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(r.returncode)
    print(json.dumps({"out": out, "duration": round(dur, 3),
                      "ambient_gain_db": args.ambient_gain_db}, ensure_ascii=False))


if __name__ == "__main__":
    main()
