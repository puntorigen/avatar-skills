#!/usr/bin/env python3
"""broll-story orchestrator.

Turn a single 6-panel storyboard SHEET into a SILENT B-roll clip of an avatar
DOING an activity (no talking-head, no lip-sync). Pipeline:

  1. gpt-image-2  : authored Phase-1 storyboard prompt + avatar reference image(s)
                    -> one composite storyboard sheet for the requested ratio.
  2. seedance-2   : animate that ONE sheet into an 8s 720p video at the same ratio,
                    using the seedance baseline storyboard->movie prompt (verbatim,
                    via prompt_tools.py — NOT simplified).
  3. mute + save  : strip audio (these segments are voice-over only) and write the
                    clip + a manifest entry, drop-in for avatar-reel-composer
                    (broll_source: existing).

The agent authors the storyboard prompt FIRST (following gpt-image-2's
prompts/storyboard_framework.md, not simplified) and passes it via --prompt-file.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
GEN_IMAGE = HOME / ".cursor/skills/gpt-image-2/scripts/generate_image.py"
PROMPT_TOOLS = HOME / ".cursor/skills/seedance-2/scripts/prompt_tools.py"
# Verbatim seedance baseline (fallback if prompt_tools.py is unavailable).
SEEDANCE_BASELINE = ("Use the reference storyboard to make a full animation movie from panels. "
                     "Audio: Diegetic sound only — natural ambience, environmental foley, "
                     "and subject-driven sound.")
RATIOS = {"9:16", "16:9", "1:1", "4:3", "3:4"}


def log(msg: str) -> None:
    print(msg, flush=True)


def next_index(out_dir: Path) -> int:
    mx = 0
    for p in out_dir.glob("*.mp4"):
        m = re.match(r"(\d{3})_", p.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


def gen_sheet(prompt_file: Path, refs: list[Path], ratio: str, out_png: Path) -> Path:
    cmd = [sys.executable, str(GEN_IMAGE), "--prompt-file", str(prompt_file),
           "-ar", ratio, "-q", "high", "--moderation", "low", "-o", str(out_png)]
    for r in refs:
        cmd += ["--ref", str(r)]
    log(f"[gpt-image-2] storyboard sheet ({ratio}) ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gpt-image-2 failed:\n{r.stderr[-800:]}")
    if not out_png.exists():
        # fall back to parsing the JSON "files" list
        m = re.findall(r'"files"\s*:\s*\[\s*"([^"]+)"', r.stdout)
        if m and Path(m[0]).exists():
            Path(m[0]).replace(out_png)
    if not out_png.exists():
        raise SystemExit(f"gpt-image-2 produced no sheet at {out_png}\n{r.stdout[-400:]}")
    log(f"[gpt-image-2] sheet -> {out_png}")
    return out_png


def seedance_baseline(panels: str | None) -> str:
    if PROMPT_TOOLS.exists():
        cmd = [sys.executable, str(PROMPT_TOOLS), "storyboard"]
        if panels:
            cmd += ["--panels", panels]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    base = SEEDANCE_BASELINE
    if panels:
        base = base.replace("from panels.", f"from panels {panels}.")
    return base


def extract_url(text: str) -> str | None:
    try:
        data = json.loads(text.strip())
    except Exception:
        data = None
    found: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("result_url", "video_url", "url", "output") and isinstance(v, str) \
                        and v.startswith("http"):
                    found.append(v)
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    if data is not None:
        walk(data)
    if not found:
        found = re.findall(r"https?://[^\s\"'<>]+\.mp4[^\s\"'<>]*", text)
    return found[0] if found else None


def animate(sheet: Path, ratio: str, duration: int, resolution: str,
            panels: str | None, work: Path) -> tuple[Path, str | None]:
    prompt = seedance_baseline(panels)
    log(f"[seedance-2] prompt: {prompt}")
    cmd = ["higgsfield", "generate", "create", "seedance_2_0",
           "--prompt", prompt, "--duration", str(duration),
           "--aspect_ratio", ratio, "--resolution", resolution,
           "--image", str(sheet), "--wait", "--wait-timeout", "20m", "--json"]
    log(f"[seedance-2] animating sheet -> {duration}s {resolution} {ratio} ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    (work / "_seedance.json").write_text(r.stdout or "", encoding="utf-8")
    (work / "_seedance.err").write_text(r.stderr or "", encoding="utf-8")
    url = extract_url((r.stdout or "") + "\n" + (r.stderr or ""))
    if not url:
        raise SystemExit(f"seedance returned no result URL (rc={r.returncode}).\n"
                         f"stderr: {(r.stderr or '')[-500:]}")
    job_id = None
    m = re.search(r'"id"\s*:\s*"([0-9a-f-]{16,})"', r.stdout or "")
    if m:
        job_id = m.group(1)
    raw = work / "_raw.mp4"
    log(f"[seedance-2] downloading {url[:90]} ...")
    dl = subprocess.run(["curl", "-fsSL", "-o", str(raw), url])
    if dl.returncode != 0 or not raw.exists():
        raise SystemExit("download of seedance result failed")
    return raw, job_id


def mute(raw: Path, out: Path) -> Path:
    r = subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-an", "-c:v", "copy",
                        str(out), "-loglevel", "error"])
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-an", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(out), "-loglevel", "error"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a silent avatar action B-roll "
                                 "(storyboard sheet -> seedance animation).")
    ap.add_argument("--prompt-file", type=Path, required=True,
                    help="Authored Phase-1 storyboard prompt (6 panels), per gpt-image-2's framework")
    ap.add_argument("--avatar-ref", type=Path, action="append", required=True,
                    help="Avatar reference image (repeatable, 1-3) for character DNA")
    ap.add_argument("--ratio", default="9:16", help="9:16 (default) or 16:9")
    ap.add_argument("--slug", required=True, help="Short id for filenames")
    ap.add_argument("--avatar-dir", type=Path, default=None,
                    help="Avatar folder; output goes to <avatar-dir>/broll/story")
    ap.add_argument("--out-dir", type=Path, default=None, help="Override output dir")
    ap.add_argument("--script", default="", help="Short VO script (manifest metadata only)")
    ap.add_argument("--duration", type=int, default=8, help="Seedance duration (default 8)")
    ap.add_argument("--resolution", default="720p", help="480p/720p/1080p (default 720p)")
    ap.add_argument("--panels", default=None, help="Animate a panel range only (e.g. '1-3'); "
                    "default whole board")
    ap.add_argument("--sheet", type=Path, default=None,
                    help="Reuse an existing storyboard sheet (skip gpt-image-2)")
    ap.add_argument("--keep-audio", action="store_true", help="Do not strip audio (rare)")
    args = ap.parse_args()

    if args.ratio not in RATIOS:
        ap.error(f"--ratio must be one of {sorted(RATIOS)}")
    if not args.prompt_file.exists():
        ap.error(f"--prompt-file not found: {args.prompt_file}")
    refs = [r.expanduser().resolve() for r in args.avatar_ref]
    for r in refs:
        if not r.exists():
            ap.error(f"--avatar-ref not found: {r}")

    if args.out_dir:
        out_dir = args.out_dir
    elif args.avatar_dir:
        out_dir = args.avatar_dir / "broll" / "story"
    else:
        out_dir = Path("broll_story")
    out_dir = out_dir.expanduser().resolve()
    work = out_dir / f"_{args.slug}_work"
    work.mkdir(parents=True, exist_ok=True)

    sheet = args.sheet.expanduser().resolve() if args.sheet else None
    if sheet is None:
        sheet = gen_sheet(args.prompt_file, refs, args.ratio, work / f"{args.slug}_board.png")

    raw, job_id = animate(sheet, args.ratio, args.duration, args.resolution, args.panels, work)

    idx = next_index(out_dir)
    clip = out_dir / f"{idx:03d}_{args.slug}.mp4"
    if args.keep_audio:
        raw.replace(clip)
    else:
        mute(raw, clip)
    sheet_final = out_dir / f"{idx:03d}_{args.slug}_board.png"
    if sheet.exists() and sheet.resolve() != sheet_final.resolve():
        try:
            sheet_final.write_bytes(sheet.read_bytes())
        except Exception:
            sheet_final = sheet

    manifest = out_dir / "manifest.json"
    entries = []
    if manifest.exists():
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8")).get("clips", [])
        except Exception:
            entries = []
    entry = {
        "id": f"{idx:03d}_{args.slug}",
        "slug": args.slug,
        "clip": str(clip),
        "sheet": str(sheet_final),
        "ratio": args.ratio,
        "duration": args.duration,
        "resolution": args.resolution,
        "panels": args.panels or "all",
        "silent": not args.keep_audio,
        "source": "broll-story",
        "seedance_job_id": job_id,
        "script": args.script,
        "prompt_file": str(args.prompt_file),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    entries.append(entry)
    manifest.write_text(json.dumps({"clips": entries}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    log(f"[done] clip -> {clip}")
    print(json.dumps({"clip": str(clip), "sheet": str(sheet_final), "ratio": args.ratio,
                      "duration": args.duration, "silent": entry["silent"],
                      "seedance_job_id": job_id, "manifest": str(manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
