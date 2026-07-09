#!/usr/bin/env python3
"""Shared utilities for the video-compose skill."""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"
REMOTION_DIR = SKILL_DIR / "remotion"

FORMAT_PRESETS = {
    "reel":      {"width": 1080, "height": 1920, "aspect": "9:16"},
    "post":      {"width": 1080, "height": 1080, "aspect": "1:1"},
    "landscape": {"width": 1920, "height": 1080, "aspect": "16:9"},
}

PREVIEW_SCALE = 0.5
PREVIEW_FPS = 24

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
    Path.home() / ".cursor/skills/bg-music/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
]

GEMINI_FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/asset-generator/config.json",
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/character-animations/config.json",
]

BG_MUSIC_HQ = Path.home() / ".cursor/skills/bg-music-hq/scripts/generate_bgm_hq.py"
BG_MUSIC_HQ_MOODS = Path.home() / ".cursor/skills/bg-music-hq/scripts/moods.json"


def load_config():
    """Load skill config (returns {} if missing)."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def get_replicate_token():
    """Get the Replicate API token from env, this skill's config, or a sibling skill."""
    token = os.environ.get("REPLICATE_API_TOKEN")
    if token:
        return token

    config = load_config()
    token = config.get("replicate_api_token", "")
    if token:
        return token

    for path in FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                t = cfg.get("replicate_api_token", "")
                if t:
                    return t
            except (json.JSONDecodeError, KeyError):
                continue

    print("Error: No Replicate API token configured.", file=sys.stderr)
    print(f"  python3 {SCRIPT_DIR}/setup_key.py YOUR_REPLICATE_API_TOKEN", file=sys.stderr)
    sys.exit(1)


def get_gemini_api_key():
    """Get the Gemini API key from env, this skill's config, or a sibling skill."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key

    config = load_config()
    key = config.get("gemini_api_key", "")
    if key:
        return key

    for path in GEMINI_FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                k = cfg.get("gemini_api_key", "")
                if k:
                    return k
            except (json.JSONDecodeError, KeyError):
                continue

    print("Error: No Gemini API key found.", file=sys.stderr)
    print("  Set GEMINI_API_KEY env var, or configure asset-generator first.", file=sys.stderr)
    sys.exit(1)


def get_groq_api_key():
    """Get the Groq API key (optional — used only for treatment/EDL LLM calls if Gemini is unavailable)."""
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key
    config = load_config()
    return config.get("groq_api_key", "")


def run_ffmpeg(args, *, description="", quiet=False):
    """Run an FFmpeg command. Returns True on success."""
    cmd = ["ffmpeg", "-y"] + args
    if description and not quiet:
        print(f"  FFmpeg: {description} ...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FFmpeg error (exit {result.returncode}):", file=sys.stderr)
        for line in (result.stderr or "").strip().split("\n")[-8:]:
            print(f"    {line}", file=sys.stderr)
        return False
    return True


def ffprobe_video(path):
    """Get video width/height/duration/fps via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "stream=width,height,r_frame_rate,codec_type:format=duration",
        "-of", "json", str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        info = json.loads(result.stdout)
        streams = info.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        fmt = info.get("format", {})

        fps_str = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) else 30.0
        else:
            fps = float(fps_str)

        return {
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "duration": float(fmt.get("duration", 0)),
            "fps": round(fps, 3),
        }
    except (json.JSONDecodeError, IndexError, ValueError, ZeroDivisionError):
        return {"width": 0, "height": 0, "duration": 0, "fps": 0}


def ffprobe_audio(path):
    """Get audio duration via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def download_file(url, output_path):
    """Download a file from a URL to a local path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading: {output_path.name} ...", file=sys.stderr)
    urllib.request.urlretrieve(str(url), str(output_path))
    return str(output_path)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_format_preset(fmt):
    return FORMAT_PRESETS.get(fmt, FORMAT_PRESETS["reel"])


def list_media_files(folder, *, extensions=None):
    """List all media files in a folder (recursive)."""
    folder = Path(folder)
    if not folder.exists():
        return []
    exts = extensions if extensions is not None else (VIDEO_EXTS | IMAGE_EXTS)
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def is_video(path):
    return Path(path).suffix.lower() in VIDEO_EXTS


def is_image(path):
    return Path(path).suffix.lower() in IMAGE_EXTS


def asset_signature(path):
    """Return a stable signature for cache invalidation (mtime + size)."""
    p = Path(path)
    if not p.exists():
        return ""
    st = p.stat()
    return f"{int(st.st_mtime)}-{st.st_size}"


def call_groq_chat(messages, *, model="openai/gpt-oss-120b", temperature=0.6,
                   response_format=None, max_tokens=4096):
    """Call Groq's chat completion API. Returns the assistant message string.

    NOTE: This skill's project policy mandates `openai/gpt-oss-120b` only.
    """
    import urllib.error

    api_key = get_groq_api_key()
    if not api_key:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        print(f"  Groq HTTP error {e.code}: {body[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Groq call failed: {e}", file=sys.stderr)
        return None


def call_gemini_chat(prompt, *, model="gemini-2.5-flash", system_instruction=None,
                     response_mime_type=None, temperature=0.6, image_paths=None):
    """Call Gemini API (text-in, text-out). Used as a fallback or primary LLM.

    Pass image_paths=[...] to include images in the prompt (vision models).
    Returns the response text or None.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("  Error: google-genai package not installed.", file=sys.stderr)
        return None

    api_key = get_gemini_api_key()
    client = genai.Client(api_key=api_key)

    parts = [prompt]
    if image_paths:
        for img_path in image_paths:
            img_bytes = Path(img_path).read_bytes()
            mime = "image/png" if str(img_path).lower().endswith(".png") else "image/jpeg"
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))

    cfg_kwargs = {"temperature": temperature}
    if system_instruction:
        cfg_kwargs["system_instruction"] = system_instruction
    if response_mime_type:
        cfg_kwargs["response_mime_type"] = response_mime_type

    try:
        resp = client.models.generate_content(
            model=model,
            contents=parts,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
        return resp.text
    except Exception as e:
        print(f"  Gemini call failed: {e}", file=sys.stderr)
        return None


def call_llm_json(system_prompt, user_prompt, *, image_paths=None, temperature=0.5):
    """Call an LLM with a strict JSON output requirement.

    Tries Groq (openai/gpt-oss-120b) first if a key is configured (text-only).
    Falls back to Gemini Flash for text or vision (if image_paths is given).
    Returns parsed JSON dict, or None on failure.
    """
    if image_paths:
        text = call_gemini_chat(
            user_prompt,
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=temperature,
            image_paths=image_paths,
        )
    else:
        groq_key = get_groq_api_key()
        if groq_key:
            text = call_groq_chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            if not text:
                text = call_gemini_chat(
                    user_prompt,
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=temperature,
                )
        else:
            text = call_gemini_chat(
                user_prompt,
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=temperature,
            )

    if not text:
        return None

    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  LLM returned invalid JSON: {e}", file=sys.stderr)
        print(f"  First 300 chars: {text[:300]}", file=sys.stderr)
        return None
