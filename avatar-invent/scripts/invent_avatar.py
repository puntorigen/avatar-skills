#!/usr/bin/env python3
"""Invent a brand-new fictional avatar from a text description.

Produces an avatar folder with the SAME structure every other avatar in this
repo uses (refs/, angles/, voices/, scene.json, talking_profile.json,
avatar.json), so avatar-reel-composer / reel-restyle can drive it directly.

Defaults are tuned for a UGC talking-head reel presenter: photorealistic,
front-facing, eyes to the lens, soft flattering light, seated half-body framing,
in a room that fits the topic. Everything is overridable.

Stages (idempotent, resume on re-run -- like create_avatar.py / scaffold_avatar.py):

    author   [AGENT]  seed + refine scene.json / talking_profile.json / voice_brief.json
    hero              generate_hero.py    -> refs/<slug>_hero.png (+ master)
    angles            avatar-camera-angles -> angles/<slug>_<move>_916.png
    voice             design_voice.py     -> voices/ (ElevenLabs design -> MiniMax clone)
    record            write avatar.json + frames/manifest.json

The author stage auto-DRAFTS the three files from the brief, then stops once so
the agent can refine the invented details (the creative casting step) before any
paid generation runs. Re-run to continue. Pass --no-review to skip the pause.

Examples:
    python3 invent_avatar.py nora \
        --description "Chilean woman, mid 30s, warm and reassuring, psychologist" \
        --setting clinic --language es
    # ...refine nora/scene.json + talking_profile.json + voice_brief.json, then:
    python3 invent_avatar.py nora
    python3 invent_avatar.py nora --status
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _common as C  # noqa: E402

GENERATE_HERO = SCRIPT_DIR / "generate_hero.py"
DESIGN_VOICE = SCRIPT_DIR / "design_voice.py"


def resolve_avatar_dir(raw: str) -> Path:
    """Route a bare avatar name under ./avatares/ so generated avatars don't
    clutter the project root. An explicit path (containing a separator or
    absolute) is respected as-is. Override the root with AVATARES_ROOT."""
    p = Path(raw).expanduser()
    seps = os.sep + (os.altsep or "")
    if not p.is_absolute() and not any(s in raw for s in seps):
        p = Path(os.environ.get("AVATARES_ROOT") or "avatares") / raw
    return p.resolve()

BRIEF_DEFAULTS = {
    "description": "",
    "setting": "",
    "style": "photoreal",
    "aspect_ratio": "9:16",
    "generator": "gpt-image-2",
    "language": "es",
    "voice_description": "",
    "quality": "high",
    "angles": None,   # None -> auto (on for vertical)
    "moves": None,    # None -> presets default
}


class Ctx:
    def __init__(self, args, presets):
        self.presets = presets
        self.avatar_dir = resolve_avatar_dir(args.avatar_dir)
        self.slug = self.avatar_dir.name
        self.name = args.name or self.slug
        self.refs_dir = self.avatar_dir / "refs"
        self.angles_dir = self.avatar_dir / "angles"
        self.voices_dir = self.avatar_dir / "voices"
        self.frames_dir = self.avatar_dir / "frames"
        self.scene_file = self.avatar_dir / "scene.json"
        self.profile_file = self.avatar_dir / "talking_profile.json"
        self.voice_brief_file = self.avatar_dir / "voice_brief.json"
        self.no_review = args.no_review
        self.force = set(args.force_stage or [])
        self.brief = self._load_brief(args)

        self.style = self.brief["style"]
        self.aspect_ratio = self.brief["aspect_ratio"]
        self.generator = self.brief["generator"]
        self.language = self.brief["language"]
        self.quality = self.brief["quality"]
        moves = self.brief.get("moves")
        self.moves = moves if moves else list(presets.get("default_moves", []))
        a = self.brief.get("angles")
        self.do_angles = C.is_vertical(self.aspect_ratio) if a is None else bool(a)

    def _load_brief(self, args) -> dict:
        brief = dict(BRIEF_DEFAULTS)
        existing = C.try_load_json(self.avatar_dir / "brief.json")
        if isinstance(existing, dict):
            brief.update({k: v for k, v in existing.items() if v is not None})
        # CLI overrides (only when explicitly provided).
        for key in ("description", "setting", "style", "aspect_ratio",
                    "generator", "language", "voice_description", "quality"):
            val = getattr(args, key, None)
            if val:
                brief[key] = val
        if args.moves is not None:
            brief["moves"] = [m.strip() for m in args.moves.split(",") if m.strip()]
        if args.angles is not None:
            brief["angles"] = args.angles
        brief["name"] = self.name
        return brief

    def save_brief(self):
        C.save_json(self.avatar_dir / "brief.json", self.brief)


# ---------------------------------------------------------------------------
# done predicates
# ---------------------------------------------------------------------------
def _scene_ok(ctx) -> bool:
    d = C.try_load_json(ctx.scene_file)
    return bool(d) and all((d.get(k) or "").strip() for k in C.SCENE_FIELDS)


def _profile_ok(ctx) -> bool:
    d = C.try_load_json(ctx.profile_file)
    return bool(d) and bool((d or {}).get("video_prompt"))


def _voice_brief_ok(ctx) -> bool:
    d = C.try_load_json(ctx.voice_brief_file)
    return bool(d) and bool((d or {}).get("voice_description"))


def done_author(ctx) -> bool:
    return _scene_ok(ctx) and _profile_ok(ctx) and _voice_brief_ok(ctx)


def _hero_crops(ctx):
    if not ctx.refs_dir.is_dir():
        return []
    return sorted(p for p in ctx.refs_dir.glob(f"{ctx.slug}_hero*.png")
                  if "_master" not in p.name)


def done_hero(ctx) -> bool:
    return bool(_hero_crops(ctx))


def _angle_crop(ctx, move) -> Path:
    return ctx.angles_dir / f"{ctx.slug}_{move}_916.png"


def missing_moves(ctx):
    return [m for m in ctx.moves if not _angle_crop(ctx, m).exists()]


def done_angles(ctx) -> bool:
    if not ctx.do_angles or not ctx.moves:
        return True
    return not missing_moves(ctx)


def done_voice(ctx) -> bool:
    idx = C.try_load_json(ctx.voices_dir / "index.json")
    if isinstance(idx, dict) and any((v or {}).get("voice_id") for v in idx.values()):
        return True
    return ctx.voices_dir.is_dir() and any(
        p.name != "index.json" and not p.name.endswith("_design.json")
        for p in ctx.voices_dir.glob("*.json"))


def done_record(ctx) -> bool:
    return (ctx.avatar_dir / "avatar.json").exists() and (ctx.frames_dir / "manifest.json").exists()


# ---------------------------------------------------------------------------
# run functions
# ---------------------------------------------------------------------------
def run_author(ctx):
    if not ctx.brief.get("description"):
        C.stop("INPUT NEEDED -- no character description.", [
            "Pass --description \"...\" to invent this avatar, e.g.:",
            "  python3 invent_avatar.py <name> --description \"...\" --setting office",
        ])
    wrote = []
    if not _scene_ok(ctx):
        C.save_json(ctx.scene_file, C.draft_scene(ctx.brief, ctx.presets))
        wrote.append(ctx.scene_file.name)
    if not _profile_ok(ctx):
        C.save_json(ctx.profile_file, C.draft_talking_profile(ctx.presets))
        wrote.append(ctx.profile_file.name)
    if not _voice_brief_ok(ctx):
        C.save_json(ctx.voice_brief_file, C.draft_voice_brief(ctx.brief, ctx.presets))
        wrote.append(ctx.voice_brief_file.name)
    if ctx.no_review:
        print(f"  [author] drafted {', '.join(wrote) or '(nothing)'} (--no-review).", file=sys.stderr)
        return
    C.stop("AGENT STEP -- review the invented avatar, then re-run to generate.", [
        f"Drafted: {', '.join(wrote) or '(all present)'} in {ctx.avatar_dir}",
        "",
        f"1) {ctx.scene_file.name}  -- subject/wardrobe/scene/light. Refine the SUBJECT into",
        "   a concrete, vivid face/age/hair/expression; tune wardrobe + room to the topic.",
        f"2) {ctx.profile_file.name}  -- the p-video delivery for this person (calm presenter,",
        "   addressing the lens). Adjust if the personality differs.",
        f"3) {ctx.voice_brief_file.name}  -- voice_description for ElevenLabs (age/gender/accent/tone).",
        "",
        "Then re-run the same command to generate the hero still, angles and voice.",
        "(Pass --no-review to skip this pause next time.)",
    ])


def run_hero(ctx):
    if not _scene_ok(ctx):
        raise SystemExit("scene.json incomplete -- finish the author stage first.")
    ctx.refs_dir.mkdir(parents=True, exist_ok=True)
    cmd = [C.PY, str(GENERATE_HERO),
           "--scene-file", str(ctx.scene_file),
           "--style", ctx.style,
           "-ar", ctx.aspect_ratio,
           "--generator", ctx.generator,
           "-q", ctx.quality,
           "--slug", ctx.slug,
           "-o", str(ctx.refs_dir)]
    rc, _ = C.run_child_json(cmd, desc=f"generate_hero ({ctx.generator}, {ctx.style}, {ctx.aspect_ratio})")
    if rc != 0 or not done_hero(ctx):
        raise SystemExit("hero generation failed.")


def _angle_ref(ctx) -> Path | None:
    master = ctx.refs_dir / f"{ctx.slug}_hero_master.png"
    if master.exists():
        return master
    crops = _hero_crops(ctx)
    return crops[0] if crops else None


def run_angles(ctx):
    if not ctx.do_angles or not ctx.moves:
        print("  angles disabled for this avatar -- skipping.", file=sys.stderr)
        return
    ref = _angle_ref(ctx)
    if not ref:
        raise SystemExit("no hero still to derive angles from (run the hero stage first).")
    todo = missing_moves(ctx)
    if not todo:
        return
    ctx.angles_dir.mkdir(parents=True, exist_ok=True)
    cmd = [C.PY, str(C.GENERATE_ANGLES),
           "--ref", str(ref),
           "--scene-file", str(ctx.scene_file),
           "--slug", ctx.slug,
           "-o", str(ctx.angles_dir),
           "--crop916", "-q", ctx.quality]
    for m in todo:
        cmd += ["--move", m]
    rc, _ = C.run_child_json(cmd, desc=f"avatar-camera-angles: {', '.join(todo)}")
    if rc != 0:
        raise SystemExit(f"angle generation failed (exit {rc}).")
    still = missing_moves(ctx)
    if still:
        print(f"  ! angles not produced for: {', '.join(still)} (re-run to retry).", file=sys.stderr)


def run_voice(ctx):
    cmd = [C.PY, str(DESIGN_VOICE),
           "--avatar-dir", str(ctx.avatar_dir),
           "--name", ctx.name,
           "--voice-brief", str(ctx.voice_brief_file)]
    rc, _ = C.run_child_json(cmd, desc="design_voice (ElevenLabs design -> MiniMax clone)")
    if rc != 0 or not done_voice(ctx):
        raise SystemExit(f"voice design/clone failed (exit {rc}).")


def run_record(ctx):
    # Seed frames/ with the hero so anything expecting a clean reference frame works.
    crops = _hero_crops(ctx)
    if crops:
        ctx.frames_dir.mkdir(parents=True, exist_ok=True)
        frame_dst = ctx.frames_dir / "frame_0001.png"
        if not frame_dst.exists():
            shutil.copy2(crops[0], frame_dst)
        C.save_json(ctx.frames_dir / "manifest.json", {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": "invented (avatar-invent)",
            "output_dir": C.rel_to(ctx.frames_dir, ctx.avatar_dir.parent),
            "total_ready": 1,
            "frames": [{
                "seq": 1,
                "file": "frame_0001.png",
                "category": "ready",
                "source": "hero_still",
            }],
        })
    write_report(ctx)


# ---------------------------------------------------------------------------
# Stage table
# ---------------------------------------------------------------------------
STAGES = [
    ("author", done_author, run_author),
    ("hero", done_hero, run_hero),
    ("angles", done_angles, run_angles),
    ("voice", done_voice, run_voice),
    ("record", done_record, run_record),
]


def _voice_ids(ctx):
    idx = C.try_load_json(ctx.voices_dir / "index.json")
    if not isinstance(idx, dict):
        return []
    return [v.get("voice_id") for v in idx.values()
            if isinstance(v, dict) and v.get("voice_id")]


def write_report(ctx) -> dict:
    stage_status = {n: ("complete" if d(ctx) else "pending") for n, d, _ in STAGES}
    ready = all(v == "complete" for v in stage_status.values())
    crops = _hero_crops(ctx)
    master = ctx.refs_dir / f"{ctx.slug}_hero_master.png"
    report = {
        "avatar": ctx.slug,
        "name": ctx.name,
        "invented": True,
        "updated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "ready": ready,
        "brief": ctx.brief,
        "style": ctx.style,
        "setting": ctx.brief.get("setting") or None,
        "aspect_ratio": ctx.aspect_ratio,
        "generator": ctx.generator,
        "language": ctx.language,
        "stages": stage_status,
        "artifacts": {
            "hero": C.rel_to(crops[0], ctx.avatar_dir) if crops else None,
            "hero_master": "refs/" + master.name if master.exists() else None,
            "scene": "scene.json" if _scene_ok(ctx) else None,
            "talking_profile": "talking_profile.json" if _profile_ok(ctx) else None,
            "voice_brief": "voice_brief.json" if _voice_brief_ok(ctx) else None,
            "angles": [f"angles/{ctx.slug}_{m}_916.png" for m in ctx.moves
                       if _angle_crop(ctx, m).exists()],
            "voices": _voice_ids(ctx),
            "voice_design": f"voices/{ctx.name}_design.json"
                if (ctx.voices_dir / f"{ctx.name}_design.json").exists() else None,
            "frames_manifest": "frames/manifest.json"
                if (ctx.frames_dir / "manifest.json").exists() else None,
        },
    }
    # Preserve a 'locations' registry written by the avatar-location skill, so
    # re-running invent_avatar on an avatar that has alternate looks does not
    # clobber them (default location stays implicit: top-level scene.json/angles).
    existing = C.try_load_json(ctx.avatar_dir / "avatar.json")
    if isinstance(existing, dict) and isinstance(existing.get("locations"), dict):
        report["locations"] = existing["locations"]
    C.save_json(ctx.avatar_dir / "avatar.json", report)
    return report


def print_table(ctx, report):
    icon = {"complete": "[x]", "pending": "[ ]"}
    print(f"\nAvatar '{report['avatar']}' -- {'READY' if report['ready'] else 'incomplete'}",
          file=sys.stderr)
    for name, _, _ in STAGES:
        tag = " (agent review)" if name == "author" else ""
        print(f"  {icon.get(report['stages'][name], '[ ]')} {name}{tag}", file=sys.stderr)
    print(f"  report: {ctx.avatar_dir / 'avatar.json'}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="Invent a fictional avatar (image + voice + JSON) from a description.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("avatar_dir", help="Avatar to build. A bare name goes under ./avatares/<name>; an explicit path is used as-is (e.g. nora, avatares/nora, path/to/nora)")
    ap.add_argument("--description", default=None, help="Freeform character description (required first run)")
    ap.add_argument("--setting", default=None,
                    help="Room/context: office, home, studio, street, outdoors, kitchen, cafe, gym, clinic")
    ap.add_argument("--style", default=None,
                    help="photoreal (default) | soft3d | anime | stylized_real | <custom text>")
    ap.add_argument("--aspect-ratio", "-ar", dest="aspect_ratio", default=None, choices=["9:16", "16:9"])
    ap.add_argument("--generator", default=None, choices=["gpt-image-2", "gemini"])
    ap.add_argument("--language", default=None, help="Voice language code (es, en, ...)")
    ap.add_argument("--voice-description", dest="voice_description", default=None,
                    help="Explicit ElevenLabs voice description (else derived from --description)")
    ap.add_argument("--name", default=None, help="Avatar/voice name (default: folder name)")
    ap.add_argument("--quality", default=None, choices=["low", "medium", "high", "auto"])
    ap.add_argument("--moves", default=None, help="Comma-separated camera moves (default: presets)")
    ap.add_argument("--angles", dest="angles", action="store_true", default=None,
                    help="Force camera-angle generation on")
    ap.add_argument("--no-angles", dest="angles", action="store_false",
                    help="Skip camera-angle generation")
    ap.add_argument("--no-review", action="store_true",
                    help="Skip the author checkpoint (draft + continue in one shot)")
    ap.add_argument("--force-stage", action="append", default=[],
                    choices=[s[0] for s in STAGES],
                    help="Re-run this stage even if complete (repeatable)")
    ap.add_argument("--status", action="store_true", help="Print readiness and exit")
    args = ap.parse_args()

    presets = C.load_presets()
    ctx = Ctx(args, presets)
    ctx.avatar_dir.mkdir(parents=True, exist_ok=True)
    ctx.save_brief()

    if args.status:
        print_table(ctx, write_report(ctx))
        return 0

    print(f"Inventing avatar '{ctx.slug}' "
          f"(style={ctx.style}, {ctx.aspect_ratio}, generator={ctx.generator})", file=sys.stderr)

    for name, done, run in STAGES:
        if done(ctx) and name not in ctx.force:
            print(f"  [{name}] already complete -- skipping", file=sys.stderr)
            continue
        print(f"  [{name}] running...", file=sys.stderr)
        run(ctx)

    print_table(ctx, write_report(ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
