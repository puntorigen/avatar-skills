#!/usr/bin/env python3
"""Turn an idea or a raw dialogue into a structured script.json (+ story.md).

Two inputs:
  --idea "..."         Let Gemini write the script from a one-line idea/brief.
  --script-file f.txt   Parse an existing dialogue ("Name: text" per line).

Usage:
    python3 write_script.py --idea "Dos marineros y una tormenta" \
        --mode theater --language es --out audio-theater/tormenta
    python3 write_script.py --script-file dialogo.txt --mode podcast \
        --language es --hosts "Lucas,Mia" --out audio-theater/ep1
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import (  # noqa: E402
    get_gemini_api_key, load_config, load_voices, save_json, slugify,
    resolve_out_dir, DEFAULT_TEXT_MODEL,
)

VALID_MODES = ("theater", "lipsync", "podcast")


def assign_voices(characters, voices_data, *, mode="theater", hosts=None):
    """Assign a Gemini voice to each character, avoiding immediate repeats."""
    pool = list(voices_data.get("auto_pool") or list(voices_data.get("voices", {}).keys()))
    valid = set(voices_data.get("voices", {}).keys())

    if mode == "podcast" and len(characters) == 2:
        ph = voices_data.get("podcast_hosts", {})
        defaults = [ph.get("host_a", "Charon"), ph.get("host_b", "Sulafat")]
        for ch, v in zip(characters, defaults):
            if not ch.get("voice"):
                ch["voice"] = v

    used = []
    for ch in characters:
        v = ch.get("voice")
        if v and v in valid:
            used.append(v)
            continue
        # pick the next pool voice not recently used
        choice = None
        for cand in pool:
            if cand not in used[-2:]:
                choice = cand
                break
        if choice is None:
            choice = pool[len(used) % len(pool)] if pool else "Charon"
        ch["voice"] = choice
        used.append(choice)
    return characters


def parse_dialogue_text(text):
    """Parse 'Name: line' style dialogue into characters + lines."""
    characters = {}
    lines = []
    order = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\s*([^:]{1,40}?)\s*:\s*(.+)$", line)
        if not m:
            # narration line with no speaker -> attribute to "Narrador"
            speaker, content = "Narrador", line
        else:
            speaker, content = m.group(1).strip(), m.group(2).strip()
        if speaker not in characters:
            characters[speaker] = {"name": speaker, "voice": None, "persona": ""}
            order.append(speaker)
        lines.append({
            "index": len(lines),
            "speaker": speaker,
            "text": content,
            "tags": [],
            "pause_after": 0.3,
        })
    return [characters[name] for name in order], lines


def build_idea_prompt(idea, mode, language, hosts):
    host_note = ""
    if mode == "podcast":
        names = hosts or "two hosts"
        host_note = (
            f"\nThis is a PODCAST with exactly two hosts ({names}). Write a natural "
            "back-and-forth conversation with a short intro and a short outro. Keep "
            "turns conversational and not too long.")
    elif mode == "lipsync":
        host_note = (
            "\nThis audio will be used as LIPSYNC reference for short animated shots. "
            "Keep every single line SHORT (one sentence, ideally under ~12 words) so "
            "each spoken clip stays well under 15 seconds.")
    else:
        host_note = (
            "\nThis is a dramatized RADIO PLAY. Use vivid, performable dialogue. You may "
            "include a Narrador character for scene-setting if helpful.")

    return f"""You are a professional scriptwriter. Write a short script in {language}.

IDEA / BRIEF: {idea}
{host_note}

Return ONLY a JSON object (no markdown, no commentary) with this exact shape:
{{
  "title": "<short title in {language}>",
  "language": "{language}",
  "characters": [
    {{"name": "<name>", "persona": "<one short line: who they are + voice quality>"}}
  ],
  "lines": [
    {{"speaker": "<character name>", "text": "<the spoken line, in {language}>", "tags": ["<optional emotion>"]}}
  ]
}}

Rules:
- 2 to 4 characters.
- "tags" are optional single-word delivery cues (e.g. "whispers", "excited", "tired", "laughs", "serious"). Use them sparingly, only where they add value. Leave [] if none.
- Do NOT put the speaker name inside "text".
- Keep the whole script tight: roughly 8-16 lines for theater/lipsync, 12-24 turns for podcast.
- Output must be valid JSON.
"""


def generate_idea_script(idea, mode, language, hosts, text_model):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=get_gemini_api_key())
    prompt = build_idea_prompt(idea, mode, language, hosts)
    print(f"  Writing script with {text_model} ...", file=sys.stderr)
    resp = client.models.generate_content(
        model=text_model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = (resp.text or "").strip()
    # Be tolerant of accidental code fences.
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            print("Error: model did not return valid JSON:\n" + raw[:500], file=sys.stderr)
            sys.exit(1)
        data = json.loads(m.group(0))
    return data


def normalize_script(data, *, mode, language):
    characters = data.get("characters") or []
    for ch in characters:
        ch.setdefault("voice", None)
        ch.setdefault("persona", "")
    lines = []
    for i, ln in enumerate(data.get("lines") or []):
        lines.append({
            "index": i,
            "speaker": ln.get("speaker", "Narrador"),
            "text": (ln.get("text") or "").strip(),
            "tags": ln.get("tags") or [],
            "pause_after": ln.get("pause_after", 0.3),
        })
    # ensure every speaker is a known character
    known = {c["name"] for c in characters}
    for ln in lines:
        if ln["speaker"] not in known:
            characters.append({"name": ln["speaker"], "voice": None, "persona": ""})
            known.add(ln["speaker"])
    return {
        "title": data.get("title") or "Untitled",
        "language": data.get("language") or language,
        "mode": mode,
        "characters": characters,
        "lines": lines,
    }


def write_story_md(script, path):
    lines = [f"# {script['title']}", ""]
    lines.append(f"_Mode: {script['mode']} · Language: {script['language']}_")
    lines.append("")
    lines.append("## Characters")
    for c in script["characters"]:
        persona = f" — {c['persona']}" if c.get("persona") else ""
        lines.append(f"- **{c['name']}** (voice: `{c.get('voice', '?')}`){persona}")
    lines.append("")
    lines.append("## Script")
    lines.append("")
    for ln in script["lines"]:
        tag = f" _[{', '.join(ln['tags'])}]_" if ln.get("tags") else ""
        lines.append(f"**{ln['speaker']}:**{tag} {ln['text']}")
        lines.append("")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Write script.json from an idea or dialogue")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--idea", help="One-line idea / brief; Gemini writes the script")
    src.add_argument("--script-file", help="Existing dialogue file ('Name: text' per line)")
    parser.add_argument("--mode", choices=VALID_MODES, default="theater")
    parser.add_argument("--language", "-l", default=None, help="Language (default from config)")
    parser.add_argument("--hosts", default=None, help="Podcast host names, comma-separated")
    parser.add_argument("--out", "-o", required=True, help="Output project folder")
    parser.add_argument("--text-model", default=None, help="Gemini text model")
    args = parser.parse_args()

    config = load_config()
    language = args.language or config.get("default_language", "es")
    text_model = args.text_model or config.get("default_text_model", DEFAULT_TEXT_MODEL)
    voices_data = load_voices()

    if args.idea:
        data = generate_idea_script(args.idea, args.mode, language, args.hosts, text_model)
        script = normalize_script(data, mode=args.mode, language=language)
    else:
        text = Path(args.script_file).read_text(encoding="utf-8")
        characters, lines = parse_dialogue_text(text)
        title = slugify(Path(args.script_file).stem).replace("-", " ").title()
        script = normalize_script(
            {"title": title, "language": language, "characters": characters, "lines": lines},
            mode=args.mode, language=language,
        )

    script["characters"] = assign_voices(
        script["characters"], voices_data, mode=args.mode,
        hosts=[h.strip() for h in args.hosts.split(",")] if args.hosts else None,
    )

    out_dir = resolve_out_dir(args.out)
    script_path = out_dir / "script.json"
    story_path = out_dir / "story.md"
    save_json(script_path, script)
    write_story_md(script, story_path)

    print(f"  Title: {script['title']}", file=sys.stderr)
    print(f"  Characters: " + ", ".join(
        f"{c['name']}({c['voice']})" for c in script["characters"]), file=sys.stderr)
    print(f"  Lines: {len(script['lines'])}", file=sys.stderr)
    print(json.dumps({
        "script": str(script_path),
        "story": str(story_path),
        "title": script["title"],
        "mode": script["mode"],
        "language": script["language"],
        "characters": [{"name": c["name"], "voice": c["voice"]} for c in script["characters"]],
        "line_count": len(script["lines"]),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
