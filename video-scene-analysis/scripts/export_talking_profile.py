#!/usr/bin/env python3
"""Export an analysis' avatar_profile to <avatar>/talking_profile.json.

Reads one or more {stem}.analysis.json files (already enriched by the agent
with an `avatar_profile`) and writes a reusable talking_profile.json into the
avatar folder. The avatar-talking-video skill auto-loads that file so every
generated talking-head clip matches the avatar's real on-camera personality.

Usage:
    python3 export_talking_profile.py clip.analysis.json
    python3 export_talking_profile.py a.analysis.json b.analysis.json --avatar-dir lolo
    python3 export_talking_profile.py clip.analysis.json --dry-run

Avatar folder resolution: --avatar-dir, else the nearest ancestor of the
analyzed video that contains a videos/ directory, else the JSON's parent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROFILE_KEYS = ("video_prompt", "negative_prompt", "mannerisms_summary")


def infer_avatar_dir(video_path: str | None, json_path: Path) -> Path:
    """Nearest ancestor containing a videos/ dir; fallback to the JSON's parent."""
    candidates = []
    if video_path:
        candidates.append(Path(video_path).expanduser())
    candidates.append(json_path)
    for c in candidates:
        c = c.resolve()
        if c.is_file():
            c = c.parent
        for cand in [c, *c.parents]:
            if (cand / "videos").is_dir():
                return cand
    return json_path.resolve().parent


def first_profile(json_paths: list[Path]) -> tuple[dict, str | None, Path]:
    """Return (avatar_profile, video_path, json_path) for the first JSON that has one."""
    last_err = None
    for jp in json_paths:
        if not jp.exists():
            last_err = f"not found: {jp}"
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            last_err = f"invalid JSON {jp}: {e}"
            continue
        prof = data.get("avatar_profile") or {}
        if prof.get("video_prompt"):
            return prof, data.get("video_path"), jp
        last_err = (f"{jp} has no avatar_profile.video_prompt yet — enrich it "
                    "first (see the video-scene-analysis agent workflow).")
    raise SystemExit(f"Error: no usable avatar_profile found ({last_err}).")


def main():
    ap = argparse.ArgumentParser(
        description="Export avatar_profile from analysis JSON to <avatar>/talking_profile.json.",
    )
    ap.add_argument("json", nargs="+", type=Path, help="One or more .analysis.json files")
    ap.add_argument("--avatar-dir", type=Path, default=None,
                    help="Target avatar folder (auto-inferred if omitted)")
    ap.add_argument("--out-name", default="talking_profile.json",
                    help="Output filename inside the avatar folder")
    ap.add_argument("--dry-run", action="store_true", help="Print the profile, do not write")
    args = ap.parse_args()

    profile, video_path, src_json = first_profile(args.json)
    avatar_dir = (args.avatar_dir.expanduser().resolve()
                  if args.avatar_dir else infer_avatar_dir(video_path, src_json))

    out = {
        "_comment": ("Reusable p-video-avatar prompts for this avatar, derived from "
                     "talking-head frames by the video-scene-analysis skill. Auto-loaded "
                     "by avatar-talking-video when --video-prompt/--negative-prompt are omitted."),
        "_source": str(src_json),
    }
    for k in PROFILE_KEYS:
        if profile.get(k):
            out[k] = profile[k]

    out_path = avatar_dir / args.out_name
    print(json.dumps({"avatar_dir": str(avatar_dir), "out": str(out_path),
                      "profile": {k: out.get(k) for k in PROFILE_KEYS}}, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("\n(dry-run: nothing written)", file=sys.stderr)
        return
    avatar_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
