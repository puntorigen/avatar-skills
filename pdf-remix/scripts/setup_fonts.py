#!/usr/bin/env python3
"""Download the bundled OFL fonts pdf-remix uses to reconstruct type molds.

These five families cover the typographic roles seen across premium marketing
lead-magnets:
  - Playfair Display  -> display_serif   (Didone titles, big serif headlines)
  - Inter             -> body_sans       (justified body, bold/italic emphasis)
  - Caveat            -> hand_marker      (casual handwritten sub-quotes)
  - Great Vibes       -> signature_script(elegant signature / author byline)
  - Kaushan Script    -> brush_script     (bold emotive brush emphasis)

All are OFL-licensed and fetched from the google/fonts repository. Idempotent:
re-running only downloads what is missing. If a download fails, the build still
works — build_pdf.py falls back to CSS generics for any missing face.

Usage:
  python3 setup_fonts.py            # download missing fonts
  python3 setup_fonts.py --force    # re-download all
  python3 setup_fonts.py --check    # report which fonts are present
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
RAW = "https://raw.githubusercontent.com/google/fonts/main/"

# local_filename -> ordered list of candidate repo paths (first that works wins)
FONTS: dict[str, list[str]] = {
    "PlayfairDisplay-var.ttf": [
        "ofl/playfairdisplay/PlayfairDisplay[wght].ttf",
    ],
    "PlayfairDisplay-Italic-var.ttf": [
        "ofl/playfairdisplay/PlayfairDisplay-Italic[wght].ttf",
    ],
    "Inter-var.ttf": [
        "ofl/inter/Inter[opsz,wght].ttf",
        "ofl/inter/Inter[slnt,wght].ttf",
    ],
    "Inter-Italic-var.ttf": [
        "ofl/inter/Inter-Italic[opsz,wght].ttf",
    ],
    "Caveat-var.ttf": [
        "ofl/caveat/Caveat[wght].ttf",
    ],
    "GreatVibes-Regular.ttf": [
        "ofl/greatvibes/GreatVibes-Regular.ttf",
    ],
    "KaushanScript-Regular.ttf": [
        "ofl/kaushanscript/KaushanScript-Regular.ttf",
    ],
}


def _download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pdf-remix/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if len(data) < 2000:  # sanity: real TTFs are tens of KB+
            return False
        dest.write_bytes(data)
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch bundled OFL fonts for pdf-remix")
    ap.add_argument("--force", action="store_true", help="Re-download even if present")
    ap.add_argument("--check", action="store_true", help="Only report presence")
    args = ap.parse_args()

    FONTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.check:
        missing = 0
        for local in FONTS:
            ok = (FONTS_DIR / local).exists()
            print(f"  [{'x' if ok else ' '}] {local}")
            missing += 0 if ok else 1
        print(f"\n{len(FONTS) - missing}/{len(FONTS)} fonts present.")
        sys.exit(0 if missing == 0 else 1)

    ok_count = 0
    for local, candidates in FONTS.items():
        dest = FONTS_DIR / local
        if dest.exists() and not args.force:
            print(f"  = {local} (already present)")
            ok_count += 1
            continue
        got = False
        for repo_path in candidates:
            url = RAW + urllib.parse.quote(repo_path, safe="/")
            if _download(url, dest):
                print(f"  + {local}  <-  {repo_path}")
                got = True
                ok_count += 1
                break
        if not got:
            print(f"  ! FAILED {local} (tried {len(candidates)} url(s)) — "
                  "build will fall back to a generic font for this role.",
                  file=sys.stderr)

    print(f"\n{ok_count}/{len(FONTS)} fonts ready in {FONTS_DIR}")


if __name__ == "__main__":
    main()
