#!/usr/bin/env python3
"""Stage 0 -- create a ready-to-compose avatar from a public Instagram profile.

Orchestrates the whole avatar-setup chain with IDEMPOTENT RESUME. Each stage
skips itself when its outputs already exist, so re-running picks up where it
left off (and after the two agent-only checkpoints below):

    download     instagram-videos      -> <avatar>/videos/*.mp4
    analyze      video-scene-analysis  -> <avatar>/videos/*.analysis.json (+ *_frames/)
    [CHECKPOINT] AGENT vision enrichment of each analysis (avatar_profile.video_prompt)
    frames       avatar-frames         -> <avatar>/frames/ + subtitle_style.json
    voice        voice-isolate + voice-clone -> <avatar>/voices/
    transitions  profile_transitions.py -> <avatar>/transition_style.json
    profile      export_talking_profile.py -> <avatar>/talking_profile.json
    report       -> <avatar>/avatar.json + readiness table

Two steps are NOT scriptable -- they need the agent:
  1. Scraping the Picnob feed via the browser MCP (see the instagram-videos
     SKILL) to produce the posts JSON this script downloads from.
  2. Vision enrichment of each *.analysis.json (camera/framing, focus/emotion,
     mannerisms and the reusable avatar_profile.video_prompt/negative_prompt),
     per the video-scene-analysis SKILL.
The orchestrator detects both by inspecting outputs and stops with precise
instructions; re-run to continue.

Examples:
    # after the agent saved posts-raw/meta/picnob_<handle>.json via the browser:
    python3 create_avatar.py mara --handle mara_therapy
    # ...enrich the analyses, then re-run to finish:
    python3 create_avatar.py mara
    # inspect readiness without running (zero API spend):
    python3 create_avatar.py lolo --status
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _arc_common as C  # noqa: E402


def resolve_avatar_dir(raw: str) -> Path:
    """Route a bare avatar name under ./avatares/ so onboarded avatars don't
    clutter the project root. An explicit path (containing a separator or
    absolute) is respected as-is. Override the root with AVATARES_ROOT."""
    p = Path(raw).expanduser()
    seps = os.sep + (os.altsep or "")
    if not p.is_absolute() and not any(s in raw for s in seps):
        p = Path(os.environ.get("AVATARES_ROOT") or "avatares") / raw
    return p.resolve()

# --- Sibling scripts (resolved against the project-local or user skills root) -
DOWNLOAD_VIDEOS = C.HOME_SKILLS / "instagram-videos/scripts/download_profile_videos.py"
ANALYZE_VIDEO = C.HOME_SKILLS / "video-scene-analysis/scripts/analyze_video.py"
EXPORT_PROFILE = C.HOME_SKILLS / "video-scene-analysis/scripts/export_talking_profile.py"
EXTRACT_FRAMES = C.HOME_SKILLS / "avatar-frames/scripts/extract_clean_frames.py"
EXTRACT_VOICE = C.HOME_SKILLS / "voice-isolate/scripts/extract_voice.py"
CLONE_VOICE = C.HOME_SKILLS / "voice-clone/scripts/clone_voice.py"
PROFILE_TRANSITIONS = C.SCRIPT_DIR / "profile_transitions.py"

PY = sys.executable or "python3"


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, args):
        self.avatar_dir = resolve_avatar_dir(args.avatar_dir)
        self.videos_dir = self.avatar_dir / "videos"
        self.frames_dir = self.avatar_dir / "frames"
        self.handle = _clean_handle(args.handle) or self.avatar_dir.name
        self.posts_json = Path(args.posts_json).expanduser() if args.posts_json else None
        self.timezone = args.timezone
        self.language = args.language
        self.voice_video = args.voice_video
        self.force = set(args.force_stage or [])


def _clean_handle(h):
    if not h:
        return None
    m = re.search(r"instagram\.com/([^/?#]+)", h)
    if m:
        h = m.group(1)
    return h.strip("/@ ").strip() or None


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------
def _videos(ctx) -> list[Path]:
    if not ctx.videos_dir.is_dir():
        return []
    return sorted(ctx.videos_dir.glob("*.mp4"))


def _analysis_path(video: Path) -> Path:
    return video.parent / f"{video.stem}.analysis.json"


def _analyses(ctx) -> list[Path]:
    if not ctx.videos_dir.is_dir():
        return []
    return sorted(ctx.videos_dir.glob("*.analysis.json"))


def _enriched_analyses(ctx) -> list[Path]:
    """Analyses the agent has enriched with a usable avatar_profile.video_prompt."""
    out = []
    for a in _analyses(ctx):
        try:
            d = C.load_json(a)
        except (ValueError, OSError):
            continue
        if (d.get("avatar_profile") or {}).get("video_prompt"):
            out.append(a)
    return out


# ---------------------------------------------------------------------------
# Stage: done predicates
# ---------------------------------------------------------------------------
def done_download(ctx) -> bool:
    return bool(_videos(ctx))


def done_analyze(ctx) -> bool:
    # At least one analyzed reel is enough to derive the avatar's profiles; you
    # don't need to analyze every downloaded video (e.g. lolo profiles from 3 of
    # 10). On a FRESH avatar (zero analyses) run_analyze processes all of them.
    return bool(_analyses(ctx))


def done_enrich(ctx) -> bool:
    return bool(_enriched_analyses(ctx))


def done_frames(ctx) -> bool:
    return (ctx.frames_dir / "manifest.json").exists()


def done_voice(ctx) -> bool:
    voices = ctx.avatar_dir / "voices"
    idx = voices / "index.json"
    if idx.exists():
        try:
            d = C.load_json(idx)
            if isinstance(d, dict) and any((v or {}).get("voice_id") for v in d.values()):
                return True
        except (ValueError, OSError):
            pass
    if voices.is_dir():
        return any(p.name != "index.json" for p in voices.glob("*.json"))
    return False


def done_transitions(ctx) -> bool:
    return (ctx.avatar_dir / "transition_style.json").exists()


def done_profile(ctx) -> bool:
    return (ctx.avatar_dir / "talking_profile.json").exists()


# ---------------------------------------------------------------------------
# Stage: run functions
# ---------------------------------------------------------------------------
def run_download(ctx):
    posts = ctx.posts_json
    if posts is None and ctx.handle:
        posts = Path(f"posts-raw/meta/picnob_{ctx.handle}.json")
    if not posts or not Path(posts).exists():
        _stop(
            "AGENT STEP NEEDED -- scrape the Instagram profile first.",
            [
                f"This avatar has no videos in {ctx.videos_dir} and no posts JSON "
                f"was found"
                + (f" at {posts}." if posts else " (pass --handle or --posts-json)."),
                "",
                "Per the instagram-videos SKILL, using the browser MCP:",
                f"  1. Confirm https://www.instagram.com/{ctx.handle}/ is PUBLIC.",
                f"  2. Open https://www.picnob.com/profile/{ctx.handle}/ and run the",
                "     scroll+collect snippet to gather every .post_box.",
                f"  3. Save the resulting array to posts-raw/meta/picnob_{ctx.handle}.json",
                "  4. Re-run this command to download + continue.",
            ],
        )
    cmd = [PY, str(DOWNLOAD_VIDEOS), "--posts-json", str(posts),
           "--output-dir", str(ctx.videos_dir), "--timezone", ctx.timezone]
    C.run_cli_json(cmd, desc=f"instagram-videos: download @{ctx.handle}")
    if not _videos(ctx):
        raise SystemExit("download produced no .mp4 files -- check the posts JSON.")


def run_analyze(ctx):
    pending = [v for v in _videos(ctx) if not _analysis_path(v).exists()]
    if not pending:
        return
    for v in pending:
        cmd = [PY, str(ANALYZE_VIDEO), str(v), "-o", str(ctx.videos_dir)]
        if ctx.language:
            cmd += ["--language", ctx.language]
        C.run_cli_json(cmd, desc=f"video-scene-analysis: {v.name}")
        if not _analysis_path(v).exists():
            raise SystemExit(f"analysis not produced for {v.name}")


def run_frames(ctx):
    vids = _videos(ctx)
    if not vids:
        raise SystemExit("no videos for frame extraction.")
    fdir = ctx.frames_dir
    fdir.mkdir(parents=True, exist_ok=True)

    ready_records, by_video = [], {}
    best_style, best_samples = None, -1
    seq = 0
    ocr_langs = f"{ctx.language},en" if ctx.language else None

    for v in vids:
        tmp = fdir / f".tmp_{v.stem}"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        cmd = [PY, str(EXTRACT_FRAMES), str(v), "-o", str(tmp)]
        if ocr_langs:
            cmd += ["--ocr-langs", ocr_langs]
        C.run_cli_json(cmd, desc=f"avatar-frames: {v.name}")

        man_p = tmp / "manifest.json"
        man = C.load_json(man_p) if man_p.exists() else {}
        for entry in man.get("frames", []):
            src = Path(entry.get("path", ""))
            if not src.exists():
                src = tmp / entry.get("file", "")
            if not src.exists():
                continue
            seq += 1
            dst = fdir / f"frame_{seq:04d}.png"
            shutil.copy2(src, dst)
            ready_records.append({
                "seq": seq,
                "file": dst.name,
                "source_video": v.name,
                "timestamp": entry.get("timestamp"),
                "timestamp_fmt": entry.get("timestamp_fmt"),
                "sharpness": entry.get("sharpness"),
                "face_sharpness": entry.get("face_sharpness"),
                "size": entry.get("size"),
                "face": entry.get("face"),
            })
        style = man.get("subtitle_style")
        if style and style.get("samples", 0) > best_samples:
            best_style, best_samples = style, style.get("samples", 0)
        by_video[v.name] = {
            "frames_ready": man.get("frames_clean", len(man.get("frames", []))),
            "frames_with_subtitles": man.get("frames_with_subtitles", 0),
        }
        shutil.rmtree(tmp, ignore_errors=True)

    C.save_json(fdir / "manifest.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "videos_processed": len(vids),
        "output_dir": str(fdir),
        "total_ready": len(ready_records),
        "subtitle_style": best_style,
        "frames": ready_records,
        "by_video": by_video,
    })
    if best_style:
        C.save_json(ctx.avatar_dir / "subtitle_style.json", best_style)
        print(f"  subtitle_style.json written ({best_samples} samples)", file=sys.stderr)
    else:
        print("  no burned-in captions detected -- subtitle_style.json not written "
              "(captions will use the skill defaults).", file=sys.stderr)
    print(f"  frames: {len(ready_records)} reference frame(s) -> {fdir}", file=sys.stderr)


def _pick_voice_video(ctx) -> Path | None:
    vids = _videos(ctx)
    if not vids:
        return None
    if ctx.voice_video:
        for v in vids:
            if ctx.voice_video in (v.name, v.stem):
                return v
        raise SystemExit(f"--voice-video {ctx.voice_video!r} not found in {ctx.videos_dir}")
    return max(vids, key=lambda v: C.ffprobe_duration(v))


def run_voice(ctx):
    v = _pick_voice_video(ctx)
    if not v:
        raise SystemExit("no videos to extract a voice from.")
    voice_dir = ctx.videos_dir / f"{v.stem}_voice"
    concat = voice_dir / "voice_concat.mp3"
    if not concat.exists():
        cmd = [PY, str(EXTRACT_VOICE), str(v)]
        if ctx.language:
            cmd += ["--language", ctx.language]
        C.run_cli_json(cmd, desc=f"voice-isolate: {v.name} (longest take)")
    if not concat.exists():
        raise SystemExit(f"voice-isolate did not produce {concat}")
    C.run_cli_json(
        [PY, str(CLONE_VOICE), str(concat), "--avatar-dir", str(ctx.avatar_dir)],
        desc="voice-clone: train cloned voice",
    )
    if not done_voice(ctx):
        raise SystemExit("voice-clone did not register a voice in voices/index.json")


def run_transitions(ctx):
    analyses = _analyses(ctx)
    if not analyses:
        raise SystemExit("no analyses for transition profiling.")
    cmd = [PY, str(PROFILE_TRANSITIONS)] + [str(a) for a in analyses] \
        + ["--out", str(ctx.avatar_dir / "transition_style.json")]
    C.run_cli_json(cmd, desc="profile_transitions: measure scene-cut style")


def run_profile(ctx):
    enriched = _enriched_analyses(ctx)
    if not enriched:
        raise SystemExit("no enriched analyses (avatar_profile.video_prompt missing).")
    cmd = [PY, str(EXPORT_PROFILE)] + [str(a) for a in enriched] \
        + ["--avatar-dir", str(ctx.avatar_dir)]
    C.run_cli_json(cmd, desc="export_talking_profile: write talking_profile.json")


# ---------------------------------------------------------------------------
# Stage table
# ---------------------------------------------------------------------------
# (name, done_fn, run_fn). run_fn=None marks the agent enrichment checkpoint.
STAGES = [
    ("download", done_download, run_download),
    ("analyze", done_analyze, run_analyze),
    ("enrich", done_enrich, None),
    ("frames", done_frames, run_frames),
    ("voice", done_voice, run_voice),
    ("transitions", done_transitions, run_transitions),
    ("profile", done_profile, run_profile),
]


def _stop(headline, lines):
    print(f"\n  ==> {headline}", file=sys.stderr)
    for ln in lines:
        print(f"      {ln}", file=sys.stderr)
    raise SystemExit(2)


def _enrichment_gate(ctx):
    missing = [a.name for a in _analyses(ctx) if a not in set(_enriched_analyses(ctx))]
    _stop(
        "AGENT STEP NEEDED -- enrich the analyses, then re-run.",
        [
            "Each *.analysis.json must gain an `avatar_profile.video_prompt` (plus "
            "per-scene camera/framing, focus/emotion and mannerisms) -- this is the",
            "vision pass described in the video-scene-analysis SKILL. View each",
            f"scene_XX.jpg under {ctx.videos_dir}/<stem>_frames/ and fill the fields.",
            "",
            "Analyses still missing avatar_profile.video_prompt:",
        ] + [f"  - {m}" for m in missing] + [
            "",
            f"Then re-run:  python3 create_avatar.py {ctx.avatar_dir.name}",
        ],
    )


def write_report(ctx):
    vids = _videos(ctx)
    stage_status = {}
    for name, done, _ in STAGES:
        stage_status[name] = "complete" if done(ctx) else "pending"
    ready = all(v == "complete" for v in stage_status.values())
    report = {
        "avatar": ctx.avatar_dir.name,
        "handle": ctx.handle,
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "ready": ready,
        "stages": stage_status,
        "videos": [{"file": v.name, "duration_s": round(C.ffprobe_duration(v), 2)}
                   for v in vids],
        # Paths are stored RELATIVE to the avatar folder so avatar.json stays
        # portable across clones (no absolute machine paths in the repo).
        "artifacts": {
            "analyses": [f"videos/{a.name}" for a in _analyses(ctx)],
            "frames_dir": "frames" if done_frames(ctx) else None,
            "subtitle_style": _opt(ctx, "subtitle_style.json"),
            "transition_style": _opt(ctx, "transition_style.json"),
            "talking_profile": _opt(ctx, "talking_profile.json"),
            "voices": _voice_ids(ctx),
        },
    }
    C.save_json(ctx.avatar_dir / "avatar.json", report)
    return report


def _opt(ctx, rel: str):
    return rel if (ctx.avatar_dir / rel).exists() else None


def _voice_ids(ctx):
    idx = ctx.avatar_dir / "voices" / "index.json"
    if not idx.exists():
        return []
    try:
        d = C.load_json(idx)
    except (ValueError, OSError):
        return []
    return [v.get("voice_id") for v in d.values() if isinstance(v, dict) and v.get("voice_id")]


def print_table(ctx, report):
    icon = {"complete": "[x]", "pending": "[ ]"}
    print(f"\nAvatar '{report['avatar']}' (@{report['handle']}) -- "
          f"{'READY' if report['ready'] else 'incomplete'}")
    print(f"  videos: {len(report['videos'])} | analyses: "
          f"{len(report['artifacts']['analyses'])} | "
          f"voices: {len(report['artifacts']['voices'])}")
    for name, _, run in STAGES:
        tag = " (agent)" if run is None else ""
        print(f"  {icon.get(report['stages'][name], '[ ]')} {name}{tag}")
    print(f"  report: {ctx.avatar_dir / 'avatar.json'}")
    if report["ready"]:
        print(f"\n  Next: write a storyboard (see examples/storyboard.example.json) and run\n"
              f"        compose_reel.py {report['avatar']}/reels/NNN_slug/storyboard.json --finish")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Create a ready-to-compose avatar from a public Instagram profile.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("avatar_dir", help="Avatar to build. A bare name goes under ./avatares/<name>; an explicit path is used as-is (e.g. mara, avatares/mara, path/to/mara)")
    ap.add_argument("--handle", default=None,
                    help="Instagram handle or profile URL (default: avatar folder name)")
    ap.add_argument("--posts-json", default=None,
                    help="Picnob posts JSON from the browser scrape "
                         "(default: posts-raw/meta/picnob_<handle>.json)")
    ap.add_argument("--timezone", default="America/Santiago",
                    help="IANA timezone for downloaded filenames")
    ap.add_argument("--language", default=None,
                    help="Language hint for analysis/voice (es, en, ...); auto if omitted")
    ap.add_argument("--voice-video", default=None,
                    help="Video name/stem to clone the voice from (default: longest)")
    ap.add_argument("--force-stage", action="append", default=[],
                    choices=[s[0] for s in STAGES],
                    help="Re-run this stage even if complete (repeatable)")
    ap.add_argument("--status", action="store_true",
                    help="Print readiness and exit without running anything")
    args = ap.parse_args()

    ctx = Ctx(args)

    if args.status:
        report = write_report(ctx)
        print_table(ctx, report)
        return 0

    if not ctx.avatar_dir.exists():
        ctx.avatar_dir.mkdir(parents=True, exist_ok=True)
    print(f"Building avatar '{ctx.avatar_dir.name}' (@{ctx.handle})", file=sys.stderr)

    for name, done, run in STAGES:
        if run is None:  # agent enrichment checkpoint
            if not done(ctx):
                _enrichment_gate(ctx)
            print(f"  [enrich] complete", file=sys.stderr)
            continue
        if done(ctx) and name not in ctx.force:
            print(f"  [{name}] already complete -- skipping", file=sys.stderr)
            continue
        print(f"  [{name}] running...", file=sys.stderr)
        run(ctx)

    report = write_report(ctx)
    print_table(ctx, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
