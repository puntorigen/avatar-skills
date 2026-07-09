#!/usr/bin/env python3
"""Trim leading and trailing silence from audio files using ffmpeg.

Uses the silencedetect filter to find where actual audio begins and ends,
then re-encodes only the active portion. Optionally adds a small fade-out.

Usage:
    python3 trim_silence.py input.mp3 --output trimmed.mp3
    python3 trim_silence.py input.mp3 --threshold -40 --min-duration 0.02
    python3 trim_silence.py input.mp3 --fade-out 50  # 50ms fade-out
    python3 trim_silence.py *.mp3 --batch --output trimmed/
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def get_audio_duration(path):
    """Get total duration of an audio file in seconds."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def detect_silence_ranges(path, threshold_db=-35, min_silence_duration=0.05):
    """Detect silence ranges using ffmpeg silencedetect.

    Returns list of (start, end) tuples for silent segments.
    """
    cmd = [
        "ffmpeg", "-i", str(path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_silence_duration}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr

    starts = re.findall(r"silence_start:\s*([\d.]+)", stderr)
    ends = re.findall(r"silence_end:\s*([\d.]+)", stderr)

    ranges = []
    for i, s in enumerate(starts):
        start = float(s)
        end = float(ends[i]) if i < len(ends) else get_audio_duration(path)
        ranges.append((start, end))

    return ranges


def find_active_region(path, threshold_db=-35, min_silence_duration=0.05, pad_ms=10):
    """Find the start and end of the non-silent region.

    Returns (start_sec, end_sec) of the active audio, with optional padding.
    """
    total = get_audio_duration(path)
    if total <= 0:
        return 0.0, 0.0

    silence_ranges = detect_silence_ranges(path, threshold_db, min_silence_duration)

    if not silence_ranges:
        return 0.0, total

    active_start = 0.0
    active_end = total

    if silence_ranges and silence_ranges[0][0] < 0.01:
        active_start = silence_ranges[0][1]

    if silence_ranges and abs(silence_ranges[-1][1] - total) < 0.05:
        active_end = silence_ranges[-1][0]

    pad_sec = pad_ms / 1000.0
    active_start = max(0.0, active_start - pad_sec)
    active_end = min(total, active_end + pad_sec)

    if active_end <= active_start:
        return 0.0, total

    return active_start, active_end


def trim_audio(input_path, output_path, start, end, *, fade_out_ms=0, bitrate="192k"):
    """Trim audio to [start, end] with optional fade-out."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = end - start
    filters = []

    if fade_out_ms > 0:
        fade_sec = fade_out_ms / 1000.0
        fade_start = max(0, duration - fade_sec)
        filters.append(f"afade=t=out:st={fade_start:.3f}:d={fade_sec:.3f}")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
    ]

    if filters:
        cmd.extend(["-af", ",".join(filters)])

    cmd.extend(["-b:a", bitrate, str(output_path)])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Error trimming {input_path.name}: {result.stderr.strip()[-200:]}", file=sys.stderr)
        return None

    return str(output_path)


def process_file(input_path, output_path, *, threshold_db, min_silence, pad_ms, fade_out_ms):
    """Full pipeline: detect active region, trim, report."""
    import shutil
    import tempfile

    input_path = Path(input_path)
    output_path = Path(output_path)
    total = get_audio_duration(input_path)

    if total <= 0:
        print(f"  {input_path.name}: could not read duration, skipping.", file=sys.stderr)
        return None

    active_start, active_end = find_active_region(
        input_path,
        threshold_db=threshold_db,
        min_silence_duration=min_silence,
        pad_ms=pad_ms,
    )

    active_duration = active_end - active_start
    removed = total - active_duration

    if removed < 0.02:
        print(f"  {input_path.name}: no significant silence detected ({total:.3f}s)", file=sys.stderr)
        if str(input_path.resolve()) != str(output_path.resolve()):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(input_path), str(output_path))
        return {
            "file": str(output_path),
            "original_duration": round(total, 3),
            "trimmed_duration": round(total, 3),
            "removed": 0.0,
            "active_start": 0.0,
            "active_end": round(total, 3),
        }

    in_place = str(input_path.resolve()) == str(output_path.resolve())

    if in_place:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=input_path.suffix)
        os.close(tmp_fd)
        trim_target = Path(tmp_path)
    else:
        trim_target = output_path

    result = trim_audio(input_path, trim_target, active_start, active_end, fade_out_ms=fade_out_ms)

    if result is None:
        if in_place and Path(tmp_path).exists():
            os.unlink(tmp_path)
        return None

    if in_place:
        shutil.move(str(trim_target), str(output_path))

    new_duration = get_audio_duration(output_path)

    print(
        f"  {input_path.name}: {total:.3f}s → {new_duration:.3f}s "
        f"(removed {removed:.3f}s silence, active at {active_start:.3f}-{active_end:.3f}s)",
        file=sys.stderr,
    )

    return {
        "file": str(output_path),
        "original_duration": round(total, 3),
        "trimmed_duration": round(new_duration, 3),
        "removed": round(removed, 3),
        "active_start": round(active_start, 3),
        "active_end": round(active_end, 3),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Trim leading/trailing silence from audio files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inputs", nargs="+", help="Input audio file(s)")
    parser.add_argument("--output", "-o", help="Output file or directory (for --batch)")
    parser.add_argument("--threshold", "-t", type=float, default=-35,
                        help="Silence threshold in dB (default: -35)")
    parser.add_argument("--min-duration", type=float, default=0.05,
                        help="Min silence duration to detect in seconds (default: 0.05)")
    parser.add_argument("--pad", type=float, default=10,
                        help="Padding around active region in ms (default: 10)")
    parser.add_argument("--fade-out", type=float, default=0,
                        help="Fade-out duration in ms (default: 0, try 20-50 for smooth tails)")
    parser.add_argument("--in-place", action="store_true",
                        help="Overwrite input files (careful!)")

    args = parser.parse_args()

    input_paths = []
    for pattern in args.inputs:
        p = Path(pattern)
        if p.is_file():
            input_paths.append(p)
        elif "*" in pattern or "?" in pattern:
            import glob
            input_paths.extend(Path(f) for f in glob.glob(pattern) if Path(f).is_file())
        else:
            print(f"Warning: {pattern} not found, skipping.", file=sys.stderr)

    if not input_paths:
        print("Error: No valid input files.", file=sys.stderr)
        sys.exit(1)

    batch = len(input_paths) > 1
    results = []

    for inp in input_paths:
        if args.in_place:
            out = inp
        elif args.output:
            out_path = Path(args.output)
            if batch or out_path.suffix == "":
                out = out_path / inp.name
            else:
                out = out_path
        else:
            out = inp.with_stem(inp.stem + "_trimmed")

        info = process_file(
            inp, out,
            threshold_db=args.threshold,
            min_silence=args.min_duration,
            pad_ms=args.pad,
            fade_out_ms=args.fade_out,
        )
        if info:
            results.append(info)

    if not results:
        print("Error: No files were processed successfully.", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(results if batch else results[0], indent=2))


if __name__ == "__main__":
    main()
