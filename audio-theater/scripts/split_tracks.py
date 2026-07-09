#!/usr/bin/env python3
"""Split a rendered audio-theater project into role-separated tracks.

Outputs (into the project folder):
  - narration.mp3    : ONLY the narration / off-camera voiceover lines, placed on
                       the original timeline (silence everywhere else).
  - lipsync_mix.mp3  : the on-camera (lip-synced) voices + all SFX, with the
                       narration MUTED. This is the track to feed an audio-driven
                       video model (e.g. seedance-2): it lip-syncs only the
                       on-camera character(s) and is never confused by the
                       off-camera narrator. Merge `narration.mp3` back onto the
                       rendered video in post.

Why split? Audio-driven video models lip-sync whatever voice is in the track. If
the narrator's voice is present, the model tries to make an on-screen character
mouth the narration. Feeding the narration-muted track keeps lip-sync correct;
the narration is layered back over the final video.

Roles come from script.json characters: a character is treated as narration when
its `role` is one of narration/narrator/voiceover/vo/offscreen/off_camera, or
when `on_camera` is false. Override with --narration / --onscreen (comma lists).

Usage:
  python3 split_tracks.py --out audio-theater/ep
  python3 split_tracks.py --out audio-theater/ep --narration "Narrador" --onscreen "Doki"
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    load_json, resolve_out_dir, get_audio_duration, run_ffmpeg, format_timecode,
)

NARRATION_ROLES = {
    "narration", "narrator", "voiceover", "voice-over", "vo",
    "offscreen", "off_camera", "off-camera",
}
AFORMAT = "aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000"


def is_narration(character):
    role = str(character.get("role", "")).strip().lower()
    if role in NARRATION_ROLES:
        return True
    if character.get("on_camera") is False:
        return True
    return False


def build_bed(placements, total, dest, *, normalize=False, target_i=-16.0, bitrate="192k"):
    """Place each (file, start) clip on a silent bed of length `total`, sum them.

    Writes WAV (pcm) when dest ends in .wav (no loudnorm); otherwise MP3.
    Returns True on success, None when there is nothing to place.
    """
    if not placements:
        return None
    inputs = []
    filt = []
    labels = []
    for n, (fp, start) in enumerate(placements):
        inputs += ["-i", str(fp)]
        start_ms = int(round(float(start) * 1000))
        chain = f"[{n}:a]{AFORMAT}"
        if start_ms > 0:
            chain += f",adelay={start_ms}:all=1"
        chain += f",apad=whole_dur={total:.3f}[a{n}]"
        filt.append(chain)
        labels.append(f"[a{n}]")
    filt.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[mix]")
    if normalize:
        filt.append(f"[mix]loudnorm=I={target_i}:TP=-1.5:LRA=11[out]")
        map_label = "[out]"
    else:
        map_label = "[mix]"
    dest = Path(dest)
    codec = ["-c:a", "pcm_s16le"] if dest.suffix == ".wav" else ["-c:a", "libmp3lame", "-b:a", bitrate]
    ok = run_ffmpeg(
        inputs + ["-filter_complex", ";".join(filt), "-map", map_label] + codec + [str(dest)],
        description=f"build {dest.name}",
    )
    return ok


def main():
    ap = argparse.ArgumentParser(description="Split a project into narration + lipsync-feed tracks")
    ap.add_argument("--out", "-o", required=True, help="Project folder")
    ap.add_argument("--narration", default=None, help="Comma list of narration/off-camera speakers (override)")
    ap.add_argument("--onscreen", default=None, help="Comma list of on-camera/lip-synced speakers (override)")
    ap.add_argument("--narration-name", default="narration.mp3")
    ap.add_argument("--feed-name", default="lipsync_mix.mp3")
    ap.add_argument("--target-i", type=float, default=-16.0)
    ap.add_argument("--bitrate", default="192k")
    args = ap.parse_args()

    out_dir = resolve_out_dir(args.out)
    lines_json = out_dir / "lines.json"
    if not lines_json.exists():
        print(f"Error: {lines_json} not found (run generate_voices.py first).", file=sys.stderr)
        sys.exit(1)
    data = load_json(lines_json)
    lines = data.get("lines", [])
    total = float(data.get("duration") or 0.0)
    if total <= 0:
        total = max((float(l.get("end", 0.0)) for l in lines), default=0.0)

    # Resolve narration vs on-camera speaker sets.
    narration_set, onscreen_override = None, None
    if args.narration is not None:
        narration_set = {s.strip() for s in args.narration.split(",") if s.strip()}
    if args.onscreen is not None:
        onscreen_override = {s.strip() for s in args.onscreen.split(",") if s.strip()}

    if narration_set is None:
        narration_set = set()
        script_path = out_dir / "script.json"
        if script_path.exists():
            for ch in load_json(script_path).get("characters", []):
                if is_narration(ch):
                    narration_set.add(ch.get("name"))

    def line_is_narration(speaker):
        if onscreen_override is not None and speaker in onscreen_override:
            return False
        return speaker in narration_set

    narration_lines, onscreen_lines = [], []
    for ln in lines:
        spk = ln.get("speaker")
        fp = out_dir / ln.get("file", "")
        start = float(ln.get("start", 0.0))
        (narration_lines if line_is_narration(spk) else onscreen_lines).append((fp, start, spk, ln.get("index")))

    if not narration_lines:
        print("Warning: no narration lines detected. Use --narration or add a `role` to script.json characters.", file=sys.stderr)
    if not onscreen_lines:
        print("Warning: no on-camera lines detected; the lipsync feed will be SFX-only.", file=sys.stderr)

    tmp = Path(tempfile.mkdtemp())
    result = {"narration": None, "lipsync_feed": None,
              "narration_speakers": sorted(narration_set),
              "duration": round(total, 3), "lines": []}
    for fp, start, spk, idx in narration_lines + onscreen_lines:
        result["lines"].append({"index": idx, "speaker": spk,
                                "start": format_timecode(start),
                                "track": "narration" if line_is_narration(spk) else "lipsync"})

    # 1) narration.mp3 (loudnorm so it sits well over the video).
    narration_path = out_dir / args.narration_name
    if narration_lines:
        ok = build_bed([(fp, st) for (fp, st, _, _) in narration_lines], total,
                       narration_path, normalize=True, target_i=args.target_i, bitrate=args.bitrate)
        if ok:
            result["narration"] = str(narration_path)

    # 2) lipsync_mix.mp3 = on-camera voices (silent bed) + SFX via mix.py.
    onscreen_bed = tmp / "dialogue_onscreen.wav"
    feed_path = out_dir / args.feed_name
    if onscreen_lines:
        build_bed([(fp, st) for (fp, st, _, _) in onscreen_lines], total, onscreen_bed, normalize=False)
    else:
        run_ffmpeg(["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(onscreen_bed)],
                   description="silent on-camera bed")
    mix_cmd = [
        sys.executable, str(SCRIPT_DIR / "mix.py"),
        "--dialogue", str(onscreen_bed),
        "--cues", str(out_dir / "cues.json"),
        "--out", str(out_dir),
        "--output-name", args.feed_name,
        "--target-i", str(args.target_i),
        "--bitrate", args.bitrate,
    ]
    proc = subprocess.run(mix_cmd, capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    if proc.returncode == 0 and feed_path.exists():
        result["lipsync_feed"] = str(feed_path)
    else:
        print("Error: failed to build the lipsync feed via mix.py.", file=sys.stderr)
        sys.exit(1)

    if result["narration"]:
        result["narration_duration"] = round(get_audio_duration(narration_path), 3)
    result["lipsync_feed_duration"] = round(get_audio_duration(feed_path), 3)

    tracks_path = out_dir / "tracks.json"
    tracks_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
