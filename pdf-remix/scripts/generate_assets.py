#!/usr/bin/env python3
"""Generate every image asset a content.json needs, in the reference PDF's style.

Reads the authored content.json (pages[].assets[]) plus the blueprint's design
motifs, then calls the asset-generator skill once per asset. A global "style
directive" derived from the mold keeps all imagery visually consistent
(cinematic film grain, muted chiaroscuro, etc.). Author portraits reuse the
brand's reference photos so the same person appears in a pose that fits the page.

Usage:
  python3 generate_assets.py --content runs/foo/content.json \
      [--assets-dir runs/foo/assets] [--blueprint runs/trampas/blueprint.json] \
      [--only p05_photo,p01_portrait] [--force] [--dry-run]

Each asset object in content.json:
  {"id":"p05_photo","kind":"emotive_photo|author_portrait|symbolic_bg|
        product_mockup|texture|hero_photo","prompt":"what to depict",
   "aspect":"2:3","use_reference":false,"treatment":"","transparent":false}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

DEFAULT_DIRECTIVE = (
    "Cinematic editorial photography, 35mm film grain, muted melancholic color "
    "grade, dramatic chiaroscuro lighting, intimate and introspective mood, "
    "natural shadows, shallow depth of field, high production value. "
    "ABSOLUTELY NO text, letters, words, captions, titles, subtitles, watermarks "
    "or logos anywhere in the image — a pure photograph only."
)

# kind -> (asset-generator style, default aspect, transparent, uses refs)
KIND_MAP = {
    "author_portrait": ("photo", "3:4", False, True),
    "emotive_photo":   ("photo", "3:4", False, False),
    "hero_photo":      ("photo", "2:3", False, False),
    "symbolic_bg":     ("photo", "2:3", False, False),
    "product_mockup":  ("photo", "3:4", False, False),
    "texture":         ("background", "2:3", False, False),
}


def build_prompt(asset: dict, directive: str, brand: dict) -> tuple[str, list[str]]:
    kind = asset.get("kind", "emotive_photo")
    prompt = (asset.get("prompt") or "").strip()
    treatment = (asset.get("treatment") or "").strip()
    refs: list[str] = []

    if kind == "author_portrait":
        pose = asset.get("prompt") or "a confident, thoughtful portrait"
        comp = asset.get("composition") or ""
        who = brand.get("name") or "the person"
        refs = list(brand.get("reference_images") or [])
        ref_clause = (
            f" Keep the exact same face and identity as the reference photos of {who}; "
            "preserve facial features, age and hair. "
        ) if refs else ""
        full = (
            f"Photorealistic {treatment or 'black and white cinematic'} portrait of {who}: "
            f"{pose}.{ref_clause}{comp} {directive}"
        )
        return full, refs

    if kind == "product_mockup":
        screen = asset.get("screen") or "an elegant course cover"
        full = (
            f"A modern tablet with a stylus resting on a clean neutral surface, the tablet "
            f"screen showing {screen}. Minimalist product mockup, soft studio light. {directive}"
        )
        return full, refs

    if kind == "symbolic_bg":
        full = (
            f"{prompt}. A single symbolic object as the clear focal point on a bright, softly "
            f"lit wall with natural window light and soft shadows, minimalist still life, lots "
            f"of negative space. {treatment or ''} {directive}"
        )
        return full, refs

    if kind == "texture":
        full = f"{prompt}. Subtle abstract texture/background, {treatment or 'soft neutral tones'}."
        return full, refs

    # emotive_photo / hero_photo
    full = f"{prompt}. {treatment or ''} {directive}"
    return full, refs


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate all assets for a content.json in the mold's style")
    ap.add_argument("--content", required=True, help="Path to content.json")
    ap.add_argument("--assets-dir", help="Where to write assets (default: <content dir>/assets)")
    ap.add_argument("--blueprint", help="blueprint.json (for style directive / motifs)")
    ap.add_argument("--style-directive", help="Override the global photographic style directive")
    ap.add_argument("--resolution", default="2K", help="asset-generator resolution (1K/2K/4K)")
    ap.add_argument("--only", help="Comma-separated asset ids to (re)generate")
    ap.add_argument("--force", action="store_true", help="Regenerate even if the file exists")
    ap.add_argument("--dry-run", action="store_true", help="Print prompts, do not generate")
    args = ap.parse_args()

    content_path = Path(args.content).expanduser()
    content = json.loads(content_path.read_text(encoding="utf-8"))
    assets_dir = Path(args.assets_dir) if args.assets_dir else (content_path.parent / "assets")
    assets_dir.mkdir(parents=True, exist_ok=True)

    directive = args.style_directive or DEFAULT_DIRECTIVE
    if not args.style_directive and args.blueprint and Path(args.blueprint).exists():
        bp = json.loads(Path(args.blueprint).read_text(encoding="utf-8"))
        motifs = bp.get("design_system", {}).get("motifs", [])
        if motifs:
            directive = DEFAULT_DIRECTIVE + " Consistent with: " + "; ".join(motifs[:2])

    only = set(x.strip() for x in args.only.split(",")) if args.only else None
    brand = content.get("brand", {})

    # Collect assets across pages.
    jobs: list[dict] = []
    for page in content.get("pages", []):
        for asset in page.get("assets", []) or []:
            if not asset.get("id"):
                continue
            if only and asset["id"] not in only:
                continue
            jobs.append(asset)

    print(f"{len(jobs)} asset(s) to process -> {assets_dir}", file=sys.stderr)
    manifest = {}
    ok = 0
    for asset in jobs:
        aid = asset["id"]
        kind = asset.get("kind", "emotive_photo")
        style, def_ar, def_tp, _uses = KIND_MAP.get(kind, KIND_MAP["emotive_photo"])
        aspect = asset.get("aspect") or def_ar
        transparent = bool(asset.get("transparent", def_tp))
        out = assets_dir / f"{aid}.png"
        prompt, refs = build_prompt(asset, directive, brand)

        if out.exists() and not args.force:
            print(f"  = {aid} (exists)", file=sys.stderr)
            manifest[aid] = str(out)
            ok += 1
            continue

        if args.dry_run:
            print(f"\n--- {aid} [{kind}] style={style} ar={aspect} refs={len(refs)}")
            print(prompt)
            continue

        print(f"  → {aid} [{kind}] ...", file=sys.stderr)
        success = C.run_asset_generator(
            prompt, out, style=style, aspect_ratio=aspect, resolution=args.resolution,
            refs=refs or None, transparent=transparent, thinking="high",
        )
        if success:
            manifest[aid] = str(out)
            ok += 1
        else:
            print(f"  ! failed: {aid}", file=sys.stderr)

    if not args.dry_run:
        (assets_dir / "assets_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"assets_dir": str(assets_dir), "generated": ok,
                          "total": len(jobs)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
