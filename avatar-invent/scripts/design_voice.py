#!/usr/bin/env python3
"""Design an invented avatar's voice with ElevenLabs Voice Design, then clone the
resulting sample with MiniMax so the rest of the pipeline keeps working.

Why two steps:
  - ElevenLabs Voice Design (text-to-voice) invents a brand-new voice from a text
    DESCRIPTION (there is no real recording to clone -- the avatar is fictional).
  - The whole reel pipeline (avatar-reel-composer / narrate.py) speaks through a
    MiniMax voice_id. So we take the long ElevenLabs design sample and feed it to
    the voice-clone skill (MiniMax), producing the exact same
    voices/<name>.json + index.json structure every other avatar uses.

Flow:
  1. POST /v1/text-to-voice/design  (voice_description + a long sample text)
       -> a few voice previews (base64 mp3 + generated_voice_id).
  2. Save all previews; pick one (default #0) as the clean sample.
  3. voice-clone clone_voice.py <sample>  -> MiniMax voice_id in voices/.

Usage:
    python3 design_voice.py --avatar-dir nora --name nora \
        --voice-brief nora/voice_brief.json
    python3 design_voice.py --avatar-dir nora --name nora \
        --description "Warm Chilean woman, mid 30s, calm and reassuring" --language es
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _common as C  # noqa: E402

API_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_TTV_MODEL = "eleven_multilingual_ttv_v2"
DESC_MIN, DESC_MAX = 20, 1000
TEXT_MIN, TEXT_MAX = 100, 1000


def _post_json(path, body, api_key, timeout=180):
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("xi-api-key", api_key)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:600]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"ElevenLabs HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"ElevenLabs request failed: {e.reason}") from None


def design_previews(api_key, *, description, text, model_id):
    desc = description.strip()
    if len(desc) < DESC_MIN:
        desc = (desc + ". Clear, warm, conversational social-media presenter voice.")[:DESC_MAX]
    desc = desc[:DESC_MAX]

    body = {"model_id": model_id, "voice_description": desc}
    text = (text or "").strip()
    if TEXT_MIN <= len(text) <= TEXT_MAX:
        body["text"] = text
    elif len(text) > TEXT_MAX:
        body["text"] = text[:TEXT_MAX]
    else:
        body["auto_generate_text"] = True

    print(f"  ElevenLabs Voice Design: {desc[:80]}...", file=sys.stderr)
    resp = _post_json("/text-to-voice/design", body, api_key)
    previews = resp.get("previews") or []
    if not previews:
        raise RuntimeError(f"no previews returned: {json.dumps(resp)[:300]}")
    print(f"  -> {len(previews)} preview(s) generated.", file=sys.stderr)
    return previews, desc


def save_previews(previews, voices_dir, name):
    prev_dir = voices_dir / "design_previews"
    prev_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, p in enumerate(previews):
        audio = p.get("audio_base_64") or p.get("audio_base64")
        if not audio:
            continue
        fp = prev_dir / f"{name}_preview_{i}.mp3"
        fp.write_bytes(base64.b64decode(audio))
        saved.append({
            "index": i,
            "file": str(fp),
            "generated_voice_id": p.get("generated_voice_id"),
            "duration_secs": p.get("duration_secs"),
            "language": p.get("language"),
        })
        print(f"     preview {i}: {fp} ({p.get('duration_secs')}s)", file=sys.stderr)
    if not saved:
        raise RuntimeError("previews contained no audio.")
    return saved


def main():
    ap = argparse.ArgumentParser(
        description="Design an invented voice (ElevenLabs) and clone it (MiniMax).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--avatar-dir", required=True, help="Avatar folder (voices/ is written here)")
    ap.add_argument("--name", default=None, help="Voice name (default: avatar folder name)")
    ap.add_argument("--voice-brief", default=None,
                    help="voice_brief.json (voice_description/language/model_id/sample_text)")
    ap.add_argument("--description", default=None, help="Voice description (overrides the brief)")
    ap.add_argument("--language", default=None, help="Language code (es/en/...)")
    ap.add_argument("--sample-text", default=None, help="Text the designed voice speaks for the sample")
    ap.add_argument("--model-id", default=None, help=f"TTV model (default {DEFAULT_TTV_MODEL})")
    ap.add_argument("--preview-index", type=int, default=0, help="Which preview to clone")
    ap.add_argument("--no-clone", action="store_true", help="Only design + save the sample (skip MiniMax)")
    ap.add_argument("--force", action="store_true", help="Re-run even if a cloned voice already exists")
    args = ap.parse_args()

    avatar_dir = Path(args.avatar_dir).expanduser().resolve()
    name = args.name or avatar_dir.name
    voices_dir = avatar_dir / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)

    # Idempotency: if a MiniMax voice is already registered, stop (unless --force).
    index = C.try_load_json(voices_dir / "index.json") or {}
    if not args.force and isinstance(index, dict) and any(
            (v or {}).get("voice_id") for v in index.values()):
        existing = next(v["voice_id"] for v in index.values() if v.get("voice_id"))
        print(f"  voice already cloned (voice_id={existing}); use --force to redo.", file=sys.stderr)
        print(json.dumps({"voice_id": existing, "skipped": True}, ensure_ascii=False))
        return 0

    brief = C.try_load_json(args.voice_brief) if args.voice_brief else {}
    brief = brief or {}
    description = args.description or brief.get("voice_description")
    if not description:
        ap.error("no voice description (pass --description or --voice-brief).")
    language = args.language or brief.get("language") or "es"
    model_id = args.model_id or brief.get("model_id") or DEFAULT_TTV_MODEL
    sample_text = args.sample_text or brief.get("sample_text")
    if not sample_text:
        presets = C.load_presets()
        st = presets["voice"]["sample_text"]
        sample_text = st.get(language, st["en"])

    api_key = C.get_elevenlabs_api_key(required=True)

    sample_path = voices_dir / f"{name}_design_sample.mp3"
    design_record = voices_dir / f"{name}_design.json"

    if args.force or not sample_path.exists():
        previews, used_desc = design_previews(
            api_key, description=description, text=sample_text, model_id=model_id)
        saved = save_previews(previews, voices_dir, name)
        idx = max(0, min(args.preview_index, len(saved) - 1))
        chosen = saved[idx]
        sample_path.write_bytes(Path(chosen["file"]).read_bytes())
        dur = chosen.get("duration_secs")
        if isinstance(dur, (int, float)) and dur < 10:
            print(f"  ! sample is only {dur:.1f}s; MiniMax cloning wants >=10s. "
                  "Consider a longer --sample-text or another preview.", file=sys.stderr)
        C.save_json(design_record, {
            "name": name,
            "provider": "elevenlabs/voice-design",
            "model_id": model_id,
            "voice_description": used_desc,
            "language": language,
            "sample_text": sample_text,
            "chosen_preview_index": idx,
            "generated_voice_id": chosen.get("generated_voice_id"),
            "duration_secs": dur,
            "sample_file": str(sample_path),
            "previews": saved,
            "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        print(f"  design sample: {sample_path}", file=sys.stderr)
    else:
        print(f"  reusing existing design sample: {sample_path}", file=sys.stderr)

    if args.no_clone:
        print(json.dumps({"sample": str(sample_path), "design_record": str(design_record),
                          "cloned": False}, ensure_ascii=False))
        return 0

    # Bridge to MiniMax via the voice-clone skill -> voices/<name>.json + index.json.
    cmd = [C.PY, str(C.CLONE_VOICE), str(sample_path),
           "--avatar-dir", str(avatar_dir), "--name", name]
    rc, payload = C.run_child_json(cmd, desc="voice-clone: clone the designed sample (MiniMax)")
    if rc != 0:
        raise SystemExit(f"voice cloning failed (exit {rc}).")
    voice_id = (payload or {}).get("voice_id")
    print(json.dumps({
        "voice_id": voice_id,
        "el_generated_voice_id": (C.try_load_json(design_record) or {}).get("generated_voice_id"),
        "sample": str(sample_path),
        "design_record": str(design_record),
        "record": (payload or {}).get("record"),
        "cloned": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
