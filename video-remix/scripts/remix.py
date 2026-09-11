#!/usr/bin/env python3
"""Remix a video MOLD onto NEW content, end to end.

Single entrypoint that orchestrates the video-remix REMIX phase as an idempotent
stage machine (mirrors reel-restyle/apply_template.py + avatar-invent):

    avatars     resolve one avatar per mold speaker (reuse avatares/<name>, or
                invent via avatar-invent). If NONE are specified, STOP and ask
                the user (invent N new, or name which existing) — N = mold speakers.
    voices      make sure each avatar has a cloned voice (avatar-invent already
                does; else clone_voice on a provided sample) + record voice_id.
    locations   create the per-scene looks the mold calls for (avatar-location),
                for any content beat carrying a non-default `location` slug.
    storyboard  build_storyboard.py -> avatar-reel-composer storyboard (+ a
                narration plan for multi-speaker molds).
    compose     avatar-reel-composer compose_reel.py --finish -> final.mp4
                (multi-speaker: assemble_narration.py first, then patch guest
                clips and compose with the pre-built narration).

Exit codes: 2 = an agent/user checkpoint is blocking (act, then re-run); 0 =
progressed (stops after the storyboard for review unless --compose); other = error.

Usage:
  python3 remix.py runs/<slug>                     # stages up to storyboard, stops for review
  python3 remix.py runs/<slug> --compose --finish  # all the way to final.mp4
  python3 remix.py runs/<slug> --status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

BUILD_SB = Path(__file__).resolve().parent / "build_storyboard.py"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _avatares_root(base_dir: Path) -> Path:
    import os
    env = os.environ.get("AVATARES_ROOT")
    return Path(env).expanduser() if env else (base_dir / "avatares")


def _voice_id_for(avatar_dir: Path):
    idx = C.try_load_json(avatar_dir / "voices" / "index.json")
    if not idx:
        return None
    if isinstance(idx, dict):
        if idx.get("voice_id"):
            return idx["voice_id"]
        voices = idx.get("voices")
        if isinstance(voices, list) and voices:
            return (voices[0] or {}).get("voice_id")
        if isinstance(voices, dict):
            for v in voices.values():
                if isinstance(v, dict) and v.get("voice_id"):
                    return v["voice_id"]
        for v in idx.values():
            if isinstance(v, dict) and v.get("voice_id"):
                return v["voice_id"]
    if isinstance(idx, list) and idx:
        return (idx[0] or {}).get("voice_id")
    return None


def _speaker_count(blueprint: dict) -> int:
    return max(1, int((blueprint.get("speakers", {}) or {}).get("count") or 1))


# --------------------------------------------------------------------------- #
# stage: avatars
# --------------------------------------------------------------------------- #
def stage_avatars(content: dict, content_path: Path, blueprint: dict, base_dir: Path,
                  *, no_review: bool) -> int:
    avatars = content.get("avatars") or []
    n_needed = _speaker_count(blueprint)
    if len(avatars) < n_needed:
        roles = (blueprint.get("speakers", {}) or {}).get("roles") or \
            (["host"] + [f"guest{i}" for i in range(1, n_needed)])
        while len(avatars) < n_needed:
            avatars.append({"role": roles[len(avatars)] if len(avatars) < len(roles) else f"guest{len(avatars)}",
                            "use": None, "invent": None, "voice_id": None})
        content["avatars"] = avatars
        C.save_json(content_path, content)

    unresolved = []
    for a in avatars:
        role = a.get("role") or "host"
        use = a.get("use")
        if use:
            adir = C.resolve_path(use, base_dir)
            if adir.is_dir():
                continue
            # `use` points nowhere yet — fall through to invent if a brief exists.
        inv = a.get("invent")
        if inv and inv.get("description"):
            name = inv.get("name") or f"{content.get('meta', {}).get('slug') or 'remix'}_{role}"
            target = _avatares_root(base_dir) / name
            cmd = [C.PY, str(C.INVENT_AVATAR), str(target), "--description", inv["description"]]
            for flag, key in (("--setting", "setting"), ("--style", "style"),
                              ("--language", "language"), ("--aspect-ratio", "aspect_ratio")):
                if inv.get(key):
                    cmd += [flag, str(inv[key])]
            if no_review:
                cmd += ["--no-review"]
            rc = C.run_child(cmd, desc=f"avatar-invent: {role} -> {target}")
            if rc == 2:
                C.stop(f"avatar-invent needs your review for '{role}'.",
                       [f"Refine {target}/scene.json + talking_profile.json + voice_brief.json,",
                        "then re-run remix.py to continue."], code=2)
            if rc != 0:
                return rc
            a["use"] = C.rel_to(target, base_dir)
            C.save_json(content_path, content)
            continue
        unresolved.append(role)

    if unresolved:
        existing = sorted(p.name for p in _avatares_root(base_dir).glob("*") if p.is_dir()) \
            if _avatares_root(base_dir).is_dir() else []
        C.stop(f"CHOOSE AVATARS — the mold needs {n_needed} presenter(s): {', '.join(unresolved)}.",
               [f"This reel needs {n_needed} distinct avatar(s) (roles: {', '.join(unresolved)}).",
                "ASK THE USER whether to (a) invent new avatars or (b) reuse existing ones, then edit "
                f"{content_path.name}:",
                "  - reuse: set avatars[].use = \"avatares/<name>\"",
                "  - invent: set avatars[].invent = {\"description\": \"...\", \"setting\": \"studio\", \"language\": \"es\"}",
                f"  existing avatares/: {', '.join(existing) if existing else '(none yet)'}",
                "Then re-run remix.py."], code=2)
    return 0


# --------------------------------------------------------------------------- #
# stage: voices
# --------------------------------------------------------------------------- #
def stage_voices(content: dict, content_path: Path, base_dir: Path) -> int:
    changed = False
    for a in content.get("avatars", []):
        use = a.get("use")
        if not use:
            continue
        adir = C.resolve_path(use, base_dir)
        vid = a.get("voice_id") or _voice_id_for(adir)
        if vid and a.get("voice_id") != vid:
            a["voice_id"] = vid
            changed = True
        if not vid:
            sample = a.get("voice_sample")
            if sample:
                cmd = [C.PY, str(C.CLONE_VOICE), str(C.resolve_path(sample, base_dir)),
                       "--avatar-dir", str(adir), "--no-preview"]
                if a.get("name"):
                    cmd += ["--name", a["name"]]
                rc = C.run_child(cmd, desc=f"voice-clone: {a.get('role')}")
                if rc != 0:
                    return rc
                a["voice_id"] = _voice_id_for(adir)
                changed = True
            else:
                print(f"  ! {a.get('role')}: no cloned voice found under {adir}/voices/ "
                      "(avatar-invent normally makes one; or set avatars[].voice_sample).", file=sys.stderr)
    if changed:
        C.save_json(content_path, content)
    return 0


# --------------------------------------------------------------------------- #
# stage: locations
# --------------------------------------------------------------------------- #
def _host_role_of(content: dict) -> str:
    for a in content.get("avatars", []):
        if a.get("role") == "host":
            return "host"
    avs = content.get("avatars", [])
    return avs[0].get("role", "host") if avs else "host"


def _derive_reel_location(content: dict, blueprint: dict, base_dir: Path):
    """Derive the ONE avatar-location that matches the mold's environment (its
    background + lighting + set elements) and the camera moves the beats use.

    Returns ``(host_role, avatar_dir, slug, cmd_flags, moves)`` or ``None`` when
    the mold has no environment or the author disabled auto-location
    (``content.location.auto == false``). Wardrobe is intentionally NOT copied —
    a location changes ENVIRONMENT + LIGHT only, so the new avatar keeps its own
    outfit/identity while inheriting the reference's look.
    """
    loc_cfg = content.get("location") or {}
    if loc_cfg.get("auto", True) is False:
        return None
    env = blueprint.get("environment") or {}
    background = (env.get("background") or "").strip()
    lighting = (env.get("lighting") or "").strip()
    if not background and not lighting:
        return None  # nothing to reproduce -> keep the avatar's default look

    host_role = _host_role_of(content)
    avatars = {a.get("role"): a for a in content.get("avatars", [])}
    a = avatars.get(host_role) or (content.get("avatars") or [None])[0]
    if not a or not a.get("use"):
        return None
    adir = C.resolve_path(a["use"], base_dir)
    if not adir.is_dir():
        return None

    meta_slug = (content.get("meta", {}) or {}).get("slug") or "mold"
    slug = C.slugify(loc_cfg.get("name") or f"{meta_slug}_look")

    set_elements = env.get("set_elements") or []
    scene_txt = background or (env.get("background_type") or "")
    if set_elements:
        scene_txt = (scene_txt + ". Elementos del set: " + ", ".join(set_elements)).strip(". ")
    brief = (loc_cfg.get("brief") or "").strip()

    moves = C.normalize_moves([b.get("move") for b in blueprint.get("beats", [])])

    fmt = ((content.get("meta", {}) or {}).get("format")
           or blueprint.get("geometry", {}).get("format", "reel"))
    ar = "16:9" if fmt == "landscape" else "9:16"

    cmd_flags: list[str] = ["-ar", ar, "--moves", ",".join(moves)]
    if scene_txt:
        cmd_flags += ["--scene", scene_txt]
    if lighting:
        cmd_flags += ["--light", lighting]
    if brief:
        cmd_flags += ["--brief", brief]
    for asset in (loc_cfg.get("assets") or []):
        ap = C.resolve_path(asset, base_dir)
        if ap.exists():
            cmd_flags += ["--asset", str(ap)]
    return host_role, adir, slug, cmd_flags, moves


def _location_ready(adir: Path, slug: str, moves: list[str], suffix: str) -> bool:
    ang = adir / "locations" / slug / "angles"
    if not ang.is_dir():
        return False
    for m in moves:
        if not list(ang.glob(f"*{m}*_{suffix}.png")) and not list(ang.glob(f"*{m}*.png")):
            return False
    return True


def stage_locations(content: dict, content_path: Path, blueprint: dict, base_dir: Path,
                    *, no_review: bool) -> int:
    avatars = {a.get("role"): a for a in content.get("avatars", [])}

    # --- (a) explicit per-beat locations (unchanged behavior) ---
    wanted: dict = {}   # (role, loc) -> brief
    for b in content.get("beats", []):
        loc = (b.get("location") or "").strip()
        if not loc or loc == "default":
            continue
        role = b.get("speaker") or "host"
        wanted[(role, loc)] = b.get("location_hint") or b.get("location_brief") or ""
    for (role, loc), brief in wanted.items():
        a = avatars.get(role) or avatars.get("host")
        if not a or not a.get("use"):
            continue
        adir = C.resolve_path(a["use"], base_dir)
        if (adir / "locations" / loc).is_dir():
            continue
        cmd = [C.PY, str(C.CREATE_LOCATION), str(adir), loc]
        if brief:
            cmd += ["--brief", brief]
        if no_review:
            cmd += ["--no-review"]
        rc = C.run_child(cmd, desc=f"avatar-location: {adir.name} / {loc}")
        if rc == 2:
            C.stop(f"avatar-location needs your review for '{adir.name}/{loc}'.",
                   [f"Refine {adir}/locations/{loc}/scene.json, then re-run remix.py."], code=2)
        if rc != 0:
            return rc

    # --- (b) auto reel-level location matching the mold's environment ---
    derived = _derive_reel_location(content, blueprint, base_dir)
    if derived is None:
        return 0
    host_role, adir, slug, cmd_flags, moves = derived

    # Record the chosen reel look so build_storyboard sets storyboard["location"].
    loc_cfg = dict(content.get("location") or {})
    if loc_cfg.get("name") != slug or "name" not in loc_cfg:
        loc_cfg["name"] = slug
        loc_cfg.setdefault("auto", True)
        content["location"] = loc_cfg
        C.save_json(content_path, content)

    fmt = ((content.get("meta", {}) or {}).get("format")
           or blueprint.get("geometry", {}).get("format", "reel"))
    suffix = "169" if fmt == "landscape" else "916"
    if _location_ready(adir, slug, moves, suffix):
        print(f"  [locations] reel look '{slug}' ready ({', '.join(moves)}).", file=sys.stderr)
        return 0

    cmd = [C.PY, str(C.CREATE_LOCATION), str(adir), slug] + cmd_flags
    if no_review:
        cmd += ["--no-review"]
    rc = C.run_child(cmd, desc=f"avatar-location (auto, from mold environment): "
                              f"{adir.name} / {slug}  [{', '.join(moves)}]")
    if rc == 2:
        C.stop(f"avatar-location needs your review for the mold look '{adir.name}/{slug}'.",
               [f"The remix derived this look from the reference's environment:",
                f"  {adir}/locations/{slug}/scene.json",
                "Refine wardrobe/scene/light (keep the avatar's identity), then re-run remix.py.",
                "(Pass --no-review to skip this checkpoint.)"], code=2)
    if rc != 0:
        return rc
    return 0


# --------------------------------------------------------------------------- #
# stage: storyboard
# --------------------------------------------------------------------------- #
def stage_storyboard(run_dir: Path, blueprint_path: Path, content_path: Path, base_dir: Path,
                     *, slug: str, fmt: str | None, resolution: str, fps: int,
                     regen: bool) -> tuple[int, dict | None]:
    sb_path = run_dir / f"{slug}.storyboard.json"
    cmd = [C.PY, str(BUILD_SB), "--blueprint", str(blueprint_path), "--content", str(content_path),
           "--base-dir", str(base_dir), "--slug", slug, "--resolution", resolution,
           "--fps", str(fps), "-o", str(sb_path)]
    if fmt:
        cmd += ["--format", fmt]
    if regen:
        cmd += ["--force"]
    rc, payload = C.run_child_json(cmd, desc="video-remix: build storyboard")
    return rc, payload


def _todo_broll(sb_path: Path) -> list[str]:
    sb = C.try_load_json(sb_path) or {}
    return [s.get("id") for s in sb.get("scenes", [])
            if str(s.get("broll_description", "")).startswith("TODO")]


# --------------------------------------------------------------------------- #
# stage: compose (single + multi-avatar)
# --------------------------------------------------------------------------- #
def stage_compose(sb_path: Path, plan_path: Path | None, content: dict, base_dir: Path,
                  *, slug: str, finish: bool, dry_run: bool, language: str | None) -> int:
    storyboard = C.load_json(sb_path)
    host_rel = storyboard.get("avatar_dir")
    reel_dir = (base_dir / host_rel / "reels" / slug).resolve()

    if plan_path and Path(plan_path).exists():
        reel_dir.mkdir(parents=True, exist_ok=True)
        acmd = [C.PY, str(C.ASSEMBLE_NARRATION), str(plan_path), "--base-dir", str(base_dir),
                "--out-dir", str(reel_dir)]
        if language:
            acmd += ["--language", language]
        rc, out = C.run_child_json(acmd, desc="avatar-reel-composer: assemble multi-avatar narration")
        if rc != 0:
            return rc
        # Patch guest scenes' broll_clip from the assembled segments (match by slug).
        clip_by_slug = {}
        for rec in (out or {}).get("segments", []):
            if rec.get("kind") == "guest" and rec.get("clip"):
                clip_by_slug[rec.get("slug")] = rec["clip"]
        for s in storyboard.get("scenes", []):
            if s.get("type") == "guest":
                gslug = s.get("_guest_slug")
                clip = clip_by_slug.get(gslug)
                if clip:
                    s["broll_clip"] = C.rel_to(clip, base_dir)
                for k in ("_guest_avatar_dir", "_guest_image", "_guest_voice_id", "_guest_slug"):
                    s.pop(k, None)
        # Persist the patched storyboard INTO the reel dir so compose reuses the narration.
        sb_in_reel = reel_dir / "storyboard.json"
        C.save_json(sb_in_reel, storyboard)
        ccmd = [C.PY, str(C.COMPOSE_REEL), str(sb_in_reel), "--base-dir", str(base_dir),
                "--out-dir", str(reel_dir)]
        if finish:
            ccmd += ["--finish"]
        if dry_run:
            ccmd += ["--dry-run"]
        if language:
            ccmd += ["--language", language]
        return C.run_child(ccmd, desc="avatar-reel-composer: compose (multi-avatar)")

    # Single-avatar path.
    ccmd = [C.PY, str(C.COMPOSE_REEL), str(sb_path), "--base-dir", str(base_dir),
            "--out-dir", str(reel_dir)]
    if finish:
        ccmd += ["--finish"]
    if dry_run:
        ccmd += ["--dry-run"]
    if language:
        ccmd += ["--language", language]
    return C.run_child(ccmd, desc="avatar-reel-composer: compose reel")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Remix a video mold onto new content (avatars -> ... -> final.mp4).")
    ap.add_argument("run_dir", help="Analyze run dir containing blueprint.json + content.json")
    ap.add_argument("--content", default=None, help="content.json (default: <run_dir>/content.json)")
    ap.add_argument("--blueprint", default=None, help="blueprint.json (default: <run_dir>/blueprint.json)")
    ap.add_argument("--base-dir", default=".", help="Base for relative paths (avatares/, reels/)")
    ap.add_argument("--slug", default=None, help="Reel slug (default: content.meta.slug or derived)")
    ap.add_argument("--format", default=None, choices=["reel", "post", "landscape"],
                    help="Override output format (default: content.meta.format or the mold's)")
    ap.add_argument("--resolution", default="720p", choices=["720p", "1080p"])
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-review", action="store_true", help="Skip avatar-invent/location review checkpoints")
    ap.add_argument("--regen-storyboard", action="store_true", help="Re-draft the storyboard")
    ap.add_argument("--compose", action="store_true", help="Compose after the storyboard is ready")
    ap.add_argument("--finish", action="store_true", help="Pass --finish to the composer (captions+music+fx)")
    ap.add_argument("--dry-run", action="store_true", help="Composer dry-run (narrate+align+slice only)")
    ap.add_argument("--allow-todo", action="store_true", help="Compose even if B-roll is still TODO")
    ap.add_argument("--status", action="store_true", help="Print readiness and exit")
    args = ap.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve()
    run_dir = Path(args.run_dir).expanduser().resolve()
    blueprint_path = Path(args.blueprint).expanduser() if args.blueprint else (run_dir / "blueprint.json")
    content_path = Path(args.content).expanduser() if args.content else (run_dir / "content.json")
    if not blueprint_path.exists():
        ap.error(f"blueprint not found: {blueprint_path}")
    if not content_path.exists():
        C.stop("No content.json yet.", [
            f"Copy the skeleton and author it: cp {run_dir / 'content_template.json'} {content_path}",
            "Fill `script` (full verbatim narration), set `avatars`, author every B-roll beat,",
            "then re-run remix.py.", ], code=2)

    blueprint = C.load_json(blueprint_path)
    content = C.load_json(content_path)
    meta = content.get("meta", {}) or {}
    slug = args.slug or meta.get("slug") or C.slugify(meta.get("topic") or run_dir.name)
    language = meta.get("language")

    if args.status:
        n = _speaker_count(blueprint)
        avs = content.get("avatars", [])
        resolved = sum(1 for a in avs if a.get("use") and C.resolve_path(a["use"], base_dir).is_dir())
        sb = run_dir / f"{slug}.storyboard.json"
        print(f"Speakers needed: {n}  ·  avatars resolved: {resolved}/{len(avs)}", file=sys.stderr)
        print(f"Storyboard: {'present' if sb.exists() else 'not built'}"
              + (f" ({sb})" if sb.exists() else ""), file=sys.stderr)
        if sb.exists():
            todo = _todo_broll(sb)
            print(f"  B-roll still TODO: {', '.join(todo) if todo else 'none'}", file=sys.stderr)
        return 0

    # --- 1. avatars ---
    rc = stage_avatars(content, content_path, blueprint, base_dir, no_review=args.no_review)
    if rc != 0:
        return rc
    content = C.load_json(content_path)  # reload (avatars stage may have persisted use paths)

    # --- 2. voices ---
    rc = stage_voices(content, content_path, base_dir)
    if rc != 0:
        return rc
    content = C.load_json(content_path)

    # --- 3. locations ---
    rc = stage_locations(content, content_path, blueprint, base_dir, no_review=args.no_review)
    if rc != 0:
        return rc
    content = C.load_json(content_path)  # reload (locations stage may set the reel look)

    # --- 4. storyboard ---
    rc, payload = stage_storyboard(run_dir, blueprint_path, content_path, base_dir,
                                   slug=slug, fmt=args.format, resolution=args.resolution,
                                   fps=args.fps, regen=args.regen_storyboard)
    if rc != 0:
        return rc
    sb_path = Path((payload or {}).get("storyboard") or (run_dir / f"{slug}.storyboard.json"))
    plan_path = (payload or {}).get("narration_plan")
    plan_path = Path(plan_path) if plan_path else None
    if not sb_path.exists():
        print("  ! storyboard not written; cannot continue.", file=sys.stderr)
        return 1
    todo = _todo_broll(sb_path)

    # --- 5. compose or stop for review ---
    if not args.compose:
        lines = [f"Storyboard drafted: {sb_path}", "Before composing, REVIEW it:",
                 "  - tune each scene.text so cuts land on natural phrase boundaries,"]
        if todo:
            lines.append(f"  - AUTHOR the B-roll for: {', '.join(todo)} (replace the TODO fields),")
        lines += ["  - TAILOR finish.music_prompt to this reel's topic + tone.",
                  "", "Then compose with:",
                  f"  python3 remix.py {args.run_dir} --compose --finish"]
        C.stop("STORYBOARD READY — review, then re-run with --compose.", lines, code=0)

    if todo and not args.allow_todo:
        C.stop("AUTHOR B-ROLL before composing.",
               [f"These scenes still have placeholder B-roll: {', '.join(todo)}.",
                f"Edit {sb_path} (or content.json) and replace each TODO, then re-run with --compose "
                "(or pass --allow-todo)."], code=2)

    return stage_compose(sb_path, plan_path, content, base_dir, slug=slug,
                         finish=args.finish, dry_run=args.dry_run, language=language)


if __name__ == "__main__":
    raise SystemExit(main())
