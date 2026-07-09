#!/usr/bin/env python3
"""Build a deterministic, human-feeling terminal timeline from a session spec.

The realism of a fake terminal lives here (not in CSS): a seeded RNG gives every
keystroke a jittered delay, spaces/punctuation pause a touch longer, an
occasional command "stumbles" (a wrong char + backspace correction), and output
streams in line-by-line after a believable latency instead of dumping at once.

The terminal is modelled as an ordered list of `lines`; each carries absolute-ms
timing so the renderer's `seekTo(t)` is a pure function of time (reproducible,
frame-exact). Commands are replayed as keystrokes (supporting backspace), so the
visible text is reconstructed by replaying keys with `t <= now` — not a naive
prefix — which is what makes typo-corrections possible.

session.json schema (all timing in ms; everything but `steps` is optional):

    {
      "theme": "warp-dark",            # warp-dark | one-dark | mono-light
      "font": "JetBrains Mono",        # falls back to Menlo (always on macOS)
      "font_size": 19,                 # logical px (in the W/scale capture space)
      "title": "zsh — virtual-avatar", # window title-bar text
      "prompt": "{g}\u279c{/} {c}~/proj{/} {m}git:(main){/} ",  # markup; or:
      "cwd": "~/code/virtual-avatar", "branch": "main",          # auto-built prompt
      "typing": {"min_ms":42,"max_ms":120,"space_extra_ms":60,
                 "punct_extra_ms":45,"pre_type_ms":220,"submit_pause_ms":320,
                 "typo_chance":0.10},
      "output": {"latency_ms":420, "stream_ms":170, "spinner_period_ms":90},
      "tail_ms": 1100,
      "steps": [
        {"cmd": "python3 make_reel.py --script hook.md"},
        {"out": ["{dim}\u25b8 discovering…{/}", "{g}\u2713{/} 12 ranked"], "stream_ms": 300},
        {"spinner": "rendering avatar", "duration_ms": 1600, "done": "{g}\u2713{/} avatar ready"},
        {"sleep_ms": 400},
        {"cmd": "ls reels/"},
        {"out": "001_hook.mp4  002_proof.mp4  003_cta.mp4"}
      ]
    }

Inline color/style markup (for prompt + output, NOT commands): {g}=green {r}=red
{y}=yellow {b}=blue {c}=cyan {m}=magenta {w}=white {dim}=dim {bold}=bold, closed
with {/}. Commands are plain text (monochrome, like real typing).
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
    "min_ms": 42, "max_ms": 120, "space_extra_ms": 60, "punct_extra_ms": 45,
    "pre_type_ms": 220, "submit_pause_ms": 320, "typo_chance": 0.10,
}
OUTPUT_DEFAULTS = {"latency_ms": 420, "stream_ms": 170, "spinner_period_ms": 90}
THEMES = {"warp-dark", "one-dark", "mono-light"}
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


def _prompt_html(session: dict) -> str:
    if session.get("prompt"):
        return conv(session["prompt"])
    cwd = session.get("cwd", "~")
    branch = session.get("branch", "main")
    return (f'<span class="c-g">\u279c</span> '
            f'<span class="c-c">{_html.escape(cwd)}</span> '
            f'<span class="c-m">git:({_html.escape(branch)})</span> ')


def _gen_keys(cmd: str, t: float, cfg: dict, rng: random.Random):
    """Return (keys, t_end). Keys are {t, ch} or {t, bs:true} (a backspace)."""
    keys: list[dict] = []
    n = len(cmd)
    stumble_at = None
    if cfg["typo_chance"] > 0 and n >= 10 and rng.random() < cfg["typo_chance"]:
        stumble_at = rng.randint(4, n - 3)
    for i, ch in enumerate(cmd):
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
    ocfg = {**OUTPUT_DEFAULTS, **(session.get("output") or {})}
    prompt_html = _prompt_html(session)
    theme = session.get("theme", "warp-dark")
    if theme not in THEMES:
        theme = "warp-dark"

    lines: list[dict] = []
    t = 0.0
    for step in session.get("steps", []):
        if "cmd" in step:
            start = round(t)
            t += step.get("pre_type_ms", cfg["pre_type_ms"])
            keys, t = _gen_keys(str(step["cmd"]), t, cfg, rng)
            t += step.get("submit_pause_ms", cfg["submit_pause_ms"])
            lines.append({"kind": "cmd", "prompt": prompt_html, "keys": keys,
                          "start": start, "submitT": round(t)})
        elif "out" in step:
            t += step.get("latency_ms", ocfg["latency_ms"])
            outs = step["out"] if isinstance(step["out"], list) else [step["out"]]
            stream = step.get("stream_ms", ocfg["stream_ms"])
            for ln in outs:
                lines.append({"kind": "out", "html": conv(ln), "t": round(t)})
                t += stream
        elif "spinner" in step:
            t += step.get("latency_ms", ocfg["latency_ms"])
            t_start = round(t)
            t += step.get("duration_ms", 1500)
            lines.append({"kind": "spin", "labelHtml": conv(step["spinner"]),
                          "tStart": t_start, "tEnd": round(t),
                          "doneHtml": conv(step.get("done", "{g}\u2713{/} done")),
                          "periodMs": step.get("period_ms", ocfg["spinner_period_ms"])})
            t += ocfg["stream_ms"]
        elif "sleep_ms" in step:
            t += step["sleep_ms"]

    # Trailing ready prompt: a fresh, empty prompt with a blinking cursor so the
    # clip ends on a calm "ready" beat instead of mid-output.
    t += 180
    lines.append({"kind": "cmd", "prompt": prompt_html, "keys": [],
                  "start": round(t), "submitT": 10 ** 12})
    t += session.get("tail_ms", 1100)

    return {
        "lines": lines,
        "durationMs": round(t),
        "theme": theme,
        "font": session.get("font", "JetBrains Mono"),
        "fontSize": session.get("font_size", 19),
        "title": session.get("title", ""),
        "kicker": session.get("kicker", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a terminal timeline from a session JSON.")
    ap.add_argument("session", type=Path)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    session = json.loads(args.session.read_text(encoding="utf-8"))
    tl = build_timeline(session, seed=args.seed)
    print(json.dumps(tl, ensure_ascii=False, indent=2))
    print(f"[timeline] {len(tl['lines'])} lines, {tl['durationMs']/1000:.2f}s",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
