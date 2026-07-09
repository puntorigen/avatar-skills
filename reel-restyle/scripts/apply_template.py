#!/usr/bin/env python3
"""Apply a reel TEMPLATE to a NEW avatar + voice + script, end to end.

Single entrypoint that orchestrates the reel-restyle pipeline:

    scaffold_avatar.py    build the new avatar (angles, voice, profile, styles)
    [agent checkpoints]   describe scene.json + talking_profile.json (vision)
    generate_storyboard.py  draft a composer storyboard from the template + script
    [agent review]        refine the text split + author every TODO B-roll
    avatar-reel-composer  compose_reel.py (+ optional finish/polish) -> final.mp4

It is idempotent: scaffolding resumes per stage, the storyboard is only drafted
once (unless --regen-storyboard), and composition runs only with --compose.
By default it STOPS after drafting the storyboard so the agent can author the
B-roll and tune the split before any video is generated.

Examples:
    # 1) scaffold + draft storyboard (stops at the author / review checkpoints):
    python3 apply_template.py mara --template lolo/reel_template.json \
        --picture refs/mara.png --voice samples/mara.wav --script script.txt

    # 2) after authoring scene.json/talking_profile.json + the B-roll, compose:
    python3 apply_template.py mara --template lolo/reel_template.json \
        --picture refs/mara.png --voice samples/mara.wav --script script.txt \
        --compose --finish

    python3 apply_template.py mara --template lolo/reel_template.json --status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _restyle_common as C  # noqa: E402

SCAFFOLD = Path(__file__).resolve().parent / "scaffold_avatar.py"
GEN_SB = Path(__file__).resolve().parent / "generate_storyboard.py"


def _todo_broll(sb_path: Path) -> list[str]:
    sb = C.try_load_json(sb_path) or {}
    return [s.get("id") for s in sb.get("scenes", [])
            if str(s.get("broll_description", "")).startswith("TODO")]


def _status(args, base_dir, avatar_dir):
    rc = C.run_child([C.PY, str(SCAFFOLD), str(avatar_dir),
                      "--template", str(Path(args.template).expanduser().resolve()),
                      "--base-dir", str(base_dir), "--status"],
                     desc="scaffold status")
    sb = _storyboard_path(args, avatar_dir)
    print(f"\nStoryboard: {'present' if sb and sb.exists() else 'not drafted'}"
          + (f"  ({sb})" if sb else ""), file=sys.stderr)
    if sb and sb.exists():
        todo = _todo_broll(sb)
        print(f"  B-roll still TODO: {', '.join(todo) if todo else 'none'}", file=sys.stderr)
    return rc


def _storyboard_path(args, avatar_dir) -> Path | None:
    if args.storyboard:
        return Path(args.storyboard).expanduser()
    if args.slug:
        return avatar_dir / f"{args.slug}.storyboard.json"
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Apply a reel template to a new avatar + voice + script.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("avatar_dir", help="New avatar folder to build/use")
    ap.add_argument("--template", required=True, help="reel_template.json from extract_template.py")
    ap.add_argument("--picture", default=None, help="Reference portrait of the new avatar")
    ap.add_argument("--voice", default=None, help="Clean voice sample of the new avatar")
    ap.add_argument("--name", default=None, help="Voice/avatar name (default: folder name)")
    ap.add_argument("--scene-file", default=None, help="scene.json path (default: <avatar>/scene.json)")
    ap.add_argument("--script", default=None, help="Script text file, or '-' for stdin")
    ap.add_argument("--segments", default=None, help="Agent-authored split JSON (see generate_storyboard.py)")
    ap.add_argument("--slug", default=None, help="Reel slug (default: derived from the script)")
    ap.add_argument("--format", default="reel", choices=["reel", "post", "landscape"])
    ap.add_argument("--resolution", default="720p", choices=["720p", "1080p"])
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--language", default=None, help="Language hint (es, en, ...)")
    ap.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"],
                    help="Angle-image fidelity for scaffolding")
    ap.add_argument("--storyboard", default=None, help="Explicit storyboard output path")
    ap.add_argument("--regen-storyboard", action="store_true", help="Re-draft the storyboard")
    ap.add_argument("--compose", action="store_true", help="Run the composer after drafting")
    ap.add_argument("--finish", action="store_true", help="Pass --finish to the composer (captions+music+fx)")
    ap.add_argument("--compose-dry-run", action="store_true",
                    help="Composer dry-run (narrate+align+slice only)")
    ap.add_argument("--allow-todo", action="store_true",
                    help="Compose even if B-roll descriptions still say TODO (not recommended)")
    ap.add_argument("--base-dir", default=".", help="Base for relative paths")
    ap.add_argument("--status", action="store_true", help="Print readiness and exit")
    args = ap.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve()
    template_path = Path(args.template).expanduser().resolve()
    if not template_path.exists():
        ap.error(f"template not found: {template_path}")
    avatar_dir = Path(args.avatar_dir).expanduser().resolve()

    if args.status:
        return _status(args, base_dir, avatar_dir)

    # --- 1. Scaffold the new avatar (idempotent; may stop at an agent checkpoint) ---
    scaffold_cmd = [C.PY, str(SCAFFOLD), str(avatar_dir),
                    "--template", str(template_path), "--base-dir", str(base_dir),
                    "--quality", args.quality]
    for flag, val in (("--picture", args.picture), ("--voice", args.voice),
                      ("--name", args.name), ("--scene-file", args.scene_file),
                      ("--language", args.language)):
        if val:
            scaffold_cmd += [flag, str(val)]
    rc = C.run_child(scaffold_cmd, desc="reel-restyle: scaffold avatar")
    if rc == 2:
        return 2  # agent checkpoint already printed by scaffold_avatar
    if rc != 0:
        return rc

    # --- 2. Draft the storyboard from the template + script ---
    if not args.script:
        ap.error("--script is required (the new narration text).")
    gen_cmd = [C.PY, str(GEN_SB), "--template", str(template_path),
               "--avatar", str(avatar_dir), "--script", str(args.script),
               "--base-dir", str(base_dir), "--format", args.format,
               "--resolution", args.resolution, "--fps", str(args.fps)]
    if args.language:
        gen_cmd += ["--language", args.language]
    if args.slug:
        gen_cmd += ["--slug", args.slug]
    if args.segments:
        gen_cmd += ["--segments", str(args.segments)]
    sb_path = _storyboard_path(args, avatar_dir)
    if sb_path:
        gen_cmd += ["-o", str(sb_path)]
    if args.regen_storyboard:
        gen_cmd += ["--force"]
    rc, payload = C.run_child_json(gen_cmd, desc="reel-restyle: draft storyboard")
    if rc != 0:
        return rc
    if payload and payload.get("storyboard"):
        sb_path = Path(payload["storyboard"])
    if not sb_path or not sb_path.exists():
        print("  ! storyboard not written; cannot continue.", file=sys.stderr)
        return 1

    todo = _todo_broll(sb_path)

    # --- 3. Compose, or stop for review ---
    if not args.compose:
        lines = [
            f"Storyboard drafted: {sb_path}",
            "Before composing, REVIEW it:",
            "  - tune each scene.text so cuts land on natural phrase boundaries,",
        ]
        if todo:
            lines.append(f"  - AUTHOR the B-roll for: {', '.join(todo)} "
                         "(replace the TODO broll_description/broll_action),")
        lines += [
            "  - TAILOR finish.music_prompt to this reel's topic + tone.",
            "",
            "Then compose with:",
            f"  python3 apply_template.py {avatar_dir.name} --template {C.rel_to(template_path, base_dir)} "
            f"--script {args.script} --compose --finish",
        ]
        C.stop("STORYBOARD READY -- review, then re-run with --compose.", lines, code=0)

    if todo and not args.allow_todo:
        C.stop("AUTHOR B-ROLL before composing.", [
            f"These scenes still have placeholder B-roll: {', '.join(todo)}.",
            f"Edit {sb_path} and replace each TODO broll_description/broll_action,",
            "then re-run with --compose (or pass --allow-todo to override).",
        ], code=2)

    compose_cmd = [C.PY, str(C.COMPOSE_REEL), str(sb_path), "--base-dir", str(base_dir)]
    if args.finish:
        compose_cmd += ["--finish"]
    if args.compose_dry_run:
        compose_cmd += ["--dry-run"]
    rc = C.run_child(compose_cmd, desc="avatar-reel-composer: compose reel")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
