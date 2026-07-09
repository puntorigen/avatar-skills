#!/usr/bin/env python3
"""Render title overlays from timeline.json via the Remotion CLI.

Each title in timeline.tracks.titles[] is rendered as an independent ProRes 4444
MOV with native alpha transparency. Titles are rendered in parallel (3 workers
by default) for speed. Output is one .mov per title at the timeline's full
resolution + fps.

ProRes 4444 was chosen over VP9/VP8 WebM because:
  - Renders ~10-50x faster than VP8
  - VP9 with --pixel-format=yuva420p sometimes silently drops alpha
  - ProRes 4444 has rock-solid alpha support
  - FFmpeg's overlay filter handles ProRes alpha natively

Usage:
    python3 render_titles.py --timeline timeline.json --titles-dir titles/
    python3 render_titles.py --timeline timeline.json --titles-dir titles/ --workers 4
    python3 render_titles.py --timeline timeline.json --titles-dir titles/ --force
"""

import argparse
import concurrent.futures
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from _common import REMOTION_DIR, load_json

TITLE_COMPOSITION_ID = "TitleOverlay"
DEFAULT_WORKERS = 3
DEFAULT_ACCENT_COLOR = "#FFD166"
DEFAULT_TEXT_COLOR = "#FFFFFF"
DEFAULT_FONT = "Inter"


def find_remotion_cli():
    """Locate the Remotion CLI binary."""
    binary = REMOTION_DIR / "node_modules" / ".bin" / "remotion"
    if binary.exists():
        return str(binary)
    npx = shutil.which("npx")
    if not npx:
        print("Error: neither Remotion CLI nor npx found.", file=sys.stderr)
        print(f"  Run: cd {REMOTION_DIR} && npm install", file=sys.stderr)
        sys.exit(1)
    return None


def render_one_title(*, title, output_path, width, height, fps, accent_color,
                     text_color, font_family):
    """Render a single title to a ProRes 4444 MOV with alpha. Returns (ok, elapsed_s)."""
    dur_ms = max(200, int(round((title["out_at"] - title["in_at"]) * 1000)))

    props = {
        "text": title["text"],
        "style": title["style"],
        "durMs": dur_ms,
        "width": width,
        "height": height,
        "fps": fps,
        "accentColor": accent_color,
        "textColor": text_color,
        "fontFamily": font_family,
    }
    extra = title.get("props") or {}
    if isinstance(extra, dict):
        if extra.get("subtitle"):
            props["subtitle"] = extra["subtitle"]
        if extra.get("accentColor"):
            props["accentColor"] = extra["accentColor"]

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    binary = find_remotion_cli()
    if binary is None:
        cmd = ["npx", "remotion", "render"]
    else:
        cmd = [binary, "render"]

    cmd += [
        TITLE_COMPOSITION_ID,
        str(output_path),
        f"--props={json.dumps(props)}",
        "--codec=prores",
        "--prores-profile=4444",
        "--pixel-format=yuva444p10le",
        "--image-format=png",
        "--concurrency=2",
        "--log=error",
    ]

    start = time.time()
    result = subprocess.run(
        cmd,
        cwd=str(REMOTION_DIR),
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"  Title render failed for {title.get('id', '?')}:", file=sys.stderr)
        for line in (result.stderr or "").strip().split("\n")[-10:]:
            print(f"    {line}", file=sys.stderr)
        return False, elapsed

    return output_path.exists(), elapsed


def main():
    parser = argparse.ArgumentParser(description="Render Remotion title overlays from timeline.json")
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--titles-dir", required=True)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--accent-color", default=DEFAULT_ACCENT_COLOR)
    parser.add_argument("--text-color", default=DEFAULT_TEXT_COLOR)
    parser.add_argument("--font", default=DEFAULT_FONT)
    parser.add_argument("--force", action="store_true",
                        help="Re-render titles even if they exist")
    args = parser.parse_args()

    timeline = load_json(args.timeline)
    titles = timeline.get("tracks", {}).get("titles", []) or []
    if not titles:
        print("No titles to render.", file=sys.stderr)
        print(json.dumps({"rendered": 0, "skipped": 0, "titles_dir": args.titles_dir}))
        return

    width = int(timeline.get("width", 1080))
    height = int(timeline.get("height", 1920))
    fps = int(timeline.get("fps", 30))

    titles_dir = Path(args.titles_dir).resolve()
    titles_dir.mkdir(parents=True, exist_ok=True)

    print(f"Rendering {len(titles)} title(s) at {width}x{height}@{fps}fps "
          f"with {args.workers} workers ...", file=sys.stderr)

    pending = []
    skipped = 0
    for i, title in enumerate(titles):
        title_id = title.get("id") or f"t{i+1}"
        out_path = titles_dir / f"{title_id}.mov"
        if out_path.exists() and not args.force:
            skipped += 1
            title["_output"] = str(out_path)
            continue
        title["_output"] = str(out_path)
        pending.append((i, title, out_path))

    if not pending:
        print(f"All {len(titles)} titles already rendered (use --force to re-render).",
              file=sys.stderr)
        print(json.dumps({
            "rendered": 0,
            "skipped": skipped,
            "titles_dir": str(titles_dir),
            "outputs": [t.get("_output") for t in titles],
        }, indent=2))
        return

    rendered = 0
    failed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(
                render_one_title,
                title=title,
                output_path=out_path,
                width=width, height=height, fps=fps,
                accent_color=args.accent_color,
                text_color=args.text_color,
                font_family=args.font,
            ): (i, title, out_path)
            for (i, title, out_path) in pending
        }

        for fut in concurrent.futures.as_completed(futures):
            i, title, out_path = futures[fut]
            try:
                ok, elapsed = fut.result()
            except Exception as e:
                print(f"  Worker error on {title.get('id')}: {e}", file=sys.stderr)
                ok, elapsed = False, 0.0

            if ok:
                rendered += 1
                print(f"  [{rendered + skipped}/{len(titles)}] "
                      f"{title.get('id', '?')} ({title.get('style', '?')}) "
                      f"-> {out_path.name}  ({elapsed:.1f}s)",
                      file=sys.stderr)
            else:
                failed += 1

    print(json.dumps({
        "rendered": rendered,
        "skipped": skipped,
        "failed": failed,
        "titles_dir": str(titles_dir),
        "outputs": [t.get("_output") for t in titles],
    }, indent=2))

    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
