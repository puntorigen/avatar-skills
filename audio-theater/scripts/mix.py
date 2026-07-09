#!/usr/bin/env python3
"""Mix dialogue.wav + cued SFX/music into final.mp3 with sidechain ducking.

- oneshot cues: placed at their start timecode at the given gain.
- ambient/music cues: looped/trimmed to [start,end], faded, and DUCKED under the
  dialogue via sidechaincompress (the dialogue is the sidechain key).
- everything is summed (amix) and loudness-normalized (loudnorm) to final.mp3.

Usage:
    python3 mix.py --dialogue audio-theater/ep/dialogue.wav \
        --cues audio-theater/ep/cues.json --out audio-theater/ep
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    load_json, resolve_out_dir, get_audio_duration, run_ffmpeg, format_timecode,
    finalize_stems, stem_paths, ratio_from_duck_db,
    assemble_content_and_music, MUSIC_DUCK_DB,
)

AFORMAT = "aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000"
DUCK_ATTACK = 20
DUCK_RELEASE = 350


def cue_window(cue):
    start = float(cue.get("start", 0.0) or 0.0)
    end = cue.get("end")
    gen = cue.get("gen_duration")
    if end is None:
        end = start + (gen or 3.0)
    return start, float(end)


def main():
    parser = argparse.ArgumentParser(description="Mix dialogue + SFX into final.mp3")
    parser.add_argument("--dialogue", default=None, help="dialogue.wav (default <out>/dialogue.wav)")
    parser.add_argument("--cues", default=None, help="cues.json (default <out>/cues.json)")
    parser.add_argument("--out", "-o", required=True, help="Project folder")
    parser.add_argument("--output-name", default="final.mp3", help="Output filename")
    parser.add_argument("--target-i", type=float, default=-16.0, help="loudnorm target LUFS")
    parser.add_argument("--bitrate", default="192k", help="MP3 bitrate")
    parser.add_argument("--no-duck", action="store_true", help="Disable sidechain ducking")
    parser.add_argument("--stems", choices=["auto", "always", "off"], default="auto",
                        help="Also emit a music-only stem and a no-music (dialogue+SFX) "
                             "stem. auto = only when music cues exist. Default: auto")
    args = parser.parse_args()

    out_dir = resolve_out_dir(args.out)
    dialogue = Path(args.dialogue) if args.dialogue else out_dir / "dialogue.wav"
    if not dialogue.exists():
        print(f"Error: dialogue not found: {dialogue}", file=sys.stderr)
        sys.exit(1)

    cues = []
    cues_path = Path(args.cues) if args.cues else out_dir / "cues.json"
    if cues_path.exists():
        cues = load_json(cues_path).get("cues", [])

    # Keep only cues that have a generated file.
    ready = []
    for c in cues:
        f = c.get("file")
        if not f:
            print(f"  Skipping cue '{c.get('id')}' (no file; run generate_sfx.py)", file=sys.stderr)
            continue
        fp = out_dir / f
        if not fp.exists():
            print(f"  Skipping cue '{c.get('id')}' (file missing: {fp})", file=sys.stderr)
            continue
        ready.append((c, fp))

    dialogue_dur = get_audio_duration(dialogue)
    total = dialogue_dur
    for c, _ in ready:
        _, end = cue_window(c)
        total = max(total, end)
    total = round(total + 0.2, 3)

    output_path = out_dir / args.output_name

    if not ready:
        # No cues: just normalize the dialogue.
        ok = run_ffmpeg([
            "-i", str(dialogue),
            "-af", f"loudnorm=I={args.target_i}:TP=-1.5:LRA=11",
            "-c:a", "libmp3lame", "-b:a", args.bitrate, str(output_path),
        ], description="normalize dialogue (no cues)")
        if not ok:
            sys.exit(1)
        print(json.dumps({"final": str(output_path), "duration": round(get_audio_duration(output_path), 3),
                          "cues_used": 0}, indent=2))
        return

    # Build ffmpeg inputs. Ambient/music inputs are stream-looped.
    inputs = ["-i", str(dialogue)]
    input_meta = []  # (cue, fp, input_index, looped)
    idx = 1
    for c, fp in ready:
        looped = c.get("type") in ("ambient", "music")
        if looped:
            inputs += ["-stream_loop", "-1", "-i", str(fp)]
        else:
            inputs += ["-i", str(fp)]
        input_meta.append((c, fp, idx, looped))
        idx += 1

    # Ambient (non-music) beds duck under the voice. MUSIC instead ducks under the
    # whole no-music CONTENT bus (voices + SFX) so it always sits under them and
    # swells back up in the gaps — so only ambient beds need a voice sidechain key.
    duck = not args.no_duck
    ambient_idx = [i for (c, fp, i, lp) in input_meta if lp and c.get("type") != "music"]
    n_keys = len(ambient_idx) if duck else 0

    filt = []
    filt.append(f"[0:a]{AFORMAT},apad=whole_dur={total}[voice]")
    if n_keys > 0:
        outs = "[vmain]" + "".join(f"[vkey{i}]" for i in range(n_keys))
        filt.append(f"[voice]asplit={n_keys + 1}{outs}")
        voice_main = "[vmain]"
    else:
        voice_main = "[voice]"

    nomusic_cue_labels, music_specs = [], []
    key_cursor = 0
    for (c, fp, i, looped) in input_meta:
        start, end = cue_window(c)
        win = max(0.3, end - start)
        is_music = c.get("type") == "music"
        gain = float(c.get("gain_db", -22 if is_music else -10))
        start_ms = int(round(start * 1000))
        label = f"a{i}"

        if looped:
            fin = float(c.get("fade_in", 1.0))
            fout = float(c.get("fade_out", 1.5))
            fout_st = max(0.0, win - fout)
            chain = (
                f"[{i}:a]{AFORMAT},atrim=0:{win:.3f},asetpts=N/SR/TB,"
                f"afade=t=in:st=0:d={fin:.3f},afade=t=out:st={fout_st:.3f}:d={fout:.3f},"
                f"volume={gain}dB"
            )
            if start_ms > 0:
                chain += f",adelay={start_ms}:all=1"
            chain += f",apad=whole_dur={total}[bed{i}]"
            filt.append(chain)

            if is_music:
                # Defer ducking: music ducks under the content bus (voices + sfx).
                music_specs.append((f"[bed{i}]", float(c.get("duck_db", MUSIC_DUCK_DB))))
            elif duck:
                ratio = ratio_from_duck_db(c.get("duck_db", -8))
                filt.append(
                    f"[bed{i}][vkey{key_cursor}]sidechaincompress="
                    f"threshold=0.03:ratio={ratio:.1f}:attack={DUCK_ATTACK}:"
                    f"release={DUCK_RELEASE}:makeup=1[{label}]"
                )
                key_cursor += 1
                nomusic_cue_labels.append(f"[{label}]")
            else:
                filt.append(f"[bed{i}]anull[{label}]")
                nomusic_cue_labels.append(f"[{label}]")
        else:
            chain = f"[{i}:a]{AFORMAT},volume={gain}dB"
            if start_ms > 0:
                chain += f",adelay={start_ms}:all=1"
            chain += f",apad=whole_dur={total}[{label}]"
            filt.append(chain)
            nomusic_cue_labels.append(f"[{label}]")

    nm_label, mu_label = assemble_content_and_music(
        filt, [voice_main] + nomusic_cue_labels, music_specs, duck=duck)

    emit_stems = (args.stems == "always" or
                  (args.stems == "auto" and bool(music_specs)))

    summary = {
        "cues_used": len(ready),
        "ducked_beds": len(ambient_idx),
        "music_cues": len(music_specs),
        "music_ducks_under": "content (voices+sfx)" if (music_specs and duck) else None,
        "timeline": [
            {"id": c.get("id"), "type": c.get("type"),
             "start": format_timecode(cue_window(c)[0]),
             "end": format_timecode(cue_window(c)[1])}
            for c, _ in ready
        ],
    }

    if not emit_stems:
        if mu_label:
            filt.append(f"{nm_label}{mu_label}"
                        f"amix=inputs=2:normalize=0:dropout_transition=0[mixed]")
            last = "[mixed]"
        else:
            last = nm_label
        filt.append(f"{last}loudnorm=I={args.target_i}:TP=-1.5:LRA=11[out]")
        filter_complex = ";".join(filt)
        ok = run_ffmpeg(
            inputs + [
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:a", "libmp3lame", "-b:a", args.bitrate,
                str(output_path),
            ],
            description=f"mix {len(ready)} cue(s) + dialogue",
        )
        if not ok:
            print("  Filter graph was:", file=sys.stderr)
            print("    " + filter_complex, file=sys.stderr)
            sys.exit(1)
        final_dur = get_audio_duration(output_path)
        print(f"  final: {output_path} ({final_dur:.2f}s, {len(ready)} cues)", file=sys.stderr)
        summary["final"] = str(output_path)
        summary["duration"] = round(final_dur, 3)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    # ── Stems: render the no-music content bus + the ducked music bus to pre-norm
    #    WAVs, then apply a single shared linear gain so full == nomusic + music.
    filter_complex = ";".join(filt)
    nomusic_path, music_path = stem_paths(output_path)
    tmp_nm = out_dir / "._stem_nomusic.wav"
    tmp_mu = out_dir / "._stem_music.wav"
    tmp_full = out_dir / "._stem_full.wav"
    ok = run_ffmpeg(
        inputs + [
            "-filter_complex", filter_complex,
            "-map", nm_label, "-c:a", "pcm_s16le", str(tmp_nm),
            "-map", mu_label, "-c:a", "pcm_s16le", str(tmp_mu),
        ],
        description=f"stems: {len(nomusic_cue_labels)} sfx + {len(music_specs)} music",
    )
    if not ok:
        print("  Filter graph was:", file=sys.stderr)
        print("    " + filter_complex, file=sys.stderr)
        sys.exit(1)

    res = finalize_stems(tmp_full, tmp_nm, tmp_mu, output_path, nomusic_path, music_path,
                         target_i=args.target_i, bitrate=args.bitrate)
    for t in (tmp_nm, tmp_mu, tmp_full):
        t.unlink(missing_ok=True)

    summary.update(res)
    print(f"  final:   {output_path}", file=sys.stderr)
    print(f"  nomusic: {nomusic_path}", file=sys.stderr)
    print(f"  music:   {music_path}", file=sys.stderr)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
