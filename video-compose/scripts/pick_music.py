#!/usr/bin/env python3
"""Music selection + generation + BPM/beat extraction.

Three subcommands:

    suggest    Propose 3 mood options for a treatment. Returns JSON with
               {moods: [{id, label, description, bpm_range}], default}.
               Pure Python — no API calls.

    generate   Generate a music track via bg-music-hq and analyze it with
               librosa. Returns JSON with {music_path, meta_path}.
               meta_path contains BPM, beat_times, structure tags.

    analyze    Analyze an existing audio file with librosa only (no generation).
               Useful when the user provides their own track.

Usage:
    python3 pick_music.py suggest --treatment treatment.yaml

    python3 pick_music.py generate --treatment treatment.yaml \
        --mood pet-heartfelt --output bgm.mp3 --meta-output bgm_meta.json

    python3 pick_music.py analyze --input bgm.mp3 -o bgm_meta.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import BG_MUSIC_HQ, BG_MUSIC_HQ_MOODS, ffprobe_audio, save_json

MOOD_PRESETS = [
    {
        "id": "pet-heartfelt",
        "label": "Heartfelt",
        "description": "Warm acoustic, emotional, slow",
        "bpm_range": (70, 90),
        "tone_keywords": ("emotional", "heartfelt", "warm", "tender", "memorial",
                          "adoption", "bond", "intimate"),
    },
    {
        "id": "pet-daily",
        "label": "Daily Life",
        "description": "Easygoing warm, relatable, mid-tempo",
        "bpm_range": (95, 110),
        "tone_keywords": ("daily", "routine", "easygoing", "wholesome",
                          "homely", "lifestyle", "relatable"),
    },
    {
        "id": "pet-playful",
        "label": "Playful",
        "description": "Bouncy, quirky, cheerful",
        "bpm_range": (120, 140),
        "tone_keywords": ("playful", "bouncy", "fun", "silly", "cheerful",
                          "zoomies", "energetic", "puppy"),
    },
    {
        "id": "pet-adventure",
        "label": "Adventure",
        "description": "Driving, sunny, outdoorsy",
        "bpm_range": (115, 135),
        "tone_keywords": ("adventure", "outdoor", "hike", "beach", "travel",
                          "road trip", "explore", "journey"),
    },
    {
        "id": "pet-epic",
        "label": "Epic",
        "description": "Cinematic, heroic, triumphant",
        "bpm_range": (90, 115),
        "tone_keywords": ("epic", "cinematic", "heroic", "triumphant",
                          "showcase", "slow-mo", "champion"),
    },
    {
        "id": "pet-chill",
        "label": "Chill",
        "description": "Lo-fi, cozy, dreamy",
        "bpm_range": (65, 80),
        "tone_keywords": ("chill", "lazy", "cozy", "lo-fi", "nap", "dreamy",
                          "cuddly", "sleepy", "afternoon"),
    },
    {
        "id": "pet-trendy",
        "label": "Trendy",
        "description": "Hook-first, modern, viral-friendly",
        "bpm_range": (110, 130),
        "tone_keywords": ("trendy", "viral", "modern", "tiktok", "hook",
                          "catchy", "instagram"),
    },
    {
        "id": "pet-transformation",
        "label": "Transformation",
        "description": "Tension build with impactful reveal",
        "bpm_range": (90, 110),
        "tone_keywords": ("transformation", "glow up", "before after",
                          "reveal", "rescue", "journey"),
    },
    {
        "id": "pet-lullaby",
        "label": "Lullaby",
        "description": "Music box, delicate, hushed",
        "bpm_range": (50, 65),
        "tone_keywords": ("lullaby", "bedtime", "asmr", "sleep", "soft",
                          "delicate", "tender"),
    },
    {
        "id": "pet-regal",
        "label": "Regal",
        "description": "Elegant, sophisticated, classical",
        "bpm_range": (80, 100),
        "tone_keywords": ("regal", "elegant", "majestic", "sophisticated",
                          "classy", "show", "glamour"),
    },
    {
        "id": "pet-goofy",
        "label": "Goofy",
        "description": "Comical, cartoon-like, quirky",
        "bpm_range": (125, 150),
        "tone_keywords": ("goofy", "derp", "fail", "comical", "cartoon",
                          "meme", "silly"),
    },
    {
        "id": "cinematic",
        "label": "Cinematic",
        "description": "Epic, orchestral, powerful",
        "bpm_range": (80, 100),
        "tone_keywords": ("trailer", "dramatic", "orchestral", "powerful",
                          "epic"),
    },
    {
        "id": "uplifting",
        "label": "Uplifting",
        "description": "Bright, optimistic, joyful",
        "bpm_range": (110, 130),
        "tone_keywords": ("uplifting", "celebration", "success", "joyful",
                          "optimistic", "bright"),
    },
    {
        "id": "lofi",
        "label": "Lofi",
        "description": "Chill, vinyl warmth, relaxed",
        "bpm_range": (70, 85),
        "tone_keywords": ("lofi", "study", "casual", "vinyl", "relaxed",
                          "chill"),
    },
]


def score_mood_for_treatment(mood, treatment_text):
    """Score how well a mood matches a treatment (lowercase keyword matches)."""
    text = treatment_text.lower()
    return sum(1 for kw in mood["tone_keywords"] if kw in text)


def suggest_moods(treatment, n=3):
    """Pick the top-N moods that match a treatment's goal+tone+shots."""
    text_parts = [
        treatment.get("goal", ""),
        treatment.get("tone", ""),
    ]
    for shot in treatment.get("shots", []):
        text_parts.append(shot.get("description", ""))
        title = shot.get("title")
        if title:
            text_parts.append(title.get("text", ""))

    text = " ".join(p for p in text_parts if p)

    scored = [(m, score_mood_for_treatment(m, text)) for m in MOOD_PRESETS]
    scored.sort(key=lambda x: (-x[1], x[0]["id"]))

    top = scored[:n]
    if all(s == 0 for _, s in top):
        defaults = ["pet-daily", "pet-heartfelt", "pet-playful"]
        top = [(next(m for m in MOOD_PRESETS if m["id"] == mid), 0) for mid in defaults]

    return [
        {
            "id": m["id"],
            "label": m["label"],
            "description": m["description"],
            "bpm_range": list(m["bpm_range"]),
            "score": s,
        }
        for m, s in top
    ]


def yaml_load(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        print("Error: PyYAML not installed.", file=sys.stderr)
        sys.exit(1)


def cmd_suggest(args):
    treatment = yaml_load(args.treatment)
    moods = suggest_moods(treatment, n=args.n)
    print(json.dumps({"moods": moods, "default": moods[0]["id"] if moods else None}, indent=2))


def call_bg_music_hq(*, prompt, mood, duration, output, format_="mp3"):
    """Spawn the bg-music-hq generator and return its JSON output."""
    if not BG_MUSIC_HQ.exists():
        print(f"Error: bg-music-hq script not found at {BG_MUSIC_HQ}", file=sys.stderr)
        sys.exit(1)

    cmd = [
        sys.executable, str(BG_MUSIC_HQ),
        prompt,
        "--mood", mood,
        "--duration", str(duration),
        "--format", format_,
        "--output", str(output),
    ]
    print(f"  Generating BGM via bg-music-hq (mood={mood}, duration={duration}s)...",
          file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            print(f"    {line}", file=sys.stderr)

    if result.returncode != 0:
        print(f"  Error: bg-music-hq exited with code {result.returncode}", file=sys.stderr)
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("  Warning: bg-music-hq output not JSON; returning raw path", file=sys.stderr)
        return {"file": str(output)}


def analyze_audio(audio_path):
    """Analyze an audio file with librosa: BPM, beats, RMS energy curve."""
    try:
        import librosa
        import numpy as np
    except ImportError:
        print("  Warning: librosa not installed; skipping beat analysis", file=sys.stderr)
        return {
            "bpm": None,
            "beat_times": [],
            "duration": ffprobe_audio(audio_path),
            "structure": [],
            "energy_curve": [],
        }

    y, sr = librosa.load(str(audio_path), mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    beat_times = [round(float(t), 4) for t in beat_times]

    if isinstance(tempo, (np.ndarray,)):
        bpm = float(tempo.flatten()[0]) if tempo.size else 0.0
    else:
        bpm = float(tempo)

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    if len(rms) > 0:
        rms_norm = (rms - rms.min()) / max(1e-9, (rms.max() - rms.min()))
        if len(rms_norm) > 64:
            stride = len(rms_norm) // 64
            energy_curve = [round(float(rms_norm[i * stride]), 3) for i in range(64)]
        else:
            energy_curve = [round(float(v), 3) for v in rms_norm]
    else:
        energy_curve = []

    structure = infer_structure(energy_curve, duration)

    return {
        "bpm": round(bpm, 2),
        "beat_times": beat_times,
        "duration": round(duration, 3),
        "structure": structure,
        "energy_curve": energy_curve,
    }


def infer_structure(energy_curve, duration):
    """Infer rough song-structure tags from the energy envelope."""
    if not energy_curve or duration <= 0:
        return []

    n = len(energy_curve)
    if n < 4:
        return [{"tag": "Inst", "start": 0.0}]

    third = n // 3
    avg_first = sum(energy_curve[:third]) / max(1, third)
    avg_mid = sum(energy_curve[third:2 * third]) / max(1, third)
    avg_last = sum(energy_curve[2 * third:]) / max(1, n - 2 * third)

    structure = [{"tag": "Intro", "start": 0.0}]
    if avg_mid > avg_first * 1.15:
        structure.append({"tag": "Build Up", "start": round(duration * 0.33, 2)})
    if avg_last < avg_mid * 0.85:
        structure.append({"tag": "Outro", "start": round(duration * 0.85, 2)})
    elif avg_last > avg_mid * 1.10:
        structure.append({"tag": "Drop", "start": round(duration * 0.66, 2)})

    return structure


def build_prompt_for_mood(mood_id, treatment):
    """Build a richer prompt for bg-music-hq based on the mood and treatment."""
    goal = treatment.get("goal", "")
    tone = treatment.get("tone", "")
    base = next((m for m in MOOD_PRESETS if m["id"] == mood_id), None)
    if base:
        return f"{base['description']} background music for {goal}. Tone: {tone}".strip(". ")
    return f"Background music for {goal}. Tone: {tone}".strip(". ")


def cmd_generate(args):
    treatment = yaml_load(args.treatment)
    target_duration = float(treatment.get("target_duration", 30))

    bgm_duration = max(int(round(target_duration + 5)), 20)

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = Path(args.meta_output).resolve() if args.meta_output else \
        output_path.with_suffix(".meta.json")

    if not output_path.exists() or args.force:
        prompt = args.prompt or build_prompt_for_mood(args.mood, treatment)
        result = call_bg_music_hq(
            prompt=prompt, mood=args.mood, duration=bgm_duration,
            output=output_path, format_="mp3",
        )
        if not result:
            sys.exit(2)

    meta = analyze_audio(output_path)
    meta["mood"] = args.mood
    meta["source"] = str(output_path)

    save_json(meta_path, meta)

    print(json.dumps({
        "music_path": str(output_path),
        "meta_path": str(meta_path),
        "bpm": meta.get("bpm"),
        "duration": meta.get("duration"),
        "n_beats": len(meta.get("beat_times", [])),
        "structure": meta.get("structure", []),
    }, indent=2))


def cmd_analyze(args):
    audio_path = Path(args.input).resolve()
    if not audio_path.exists():
        print(f"Error: audio file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    meta = analyze_audio(audio_path)
    meta["source"] = str(audio_path)
    meta["mood"] = args.mood

    output_path = Path(args.output).resolve() if args.output else \
        audio_path.with_suffix(".meta.json")

    save_json(output_path, meta)

    print(json.dumps({
        "music_path": str(audio_path),
        "meta_path": str(output_path),
        "bpm": meta.get("bpm"),
        "duration": meta.get("duration"),
        "n_beats": len(meta.get("beat_times", [])),
        "structure": meta.get("structure", []),
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Music selection + generation + BPM analysis")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sug = sub.add_parser("suggest", help="Suggest moods for a treatment")
    p_sug.add_argument("--treatment", required=True)
    p_sug.add_argument("-n", type=int, default=3)
    p_sug.set_defaults(func=cmd_suggest)

    p_gen = sub.add_parser("generate", help="Generate music + analyze")
    p_gen.add_argument("--treatment", required=True)
    p_gen.add_argument("--mood", required=True, help="Mood id (e.g. pet-heartfelt)")
    p_gen.add_argument("--prompt", default=None, help="Override the prompt sent to bg-music-hq")
    p_gen.add_argument("-o", "--output", required=True, help="Output bgm.mp3 path")
    p_gen.add_argument("--meta-output", default=None, help="Output bgm_meta.json path")
    p_gen.add_argument("--force", action="store_true", help="Re-generate even if output exists")
    p_gen.set_defaults(func=cmd_generate)

    p_an = sub.add_parser("analyze", help="Analyze an existing audio file")
    p_an.add_argument("--input", required=True)
    p_an.add_argument("-o", "--output", default=None)
    p_an.add_argument("--mood", default="user-provided")
    p_an.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
