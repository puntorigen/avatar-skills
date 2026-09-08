#!/usr/bin/env python3
"""Analyze downloaded carousels and derive a winning slide-by-slide blueprint.

Uses Gemini vision to read the slides of each top carousel and label the role of
each slide (cover/hook, idea, quote, data, recap, CTA), the caption structure and
the hook technique. Fuses the findings with the reel-discovery narrative patterns
(listicle, contrarian, mind-reading, direct question, simple how-to).

Degrades gracefully: if the vision call fails, it falls back to a heuristic
blueprint based on slide counts + the known narrative patterns, so the pipeline
always yields a usable blueprint.

Usage:
  python3 analyze_structure.py --run-dir runs/rupturas [--max 4]

Outputs (in --run-dir):
  blueprint.json    machine-readable consolidated blueprint
  blueprint.md      human-readable blueprint used by the class + generator
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# Narrative patterns proven in reel-discovery for the ruptures/grief niche.
REEL_PATTERNS = [
    {"id": "P1", "name": "Listicle personal numerado",
     "desc": "«N cosas que…» — cada slide = un ítem accionable."},
    {"id": "P2", "name": "Contrarian / reframe",
     "desc": "Rompe una creencia común: «La meta no es que vuelva…»."},
    {"id": "P3", "name": "Lectura de mente / validación",
     "desc": "Le pone palabras a lo que el espectador ya siente."},
    {"id": "P4", "name": "Pregunta directa al dolor",
     "desc": "«¿Por qué no puedes superar a tu ex?» — abre un gap."},
    {"id": "P5", "name": "Autoridad simple (how-to)",
     "desc": "«Cómo superar a tu ex» — pasos claros y directos."},
]

VISION_INSTRUCTION = (
    "Eres un estratega de contenido. Te muestro, en orden, las diapositivas (slides) de un "
    "carrusel de Instagram del nicho de rupturas amorosas y duelo. Analiza su estructura y "
    "responde SOLO con JSON válido con esta forma exacta:\n"
    '{"slides":[{"n":1,"role":"portada|idea|cita|dato|recap|cta","purpose":"...","text_summary":"..."}],'
    '"hook_technique":"...","narrative_pattern":"listicle|contrarian|mind-reading|question|how-to",'
    '"caption_structure":"...","why_it_works":"..."}\n'
    "role debe ser uno de: portada, idea, cita, dato, recap, cta. Sé conciso y en español."
)


def analyze_one(client, slide_paths: list[Path]) -> dict | None:
    try:
        from PIL import Image as PILImage
    except Exception:  # noqa: BLE001
        return None
    contents: list = [VISION_INSTRUCTION]
    for p in slide_paths:
        try:
            contents.append(PILImage.open(str(p)))
        except Exception:  # noqa: BLE001
            continue
    if len(contents) < 2:
        return None
    try:
        resp = client.models.generate_content(model=C.VISION_MODEL, contents=contents)
        text = (resp.text or "").strip()
    except Exception as e:  # noqa: BLE001
        print(f"  ! vision error: {e}", file=sys.stderr)
        return None
    # Strip code fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("json"):
            text = ""
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        # Try to salvage the first {...} block.
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except Exception:  # noqa: BLE001
                return None
    return None


def heuristic_blueprint(slide_count: int) -> list[dict]:
    n = max(slide_count, 5)
    roles = [{"n": 1, "role": "portada", "purpose": "Gancho: dolor + promesa en 5-7 palabras"}]
    idea_slots = n - 2
    for i in range(idea_slots):
        roles.append({"n": i + 2, "role": "idea",
                      "purpose": f"Idea/paso {i + 1}: una sola idea, título + 1-2 líneas"})
    roles.append({"n": n, "role": "cta",
                  "purpose": "Cierre + llamado a la acción (guardar / comentar / seguir)"})
    return roles


def consolidate(analyses: list[dict], top_carousels: list[dict]) -> dict:
    slide_counts = [c.get("slide_count", 0) for c in top_carousels if c.get("slide_count")]
    typical = Counter(slide_counts).most_common(1)[0][0] if slide_counts else 7

    patterns = Counter(a.get("narrative_pattern") for a in analyses if a.get("narrative_pattern"))
    hooks = [a.get("hook_technique") for a in analyses if a.get("hook_technique")]

    # Recommended role sequence: prefer a real analysis with a full slide list.
    role_seq = None
    for a in analyses:
        slides = a.get("slides") or []
        if len(slides) >= 4:
            role_seq = [{"n": s.get("n"), "role": s.get("role"), "purpose": s.get("purpose", "")}
                        for s in slides]
            break
    if not role_seq:
        role_seq = heuristic_blueprint(typical)

    return {
        "typical_slide_count": typical,
        "recommended_slides": role_seq,
        "dominant_narrative_patterns": patterns.most_common(),
        "hook_techniques": hooks[:5],
        "reel_discovery_patterns": REEL_PATTERNS,
        "per_carousel": analyses,
    }


def render_md(blueprint: dict, top_carousels: list[dict]) -> str:
    L = ["# Blueprint del carrusel ganador", ""]
    L.append(f"**Nº de slides típico:** {blueprint['typical_slide_count']}")
    if blueprint["dominant_narrative_patterns"]:
        pats = ", ".join(f"{p} ({n})" for p, n in blueprint["dominant_narrative_patterns"])
        L.append(f"**Patrones narrativos dominantes:** {pats}")
    L.append("")
    L.append("## Estructura slide por slide (molde a replicar)")
    L.append("")
    L.append("| Slide | Rol | Propósito |")
    L.append("| ---: | --- | --- |")
    for s in blueprint["recommended_slides"]:
        L.append(f"| {s.get('n')} | {s.get('role')} | {s.get('purpose','')} |")
    L.append("")
    if blueprint["hook_techniques"]:
        L.append("## Técnicas de gancho observadas")
        for h in blueprint["hook_techniques"]:
            if h:
                L.append(f"- {h}")
        L.append("")
    L.append("## Patrones narrativos (reel-discovery) para el copy")
    for p in blueprint["reel_discovery_patterns"]:
        L.append(f"- **{p['id']} {p['name']}** — {p['desc']}")
    L.append("")
    if top_carousels:
        L.append("## Carruseles de referencia")
        for c in top_carousels:
            L.append(f"- @{c['handle']} · {c['slide_count']} slides · {c['engagement']:,} eng · {c['url']}")
        L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="Derive a slide-by-slide blueprint from downloaded carousels")
    ap.add_argument("--run-dir", required=True, help="Directory produced by research_carousels.py")
    ap.add_argument("--max", type=int, default=4, help="Max carousels to analyze with vision")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    research_path = run_dir / "research.json"
    if not research_path.exists():
        print(f"Error: {research_path} not found. Run research_carousels.py first.", file=sys.stderr)
        sys.exit(1)
    research = json.loads(research_path.read_text(encoding="utf-8"))
    top_carousels = research.get("top_carousels", [])

    client = None
    key = C.gemini_key()
    if key:
        try:
            from google import genai
            client = genai.Client(api_key=key)
        except Exception as e:  # noqa: BLE001
            print(f"Warning: google-genai unavailable ({e}); using heuristic blueprint.", file=sys.stderr)
    else:
        print("Warning: no Gemini key; using heuristic blueprint.", file=sys.stderr)

    analyses: list[dict] = []
    if client:
        for c in top_carousels[: args.max]:
            slide_dir = run_dir / c["handle"] / c["shortcode"]
            slides = sorted(slide_dir.glob("slide_*.jpg"))
            if not slides:
                continue
            print(f"Analyzing @{c['handle']}/{c['shortcode']} ({len(slides)} slides)...", file=sys.stderr)
            a = analyze_one(client, slides)
            if a:
                a["_source"] = f"@{c['handle']}/{c['shortcode']}"
                analyses.append(a)

    blueprint = consolidate(analyses, top_carousels)
    (run_dir / "blueprint.json").write_text(
        json.dumps(blueprint, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "blueprint.md").write_text(
        render_md(blueprint, top_carousels), encoding="utf-8")

    print(json.dumps({
        "run_dir": str(run_dir),
        "analyzed": len(analyses),
        "typical_slide_count": blueprint["typical_slide_count"],
        "used_vision": bool(analyses),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
