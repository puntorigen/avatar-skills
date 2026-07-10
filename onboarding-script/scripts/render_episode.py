#!/usr/bin/env python3
"""Render episode beat sheets into the format-agnostic onboarding script package.

For each <slug>.episode.json, writes into --out:
  <slug>.script.md        human shooting script (beats, timing, VO, on-screen/demo, captions)
  <slug>.narration.txt    clean spoken VO only (feed voice-clone / avatar-reel-composer narrate.py)
  <slug>.reel.txt         avatar-video-reel plain-text script with [DEMO: url | intent] markers
  <slug>.storyboard.json  avatar-reel-composer storyboard scaffold (scene.text tiles the narration)
and (re)writes README.md — the series index, in order.

Pure stdlib.

    python3 render_episode.py onboarding/acme/episodes/*.episode.json --out onboarding/acme/scripts/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TALKING_MOTIONS = ["zoom_center", "push_in", "pull_out"]


def is_todo(text: str) -> bool:
    t = (text or "").strip()
    return not t or t.lower().startswith("todo")


def spoken_beats(ep: dict) -> list[dict]:
    """Beats that carry a voice-over (non-empty narration)."""
    return [b for b in ep.get("beats", []) if (b.get("narration") or "").strip()]


def md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def sanitize_demo_intent(text: str) -> str:
    # avatar-video-reel parses [DEMO: url | intent]; keep | and ] out of the intent.
    return (text or "").replace("|", "/").replace("]", ")").replace("\n", " ").strip()


# ---------------------------------------------------------------- narration.txt

def render_narration(ep: dict) -> str:
    parts = [(b.get("narration") or "").strip() for b in spoken_beats(ep)]
    return "\n\n".join(parts) + "\n"


# --------------------------------------------------------------------- reel.txt

def render_reel(ep: dict) -> str:
    lines: list[str] = []
    for b in spoken_beats(ep):
        narration = (b.get("narration") or "").strip()
        if b.get("kind") == "demo":
            demo = b.get("demo") or {}
            url = (demo.get("url") or "TODO_URL").strip() or "TODO_URL"
            intent = sanitize_demo_intent(demo.get("intent") or "TODO: demo intent")
            lines.append(f"[DEMO: {url} | {intent}]")
            lines.append(narration)
            lines.append("[/DEMO]")
        else:
            lines.append(narration)
        lines.append("")  # blank line between beats
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------- storyboard.json

def render_storyboard(ep: dict) -> dict:
    scenes = []
    texts = []
    th_i = 0
    for i, b in enumerate(spoken_beats(ep), start=1):
        text = (b.get("narration") or "").strip()
        texts.append(text)
        kind = b.get("kind")
        sid = f"s{i}"
        if kind == "demo":
            demo = b.get("demo") or {}
            url = (demo.get("url") or "").strip()
            intent = (demo.get("intent") or "").strip()
            desc = intent or f"screen recording for {ep.get('title')}"
            if url:
                desc += f" (screen recording — e.g. broll-web-capture on {url})"
            scenes.append({
                "id": sid, "type": "broll", "text": text, "motion": "none",
                "broll_description": desc, "broll_camera": "push_in", "broll_action": "",
            })
        elif kind == "broll":
            scenes.append({
                "id": sid, "type": "broll", "text": text, "motion": "none",
                "broll_description": (b.get("broll") or f"B-roll for {ep.get('title')}"),
                "broll_camera": "push_in",
                "broll_action": "people/objects/UI, no presenter on camera",
            })
        else:  # talking_head
            motion = TALKING_MOTIONS[th_i % len(TALKING_MOTIONS)]
            th_i += 1
            scenes.append({
                "id": sid, "type": "talking_head", "text": text,
                "motion": motion, "angle": "eye_level",
                "emphasis": (i == 1),
            })
    return {
        "avatar_dir": "avatares/<AVATAR>",
        "slug": ep.get("slug"),
        "reference_analysis": None,
        "format": "reel",
        "resolution": "720p",
        "fps": 30,
        "voice": ep.get("voice") or {"emotion": "warm"},
        "language": ep.get("language", "en"),
        "script": " ".join(texts),
        "scenes": scenes,
        "_note": (
            "Set avatar_dir to a real avatar folder (see avatar-reel-composer). "
            "broll scenes are screen-capture/B-roll placeholders: keep the VO (text), "
            "and either refine broll_description or swap for a real screen recording "
            "(broll-web-capture / avatar-video-reel [DEMO])."
        ),
    }


# ----------------------------------------------------------------- script.md

def render_markdown(ep: dict) -> str:
    beats = ep.get("beats", []) or []
    total = sum(int(b.get("seconds", 0) or 0) for b in beats)
    lines: list[str] = []
    lines.append(f"# {ep.get('order', '?'):02d} · {ep.get('title', ep.get('slug'))}")
    lines.append("")
    lines.append(f"- **Company:** {ep.get('company_name') or ep.get('company') or '—'}"
                 f"  ·  **Audience:** {ep.get('audience', '—')}"
                 f"  ·  **Language:** {ep.get('language', '—')}")
    lines.append(f"- **Target:** {ep.get('target_seconds', '—')}s (beats sum to {total}s)")
    lines.append(f"- **Objective:** {ep.get('objective', '—')}")
    if ep.get("sources"):
        lines.append(f"- **Sources:** {', '.join(str(s) for s in ep['sources'])}")
    lines.append("")
    lines.append("| t | Beat | Kind | Spoken (VO) | On-screen / Demo | Caption |")
    lines.append("|---|------|------|-------------|------------------|---------|")
    clock = 0
    for b in beats:
        dur = int(b.get("seconds", 0) or 0)
        span = f"{clock}-{clock + dur}s"
        clock += dur
        kind = b.get("kind", "?")
        if kind == "demo":
            demo = b.get("demo") or {}
            on_screen = f"DEMO {demo.get('url', '')} — {demo.get('intent', '')}"
        elif kind == "broll":
            on_screen = f"B-ROLL: {b.get('broll', '')}"
        else:
            on_screen = b.get("on_screen", "")
        lines.append(
            f"| {span} | {b.get('id', '?')} | {kind} | {md_escape(b.get('narration', ''))} "
            f"| {md_escape(on_screen)} | {md_escape(b.get('caption', ''))} |"
        )
    lines.append("")
    lines.append("> Keep VO short and spoken (captions show one phrase at a time). "
                 "demo beats = voice-over spoken while the screen recording plays.")
    lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------- README

def render_index(episodes: list[tuple[dict, str]], company_name: str) -> str:
    lines: list[str] = []
    lines.append(f"# {company_name} — onboarding reel series")
    lines.append("")
    lines.append("Ordered onboarding video scripts. Each episode ships four files: the human "
                 "shooting script (`.script.md`), the clean narration (`.narration.txt`), an "
                 "[`avatar-video-reel`](../../../avatar-video-reel/SKILL.md) script "
                 "(`.reel.txt`, with `[DEMO]` markers) and an "
                 "[`avatar-reel-composer`](../../../avatar-reel-composer/SKILL.md) storyboard "
                 "(`.storyboard.json`).")
    lines.append("")
    for ep, stem in sorted(episodes, key=lambda x: x[0].get("order", 0)):
        secs = sum(int(b.get("seconds", 0) or 0) for b in ep.get("beats", []))
        lines.append(f"## {ep.get('order', '?'):02d}. {ep.get('title', stem)}  ·  ~{secs}s")
        if ep.get("objective"):
            lines.append("")
            lines.append(ep["objective"])
        lines.append("")
        lines.append(f"- Shooting script: [`{stem}.script.md`]({stem}.script.md)")
        lines.append(f"- Narration: [`{stem}.narration.txt`]({stem}.narration.txt)")
        lines.append(f"- avatar-video-reel: [`{stem}.reel.txt`]({stem}.reel.txt)")
        lines.append(f"- avatar-reel-composer: [`{stem}.storyboard.json`]({stem}.storyboard.json)")
        lines.append("")
    return "\n".join(lines)


def expand_inputs(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("*.episode.json")))
        elif path.exists():
            files.append(path)
        else:
            print(f"WARN  input not found: {p}", file=sys.stderr)
    # de-dup, preserve order
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f); out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Render onboarding episode beat sheets into the script package.")
    ap.add_argument("episodes", nargs="+", help="episode.json file(s) or a directory of them")
    ap.add_argument("--out", type=Path, help="Output dir (default: <episodes-parent>/../scripts or the parent)")
    ap.add_argument("--no-index", action="store_true", help="Do not (re)write README.md")
    args = ap.parse_args()

    files = expand_inputs(args.episodes)
    if not files:
        print("ERROR: no episode.json inputs found", file=sys.stderr)
        return 1

    if args.out:
        out_dir = args.out
    else:
        parent = files[0].parent
        out_dir = (parent.parent / "scripts") if parent.name == "episodes" else parent
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[tuple[dict, str]] = []
    company_name = "Company"
    for f in files:
        try:
            ep = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: could not read {f}: {exc}", file=sys.stderr)
            continue
        stem = f.name.removesuffix(".episode.json").removesuffix(".json")
        company_name = ep.get("company_name") or ep.get("company") or company_name

        (out_dir / f"{stem}.script.md").write_text(render_markdown(ep), encoding="utf-8")
        (out_dir / f"{stem}.narration.txt").write_text(render_narration(ep), encoding="utf-8")
        (out_dir / f"{stem}.reel.txt").write_text(render_reel(ep), encoding="utf-8")
        (out_dir / f"{stem}.storyboard.json").write_text(
            json.dumps(render_storyboard(ep), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  -> {out_dir}/{stem}.{{script.md,narration.txt,reel.txt,storyboard.json}}")
        rendered.append((ep, stem))

    if rendered and not args.no_index:
        (out_dir / "README.md").write_text(render_index(rendered, company_name), encoding="utf-8")
        print(f"  -> {out_dir}/README.md  ({len(rendered)} episodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
