#!/usr/bin/env python3
"""Scaffold a NEW avatar from raw inputs so a reel template can be applied to it.

Given a reel_template.json (from extract_template.py), a single avatar PICTURE,
a raw VOICE sample and a name, this builds exactly the assets the
avatar-reel-composer needs -- with IDEMPOTENT RESUME (each stage skips itself
when its outputs already exist):

    picture   copy the reference picture        -> <avatar>/refs/<file>
    [author]  AGENT writes scene.json + talking_profile.json   (vision checkpoint)
    angles    avatar-camera-angles              -> <avatar>/angles/<slug>_<move>_916.png
              (or ..._169.png for --format landscape / 16:9 YouTube)
    voice     voice-clone                       -> <avatar>/voices/ (+ voice_id)
    styles    copy reference transition/subtitle styles -> <avatar>/{transition,subtitle}_style.json

One step is NOT scriptable -- it needs the agent's vision:
    [author] Look at the picture and (a) describe scene.json
             (subject/wardrobe/scene/light, per avatar-camera-angles) and
             (b) write talking_profile.json (video_prompt describing the NEW
             person + delivery seeded from the template's delivery_style_seed).
The orchestrator detects this by inspecting outputs and stops with precise
instructions; re-run to continue.

Examples:
    python3 scaffold_avatar.py mara --template lolo/reel_template.json \
        --picture refs/mara.png --voice samples/mara_voice.wav
    # ...after writing scene.json + talking_profile.json, re-run to finish:
    python3 scaffold_avatar.py mara --template lolo/reel_template.json \
        --picture refs/mara.png --voice samples/mara_voice.wav
    python3 scaffold_avatar.py mara --template lolo/reel_template.json --status
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _restyle_common as C  # noqa: E402

SCENE_FIELDS = ("subject", "wardrobe", "scene", "light")


def resolve_avatar_dir(raw: str) -> Path:
    """Route a bare avatar name under ./avatares/ so scaffolded avatars don't
    clutter the project root. An explicit path (containing a separator or
    absolute) is respected as-is. Override the root with AVATARES_ROOT."""
    p = Path(raw).expanduser()
    seps = os.sep + (os.altsep or "")
    if not p.is_absolute() and not any(s in raw for s in seps):
        p = Path(os.environ.get("AVATARES_ROOT") or "avatares") / raw
    return p.resolve()


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, args):
        self.base_dir = Path(args.base_dir).expanduser().resolve()
        self.avatar_dir = resolve_avatar_dir(args.avatar_dir)
        self.refs_dir = self.avatar_dir / "refs"
        self.angles_dir = self.avatar_dir / "angles"
        self.name = args.name or self.avatar_dir.name
        self.slug = self.avatar_dir.name
        self.picture = Path(args.picture).expanduser().resolve() if args.picture else None
        self.voice = Path(args.voice).expanduser().resolve() if args.voice else None
        self.scene_file = (Path(args.scene_file).expanduser().resolve()
                           if args.scene_file else self.avatar_dir / "scene.json")
        self.language = args.language
        self.quality = args.quality
        self.fmt = args.format
        self.angle_suffix = C.angle_suffix(self.fmt)
        self.angle_crop_flag = C.angle_crop_flag(self.fmt)
        self.force = set(args.force_stage or [])
        self.template_path = Path(args.template).expanduser().resolve()
        self.template = C.load_json(self.template_path)
        self.moves = list(self.template.get("angles_needed") or [])


# ---------------------------------------------------------------------------
# done predicates
# ---------------------------------------------------------------------------
def done_picture(ctx) -> bool:
    return C.first_image(ctx.refs_dir) is not None


def _scene_ok(ctx) -> bool:
    d = C.try_load_json(ctx.scene_file)
    return bool(d) and all((d.get(k) or "").strip() for k in SCENE_FIELDS)


def _profile_ok(ctx) -> bool:
    d = C.try_load_json(ctx.avatar_dir / "talking_profile.json")
    return bool(d) and bool((d or {}).get("video_prompt"))


def done_author(ctx) -> bool:
    return _scene_ok(ctx) and _profile_ok(ctx)


def _angle_file(ctx, move) -> Path:
    return ctx.angles_dir / f"{ctx.slug}_{move}{ctx.angle_suffix}.png"


def missing_moves(ctx) -> list[str]:
    return [m for m in ctx.moves if not _angle_file(ctx, m).exists()]


def done_angles(ctx) -> bool:
    return bool(ctx.moves) and not missing_moves(ctx)


def done_voice(ctx) -> bool:
    idx = C.try_load_json(ctx.avatar_dir / "voices" / "index.json")
    if isinstance(idx, dict) and any((v or {}).get("voice_id") for v in idx.values()):
        return True
    vdir = ctx.avatar_dir / "voices"
    return vdir.is_dir() and any(p.name != "index.json" for p in vdir.glob("*.json"))


def done_styles(ctx) -> bool:
    return (ctx.avatar_dir / "transition_style.json").exists()


# ---------------------------------------------------------------------------
# run functions
# ---------------------------------------------------------------------------
def run_picture(ctx):
    if not ctx.picture:
        C.stop("INPUT NEEDED -- no reference picture.", [
            f"This avatar has no image in {ctx.refs_dir}.",
            "Pass --picture <png|jpg> (a sharp, front-ish portrait of the new avatar).",
        ])
    if not ctx.picture.exists():
        raise SystemExit(f"picture not found: {ctx.picture}")
    ctx.refs_dir.mkdir(parents=True, exist_ok=True)
    dst = ctx.refs_dir / ctx.picture.name
    if dst.resolve() != ctx.picture.resolve():
        shutil.copy2(ctx.picture, dst)
    print(f"  reference picture: {dst}", file=sys.stderr)


def author_gate(ctx):
    seed = ctx.template.get("delivery_style_seed") or "(no delivery seed in template)"
    lines = [
        "Look at the avatar PICTURE and write TWO files, then re-run to continue:",
        "",
        f"1) {ctx.scene_file}  -- subject/wardrobe/scene/light of the NEW avatar,",
        "   exactly as the avatar-camera-angles skill expects, e.g.:",
        '   { "subject": "...", "wardrobe": "...", "scene": "...", "light": "..." }',
        "",
        f"2) {ctx.avatar_dir / 'talking_profile.json'}  -- p-video-avatar prompts for",
        "   the NEW person (a DIFFERENT identity). Describe THIS person's look, then",
        "   carry over the reference's DELIVERY style (calm, addressing the lens, etc):",
        '   { "video_prompt": "...", "negative_prompt": "...", "mannerisms_summary": "..." }',
        "",
        "   Reference delivery style to emulate (do NOT copy the identity):",
        f"     {seed}",
    ]
    if not _scene_ok(ctx):
        lines.append("")
        lines.append(f"   MISSING/incomplete: {ctx.scene_file}")
    if not _profile_ok(ctx):
        lines.append(f"   MISSING/incomplete: {ctx.avatar_dir / 'talking_profile.json'} (needs video_prompt)")
    C.stop("AGENT STEP NEEDED -- describe the new avatar (vision), then re-run.", lines)


def run_angles(ctx):
    if not ctx.moves:
        print("  template has no angles_needed -- skipping angle generation.", file=sys.stderr)
        return
    ref = C.first_image(ctx.refs_dir)
    if not ref:
        raise SystemExit("no reference picture in refs/ (run the picture stage first).")
    todo = missing_moves(ctx)
    if not todo:
        return
    ctx.angles_dir.mkdir(parents=True, exist_ok=True)
    cmd = [C.PY, str(C.GENERATE_ANGLES),
           "--ref", str(ref),
           "--scene-file", str(ctx.scene_file),
           "--slug", ctx.slug,
           "-o", str(ctx.angles_dir),
           ctx.angle_crop_flag, "--quality", ctx.quality]
    for m in todo:
        cmd += ["--move", m]
    rc, _ = C.run_child_json(cmd, desc=f"avatar-camera-angles: {', '.join(todo)}")
    if rc != 0:
        raise SystemExit(f"angle generation failed (exit {rc}).")
    still_missing = missing_moves(ctx)
    if still_missing:
        raise SystemExit(f"angle stills not produced for: {', '.join(still_missing)}")


def run_voice(ctx):
    if not ctx.voice:
        C.stop("INPUT NEEDED -- no voice sample.", [
            f"This avatar has no cloned voice in {ctx.avatar_dir / 'voices'}.",
            "Pass --voice <wav|mp3|m4a> (10s-5min of clean speech of the new avatar).",
        ])
    if not ctx.voice.exists():
        raise SystemExit(f"voice file not found: {ctx.voice}")
    cmd = [C.PY, str(C.CLONE_VOICE), str(ctx.voice),
           "--avatar-dir", str(ctx.avatar_dir), "--name", ctx.name]
    rc, _ = C.run_child_json(cmd, desc="voice-clone: train cloned voice")
    if rc != 0:
        raise SystemExit(f"voice cloning failed (exit {rc}).")
    if not done_voice(ctx):
        raise SystemExit("voice-clone did not register a voice in voices/index.json")


def _copy_style(ctx, src_rel, embedded, dst_name) -> bool:
    dst = ctx.avatar_dir / dst_name
    if src_rel:
        src = C.resolve_path(src_rel, ctx.base_dir)
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  {dst_name}: copied from {src}", file=sys.stderr)
            return True
    if embedded:
        C.save_json(dst, embedded)
        print(f"  {dst_name}: written from embedded template copy", file=sys.stderr)
        return True
    return False


def run_styles(ctx):
    src = ctx.template.get("source", {}) or {}
    caps = ctx.template.get("captions", {}) or {}
    if not _copy_style(ctx, src.get("transition_style"),
                       ctx.template.get("transitions"), "transition_style.json"):
        print("  ! no transition style available -- polish will use composer defaults.",
              file=sys.stderr)
    if not _copy_style(ctx, src.get("subtitle_style"),
                       caps.get("subtitle_style"), "subtitle_style.json"):
        print("  ! no subtitle style available -- captions will use composer defaults.",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Stage table  (name, done_fn, run_fn). run_fn=None => agent checkpoint.
# ---------------------------------------------------------------------------
STAGES = [
    ("picture", done_picture, run_picture),
    ("author", done_author, None),
    ("angles", done_angles, run_angles),
    ("voice", done_voice, run_voice),
    ("styles", done_styles, run_styles),
]


def write_report(ctx) -> dict:
    stage_status = {name: ("complete" if done(ctx) else "pending") for name, done, _ in STAGES}
    ready = all(v == "complete" for v in stage_status.values())
    report = {
        "avatar": ctx.avatar_dir.name,
        "name": ctx.name,
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "ready": ready,
        "template": C.rel_to(ctx.template_path, ctx.base_dir),
        "stages": stage_status,
        "angles_needed": ctx.moves,
        "artifacts": {
            "scene": "scene.json" if _scene_ok(ctx) else None,
            "talking_profile": "talking_profile.json" if _profile_ok(ctx) else None,
            "angles": [f"angles/{ctx.slug}_{m}{ctx.angle_suffix}.png" for m in ctx.moves
                       if _angle_file(ctx, m).exists()],
            "voices": _voice_ids(ctx),
            "transition_style": "transition_style.json"
                if (ctx.avatar_dir / "transition_style.json").exists() else None,
            "subtitle_style": "subtitle_style.json"
                if (ctx.avatar_dir / "subtitle_style.json").exists() else None,
        },
    }
    C.save_json(ctx.avatar_dir / "restyle_avatar.json", report)
    return report


def _voice_ids(ctx):
    idx = C.try_load_json(ctx.avatar_dir / "voices" / "index.json")
    if not isinstance(idx, dict):
        return []
    return [v.get("voice_id") for v in idx.values() if isinstance(v, dict) and v.get("voice_id")]


def print_table(ctx, report):
    icon = {"complete": "[x]", "pending": "[ ]"}
    print(f"\nAvatar '{report['avatar']}' -- {'READY' if report['ready'] else 'incomplete'}",
          file=sys.stderr)
    for name, _, run in STAGES:
        tag = " (agent)" if run is None else ""
        print(f"  {icon.get(report['stages'][name], '[ ]')} {name}{tag}", file=sys.stderr)
    print(f"  report: {ctx.avatar_dir / 'restyle_avatar.json'}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="Scaffold a new avatar from a picture + voice for a reel template.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("avatar_dir", help="New avatar to build. A bare name goes under ./avatares/<name>; an explicit path is used as-is (e.g. mara, avatares/mara, path/to/mara)")
    ap.add_argument("--template", required=True, help="reel_template.json from extract_template.py")
    ap.add_argument("--picture", default=None, help="Reference portrait of the new avatar")
    ap.add_argument("--voice", default=None, help="Clean voice sample of the new avatar (wav/mp3/m4a)")
    ap.add_argument("--name", default=None, help="Voice/avatar name (default: avatar folder name)")
    ap.add_argument("--scene-file", default=None, help="scene.json path (default: <avatar>/scene.json)")
    ap.add_argument("--language", default=None, help="Language hint (es, en, ...)")
    ap.add_argument("--format", default="reel", choices=["reel", "post", "landscape"],
                    help="Target output format. Selects the angle crop: reel/post -> 9:16 "
                         "(_916.png), landscape -> 16:9 (_169.png) for YouTube.")
    ap.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"],
                    help="Angle-image fidelity passed to avatar-camera-angles")
    ap.add_argument("--base-dir", default=".", help="Base for resolving template-relative paths")
    ap.add_argument("--force-stage", action="append", default=[],
                    choices=[s[0] for s in STAGES],
                    help="Re-run this stage even if complete (repeatable)")
    ap.add_argument("--status", action="store_true", help="Print readiness and exit")
    args = ap.parse_args()

    ctx = Ctx(args)

    if args.status:
        print_table(ctx, write_report(ctx))
        return 0

    ctx.avatar_dir.mkdir(parents=True, exist_ok=True)
    print(f"Scaffolding avatar '{ctx.avatar_dir.name}' from template "
          f"{ctx.template.get('source', {}).get('avatar')}", file=sys.stderr)

    for name, done, run in STAGES:
        if run is None:  # agent checkpoint
            if not done(ctx):
                author_gate(ctx)
            print(f"  [{name}] complete", file=sys.stderr)
            continue
        if done(ctx) and name not in ctx.force:
            print(f"  [{name}] already complete -- skipping", file=sys.stderr)
            continue
        print(f"  [{name}] running...", file=sys.stderr)
        run(ctx)

    print_table(ctx, write_report(ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
