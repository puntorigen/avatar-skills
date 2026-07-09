#!/usr/bin/env python3
"""Spatial stereo mix for the audio-theater *theater* mode.

Unlike mix.py (which mixes the flattened dialogue.wav), this mixer places each
per-line voice clip and each one-shot SFX on a virtual stereo stage (pan +
distance + optional movement), so a character can sit left/right, walk closer
while talking, or a bird can cross the scene L->R. Ambient/music beds stay
stereo (optional balance/distance) and are ducked under the voices.

Positions come from (all optional, backward compatible):
  - script.json  characters[].stage  {pan, distance}      (a character's seat)
  - script.json  lines[].spatial      {pan,distance} | {from,to} | {path:[...]}  (per-line override / movement)
  - cues.json    cues[].spatial       same shapes                                (per-SFX position / movement)

With no spatial info it behaves ~like mix.py but seats non-narration speakers
at gentle alternating L/R offsets for a natural stereo image. THEATER ONLY: the
lipsync feed (split_tracks.py) must stay center/mono-safe and keeps using mix.py.

Usage:
    python3 mix_spatial.py --out audio-theater/ep
    python3 mix_spatial.py --out audio-theater/ep --crossfeed --voice-pan-limit 0.6
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import spatial as sp  # noqa: E402
from _common import (  # noqa: E402
    load_json, resolve_out_dir, get_audio_duration, run_ffmpeg, format_timecode,
    finalize_stems, stem_paths, ratio_from_duck_db,
    assemble_content_and_music, MUSIC_DUCK_DB,
)

STEREO = sp.STEREO_48K
DUCK_ATTACK = 20
DUCK_RELEASE = 350
NARRATION_NAME_PREFIXES = ("narrad", "narrat")  # Narrador / Narrator -> centered
NARRATION_ROLES = {
    "narration", "narrator", "voiceover", "voice-over", "vo",
    "offscreen", "off_camera", "off-camera",
}


def music_scene_spatial(spatial, win):
    """Sanitize a scene-music cue's spatial into a SUBTLE, single-direction gesture.

    Music must NOT zig-zag (on/off/on/off reads as broken). Background score and
    narrator-style music should stay FIXED; only diegetic *scene* music moves, and
    even then as one clean gesture. Supported authoring:
      {pan, distance}                 -> fixed point source
      {enter: "left"|"right"|"front"} -> glides in to the seat over a few seconds,
                                         then holds (pair with fade_in)
      {exit:  "left"|"right"|"front"} -> holds, then glides out at the very end
                                         (pair with fade_out)
      {from, to}                      -> single sweep over the window (as authored)
      {path:[...]}                    -> collapsed to first+last (no bouncing)
    Returns a spatial dict that sp.build_source_chain understands.
    """
    seat_pan = float(spatial.get("pan", 0.0))
    seat_d = float(spatial.get("distance", 0.3))
    g = min(5.0, max(1.0, win * 0.5))  # gesture length (s): a few seconds, capped

    def side_pos(direction):
        if direction == "left":
            return (-0.75, min(seat_d + 0.30, 0.95))
        if direction == "right":
            return (0.75, min(seat_d + 0.30, 0.95))
        return (seat_pan, min(seat_d + 0.45, 0.95))  # front/back -> approach in depth

    if spatial.get("enter"):
        p0, d0 = side_pos(str(spatial["enter"]).lower())
        return {"path": [
            {"t": 0.0, "pan": p0, "distance": d0},
            {"t": g, "pan": seat_pan, "distance": seat_d},
            {"t": win, "pan": seat_pan, "distance": seat_d},
        ]}
    if spatial.get("exit"):
        p1, d1 = side_pos(str(spatial["exit"]).lower())
        return {"path": [
            {"t": 0.0, "pan": seat_pan, "distance": seat_d},
            {"t": max(0.0, win - g), "pan": seat_pan, "distance": seat_d},
            {"t": win, "pan": p1, "distance": d1},
        ]}
    if "from" in spatial and "to" in spatial:
        return {"from": spatial["from"], "to": spatial["to"]}
    if spatial.get("path"):
        pts = sorted(spatial["path"], key=lambda k: float(k.get("t", 0.0)))
        if len(pts) >= 2:
            return {"path": [pts[0], pts[-1]]}  # first->last only, no zig-zag
    return {"pan": seat_pan, "distance": seat_d}


def cue_window(cue):
    start = float(cue.get("start", 0.0) or 0.0)
    end = cue.get("end")
    gen = cue.get("gen_duration")
    if end is None:
        end = start + (gen or 3.0)
    return start, float(end)


def is_narration_char(ch):
    if str(ch.get("role", "")).strip().lower() in NARRATION_ROLES:
        return True
    if ch.get("on_camera") is False:
        return True
    name = str(ch.get("name", "")).strip().lower()
    return name.startswith(NARRATION_NAME_PREFIXES)


def compute_seats(characters):
    """Default seat (pan, distance) per character when no explicit stage given."""
    seats, others = {}, []
    for ch in characters:
        name = ch.get("name")
        if is_narration_char(ch):
            seats[name] = (0.0, sp.NARRATION_DEFAULT_DISTANCE)
        else:
            others.append(name)
    offsets = [-0.3, 0.3, -0.45, 0.45, -0.6, 0.6]
    for i, name in enumerate(others):
        seats[name] = (offsets[i % len(offsets)], sp.VOICE_DEFAULT_DISTANCE)
    return seats


def main():
    ap = argparse.ArgumentParser(description="Spatial stereo theater mix")
    ap.add_argument("--out", "-o", required=True, help="Project folder")
    ap.add_argument("--dialogue", default=None, help="(unused; voices come from lines.json)")
    ap.add_argument("--cues", default=None, help="cues.json (default <out>/cues.json)")
    ap.add_argument("--output-name", default="final.mp3", help="Output filename")
    ap.add_argument("--voice-pan-limit", type=float, default=sp.VOICE_PAN_LIMIT,
                    help="Clamp voice pan to +/- this (intelligibility). Default 0.5")
    ap.add_argument("--sfx-pan-limit", type=float, default=sp.SFX_PAN_LIMIT,
                    help="Clamp SFX pan to +/- this. Default 0.95")
    ap.add_argument("--max-atten-db", type=float, default=sp.MAX_ATTEN_DB,
                    help="Level drop at distance==1. Default -11")
    ap.add_argument("--crossfeed", action="store_true",
                    help="Apply headphone crossfeed (softens hard pans)")
    ap.add_argument("--no-duck", action="store_true",
                    help="Disable all sidechain ducking (beds and SFX)")
    ap.add_argument("--no-duck-sfx", action="store_true",
                    help="Don't duck one-shot SFX under the narration (keeps SFX full level)")
    ap.add_argument("--sfx-duck-db", type=float, default=-6.0,
                    help="How much one-shot SFX dip under the narrator. Default -6")
    ap.add_argument("--sfx-min-distance", type=float, default=0.12,
                    help="Floor on SFX distance so the narrator always reads as closest. Default 0.12")
    ap.add_argument("--voice-gain-db", type=float, default=0.0,
                    help="Trim/boost voice bus before mix (negative = quieter). Default 0")
    ap.add_argument("--target-i", type=float, default=-16.0, help="loudnorm target LUFS")
    ap.add_argument("--bitrate", default="192k", help="MP3 bitrate")
    ap.add_argument("--stems", choices=["auto", "always", "off"], default="auto",
                    help="Also emit a music-only stem and a no-music (dialogue+SFX) "
                         "stem. auto = only when music cues exist. Default: auto")
    args = ap.parse_args()

    out_dir = resolve_out_dir(args.out)
    lines_json = out_dir / "lines.json"
    if not lines_json.exists():
        print(f"Error: {lines_json} not found (run generate_voices.py first).", file=sys.stderr)
        sys.exit(1)
    ldata = load_json(lines_json)
    lines = ldata.get("lines", [])

    # script.json: character seats + per-line spatial overrides.
    char_stage, line_spatial, characters = {}, {}, []
    script_path = out_dir / "script.json"
    if script_path.exists():
        sdata = load_json(script_path)
        characters = sdata.get("characters", [])
        for ch in characters:
            if isinstance(ch.get("stage"), dict):
                char_stage[ch.get("name")] = ch["stage"]
        for sl in sdata.get("lines", []):
            if isinstance(sl.get("spatial"), dict):
                line_spatial[sl.get("index")] = sl["spatial"]
    seats = compute_seats(characters)
    narration_speakers = {ch.get("name") for ch in characters if is_narration_char(ch)}

    # cues.json
    cues = []
    cues_path = Path(args.cues) if args.cues else out_dir / "cues.json"
    if cues_path.exists():
        cues = load_json(cues_path).get("cues", [])
    ready = []
    for c in cues:
        f = c.get("file")
        fp = out_dir / f if f else None
        if not f or not fp.exists():
            print(f"  Skipping cue '{c.get('id')}' (no/missing file)", file=sys.stderr)
            continue
        ready.append((c, fp))

    if not lines and not ready:
        print("Error: nothing to mix (no voice lines and no cues).", file=sys.stderr)
        sys.exit(1)

    # Total timeline.
    total = float(ldata.get("duration") or 0.0)
    for ln in lines:
        total = max(total, float(ln.get("end", 0.0) or 0.0))
    for c, _ in ready:
        total = max(total, cue_window(c)[1])
    total = round(total + 0.2, 3)

    # ── Build ffmpeg inputs ──────────────────────────────────────────────
    inputs, voice_specs, cue_specs = [], [], []
    idx = 0
    for ln in lines:
        fp = out_dir / ln.get("file", "")
        if not fp.exists():
            print(f"  Skipping line {ln.get('index')} (missing clip {fp})", file=sys.stderr)
            continue
        speaker = ln.get("speaker")
        seat_pan, seat_dist = seats.get(speaker, (0.0, sp.VOICE_DEFAULT_DISTANCE))
        stage = char_stage.get(speaker) or {}
        dpan = float(stage.get("pan", seat_pan))
        ddist = float(stage.get("distance", seat_dist))
        spatial = line_spatial.get(ln.get("index"))  # may be None -> static seat
        win = float(ln.get("duration") or 1.0)
        chain, _moving = sp.build_source_chain(
            spatial, win=win, default_pan=dpan, default_distance=ddist,
            pan_limit=args.voice_pan_limit, max_atten_db=args.max_atten_db)
        is_narr = speaker in narration_speakers
        inputs += ["-i", str(fp)]
        voice_specs.append((idx, chain, int(round(float(ln.get("start", 0.0)) * 1000)), is_narr))
        idx += 1

    for c, fp in ready:
        looped = c.get("type") in ("ambient", "music")
        if looped:
            inputs += ["-stream_loop", "-1", "-i", str(fp)]
        else:
            inputs += ["-i", str(fp)]
        cue_specs.append((idx, c, fp, looped))
        idx += 1

    filt = []

    oneshot_specs = [(i, c, fp) for (i, c, fp, lp) in cue_specs if not lp]
    # Ambient SFX beds duck under the voice; MUSIC ducks under the whole content
    # bus (voices + SFX) further down, so the two are handled separately.
    ambient_specs = [(i, c, fp) for (i, c, fp, lp) in cue_specs
                     if lp and c.get("type") != "music"]
    music_cue_specs = [(i, c, fp) for (i, c, fp, lp) in cue_specs
                       if lp and c.get("type") == "music"]
    have_voices = bool(voice_specs)
    has_narration = any(is_narr for (_, _, _, is_narr) in voice_specs)
    duck = not args.no_duck
    duck_beds = duck and have_voices and bool(ambient_specs)
    duck_sfx = (duck and (not args.no_duck_sfx)
                and have_voices and bool(oneshot_specs))

    # Voices -> positioned stereo, delayed, padded. Narration voices also feed a
    # separate "narration bus" used to duck SFX, so the narrator always wins.
    vlabels, narr_key_labels = [], []
    voice_gain = float(args.voice_gain_db or 0.0)
    for (i, chain, ms, is_narr) in voice_specs:
        s = f"[{i}:a]"
        if voice_gain:
            s += f"volume={voice_gain}dB,"
        s += chain
        if ms > 0:
            s += f",adelay={ms}:all=1"
        s += f",apad=whole_dur={total}"
        if duck_sfx and has_narration and is_narr:
            s += f",asplit=2[v{i}][vn{i}]"
            narr_key_labels.append(f"[vn{i}]")
        else:
            s += f"[v{i}]"
        filt.append(s)
        vlabels.append(f"[v{i}]")

    voicemix = None
    if have_voices:
        if len(vlabels) == 1:
            filt.append(f"{vlabels[0]}{STEREO}[voicemix]")
        else:
            filt.append("".join(vlabels) +
                        f"amix=inputs={len(vlabels)}:normalize=0:dropout_transition=0[voicemix]")
        voicemix = "[voicemix]"

    # Build the narration bus (SFX duck key) when we have narration; otherwise
    # SFX (if ducked) key off the full voice mix.
    if duck_sfx and has_narration:
        if len(narr_key_labels) == 1:
            filt.append(f"{narr_key_labels[0]}{STEREO}[narrbus]")
        else:
            filt.append("".join(narr_key_labels) +
                        f"amix=inputs={len(narr_key_labels)}:normalize=0:dropout_transition=0[narrbus]")
    sfx_key_from_voicemix = duck_sfx and not has_narration

    # Split the voice mix into: main + one key per ducked bed (+ SFX keys if there
    # is no narration bus to key off).
    n_bed_keys = len(ambient_specs) if duck_beds else 0
    n_sfx = len(oneshot_specs) if duck_sfx else 0
    bed_key_labels, sfx_key_labels = [], []
    vm_parts = ["[vmain]"]
    for k in range(n_bed_keys):
        vm_parts.append(f"[bk{k}]")
        bed_key_labels.append(f"[bk{k}]")
    if sfx_key_from_voicemix:
        for k in range(n_sfx):
            vm_parts.append(f"[sk{k}]")
            sfx_key_labels.append(f"[sk{k}]")
    if have_voices and len(vm_parts) > 1:
        filt.append(f"{voicemix}asplit={len(vm_parts)}" + "".join(vm_parts))
        vmain = "[vmain]"
    else:
        vmain = voicemix

    if duck_sfx and has_narration:
        outs = "".join(f"[sk{k}]" for k in range(n_sfx))
        filt.append(f"[narrbus]asplit={n_sfx}{outs}")
        sfx_key_labels = [f"[sk{k}]" for k in range(n_sfx)]

    nomusic_cue_labels, music_specs = [], []
    bed_cursor, sfx_cursor = 0, 0
    scene_music_ids = []

    # 1) Ambient SFX beds: stereo, optional balance/distance, ducked under voice.
    for (i, c, fp) in ambient_specs:
        start, end = cue_window(c)
        win = max(0.3, end - start)
        ms = int(round(start * 1000))
        gain = float(c.get("gain_db", -16))
        spatial = c.get("spatial") if isinstance(c.get("spatial"), dict) else None
        label = f"a{i}"
        fin = float(c.get("fade_in", 1.0))
        fout = float(c.get("fade_out", 1.5))
        fout_st = max(0.0, win - fout)
        chain = (
            f"[{i}:a]{STEREO},atrim=0:{win:.3f},asetpts=N/SR/TB,"
            f"afade=t=in:st=0:d={fin:.3f},afade=t=out:st={fout_st:.3f}:d={fout:.3f},"
            f"volume={gain}dB"
        )
        if spatial and spatial.get("pan") is not None:
            gl, gr = sp.balance_gains(float(spatial["pan"]))
            chain += f",pan=stereo|c0={gl:.5f}*c0|c1={gr:.5f}*c1"
        if spatial and spatial.get("distance") is not None:
            d = sp.clamp(spatial["distance"], 0.0, 1.0)
            chain += (f",volume={args.max_atten_db * d:.2f}dB,"
                      f"lowpass=f={sp.fc_from_distance(d):.1f}")
        if ms > 0:
            chain += f",adelay={ms}:all=1"
        chain += f",apad=whole_dur={total}[bed{i}]"
        filt.append(chain)
        if duck_beds:
            ratio = ratio_from_duck_db(c.get("duck_db", -5))
            filt.append(
                f"[bed{i}]{bed_key_labels[bed_cursor]}sidechaincompress="
                f"threshold=0.03:ratio={ratio:.1f}:attack={DUCK_ATTACK}:"
                f"release={DUCK_RELEASE}:makeup=1[{label}]"
            )
            bed_cursor += 1
        else:
            filt.append(f"[bed{i}]anull[{label}]")
        nomusic_cue_labels.append(f"[{label}]")

    # 2) One-shot SFX: positioned/moving point source, ducked under narration.
    for (i, c, fp) in oneshot_specs:
        start, end = cue_window(c)
        win = max(0.3, end - start)
        ms = int(round(start * 1000))
        gain = float(c.get("gain_db", -9))
        spatial = c.get("spatial") if isinstance(c.get("spatial"), dict) else None
        label = f"a{i}"
        chain, _moving = sp.build_source_chain(
            spatial, win=win, default_pan=0.0, default_distance=0.25,
            pan_limit=args.sfx_pan_limit, max_atten_db=args.max_atten_db,
            min_distance=max(0.0, args.sfx_min_distance))
        s = f"[{i}:a]{chain},volume={gain}dB"
        if ms > 0:
            s += f",adelay={ms}:all=1"
        if duck_sfx:
            s += f",apad=whole_dur={total}[osrc{i}]"
            filt.append(s)
            ratio = ratio_from_duck_db(args.sfx_duck_db)
            filt.append(
                f"[osrc{i}]{sfx_key_labels[sfx_cursor]}sidechaincompress="
                f"threshold=0.05:ratio={ratio:.1f}:attack=5:release=250:makeup=1[{label}]"
            )
            sfx_cursor += 1
        else:
            s += f",apad=whole_dur={total}[{label}]"
            filt.append(s)
        nomusic_cue_labels.append(f"[{label}]")

    # 3) Music beds (RAW, no inline duck). FIXED wide stereo bed for score /
    #    narrator-style music; a SUBTLE single-direction gesture for scene music.
    for (i, c, fp) in music_cue_specs:
        start, end = cue_window(c)
        win = max(0.3, end - start)
        ms = int(round(start * 1000))
        gain = float(c.get("gain_db", -22))
        spatial = c.get("spatial") if isinstance(c.get("spatial"), dict) else None
        scene_music = bool(spatial and (spatial.get("scene") or spatial.get("enter")
                                        or spatial.get("exit") or "from" in spatial
                                        or "path" in spatial))
        fin = float(c.get("fade_in", 1.5))
        fout = float(c.get("fade_out", 2.0))
        fout_st = max(0.0, win - fout)
        chain = (
            f"[{i}:a]{STEREO},atrim=0:{win:.3f},asetpts=N/SR/TB,"
            f"afade=t=in:st=0:d={fin:.3f},afade=t=out:st={fout_st:.3f}:d={fout:.3f},"
            f"volume={gain}dB"
        )
        if scene_music:
            sane = music_scene_spatial(spatial, win)
            pos, _moving = sp.build_source_chain(
                sane, win=win, default_pan=float(spatial.get("pan", 0.0)),
                default_distance=float(spatial.get("distance", 0.3)),
                pan_limit=args.sfx_pan_limit, max_atten_db=args.max_atten_db)
            chain += f",{pos}"
            scene_music_ids.append(c.get("id"))
        else:
            # Fixed wide bed; optional gentle balance/distance, but NO movement.
            if spatial and spatial.get("pan") is not None:
                gl, gr = sp.balance_gains(float(spatial["pan"]))
                chain += f",pan=stereo|c0={gl:.5f}*c0|c1={gr:.5f}*c1"
            if spatial and spatial.get("distance") is not None:
                d = sp.clamp(spatial["distance"], 0.0, 1.0)
                chain += (f",volume={args.max_atten_db * d:.2f}dB,"
                          f"lowpass=f={sp.fc_from_distance(d):.1f}")
        if ms > 0:
            chain += f",adelay={ms}:all=1"
        chain += f",apad=whole_dur={total}[bed{i}]"
        filt.append(chain)
        music_specs.append((f"[bed{i}]", float(c.get("duck_db", MUSIC_DUCK_DB))))

    if not (vmain or nomusic_cue_labels or music_specs):
        print("Error: nothing to mix after filtering.", file=sys.stderr)
        sys.exit(1)

    # Music ducks under the whole no-music CONTENT bus (voices + SFX), swelling
    # back up in the gaps. crossfeed is applied per bus (linear).
    nomusic_labels = ([vmain] if vmain else []) + nomusic_cue_labels
    nm_label, mu_label = assemble_content_and_music(
        filt, nomusic_labels, music_specs, crossfeed=args.crossfeed, duck=duck)

    output_path = out_dir / args.output_name
    emit_stems = (args.stems == "always" or
                  (args.stems == "auto" and bool(music_specs)))

    summary = {
        "voices": len(voice_specs),
        "cues_used": len(ready),
        "ducked_beds": len(ambient_specs) if duck_beds else 0,
        "ducked_sfx": len(oneshot_specs) if duck_sfx else 0,
        "sfx_duck_under": ("narration" if (duck_sfx and has_narration)
                           else "voices" if duck_sfx else None),
        "music_cues": len(music_specs),
        "music_ducks_under": "content (voices+sfx)" if (music_specs and duck) else None,
        "scene_music": scene_music_ids,
        "crossfeed": bool(args.crossfeed),
        "timeline": [
            {"id": c.get("id"), "type": c.get("type"),
             "spatial": c.get("spatial"),
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
            description=f"spatial mix: {len(voice_specs)} voices + {len(ready)} cue(s)",
        )
        if not ok:
            print("  Filter graph was:", file=sys.stderr)
            print("    " + filter_complex, file=sys.stderr)
            sys.exit(1)
        final_dur = get_audio_duration(output_path)
        print(f"  final: {output_path} ({final_dur:.2f}s)", file=sys.stderr)
        summary["final"] = str(output_path)
        summary["duration"] = round(final_dur, 3)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    # ── Stems: render the no-music content bus + the ducked music bus to pre-norm
    #    WAVs, then one shared linear gain finalizes all three (full == nm + music).
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
        description=f"spatial stems: {len(voice_specs)} voices, "
                    f"{len(nomusic_cue_labels)} sfx, {len(music_specs)} music",
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
