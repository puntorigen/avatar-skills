#!/usr/bin/env python3
"""Build a deterministic, human-feeling *IDE agent-chat* timeline from a session spec.

This is the `broll-cursor` counterpart of `broll-terminal`'s `timeline.py`: instead
of a shell (typed commands + streamed stdout) it models a **Cursor-style agent chat**
— the user types a prompt into the composer with human keystroke jitter, sends it,
and an assistant turn streams in token-by-token with **tool-call rows** (skills) that
spin then resolve with a checkmark.

Like the terminal skill, everything carries absolute-ms timing so the renderer's
`seekTo(t)` is a pure function of time (reproducible, frame-exact), and NOTHING is
ever executed — the "agent" only says/does whatever the session JSON declares.

session.json schema (all timing in ms; everything but `steps` is optional):

    {
      "theme": "cursor-dark",             # cursor-dark | cursor-light
      "title": "Cursor — avatar-skills",  # window title-bar text
      "kicker": "one prompt → one reel",  # small uppercase label above the window
      "model": "claude-4.6-sonnet",       # model pill in the chat header
      "agent_name": "Agent",              # header label
      "font_size": 21,                    # base chat font (logical px)
      "placeholder": "Plan, search, build anything…",  # composer placeholder
      "typing": {"min_ms":34,"max_ms":92,"space_extra_ms":40,"punct_extra_ms":28,
                 "pre_type_ms":180,"submit_pause_ms":260,"typo_chance":0.10},
      "assistant": {"cps":55,"latency_ms":320,"line_gap_ms":260,"tool_gap_ms":170,
                    "spinner_period_ms":90},
      "tail_ms": 1000,
      "steps": [
        {"user": "invent a Sherlock-style detective host for an avatar-skills demo"},
        {"say": "On it — here's the plan."},
        {"tool":"avatar-invent","detail":"inventing the face + voice",
         "duration_ms":1600,"done":"hero + 5 angles"},
        {"say": "Done. Your detective is live."}
      ]
    }

Assistant `say` lines accept inline color/style markup ({g} green, {r} red, {y}
yellow, {b} blue, {c} cyan, {m} magenta, {w} white, {dim} dim, {bold} bold, closed
with {/}); the user prompt is plain (typed like real text). Tool `name`/`done`/`detail`
are plain-escaped.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import random
import re
import sys
from pathlib import Path

_TAGS = {"g": "c-g", "r": "c-r", "y": "c-y", "b": "c-b", "c": "c-c",
         "m": "c-m", "w": "c-w", "dim": "dim", "bold": "bold"}

TYPING_DEFAULTS = {
    "min_ms": 34, "max_ms": 92, "space_extra_ms": 40, "punct_extra_ms": 28,
    "pre_type_ms": 180, "submit_pause_ms": 260, "typo_chance": 0.10,
}
ASSISTANT_DEFAULTS = {
    "cps": 55, "latency_ms": 320, "line_gap_ms": 260, "tool_gap_ms": 170,
    "spinner_period_ms": 90,
}
THEMES = {"cursor-dark", "cursor-light"}
_TYPO_KEYS = "asdfghjklqwertyuiop"
_PUNCT = set(",.;:/_-=\"'")


def conv(s: str) -> str:
    """Escape HTML then expand inline {tag}…{/} markup into <span> classes."""
    s = _html.escape(str(s))

    def _open(m: re.Match) -> str:
        cls = _TAGS.get(m.group(1))
        return f'<span class="{cls}">' if cls else m.group(0)

    s = re.sub(r"\{(\w+)\}", _open, s)
    return s.replace("{/}", "</span>")


def _gen_keys(text: str, t: float, cfg: dict, rng: random.Random):
    """Return (keys, t_end). Keys are {t, ch} or {t, bs:true} (a backspace).

    Same human-typing model as broll-terminal: jittered per-key delay, a touch
    more on spaces/punctuation, and an occasional stumble (wrong char + backspace).
    """
    keys: list[dict] = []
    n = len(text)
    stumble_at = None
    if cfg["typo_chance"] > 0 and n >= 10 and rng.random() < cfg["typo_chance"]:
        stumble_at = rng.randint(4, n - 3)
    for i, ch in enumerate(text):
        dt = rng.uniform(cfg["min_ms"], cfg["max_ms"])
        if ch == " ":
            dt += cfg["space_extra_ms"]
        elif ch in _PUNCT:
            dt += cfg["punct_extra_ms"]
        t += dt
        keys.append({"t": round(t), "ch": ch})
        if stumble_at is not None and i == stumble_at:
            wrongs = rng.randint(1, 2)
            for _ in range(wrongs):
                t += rng.uniform(cfg["min_ms"], cfg["max_ms"])
                keys.append({"t": round(t), "ch": rng.choice(_TYPO_KEYS)})
            t += rng.uniform(180, 320)          # notice the mistake
            for _ in range(wrongs):
                t += rng.uniform(60, 120)
                keys.append({"t": round(t), "bs": True})
            t += rng.uniform(70, 170)           # resume
    return keys, t


def build_timeline(session: dict, seed: int = 7) -> dict:
    rng = random.Random(seed)
    cfg = {**TYPING_DEFAULTS, **(session.get("typing") or {})}
    acfg = {**ASSISTANT_DEFAULTS, **(session.get("assistant") or {})}
    theme = session.get("theme", "cursor-dark")
    if theme not in THEMES:
        theme = "cursor-dark"
    ms_per_char = 1000.0 / max(1.0, float(acfg["cps"]))

    events: list[dict] = []
    t = 0.0
    for step in session.get("steps", []):
        if "user" in step:
            start = round(t)
            t += step.get("pre_type_ms", cfg["pre_type_ms"])
            keys, t = _gen_keys(str(step["user"]), t, cfg, rng)
            t += step.get("submit_pause_ms", cfg["submit_pause_ms"])
            events.append({"kind": "user", "keys": keys, "start": start,
                           "submitT": round(t),
                           "textHtml": _html.escape(str(step["user"]))})
            t += 120  # brief beat before the assistant starts responding
        elif "say" in step:
            t += step.get("latency_ms", acfg["latency_ms"])
            text = str(step["say"])
            t0 = round(t)
            t += max(1, len(text)) * ms_per_char
            events.append({"kind": "say", "t0": t0, "t1": round(t),
                           "text": text, "msPerChar": ms_per_char})
            t += step.get("line_gap_ms", acfg["line_gap_ms"])
        elif "tool" in step:
            t += step.get("tool_gap_ms", acfg["tool_gap_ms"])
            t_start = round(t)
            t += step.get("duration_ms", 1400)
            events.append({"kind": "tool", "tStart": t_start, "tEnd": round(t),
                           "name": _html.escape(str(step["tool"])),
                           "detail": _html.escape(str(step.get("detail", ""))),
                           "done": _html.escape(str(step.get("done", "done"))),
                           "periodMs": step.get("period_ms", acfg["spinner_period_ms"])})
            t += step.get("line_gap_ms", acfg["line_gap_ms"])
        elif "sleep_ms" in step:
            t += step["sleep_ms"]

    t += session.get("tail_ms", 1000)

    return {
        "events": events,
        "durationMs": round(t),
        "theme": theme,
        "title": session.get("title", ""),
        "kicker": session.get("kicker", ""),
        "model": session.get("model", ""),
        "agentName": session.get("agent_name", "Agent"),
        "placeholder": session.get("placeholder", "Plan, search, build anything…"),
        "fontSize": session.get("font_size", 21),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a Cursor agent-chat timeline from a session JSON.")
    ap.add_argument("session", type=Path)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    session = json.loads(args.session.read_text(encoding="utf-8"))
    tl = build_timeline(session, seed=args.seed)
    print(json.dumps(tl, ensure_ascii=False, indent=2))
    print(f"[timeline] {len(tl['events'])} events, {tl['durationMs']/1000:.2f}s",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
