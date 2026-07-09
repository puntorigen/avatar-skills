#!/usr/bin/env python3
"""Find real public YouTube footage about a topic/person and turn the relevant
windows into clean 9:16 B-roll clips for an avatar reel.

Orchestrates the focused scripts with an idempotent, resumable flow and a single
AGENT checkpoint (mirrors avatar-reel-composer/create_avatar.py):

  1. search.py       -> <work>/candidates.json + candidates.md          (ranked)
  2. transcripts.py  -> <work>/transcripts/<id>.{json,md}               (timecoded)
                     -> <work>/selection.template.json                  (skeleton)
  --- CHECKPOINT: the agent reads the transcripts + candidates, then writes
      <work>/selection.json with the [start,end] windows worth cutting ---
  3. cut_segment.py  -> <avatar>/broll/found/<NNN>_<slug>.mp4 + manifest.json
                        (+ optional review frames)

Re-run the SAME command to resume: finished stages are skipped. Stage 3 only
runs once selection.json exists.

Examples:
    python3 find_broll.py --query "anthony bourdain street food vietnam" \
        --avatar-dir lolo --max-candidates 8 --lang en
    # ... agent writes found-broll/<slug>/selection.json, then re-run the same line.
    python3 find_broll.py --query "..." --avatar-dir lolo --status
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

PY = sys.executable
SD = Path(__file__).resolve().parent


def _run(cmd: list[str], desc: str) -> dict | None:
    print(f"\n=== {desc} ===", file=sys.stderr)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stderr:
        sys.stderr.write(res.stderr)
    if res.returncode != 0:
        print(f"  [fail] {desc} (exit {res.returncode})", file=sys.stderr)
        return None
    for line in reversed(res.stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {}


def _selection_template(candidates: list[dict], transcripts: list[dict]) -> dict:
    ok_ids = {t["video_id"] for t in transcripts if t.get("ok")}
    segs = []
    for r in candidates:
        vid = r.get("video_id") or C.extract_video_id(r.get("url", "") or "")
        if vid in ok_ids:
            segs.append({
                "url": r.get("url"),
                "start": 0.0, "end": 6.0,
                "description": "TODO: what this window shows (people/objects/place)",
                "fit": "crop",
                "_title": r.get("title"),
                "_license": r.get("license"),
            })
    return {
        "_instructions": ("Edit this file: keep only the windows you want, set real "
                          "start/end (seconds, from the transcripts/*.md mm:ss markers) "
                          "and a description. Add more entries from the same or other "
                          "videos as needed. Then rename to selection.json and re-run."),
        "segments": segs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Find YouTube footage about a topic/person and cut it into B-roll clips.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--query", required=True, help="Topic or person (e.g. 'anthony bourdain street food').")
    ap.add_argument("--avatar-dir", help="Avatar folder; final clips land in <avatar>/broll/found/.")
    ap.add_argument("--work-dir", help="Working dir for research artifacts (default found-broll/<slug>).")
    ap.add_argument("--slug", help="Short id for the work folder (default: from --query).")
    ap.add_argument("--max-candidates", type=int, default=8, help="Videos to search + transcribe (default 8).")
    ap.add_argument("--sort", default="relevance", choices=["relevance", "views", "recent"])
    ap.add_argument("--lang", nargs="+", default=["en", "es"], help="Caption languages in order.")
    ap.add_argument("--region", help="Data API region code (e.g. US).")
    ap.add_argument("--max-duration", type=int, help="Skip candidate videos longer than N seconds.")
    ap.add_argument("--creative-commons", action="store_true",
                    help="Only Creative-Commons videos (safer to republish; with attribution).")
    ap.add_argument("--fit", default="crop", choices=["crop", "pad", "blur"],
                    help="Default 16:9->9:16 strategy for cut clips. 'crop' (default) = center "
                         "crop-to-fill covering the whole 9:16 frame, never letterbox padding. "
                         "'pad'/'blur' are opt-in for shots where cropping loses essential content.")
    ap.add_argument("--max-height", type=int, default=720, help="Max source height to download (default 720).")
    ap.add_argument("--frames", action="store_true", help="Save a review frame jpg per cut clip.")
    ap.add_argument("--whisper", action="store_true", help="ASR fallback for videos without captions (slow).")
    ap.add_argument("--cookies-from-browser", help="Browser for cookies on bot-gated videos (e.g. firefox).")
    ap.add_argument("--force-search", action="store_true", help="Re-run search even if candidates.json exists.")
    ap.add_argument("--force-transcripts", action="store_true", help="Re-fetch transcripts.")
    ap.add_argument("--status", action="store_true", help="Show stage status and exit (no work).")
    args = ap.parse_args()

    slug = args.slug or C.slugify(args.query, 40)
    work = (Path(args.work_dir).expanduser().resolve() if args.work_dir
            else (Path.cwd() / "found-broll" / slug))
    work.mkdir(parents=True, exist_ok=True)
    cand_json = work / "candidates.json"
    tdir = work / "transcripts"
    sel_template = work / "selection.template.json"
    sel = work / "selection.json"

    def have_transcripts() -> bool:
        return tdir.is_dir() and any(tdir.glob("*.json"))

    if args.status:
        print(json.dumps({
            "work_dir": str(work), "slug": slug,
            "search_done": cand_json.exists(),
            "transcripts_done": have_transcripts(),
            "selection_ready": sel.exists(),
        }, ensure_ascii=False, indent=2))
        return 0

    # --- Stage 1: search ---
    if cand_json.exists() and not args.force_search:
        print(f"[1/3] search: reusing {cand_json}", file=sys.stderr)
    else:
        cmd = [PY, str(SD / "search.py"), "--query", args.query,
               "--limit", str(args.max_candidates), "--sort", args.sort, "-o", str(work)]
        if args.region:
            cmd += ["--region", args.region]
        if args.max_duration:
            cmd += ["--max-duration", str(args.max_duration)]
        if args.creative_commons:
            cmd += ["--creative-commons"]
        if _run(cmd, "[1/3] search.py") is None:
            return 1
    candidates = json.loads(cand_json.read_text(encoding="utf-8")).get("candidates", [])
    if not candidates:
        print("No candidates found. Try a different --query, drop --creative-commons, "
              "or set YT_API_KEY.", file=sys.stderr)
        return 1

    # --- Stage 2: transcripts ---
    if have_transcripts() and not args.force_transcripts:
        print(f"[2/3] transcripts: reusing {tdir}", file=sys.stderr)
        tres = [{"video_id": p.stem, "ok": True} for p in tdir.glob("*.json")]
    else:
        cmd = [PY, str(SD / "transcripts.py"), "--candidates", str(cand_json),
               "--max", str(args.max_candidates), "--lang", *args.lang, "-o", str(work)]
        if args.whisper:
            cmd += ["--whisper"]
        if args.cookies_from_browser:
            cmd += ["--cookies-from-browser", args.cookies_from_browser]
        out = _run(cmd, "[2/3] transcripts.py")
        if out is None:
            return 1
        tres = out.get("results", [])

    if not sel.exists():
        tmpl = _selection_template(candidates, tres)
        C.write_manifest(sel_template, tmpl)
        print("\n" + "=" * 72, file=sys.stderr)
        print("CHECKPOINT — agent action required:", file=sys.stderr)
        print(f"  1. Skim {work}/candidates.md and {tdir}/*.md", file=sys.stderr)
        print(f"  2. Copy {sel_template.name} -> selection.json and edit it:", file=sys.stderr)
        print("     keep the windows you want, set real start/end (from the mm:ss", file=sys.stderr)
        print("     markers) + a description; add/remove entries freely.", file=sys.stderr)
        print(f"  3. Re-run the same command to cut the clips.", file=sys.stderr)
        print("=" * 72, file=sys.stderr)
        print(json.dumps({"stage": "checkpoint", "work_dir": str(work),
                          "candidates_md": str(work / "candidates.md"),
                          "transcripts_dir": str(tdir),
                          "selection_template": str(sel_template)}, ensure_ascii=False))
        return 0

    # --- Stage 3: cut selected windows ---
    segments = json.loads(sel.read_text(encoding="utf-8")).get("segments", [])
    segments = [s for s in segments if s.get("url") and s.get("end", 0) > s.get("start", 0)]
    if not segments:
        print("selection.json has no valid segments (need url + start < end).", file=sys.stderr)
        return 1

    made = []
    for i, s in enumerate(segments, 1):
        cmd = [PY, str(SD / "cut_segment.py"), "--url", str(s["url"]),
               "--start", str(s["start"]), "--end", str(s["end"]),
               "--description", s.get("description", f"clip {i}"),
               "--fit", s.get("fit", args.fit), "--max-height", str(args.max_height)]
        if args.avatar_dir:
            cmd += ["--avatar-dir", args.avatar_dir]
        else:
            cmd += ["--out-dir", str(work / "clips")]
        if args.frames:
            cmd += ["--frame"]
        if args.cookies_from_browser:
            cmd += ["--cookies-from-browser", args.cookies_from_browser]
        out = _run(cmd, f"[3/3] cut_segment {i}/{len(segments)}")
        if out and out.get("video"):
            made.append(out)

    print("\n" + "=" * 72, file=sys.stderr)
    print(f"Done: {len(made)}/{len(segments)} clips cut.", file=sys.stderr)
    non_reusable = [m for m in made if not m.get("reusable")]
    if non_reusable:
        print(f"  RIGHTS: {len(non_reusable)} clip(s) are standard-license — REFERENCE only, "
              "not cleared for publishing (see manifest rights_note).", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print(json.dumps({"stage": "cut", "count": len(made), "clips": made}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
