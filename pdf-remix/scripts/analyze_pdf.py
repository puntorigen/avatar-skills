#!/usr/bin/env python3
"""Analyze a reference PDF and extract a reusable design + narrative MOLD.

This is the "reel-discovery for PDFs": it deconstructs a premium document so we
can replicate its exact structure with new content.

It fuses three signal sources:
  1. Programmatic  — page geometry, extracted text, embedded font names, image
     bounding boxes (PyMuPDF) and pixel-accurate dominant colors (Pillow).
  2. Vision (Gemini)— per-page semantics: layout archetype, background type,
     imagery roles (subject / treatment / camera / position), typographic roles,
     emphasis rules, highlighted words, per-page narration and layout notes.
  3. Synthesis      — a final vision pass over representative pages that names
     the global design system (palette semantics, type scale, emphasis rules,
     motifs) and the narrative arc (beats, section unit, voice, CTA).

Outputs (under --out-dir, default runs/<slug>/):
  preview/page-NN.png     rendered pages (reference)
  blueprint.json          machine-readable mold (design system + per-page + arc)
  blueprint.md            human-readable mold (used in class + by the generator)
  content_template.json   pre-filled skeleton to author NEW content onto the mold

Usage:
  python3 analyze_pdf.py "/path/to/reference.pdf" [--out-dir runs/mydoc] [--dpi 120] [--max-pages N]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

ARCHETYPES = [
    "cover", "quote_dark", "manifesto_text", "statement_object",
    "section_opener", "what_is", "split_grid", "bridge", "cta_closing", "freeform",
]

PAGE_INSTRUCTION = (
    "Eres un director de arte y estratega de contenido. Te muestro UNA página de un PDF de "
    "marketing (lead magnet) de alta calidad. Analiza su diseño y narrativa para poder "
    "REPLICAR el molde con contenido nuevo. Responde SOLO con JSON válido con esta forma exacta:\n"
    "{\n"
    '  "archetype": "cover|quote_dark|manifesto_text|statement_object|section_opener|what_is|split_grid|bridge|cta_closing|freeform",\n'
    '  "background": "fullbleed_photo|solid_dark|solid_light|textured_light|split_photo_panel",\n'
    '  "mood": "emoción/tono dominante en 2-4 palabras",\n'
    '  "imagery": [{"role":"author_portrait|hero_photo|emotive_photo|symbolic_object|product_mockup|texture",'
    '"subject":"person|object|scene","treatment":"ej: blanco y negro cinematográfico|color desaturado|cálido",'
    '"camera":"close-up|plano medio|plano general|cenital|contrapicado","position":"full|left|right|top|bottom|center",'
    '"description":"qué se ve, útil para regenerarla"}],\n'
    '  "text_blocks": [{"role":"eyebrow|title|subtitle|section_title|body|quote|self_talk|handwritten_note|callout|cta_button|byline|footer|brand_bar",'
    '"font_style":"serif_display|brush_script|signature_script|handwritten|sans",'
    '"case":"title|upper|sentence","color":"ink|accent|on_dark|muted","align":"left|center|right",'
    '"emphasis":"none|bold|italic|bold-italic","size":"xl|l|m|s","text":"transcripción literal del texto"}],\n'
    '  "highlight_words": ["palabras o frases resaltadas (en color acento o negrita) y por qué destacan"],\n'
    '  "narration": "1-2 frases: qué mensaje transmite y por qué se muestra así",\n'
    '  "layout_notes": "posición relativa de bloques, hairlines, columnas, grid, márgenes"\n'
    "}\n"
    "Transcribe el texto tal cual (respeta mayúsculas). Sé preciso con archetype. Responde en español."
)

SYNTH_INSTRUCTION = (
    "Eres director de arte. A partir de estas páginas representativas de un PDF de marketing y "
    "del resumen de todas sus páginas, define el MOLDE reutilizable. Responde SOLO con JSON válido:\n"
    "{\n"
    '  "design_system": {\n'
    '    "palette_semantics": {"ink":"uso","paper":"uso","accent":"uso (color de marca)","on_dark":"uso","muted":"uso"},\n'
    '    "typography": {"display_serif":"cuándo/para qué","brush_script":"...","signature_script":"...","handwritten":"...","body_sans":"..."},\n'
    '    "type_scale": "relación de tamaños entre título/sección/cuerpo/nota (aprox)",\n'
    '    "emphasis_rules": {"key_claim":"cómo se enfatiza la afirmación clave","self_talk":"cómo se muestran las frases de la voz interna del lector","accent_usage":"cuándo se usa el color acento","highlight_style":"cómo se resaltan palabras (color/negrita/subrayado/caja)"},\n'
    '    "motifs": ["elementos recurrentes: hairlines, barras de marca, objetos simbólicos, tipo de fotografía"]\n'
    "  },\n"
    '  "narrative_arc": {\n'
    '    "type":"tipo de documento y estrategia",\n'
    '    "voice":"persona/tono de la narración",\n'
    '    "beats":["secuencia de momentos narrativos de principio a fin"],\n'
    '    "section_unit":{"pages_per_item":N,"sub_pages":["roles de las páginas que componen cada ítem/sección repetida"]},\n'
    '    "cta":{"type":"tipo de llamado a la acción","pattern":"cómo se presenta"}\n'
    "  },\n"
    '  "replication_notes":"3-5 reglas clave para que el documento nuevo iguale o supere la calidad del original"\n'
    "}\n"
    "Responde en español."
)


def pick_palette(doc_colors: list[str]) -> dict:
    """Assign semantic palette slots from doc-wide dominant colors."""
    if not doc_colors:
        return {"ink": "#111114", "paper": "#ececec", "accent": "#c81414",
                "accent_dark": "#8b1a1a", "on_dark": "#ffffff", "muted": "#6b6b6b"}
    by_lum = sorted(doc_colors, key=C.luminance)
    ink = by_lum[0]
    paper = by_lum[-1]
    # Accent = most saturated color that isn't near-black or near-white.
    candidates = [c for c in doc_colors
                  if 0.08 < C.luminance(c) < 0.92 and C.saturation(c) > 0.35]
    accent = max(candidates, key=C.saturation) if candidates else "#c81414"
    r, g, b = C.hex_to_rgb(accent)
    accent_dark = f"#{int(r * 0.6):02x}{int(g * 0.6):02x}{int(b * 0.6):02x}"
    # Muted = a mid-luminance low-saturation gray if present.
    grays = [c for c in doc_colors if C.saturation(c) < 0.2 and 0.25 < C.luminance(c) < 0.75]
    muted = grays[0] if grays else "#6b6b6b"
    return {"ink": ink, "paper": paper, "accent": accent,
            "accent_dark": accent_dark, "on_dark": "#ffffff", "muted": muted}


def build_content_template(per_page: list[dict]) -> dict:
    """Turn the analyzed pages into an editable skeleton for NEW content."""
    tpl_pages = []
    for pg in per_page:
        n = pg["n"]
        arche = pg.get("archetype", "freeform")
        # Content fields = the distinct text roles present on this page.
        content: dict = {}
        for tb in pg.get("text_blocks", []) or []:
            role = tb.get("role", "body")
            key = role
            # keep multiple body blocks joined
            if key in content:
                if isinstance(content[key], list):
                    content[key].append("")
                else:
                    content[key] = [content[key], ""]
            else:
                content[key] = ""
        assets = []
        for j, im in enumerate(pg.get("imagery", []) or []):
            assets.append({
                "id": f"p{n:02d}_{im.get('role', 'image')}_{j + 1}",
                "role": im.get("role", "hero_photo"),
                "subject": im.get("subject", "scene"),
                "treatment": im.get("treatment", ""),
                "camera": im.get("camera", ""),
                "position": im.get("position", "full"),
                "prompt": "",              # agent fills: what to depict for NEW content
                "use_reference": im.get("role") in ("author_portrait",),
                "reference_pose": "" if im.get("role") == "author_portrait" else None,
            })
        tpl_pages.append({
            "n": n,
            "archetype": arche,
            "background": pg.get("background", "solid_light"),
            "assets": assets,
            "content": content,
            "_original_text_hint": pg.get("narration", ""),
        })
    return {
        "brand": {
            "name": "", "handle": "", "author_byline": "", "channel_url": "",
            "reference_images": [],
            "palette_override": {},
        },
        "meta": {"title": "", "subtitle": "", "topic": "", "language": "es"},
        "pages": tpl_pages,
    }


def render_md(bp: dict) -> str:
    ds = bp.get("design_system", {})
    pal = ds.get("palette", {})
    arc = bp.get("narrative_arc", {})
    L = ["# Molde del PDF (blueprint para replicar)", ""]
    L.append(f"**Fuente:** `{Path(bp['source_pdf']).name}`  ·  {bp['page_count']} páginas  ·  "
             f"{bp['geometry']['format']} {bp['geometry']['orientation']}")
    L.append("")
    L.append("## Sistema de diseño")
    L.append("")
    L.append("### Paleta")
    L.append("| Slot | Color | Uso |")
    L.append("| --- | --- | --- |")
    sem = ds.get("palette_semantics", {})
    for slot in ("ink", "paper", "accent", "accent_dark", "on_dark", "muted"):
        if slot in pal:
            L.append(f"| {slot} | `{pal[slot]}` | {sem.get(slot, '')} |")
    L.append("")
    if ds.get("fonts_detected"):
        L.append(f"**Fuentes embebidas detectadas:** {', '.join(ds['fonts_detected'][:12])}")
        L.append("")
    typ = ds.get("typography", {})
    if typ:
        L.append("### Tipografía (roles)")
        for role, use in typ.items():
            L.append(f"- **{role}** — {use}")
        if ds.get("type_scale"):
            L.append(f"- **escala** — {ds['type_scale']}")
        L.append("")
    emph = ds.get("emphasis_rules", {})
    if emph:
        L.append("### Reglas de énfasis / resaltado")
        for k, v in emph.items():
            L.append(f"- **{k}** — {v}")
        L.append("")
    if ds.get("motifs"):
        L.append("### Motivos recurrentes")
        for m in ds["motifs"]:
            L.append(f"- {m}")
        L.append("")
    L.append("## Arco narrativo")
    if arc.get("type"):
        L.append(f"**Tipo:** {arc['type']}")
    if arc.get("voice"):
        L.append(f"**Voz:** {arc['voice']}")
    if arc.get("beats"):
        L.append("")
        L.append("**Beats:**")
        for i, b in enumerate(arc["beats"], 1):
            L.append(f"{i}. {b}")
    su = arc.get("section_unit", {})
    if su:
        L.append("")
        L.append(f"**Unidad de sección repetida:** {su.get('pages_per_item', '?')} páginas → "
                 f"{', '.join(su.get('sub_pages', []))}")
    if arc.get("cta"):
        L.append("")
        L.append(f"**CTA:** {arc['cta'].get('type', '')} — {arc['cta'].get('pattern', '')}")
    L.append("")
    if bp.get("replication_notes"):
        L.append("## Reglas para igualar o superar el original")
        notes = bp["replication_notes"]
        if isinstance(notes, str):
            L.append(notes)
        else:
            for nnote in notes:
                L.append(f"- {nnote}")
        L.append("")
    L.append("## Mapa de páginas (archetype por página)")
    L.append("| Pág | Archetype | Fondo | Imágenes | Texto (roles) |")
    L.append("| ---: | --- | --- | --- | --- |")
    for pg in bp["pages"]:
        roles = ", ".join(sorted({tb.get("role", "") for tb in pg.get("text_blocks", [])}))
        imgs = ", ".join(sorted({im.get("role", "") for im in pg.get("imagery", [])})) or "—"
        L.append(f"| {pg['n']} | {pg.get('archetype', '')} | {pg.get('background', '')} | {imgs} | {roles} |")
    L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract a reusable design+narrative mold from a PDF")
    ap.add_argument("pdf", help="Path to the reference PDF")
    ap.add_argument("--out-dir", help="Output dir (default runs/<slug>)")
    ap.add_argument("--dpi", type=int, default=120, help="Render DPI for page images")
    ap.add_argument("--max-pages", type=int, default=None, help="Analyze only first N pages")
    ap.add_argument("--no-vision", action="store_true", help="Skip Gemini vision (geometry/palette only)")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    slug = C.slugify(pdf_path.stem)
    out_dir = Path(args.out_dir) if args.out_dir else (C.SKILL_DIR / "runs" / slug)
    preview_dir = out_dir / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)

    geom = C.page_geometry(pdf_path)
    print(f"Rendering {geom['page_count']} pages ({geom['format']} {geom['orientation']})...",
          file=sys.stderr)
    page_imgs = C.render_pages(pdf_path, preview_dir, dpi=args.dpi, max_pages=args.max_pages)
    structure = C.extract_structure(pdf_path)

    # Doc-wide palette from a handful of representative pages (spread across doc).
    sample_idx = sorted(set([0, len(page_imgs) // 4, len(page_imgs) // 2,
                             3 * len(page_imgs) // 4, len(page_imgs) - 1]))
    doc_colors: list[str] = []
    for i in sample_idx:
        if 0 <= i < len(page_imgs):
            doc_colors += C.dominant_colors(page_imgs[i], k=6)
    # Dedup while keeping order, then reduce to a compact set.
    seen, uniq = set(), []
    for c in doc_colors:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    palette = pick_palette(uniq)

    fonts_detected: list[str] = []
    for s in structure:
        for f in s["fonts"]:
            if f not in fonts_detected:
                fonts_detected.append(f)

    client = None if args.no_vision else C.genai_client()

    per_page: list[dict] = []
    for idx, img in enumerate(page_imgs):
        n = idx + 1
        base = {"n": n, "text_excerpt": (structure[idx]["text"][:600] if idx < len(structure) else ""),
                "image_count": structure[idx]["image_count"] if idx < len(structure) else 0}
        analysis = None
        if client is not None:
            print(f"  vision: page {n}/{len(page_imgs)}", file=sys.stderr)
            analysis = C.vision_json(client, PAGE_INSTRUCTION, [img])
        if not analysis:
            analysis = {"archetype": "freeform", "background": "solid_light",
                        "imagery": [], "text_blocks": [], "highlight_words": [],
                        "narration": "", "layout_notes": ""}
        analysis.update(base)
        analysis["preview"] = str(img.relative_to(out_dir))
        analysis["dominant_colors"] = C.dominant_colors(img, k=5)
        per_page.append(analysis)

    # Global synthesis over representative pages.
    design_system = {
        "palette": palette,
        "palette_semantics": {},
        "fonts_detected": fonts_detected,
        "typography": {}, "type_scale": "", "emphasis_rules": {}, "motifs": [],
    }
    narrative_arc: dict = {}
    replication_notes: list | str = []
    if client is not None:
        page_summ = "\n".join(
            f"p{p['n']}: [{p.get('archetype')}] "
            f"{(p.get('narration') or '')[:120]}"
            for p in per_page
        )
        rep_imgs = [page_imgs[i] for i in sample_idx if 0 <= i < len(page_imgs)]
        synth = C.vision_json(client, SYNTH_INSTRUCTION, rep_imgs,
                              extra="Resumen de páginas:\n" + page_summ)
        if synth:
            ds = synth.get("design_system", {})
            design_system["palette_semantics"] = ds.get("palette_semantics", {})
            design_system["typography"] = ds.get("typography", {})
            design_system["type_scale"] = ds.get("type_scale", "")
            design_system["emphasis_rules"] = ds.get("emphasis_rules", {})
            design_system["motifs"] = ds.get("motifs", [])
            narrative_arc = synth.get("narrative_arc", {})
            replication_notes = synth.get("replication_notes", [])

    # Archetype library (observed counts).
    arch_counts = Counter(p.get("archetype", "freeform") for p in per_page)

    blueprint = {
        "source_pdf": str(pdf_path),
        "page_count": geom["page_count"],
        "geometry": geom,
        "design_system": design_system,
        "layout_archetypes": [{"id": a, "count": c} for a, c in arch_counts.most_common()],
        "narrative_arc": narrative_arc,
        "replication_notes": replication_notes,
        "pages": per_page,
    }

    (out_dir / "blueprint.json").write_text(
        json.dumps(blueprint, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "blueprint.md").write_text(render_md(blueprint), encoding="utf-8")

    content_tpl = build_content_template(per_page)
    (out_dir / "content_template.json").write_text(
        json.dumps(content_tpl, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "out_dir": str(out_dir),
        "pages": len(per_page),
        "used_vision": client is not None,
        "palette": palette,
        "archetypes": dict(arch_counts),
        "artifacts": ["blueprint.json", "blueprint.md", "content_template.json",
                      f"preview/ ({len(page_imgs)} imgs)"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
