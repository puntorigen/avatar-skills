#!/usr/bin/env python3
"""List the locations (looks) available for an avatar.

Shows the implicit DEFAULT location (the avatar's top-level scene.json + angles/)
plus every location under ``<avatar>/locations/<loc>/``, with a short look summary
and the number of camera angles ready. Reads location.json records and falls back
to scanning the folders so it works even before a location is fully recorded.

Usage:
    python3 list_locations.py nora
    python3 list_locations.py doki-monster --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _common as C  # noqa: E402


def _short(text: str, n: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def _count_angles(angles_dir: Path) -> int:
    if not angles_dir.is_dir():
        return 0
    return len(list(angles_dir.glob("*_916.png")))


def collect(avatar_dir: Path) -> dict:
    avatar_dir = avatar_dir.expanduser().resolve()
    slug = avatar_dir.name
    out = {"avatar": slug, "locations": []}

    # Default location = top-level scene.json + angles/.
    default_scene = C.try_load_json(avatar_dir / "scene.json") or {}
    out["locations"].append({
        "location": "default",
        "name": "default",
        "status": "ready" if default_scene else "missing",
        "wardrobe": _short(default_scene.get("wardrobe", "")),
        "scene": _short(default_scene.get("scene", "")),
        "assets": 0,
        "angles": _count_angles(avatar_dir / "angles"),
        "dir": ".",
    })

    loc_root = avatar_dir / "locations"
    if loc_root.is_dir():
        for loc_dir in sorted(p for p in loc_root.iterdir() if p.is_dir()):
            rec = C.try_load_json(loc_dir / "location.json") or {}
            scene = C.try_load_json(loc_dir / "scene.json") or {}
            look = rec.get("look") or {}
            out["locations"].append({
                "location": rec.get("location", loc_dir.name),
                "name": rec.get("name", loc_dir.name),
                "status": rec.get("status", "draft"),
                "wardrobe": _short(look.get("wardrobe") or scene.get("wardrobe", "")),
                "scene": _short(look.get("scene") or scene.get("scene", "")),
                "assets": len(rec.get("assets") or scene.get("assets") or []),
                "angles": _count_angles(loc_dir / "angles"),
                "dir": C.rel_to(loc_dir, avatar_dir),
            })
    return out


def main():
    ap = argparse.ArgumentParser(description="List an avatar's locations (looks).")
    ap.add_argument("avatar_dir", help="Avatar folder (e.g. nora or doki-monster)")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = ap.parse_args()

    avatar_dir = Path(args.avatar_dir)
    if not avatar_dir.is_dir():
        ap.error(f"avatar dir not found: {avatar_dir}")
    data = collect(avatar_dir)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"\nLocations for avatar '{data['avatar']}':\n")
    for loc in data["locations"]:
        tag = "*" if loc["location"] == "default" else " "
        head = f" {tag} {loc['location']:18s} [{loc['status']}]  {loc['angles']} angle(s)"
        if loc["assets"]:
            head += f", {loc['assets']} asset(s)"
        print(head)
        if loc["wardrobe"]:
            print(f"      wardrobe: {loc['wardrobe']}")
        if loc["scene"]:
            print(f"      scene   : {loc['scene']}")
    print("\n  (* = default look = top-level scene.json/angles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
