#!/usr/bin/env python3
"""Generate a branded Instagram carousel from a slide plan + brand profile.

Reuses the asset-generator skill (Gemini 3 Pro Image) by invoking its
generate_asset.py as a subprocess for every slide. Visual consistency across
slides is achieved by generating the cover first and passing it as a reference
to the remaining slides, together with the brand assets (logo + identity photos).

Usage:
  python3 generate_carousel.py --plan plan.json --brand ../brands/arnoldo.json \
      --out-dir out/mi-carrusel
  python3 generate_carousel.py --plan plan.json --brand arnoldo --dry-run

plan.json schema:
  {
    "title": "7 señales de que ya estás sanando",
    "aspect_ratio": "4:5",
    "slides": [
      {"role":"portada","headline":"...","body":"","show_face":true,"style":"portada"},
      {"role":"idea","headline":"1. ...","body":"...","show_face":false,"style":"idea"},
      {"role":"cta","headline":"...","body":"...","show_face":true,"style":"cta"}
    ],
    "caption": "optional caption text",
    "hashtags": ["opt","ional"]
  }

Outputs (in --out-dir):
  slide_01.png .. slide_NN.png, caption.txt, hashtags.txt, plan.used.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# Resolve the bundled sibling renderer (repo-local first, then ~/.cursor/skills).
ASSET_GEN = C.skill_path("asset-generator/scripts/generate_asset.py")
BRANDS_DIR = C.SKILL_DIR / "brands"
SLIDE_STYLES = C.SKILL_DIR / "slide_styles.json"


def load_brand(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if not p.exists():
        p = BRANDS_DIR / f"{name_or_path}.json"
    if not p.exists():
        print(f"Error: brand profile not found: {name_or_path}", file=sys.stderr)
        sys.exit(1)
    brand = json.loads(p.read_text(encoding="utf-8"))
    brand["_dir"] = str(p.parent)
    return brand


def load_styles() -> dict:
    if SLIDE_STYLES.exists():
        return json.loads(SLIDE_STYLES.read_text(encoding="utf-8"))
    return {}


def resolve_asset(brand: dict, rel: str) -> Path | None:
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = Path(brand["_dir"]) / rel
    return p if p.exists() else None


def build_slide_prompt(slide: dict, brand: dict, styles: dict,
                       refs: list[tuple[str, Path]]) -> str:
    """Compose a raw prompt for one slide, with {imageN} placeholders per ref."""
    palette = brand.get("palette", {})
    fonts = brand.get("fonts", {})
    style_key = slide.get("style") or slide.get("role") or "idea"
    style = styles.get(style_key, {})

    # Placeholder map (order = --ref order passed to generate_asset.py).
    ph = {kind: f"{{image{i+1}}}" for i, (kind, _) in enumerate(refs)}

    headline = (slide.get("headline") or "").strip()
    body = (slide.get("body") or "").strip()

    parts = [
        f"Diapositiva de un carrusel de Instagram en formato vertical {brand.get('default_aspect_ratio','4:5')} "
        f"(1080x1350). Diseño editorial premium, limpio y con mucho aire, legible en móvil.",
        f"Paleta de marca: fondo {palette.get('background','#FBF7F2')}, "
        f"texto principal {palette.get('ink','#1A1A1A')}, acento {palette.get('accent','#E4708A')}"
        + (f", secundario {palette.get('muted','#8A8A8A')}." if palette.get("muted") else "."),
        f"Tipografía: titulares en {fonts.get('heading','una sans serif geométrica con carácter')} "
        f"y cuerpo en {fonts.get('body','una sans serif humanista muy legible')}.",
        f"Estilo visual: {brand.get('visual_style','minimalista y cálido')}.",
        f"Tono editorial: {brand.get('tone','cálido, cercano y esperanzador')}.",
    ]

    if style.get("layout"):
        parts.append(f"Composición ({style_key}): {style['layout']}")
    if style.get("text_treatment"):
        parts.append(f"Tratamiento de texto: {style['text_treatment']}")

    # Exact text to render. Delimit with [[ ]] (never rendered) and tell the
    # model explicitly not to draw any quotation marks it isn't given.
    if headline:
        parts.append(
            "Renderiza EXACTAMENTE el siguiente titular, respetando los saltos de línea, "
            "en español perfecto y sin errores ortográficos. No dibujes los corchetes ni "
            f"agregues comillas: [[{headline}]]"
        )
    if body:
        parts.append(f"Texto de apoyo (más pequeño, secundario), sin comillas: [[{body}]]")

    # Face / identity.
    if "face" in ph:
        pos = style.get("face_position", "integrada de forma natural en la composición, sin tapar el texto")
        parts.append(
            f"Incluye a la persona de {ph['face']} (conserva sus rasgos faciales EXACTOS, "
            f"misma persona), {pos}. Iluminación cálida y natural."
        )
    else:
        if slide.get("show_face"):
            parts.append("Diseño centrado en tipografía (no hay foto de la persona disponible).")
        else:
            parts.append("Sin personas: diseño centrado en tipografía y formas simples de marca.")

    if "logo" in ph:
        parts.append(f"Coloca el logo de {ph['logo']} de forma discreta en una esquina inferior.")

    if style_key == "cta" and brand.get("handle"):
        parts.append(f"En el pie del slide incluye el nombre de usuario exacto, sin comillas: {brand['handle']}.")

    if "style_ref" in ph:
        parts.append(
            f"MUY IMPORTANTE: mantén EXACTAMENTE la misma identidad visual que {ph['style_ref']} "
            "(misma paleta, mismas tipografías, mismos márgenes y tratamiento), de modo que todas "
            "las diapositivas se vean como un mismo conjunto coherente."
        )

    parts.append("No agregues marcas de agua, ni logos de Instagram, ni texto extra fuera del indicado.")
    return " ".join(parts)


def collect_refs(slide: dict, brand: dict, cover_path: Path | None,
                 slide_index: int) -> list[tuple[str, Path]]:
    refs: list[tuple[str, Path]] = []
    assets = brand.get("assets", {})

    logo = resolve_asset(brand, assets.get("logo", ""))
    if logo:
        refs.append(("logo", logo))

    if slide.get("show_face"):
        photos = assets.get("identity_photos", []) or []
        added = 0
        for rel in photos:
            ph = resolve_asset(brand, rel)
            if ph:
                refs.append(("face", ph))
                added += 1
            if added >= 2:
                break

    # Consistency reference: pass the already-generated cover to later slides.
    if slide_index > 0 and cover_path and cover_path.exists():
        refs.append(("style_ref", cover_path))

    return refs[:14]


def run_generate_asset(prompt: str, out_path: Path, aspect_ratio: str,
                       refs: list[tuple[str, Path]], dry_run: bool) -> bool:
    cmd = [sys.executable, str(ASSET_GEN), prompt, "-ar", aspect_ratio,
           "--raw-prompt", "-o", str(out_path)]
    for _, p in refs:
        cmd += ["--ref", str(p)]
    if dry_run:
        print(f"\n--- {out_path.name} ---")
        print("refs:", [f"{k}:{p.name}" for k, p in refs])
        print(prompt)
        return True
    print(f"Generating {out_path.name} ...", file=sys.stderr)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not out_path.exists():
        print(res.stderr[-1500:], file=sys.stderr)
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a branded IG carousel from a plan")
    ap.add_argument("--plan", required=True, help="Path to plan.json")
    ap.add_argument("--brand", required=True, help="Brand name (brands/<name>.json) or path")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--dry-run", action="store_true", help="Print prompts without calling Gemini")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    brand = load_brand(args.brand)
    styles = load_styles()

    aspect_ratio = plan.get("aspect_ratio") or brand.get("default_aspect_ratio") or "4:5"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    slides = plan.get("slides", [])
    if not slides:
        print("Error: plan has no slides.", file=sys.stderr)
        sys.exit(1)

    cover_path = out_dir / "slide_01.png"
    generated, failed = [], []
    for i, slide in enumerate(slides):
        out_path = out_dir / f"slide_{i+1:02d}.png"
        refs = collect_refs(slide, brand, cover_path, i)
        prompt = build_slide_prompt(slide, brand, styles, refs)
        ok = run_generate_asset(prompt, out_path, aspect_ratio, refs, args.dry_run)
        (generated if ok else failed).append(out_path.name)

    # Sidecar files.
    if plan.get("caption"):
        (out_dir / "caption.txt").write_text(plan["caption"], encoding="utf-8")
    if plan.get("hashtags"):
        tags = plan["hashtags"]
        block = " ".join(t if t.startswith("#") else f"#{t}" for t in tags)
        (out_dir / "hashtags.txt").write_text(block + "\n", encoding="utf-8")
    (out_dir / "plan.used.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "out_dir": str(out_dir),
        "aspect_ratio": aspect_ratio,
        "generated": generated,
        "failed": failed,
        "dry_run": args.dry_run,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
