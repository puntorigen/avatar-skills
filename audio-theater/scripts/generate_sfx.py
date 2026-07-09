#!/usr/bin/env python3
"""Generate the cued sounds listed in cues.json.

SFX backend for ambient/oneshot cues (pick with --backend, default auto):
- elevenlabs     -> ElevenLabs Sound Effects (eleven_text_to_sound_v2). Most
                    realistic foley/ambience + native seamless looping. Needs
                    an ElevenLabs API key.
- sound-effects  -> Stable Audio 2.5 via the sound-effects skill (synthesis;
                    good for abstract/UI sounds, weaker on realistic foley).
- auto           -> elevenlabs when a key is configured, else sound-effects.

Music cues (type music) are INSTRUMENTAL: hq = MiniMax Music 2.6 with
is_instrumental=true (audio_music.py; never sings), fast = the bg-music skill.

Files land in <out>/sfx/<id>.mp3 and the generated path + duration are written
back into cues.json so mix.py can place them.

Usage:
    python3 generate_sfx.py --cues audio-theater/ep/cues.json --out audio-theater/ep
    python3 generate_sfx.py --cues ... --out ... --backend elevenlabs
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import elevenlabs_sfx  # noqa: E402
import audio_music  # noqa: E402
from _common import (  # noqa: E402
    load_json, save_json, load_config, resolve_out_dir, get_audio_duration,
    get_replicate_token, get_elevenlabs_api_key,
    SOUND_EFFECTS, BG_MUSIC,
)

# ElevenLabs accepts loops up to 30s; we request a shorter seamless loop and let
# mix.py repeat it across the full ambient window.
EL_AMBIENT_LOOP_SECONDS = 22

SFX_CATEGORIES = {"ui", "notification", "success", "error", "transition", "ambient",
                  "game", "voice", "nature", "mechanical", "musical", "foley", "generic"}


def cue_needed_seconds(cue):
    start = float(cue.get("start", 0.0) or 0.0)
    end = cue.get("end")
    if end is None:
        return None
    return max(0.5, float(end) - start)


def gen_sound_effect(cue, out_file, token):
    """Generate an ambient/oneshot cue via the sound-effects skill."""
    if not SOUND_EFFECTS.exists():
        print(f"  Error: sound-effects skill not found at {SOUND_EFFECTS}", file=sys.stderr)
        return False

    is_ambient = cue.get("type") == "ambient"
    category = cue.get("category") or ("ambient" if is_ambient else "foley")
    if category not in SFX_CATEGORIES:
        category = "ambient" if is_ambient else "generic"

    needed = cue_needed_seconds(cue)
    if is_ambient:
        # Generate a loopable bed; mix.py loops/trims to the exact window.
        gen_dur = int(min(max(needed or 15, 12), 45))
    else:
        gen_dur = int(cue.get("gen_seconds", 3))
    gen_dur = max(1, min(90, gen_dur))

    cmd = [sys.executable, str(SOUND_EFFECTS), cue["description"],
           "--category", category, "--duration", str(gen_dur),
           "--output", str(out_file)]
    if is_ambient:
        cmd.append("--no-trim")
    if cue.get("seed") is not None:
        cmd.extend(["--seed", str(cue["seed"])])

    return _run(cmd, token)


def gen_elevenlabs(cue, out_file, api_key):
    """Generate an ambient/oneshot cue via ElevenLabs Sound Effects.

    Ambient cues are rendered as a seamless loop (loop=true) that mix.py repeats
    across the cue window; one-shots let the model auto-pick a natural length
    unless the cue pins gen_seconds. The raw description is sent verbatim — the
    model handles natural language well, so we don't append keyword soup.
    """
    is_ambient = cue.get("type") == "ambient"
    pi = float(cue.get("prompt_influence", 0.4))
    desc = cue.get("description", "")

    if is_ambient:
        needed = cue_needed_seconds(cue) or 15
        duration = min(max(needed, 8), EL_AMBIENT_LOOP_SECONDS)
        loop = True
    else:
        duration = cue.get("gen_seconds")  # None => model auto-length
        loop = False

    return elevenlabs_sfx.generate_sfx(
        api_key, desc, out_file,
        duration_seconds=duration, loop=loop, prompt_influence=pi,
    )


def gen_music(cue, out_file, token, default_backend="auto"):
    """Generate an INSTRUMENTAL music cue for the theater.

    Backends (per-cue `music_backend` overrides the run default):
    - hq   -> MiniMax Music 2.6 with is_instrumental=true (audio_music.py). The
              model ignores lyrics and never sings; the prompt carries the whole
              musical intent. Best for scores, beds, scene music. (default)
    - fast -> the bg-music skill (quick instrumental tracks).
    - auto -> hq when the MiniMax path is available, else fast.

    We deliberately DO NOT use bg-music-hq here: it targets music-2.5 (no
    instrumental flag) and routes structure directions through `lyrics`, which
    music-2.5 sings literally. The bed is generated un-faded; the mixer owns
    fades / ducking / spatial placement.
    """
    backend = cue.get("music_backend") or default_backend
    if backend == "auto":
        backend = "hq"
    needed = cue_needed_seconds(cue)

    if backend == "hq":
        print("    music backend: hq (MiniMax Music 2.6, instrumental)", file=sys.stderr)
        prompt = audio_music.generate(
            cue.get("description", "background music"), out_file,
            mood=cue.get("mood", "generic"),
            duration=int(needed) if needed else None,
            prompt_override=cue.get("prompt"),
            token=token,
        )
        return bool(prompt)

    # fast -> bg-music skill
    if not BG_MUSIC.exists():
        print(f"  Error: bg-music skill not found at {BG_MUSIC}", file=sys.stderr)
        return False
    print("    music backend: fast (bg-music)", file=sys.stderr)
    cmd = [sys.executable, str(BG_MUSIC), cue.get("description", "background music"),
           "--output", str(out_file), "--no-fade"]
    if cue.get("mood"):
        cmd.extend(["--mood", cue["mood"]])
    if needed:
        cmd.extend(["--duration", str(int(needed))])
    return _run(cmd, token)


def _run(cmd, token):
    env = dict(os.environ)
    if token:
        env["REPLICATE_API_TOKEN"] = token
    print(f"  $ {Path(cmd[1]).name} \"{cmd[2][:40]}\" ...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().split("\n")[-4:]
        for line in tail:
            print(f"      {line}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate cued SFX/music from cues.json")
    parser.add_argument("--cues", default=None, help="cues.json (default <out>/cues.json)")
    parser.add_argument("--out", "-o", required=True, help="Project folder")
    parser.add_argument("--only", default=None, help="Comma-separated cue ids to (re)generate")
    parser.add_argument("--backend", default=None,
                        choices=["auto", "elevenlabs", "sound-effects"],
                        help="SFX backend for ambient/oneshot cues (default: config or auto)")
    parser.add_argument("--music-backend", default=None,
                        choices=["auto", "hq", "fast"],
                        help="Music backend for type=music cues: hq=MiniMax Music 2.6 "
                             "instrumental (no sung lyrics), fast=bg-music (quicker). "
                             "Default: config or auto (hq). Per-cue `music_backend` overrides.")
    args = parser.parse_args()

    out_dir = resolve_out_dir(args.out)
    cues_path = Path(args.cues) if args.cues else out_dir / "cues.json"
    if not cues_path.exists():
        print(f"Error: {cues_path} not found. Author it first (see SKILL.md cues schema).",
              file=sys.stderr)
        sys.exit(1)

    data = load_json(cues_path)
    cues = data.get("cues", [])
    sfx_dir = out_dir / "sfx"
    sfx_dir.mkdir(parents=True, exist_ok=True)

    token = get_replicate_token(required=False)
    el_key = get_elevenlabs_api_key()
    backend = args.backend or load_config().get("default_sfx_backend", "auto")
    if backend == "auto":
        backend = "elevenlabs" if el_key else "sound-effects"
    if backend == "elevenlabs" and not el_key:
        print("  No ElevenLabs key found; falling back to sound-effects (Stable Audio).",
              file=sys.stderr)
        print("  For realistic SFX, add a key: "
              "python3 scripts/setup_key.py --elevenlabs YOUR_KEY", file=sys.stderr)
        backend = "sound-effects"
    print(f"  SFX backend: {backend}", file=sys.stderr)
    music_backend = args.music_backend or load_config().get("default_music_backend", "auto")
    only = set(s.strip() for s in args.only.split(",")) if args.only else None

    generated, failed = [], []
    for cue in cues:
        cid = cue.get("id")
        if not cid:
            continue
        if only and cid not in only:
            continue
        ctype = cue.get("type", "oneshot")
        out_file = sfx_dir / f"{cid}.mp3"

        if ctype == "music":
            ok = gen_music(cue, out_file, token, default_backend=music_backend)
        elif ctype in ("ambient", "oneshot"):
            if backend == "elevenlabs":
                ok = gen_elevenlabs(cue, out_file, el_key)
            else:
                ok = gen_sound_effect(cue, out_file, token)
        else:
            print(f"  Skipping cue '{cid}': unknown type '{ctype}'", file=sys.stderr)
            failed.append(cid)
            continue

        if ok and out_file.exists():
            dur = round(get_audio_duration(out_file), 3)
            cue["file"] = str(out_file.relative_to(out_dir))
            cue["gen_duration"] = dur
            generated.append({"id": cid, "file": cue["file"], "duration": dur})
            print(f"  ✓ {cid} -> {cue['file']} ({dur:.2f}s)", file=sys.stderr)
        else:
            failed.append(cid)
            print(f"  ✗ {cid} failed", file=sys.stderr)

    save_json(cues_path, data)
    print(json.dumps({
        "cues_json": str(cues_path),
        "sfx_dir": str(sfx_dir),
        "generated": generated,
        "failed": failed,
    }, indent=2, ensure_ascii=False))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
