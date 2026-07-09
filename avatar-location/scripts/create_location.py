#!/usr/bin/env python3
"""Create a new LOCATION (a look) for an existing avatar.

A location keeps the avatar's IDENTITY (face, gestures, voice, talking_profile)
and only varies the LOOK: wardrobe + environment + light, optionally with asset
refs (a logo on a shirt, a prop in the scene). It produces an identity-anchored
hero still + camera angles under ``<avatar>/locations/<loc>/``, selectable later
per reel / per scene by avatar-reel-composer. The avatar's *default* location is
just what exists today (the top-level ``scene.json`` + ``angles/``) — untouched.

Idempotent stage machine (resume on re-run), mirroring avatar-invent:

    author  [AGENT]  seed locations/<loc>/scene.json (subject copied from the
                     avatar + NEW wardrobe/scene/light from --setting/--brief/
                     flags/--from-image, + asset refs), then pause once for
                     review before any paid generation.
    hero             generate_hero.py --anchor-identity --ref <avatar hero_master>
                     [--ref <asset>...]  -> locations/<loc>/refs/<slug>__<loc>_hero.png
    angles           generate_angles.py --ref <location hero> [--ref <asset>...]
                     -> locations/<loc>/angles/<slug>__<loc>_<move>_916.png
    record           write location.json + merge into avatar.json 'locations'

Examples:
    # Seed from a preset setting, review, then generate
    python3 create_location.py nora studio_night --setting studio \
        --brief "evening content-studio, moody teal key light, black turtleneck"
    # ...refine nora/locations/studio_night/scene.json, then re-run:
    python3 create_location.py nora studio_night

    # A branded look with a logo stamped on the shirt
    python3 create_location.py doki-monster brand_tee \
        --asset doki-monster/brand/logo-primary.png \
        --asset-placement "printed large and centered on the chest of the white t-shirt" \
        --no-review

    python3 create_location.py nora studio_night --status
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _common as C  # noqa: E402

SCENE_FIELDS = ("subject", "wardrobe", "scene", "light")


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, args, presets):
        self.presets = presets
        self.avatar_dir = Path(args.avatar_dir).expanduser().resolve()
        if not self.avatar_dir.is_dir():
            raise SystemExit(f"avatar dir not found: {self.avatar_dir}")
        self.avatar_slug = self.avatar_dir.name
        self.loc = C.slugify(args.location)
        self.name = args.name or args.location.strip() or self.loc
        self.slug = f"{self.avatar_slug}__{self.loc}"

        self.loc_dir = self.avatar_dir / "locations" / self.loc
        self.refs_dir = self.loc_dir / "refs"
        self.angles_dir = self.loc_dir / "angles"
        self.assets_dir = self.loc_dir / "assets"
        self.scene_file = self.loc_dir / "scene.json"
        self.location_file = self.loc_dir / "location.json"

        self.avatar_scene = C.try_load_json(self.avatar_dir / "scene.json") or {}
        self.avatar_json = C.try_load_json(self.avatar_dir / "avatar.json") or {}

        # Look defaults inherited from the avatar (overridable per-flag).
        self.style = args.style or self.avatar_json.get("style") or "photoreal"
        self.aspect_ratio = args.aspect_ratio or self.avatar_json.get("aspect_ratio") or "9:16"
        self.generator = args.generator or self.avatar_json.get("generator") or "gpt-image-2"
        self.quality = args.quality or "high"
        moves = [m.strip() for m in (args.moves or "").split(",") if m.strip()]
        self.moves = moves or list(presets.get("default_moves", []))

        self.no_review = args.no_review
        self.force = set(args.force_stage or [])
        self.brief = (args.brief or "").strip()
        # Raw look flags (used by draft_scene / the location record).
        self._args_setting = args.setting
        self._args_wardrobe = args.wardrobe
        self._args_scene = args.scene
        self._args_light = args.light
        self.assets = self._collect_assets(args)
        self.from_image = Path(args.from_image).expanduser() if args.from_image else None
        if self.from_image and not self.from_image.exists():
            raise SystemExit(f"--from-image not found: {self.from_image}")

    def _collect_assets(self, args) -> list[dict]:
        out = []
        srcs = args.asset or []
        placements = args.asset_placement or []
        if placements and len(placements) != len(srcs):
            raise SystemExit("--asset-placement count must match --asset count (or omit placements).")
        for i, src in enumerate(srcs):
            p = Path(src).expanduser()
            if not p.exists():
                raise SystemExit(f"--asset not found: {p}")
            placement = (placements[i] if i < len(placements) else "").strip() \
                or "incorporated faithfully as shown in the attached reference"
            out.append({"src": p, "placement": placement})
        return out

    # Identity anchor: the avatar's master hero (so a re-dressed/re-roomed look
    # stays the exact same person). Falls back to any clean reference image.
    def identity_anchor(self) -> Path | None:
        hm = (self.avatar_json.get("artifacts") or {}).get("hero_master")
        cands = []
        if hm:
            cands.append(self.avatar_dir / hm)
        cands += [
            self.avatar_dir / "refs" / f"{self.avatar_slug}_hero_master.png",
            self.avatar_dir / "refs" / f"{self.avatar_slug}_hero.png",
        ]
        for c in cands:
            if c.exists():
                return c
        for sub in ("refs", "frames", "angles"):
            img = C.first_image(self.avatar_dir / sub)
            if img:
                return img
        return None


# ---------------------------------------------------------------------------
# done predicates
# ---------------------------------------------------------------------------
def _scene_ok(ctx) -> bool:
    d = C.try_load_json(ctx.scene_file)
    return bool(d) and all((str(d.get(k) or "")).strip() for k in SCENE_FIELDS)


def _hero_crops(ctx):
    if not ctx.refs_dir.is_dir():
        return []
    return sorted(p for p in ctx.refs_dir.glob(f"{ctx.slug}_hero*.png")
                  if "_master" not in p.name)


def _hero_master(ctx) -> Path | None:
    m = ctx.refs_dir / f"{ctx.slug}_hero_master.png"
    if m.exists():
        return m
    crops = _hero_crops(ctx)
    return crops[0] if crops else None


def _angle_crop(ctx, move) -> Path:
    return ctx.angles_dir / f"{ctx.slug}_{move}_916.png"


def missing_moves(ctx):
    return [m for m in ctx.moves if not _angle_crop(ctx, m).exists()]


def done_author(ctx) -> bool:
    return _scene_ok(ctx)


def done_hero(ctx) -> bool:
    return bool(_hero_crops(ctx))


def done_angles(ctx) -> bool:
    if not ctx.moves:
        return True
    return not missing_moves(ctx)


def done_record(ctx) -> bool:
    rec = C.try_load_json(ctx.location_file)
    if not rec or not rec.get("status"):
        return False
    locs = (ctx.avatar_json.get("locations") or {})
    return ctx.loc in locs


# ---------------------------------------------------------------------------
# author
# ---------------------------------------------------------------------------
def _asset_refs(ctx) -> list[Path]:
    """Resolve the asset files recorded in the location scene.json (assets[].file)."""
    d = C.try_load_json(ctx.scene_file) or {}
    out = []
    for a in d.get("assets") or []:
        f = (a.get("file") or "") if isinstance(a, dict) else ""
        if not f:
            continue
        p = (ctx.loc_dir / f)
        if p.exists():
            out.append(p)
    return out


def draft_scene(ctx) -> dict:
    """Seed the location's scene.json: subject copied from the avatar, look from
    --setting / explicit flags / --brief, falling back to the avatar's own look so
    every field is non-empty (a valid no-op look) even with --no-review."""
    base = {
        "subject": (ctx.avatar_scene.get("subject") or "").strip(),
        "wardrobe": (ctx.avatar_scene.get("wardrobe") or "").strip(),
        "scene": (ctx.avatar_scene.get("scene") or "").strip(),
        "light": (ctx.avatar_scene.get("light") or "").strip()
        or ctx.presets.get("default_light", ""),
    }
    if ctx._args_setting:
        s = (ctx.presets.get("settings") or {}).get(ctx._args_setting.lower())
        if s:
            base["wardrobe"] = s.get("wardrobe", base["wardrobe"])
            base["scene"] = s.get("scene", base["scene"])
            base["light"] = ctx.presets.get("default_light", base["light"])
    if ctx.brief:
        # A free-text brief most often describes the environment/look as a whole.
        # Seed it into SETTING; the author checkpoint is where the agent splits it
        # into precise wardrobe / scene / light. (--no-review keeps it as-is.)
        base["scene"] = ctx.brief
    if ctx._args_wardrobe:
        base["wardrobe"] = ctx._args_wardrobe
    if ctx._args_scene:
        base["scene"] = ctx._args_scene
    if ctx._args_light:
        base["light"] = ctx._args_light
    if ctx.assets:
        base["assets"] = [{"file": f"assets/{a['src'].name}", "placement": a["placement"]}
                          for a in ctx.assets]
    return base


def run_author(ctx):
    if not (ctx.avatar_scene.get("subject") or "").strip():
        C.stop("INPUT NEEDED -- the avatar has no scene.json subject.", [
            f"Expected a subject in {ctx.avatar_dir / 'scene.json'}.",
            "A location reuses the avatar's identity; the avatar must exist first.",
        ])
    ctx.loc_dir.mkdir(parents=True, exist_ok=True)
    # Copy asset refs into the location's assets/ folder (so the look is self-contained).
    if ctx.assets:
        ctx.assets_dir.mkdir(parents=True, exist_ok=True)
        for a in ctx.assets:
            dst = ctx.assets_dir / a["src"].name
            if not dst.exists() or dst.resolve() != a["src"].resolve():
                shutil.copy2(a["src"], dst)
    # Copy a look reference (if any) into refs/.
    look_ref_rel = None
    if ctx.from_image:
        ctx.refs_dir.mkdir(parents=True, exist_ok=True)
        dst = ctx.refs_dir / f"look_reference{ctx.from_image.suffix.lower()}"
        if not dst.exists() or dst.resolve() != ctx.from_image.resolve():
            shutil.copy2(ctx.from_image, dst)
        look_ref_rel = C.rel_to(dst, ctx.loc_dir)

    wrote = []
    if not _scene_ok(ctx):
        C.save_json(ctx.scene_file, draft_scene(ctx))
        wrote.append(ctx.scene_file.name)
    # Seed the location record early so --status / list_locations work pre-generation.
    _write_location_record(ctx, status="draft", look_ref=look_ref_rel)

    if ctx.no_review:
        print(f"  [author] drafted {', '.join(wrote) or '(present)'} (--no-review).", file=sys.stderr)
        return
    lines = [
        f"Drafted: {', '.join(wrote) or '(scene present)'} in {ctx.loc_dir}",
        "",
        f"Edit {ctx.scene_file} -- the LOOK only (the subject is the avatar's, keep it):",
        "  * wardrobe : the new outfit (be specific: garment, color, material).",
        "  * scene    : the new environment / background.",
        "  * light    : the lighting mood for this look.",
    ]
    if ctx.assets:
        lines += ["  * assets[] : {file, placement} -- refine each placement instruction.",
                  "    (asset images were copied into assets/.)"]
    if look_ref_rel:
        lines += [f"  * a look reference was saved at {look_ref_rel} and will be attached to the hero."]
    lines += [
        "",
        "Then re-run the same command to generate the identity-anchored hero + angles.",
        "(Pass --no-review to skip this pause next time.)",
    ]
    C.stop("AGENT STEP -- review the location LOOK, then re-run to generate.", lines)


# ---------------------------------------------------------------------------
# hero
# ---------------------------------------------------------------------------
def run_hero(ctx):
    if not _scene_ok(ctx):
        raise SystemExit("location scene.json incomplete -- finish the author stage first.")
    anchor = ctx.identity_anchor()
    if not anchor:
        raise SystemExit(f"no identity anchor found for avatar '{ctx.avatar_slug}' "
                         f"(expected refs/{ctx.avatar_slug}_hero_master.png).")
    ctx.refs_dir.mkdir(parents=True, exist_ok=True)
    refs = [anchor]
    look_ref = ctx.refs_dir / next((f"look_reference{e}" for e in C.IMAGE_EXTS
                                    if (ctx.refs_dir / f"look_reference{e}").exists()), "look_reference.png")
    if look_ref.exists():
        refs.append(look_ref)
    refs += _asset_refs(ctx)
    if len(refs) > 4:
        print(f"  ! {len(refs)} reference images -- gpt-image-2 favors few; "
              f"trim to identity + 1-2 assets if identity drifts.", file=sys.stderr)

    cmd = [C.PY, str(C.GENERATE_HERO),
           "--scene-file", str(ctx.scene_file),
           "--anchor-identity",
           "--style", ctx.style,
           "-ar", ctx.aspect_ratio,
           "--generator", ctx.generator,
           "-q", ctx.quality,
           "--slug", ctx.slug,
           "-o", str(ctx.refs_dir)]
    for r in refs:
        cmd += ["--ref", str(r)]
    rc, _ = C.run_child_json(cmd, desc=f"generate_hero (identity-anchored, {ctx.style}, {ctx.aspect_ratio})")
    if rc != 0 or not done_hero(ctx):
        raise SystemExit("location hero generation failed.")


# ---------------------------------------------------------------------------
# angles
# ---------------------------------------------------------------------------
def run_angles(ctx):
    if not ctx.moves:
        print("  no moves configured -- skipping angles.", file=sys.stderr)
        return
    ref = _hero_master(ctx)
    if not ref:
        raise SystemExit("no location hero to derive angles from (run the hero stage first).")
    todo = missing_moves(ctx)
    if not todo:
        return
    ctx.angles_dir.mkdir(parents=True, exist_ok=True)
    refs = [ref] + _asset_refs(ctx)
    cmd = [C.PY, str(C.GENERATE_ANGLES),
           "--scene-file", str(ctx.scene_file),
           "--slug", ctx.slug,
           "-o", str(ctx.angles_dir),
           "--crop916", "-q", ctx.quality]
    for r in refs:
        cmd += ["--ref", str(r)]
    for m in todo:
        cmd += ["--move", m]
    rc, _ = C.run_child_json(cmd, desc=f"avatar-camera-angles: {', '.join(todo)}")
    if rc != 0:
        raise SystemExit(f"angle generation failed (exit {rc}).")
    still = missing_moves(ctx)
    if still:
        print(f"  ! angles not produced for: {', '.join(still)} (re-run to retry).", file=sys.stderr)


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------
def _write_location_record(ctx, *, status, look_ref=None) -> dict:
    scene = C.try_load_json(ctx.scene_file) or {}
    crops = _hero_crops(ctx)
    master = ctx.refs_dir / f"{ctx.slug}_hero_master.png"
    angles = [C.rel_to(_angle_crop(ctx, m), ctx.loc_dir) for m in ctx.moves
              if _angle_crop(ctx, m).exists()]
    prev = C.try_load_json(ctx.location_file) or {}
    rec = {
        "avatar": ctx.avatar_slug,
        "location": ctx.loc,
        "name": ctx.name,
        "brief": ctx.brief or prev.get("brief", ""),
        "source": ("from-image" if ctx.from_image else
                   ("brief" if ctx.brief else
                    ("setting" if ctx._args_setting else "flags"))),
        "status": status,
        "style": ctx.style,
        "aspect_ratio": ctx.aspect_ratio,
        "generator": ctx.generator,
        "created_at": prev.get("created_at") or datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "scene": "scene.json",
        "look": {k: scene.get(k, "") for k in ("wardrobe", "scene", "light")},
        "assets": scene.get("assets", []),
        "look_reference": look_ref or prev.get("look_reference"),
        "moves": ctx.moves,
        "hero": C.rel_to(crops[0], ctx.loc_dir) if crops else None,
        "hero_master": ("refs/" + master.name) if master.exists() else None,
        "angles": angles,
    }
    C.save_json(ctx.location_file, rec)
    return rec


def _register_in_avatar(ctx, rec):
    """Merge this location into the avatar.json 'locations' registry (additive,
    preserves any other keys / shape; works for invented or cloned avatars)."""
    av_path = ctx.avatar_dir / "avatar.json"
    av = C.try_load_json(av_path) or {}
    locs = av.get("locations")
    if not isinstance(locs, dict):
        locs = {}
    locs[ctx.loc] = {
        "name": rec["name"],
        "dir": C.rel_to(ctx.loc_dir, ctx.avatar_dir),
        "status": rec["status"],
        "angles": len(rec.get("angles") or []),
        "assets": len(rec.get("assets") or []),
        "updated_at": rec["updated_at"],
    }
    av["locations"] = locs
    C.save_json(av_path, av)
    ctx.avatar_json = av


def run_record(ctx):
    status = "ready" if (done_hero(ctx) and done_angles(ctx)) else "partial"
    look_ref = (C.try_load_json(ctx.location_file) or {}).get("look_reference")
    rec = _write_location_record(ctx, status=status, look_ref=look_ref)
    _register_in_avatar(ctx, rec)


# ---------------------------------------------------------------------------
# Stage table
# ---------------------------------------------------------------------------
STAGES = [
    ("author", done_author, run_author),
    ("hero", done_hero, run_hero),
    ("angles", done_angles, run_angles),
    ("record", done_record, run_record),
]


def print_table(ctx):
    icon = {True: "[x]", False: "[ ]"}
    ready = all(d(ctx) for _, d, _ in STAGES)
    print(f"\nLocation '{ctx.loc}' for avatar '{ctx.avatar_slug}' -- "
          f"{'READY' if ready else 'incomplete'}", file=sys.stderr)
    for name, done, _ in STAGES:
        tag = " (agent review)" if name == "author" else ""
        print(f"  {icon[done(ctx)]} {name}{tag}", file=sys.stderr)
    print(f"  dir: {ctx.loc_dir}", file=sys.stderr)
    if done_angles(ctx):
        print(f"  angles: {', '.join(ctx.moves)}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="Create a new look (location) for an existing avatar.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("avatar_dir", help="Existing avatar folder (e.g. nora or doki-monster)")
    ap.add_argument("location", help="Location name / slug (e.g. studio_night)")
    ap.add_argument("--name", default=None, help="Display name (default: derived from the location)")
    ap.add_argument("--brief", default=None, help="Free-text look description (environment/wardrobe/mood)")
    ap.add_argument("--setting", default=None,
                    help="Preset setting keyword (office, home, studio, street, outdoors, "
                         "kitchen, cafe, gym, clinic) for a quick wardrobe+scene seed")
    ap.add_argument("--wardrobe", default=None, help="Explicit wardrobe text")
    ap.add_argument("--scene", default=None, help="Explicit scene/environment text")
    ap.add_argument("--light", default=None, help="Explicit lighting text")
    ap.add_argument("--from-image", dest="from_image", default=None,
                    help="A reference image of the desired look; attached to the hero generation")
    ap.add_argument("--asset", action="append", default=[], metavar="PATH",
                    help="Asset image to incorporate (logo/prop), repeatable")
    ap.add_argument("--asset-placement", action="append", default=[], metavar="TEXT",
                    help="Placement for the matching --asset (repeatable, paired by order)")
    ap.add_argument("--style", default=None, help="Render style override (default: avatar's style)")
    ap.add_argument("--aspect-ratio", "-ar", dest="aspect_ratio", default=None, choices=["9:16", "16:9"])
    ap.add_argument("--generator", default=None, choices=["gpt-image-2", "gemini"])
    ap.add_argument("--quality", default=None, choices=["low", "medium", "high", "auto"],
                    help="gpt-image-2 fidelity (use 'low' to scout cheaply; default high)")
    ap.add_argument("--moves", default=None, help="Comma-separated camera moves (default: presets)")
    ap.add_argument("--no-review", action="store_true",
                    help="Skip the author checkpoint (draft + continue in one shot)")
    ap.add_argument("--force-stage", action="append", default=[],
                    choices=[s[0] for s in STAGES],
                    help="Re-run this stage even if complete (repeatable)")
    ap.add_argument("--status", action="store_true", help="Print readiness and exit")
    args = ap.parse_args()

    presets = C.load_presets()
    ctx = Ctx(args, presets)

    if args.status:
        print_table(ctx)
        return 0

    print(f"Creating location '{ctx.loc}' for '{ctx.avatar_slug}' "
          f"(style={ctx.style}, {ctx.aspect_ratio}, generator={ctx.generator})", file=sys.stderr)

    for name, done, run in STAGES:
        if done(ctx) and name not in ctx.force:
            print(f"  [{name}] already complete -- skipping", file=sys.stderr)
            continue
        print(f"  [{name}] running...", file=sys.stderr)
        run(ctx)

    print_table(ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
