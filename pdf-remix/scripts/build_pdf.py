#!/usr/bin/env python3
"""Render an authored content.json into a premium multi-page PDF using the mold.

Design-system driven: the palette, typographic roles and per-page layout
archetypes come from the blueprint (and content.brand overrides). Text is real,
crisp HTML (Chromium print) — only imagery is AI-generated — so the output can
match or exceed the reference's quality.

Inline markup usable in any content string:
    **bold**      -> <b>            (key claims)
    *italic*      -> <i>            (self-talk / quotes)
    ==accent==    -> accent color   (highlighted words)
    blank line    -> new paragraph  (in body fields)

Usage:
  python3 build_pdf.py --content runs/foo/content.json \
      [--blueprint runs/trampas/blueprint.json] [--assets-dir runs/foo/assets] \
      -o runs/foo/output.pdf [--html-only]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

DEFAULT_PALETTE = {"ink": "#121111", "paper": "#e6e6e6", "accent": "#c4121a",
                   "accent_dark": "#7a0d13", "on_dark": "#ffffff", "muted": "#5f5f5f"}


# --------------------------------------------------------------------------- #
# Inline formatting
# --------------------------------------------------------------------------- #
def fmt(text) -> str:
    """Escape + apply lightweight inline markup (**bold**, *italic*, ==accent==)."""
    if text is None:
        return ""
    if isinstance(text, list):
        text = "\n\n".join(str(t) for t in text)
    s = html.escape(str(text))
    s = re.sub(r"==(.+?)==", r'<span class="accent">\1</span>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", s)
    return s


def fmt_body(text) -> str:
    """Format body text with blank-line paragraph splitting."""
    if text is None:
        return ""
    if isinstance(text, list):
        chunks = [str(t) for t in text]
    else:
        chunks = re.split(r"\n\s*\n", str(text))
    return "".join(f"<p>{fmt(c.strip())}</p>" for c in chunks if c.strip())


# --------------------------------------------------------------------------- #
# Asset resolution
# --------------------------------------------------------------------------- #
def resolve_asset(val, assets_dir: Path) -> str | None:
    """Return a file:// URL for an asset id or path, else None (placeholder)."""
    if not val:
        return None
    p = Path(val)
    if p.exists():
        return f"file://{p.resolve()}"
    for cand in (assets_dir / val, assets_dir / f"{val}.png",
                 assets_dir / f"{val}.jpg", assets_dir / f"{val}.jpeg"):
        if cand.exists():
            return f"file://{cand.resolve()}"
    return None


def img_or_ph(url: str | None, label: str, cls: str = "") -> str:
    if url:
        return f'<img class="{cls}" src="{url}" alt="">'
    return f'<div class="ph {cls}">{html.escape(label)}</div>'


# --------------------------------------------------------------------------- #
# Per-archetype renderers  (each returns the inner HTML of a .page)
# --------------------------------------------------------------------------- #
def r_cover(pg, A) -> tuple[str, str]:
    portrait = A("portrait") or A("photo")
    bg = img_or_ph(portrait, "author portrait", "bleed-img")
    inner = f"""
      {bg}
      <div class="scrim"></div><div class="scrim-b"></div>
      <div class="c-title">
        <div class="display">{fmt(pg.get('title'))}</div>
        <div class="c-sub">{fmt(pg.get('subtitle'))}</div>
      </div>
      <div class="c-body">{fmt(pg.get('callout'))}</div>
      <div class="c-sign"><div class="sign">{fmt(pg.get('byline'))}</div></div>
      <div class="brand-bar">{fmt(pg.get('brand_bar'))}</div>
    """
    return "cover", inner


def r_quote_dark(pg, A) -> tuple[str, str]:
    parts = []
    if pg.get("quote"):
        parts.append(f'<div class="q-serif">{fmt(pg["quote"])}</div>')
    if pg.get("brush"):
        parts.append(f'<div class="q-brush">{fmt(pg["brush"])}</div>')
    if pg.get("tail"):
        parts.append(f'<div class="q-serif">{fmt(pg["tail"])}</div>')
    inner = f"""
      <div class="hairline-v top"></div>
      <div class="q-wrap">{''.join(parts)}</div>
      <div class="hairline-v bot"></div>
    """
    return "quote_dark", inner


def r_manifesto_text(pg, A) -> tuple[str, str]:
    head = f'<span class="display">{fmt(pg.get("head_display"))}</span> '
    if pg.get("head_brush"):
        head += f'<span class="brush">{fmt(pg["head_brush"])}</span>'
    photo = A("photo")
    photo_html = (f'<div class="m-photo">{img_or_ph(photo, "photo")}</div>'
                  if ("photo" in pg or photo) else "")
    inner = f"""
      <div class="m-head">{head}</div>
      <div class="body">{fmt_body(pg.get('body'))}</div>
      {photo_html}
    """
    return "manifesto_text", inner


def r_statement_object(pg, A) -> tuple[str, str]:
    bg = A("bg") or A("object") or A("photo")
    head = fmt(pg.get("statement"))
    if pg.get("accent_line"):
        head += f'<br><span class="accent">{fmt(pg["accent_line"])}</span>'
    inner = f"""
      <div class="so-bg">{img_or_ph(bg, "symbolic background", "bleed-img")}</div>
      <div class="so-head"><div class="display">{head}</div></div>
      <div class="so-hand"><div class="hand">{fmt(pg.get('handwritten'))}</div></div>
      <div class="hairline-v"></div>
    """
    return "statement_object", inner


def r_section_opener(pg, A) -> tuple[str, str]:
    side = pg.get("side", "right")
    photo = A("photo")
    inner = f"""
      <div class="so-photo">{img_or_ph(photo, "emotive photo")}</div>
      <div class="so-text">
        <div class="so-kicker">{fmt(pg.get('kicker'))}</div>
        <div class="so-name">{fmt(pg.get('name'))}</div>
        <div class="so-quote">{fmt(pg.get('quote'))}</div>
      </div>
    """
    return f"section_opener {side}", inner


def r_what_is(pg, A) -> tuple[str, str]:
    variant = pg.get("variant", "photo_top")
    photo = A("photo")
    title = fmt(pg.get("title") or "Qué es")
    if variant == "fullbleed_dark":
        inner = f"""
          <div class="wi-bg">{img_or_ph(photo, "emotive photo", "bleed-img")}</div>
          <div class="wi-text">
            <div class="wi-title">{title}</div>
            <div class="body">{fmt_body(pg.get('body'))}</div>
          </div>
        """
        return "what_is fullbleed_dark", inner
    inner = f"""
      <div class="wi-photo">{img_or_ph(photo, "emotive photo")}</div>
      <div class="wi-text">
        <div class="wi-title">{title}</div>
        <div class="body">{fmt_body(pg.get('body'))}</div>
      </div>
    """
    return "what_is photo_top", inner


def r_split_grid(pg, A) -> tuple[str, str]:
    cells = pg.get("cells") or []
    # Default order mirrors the mold: text, photo / photo, text.
    if not cells:
        cells = [{"type": "text"}, {"type": "photo"}, {"type": "photo"}, {"type": "text"}]
    html_cells = []
    for i, c in enumerate(cells[:4]):
        if c.get("type") == "photo":
            url = A(c.get("asset", ""))
            html_cells.append(f'<div class="cell photo">{img_or_ph(url, "photo")}</div>')
        else:
            st = f'<div class="section-title">{fmt(c.get("section_title"))}</div>' if c.get("section_title") else ""
            html_cells.append(
                f'<div class="cell text">{st}<div class="body">{fmt_body(c.get("body"))}</div></div>')
    return "split_grid", "".join(html_cells)


def r_bridge(pg, A) -> tuple[str, str]:
    head = ""
    if pg.get("head_brush"):
        head += f'<span class="brush">{fmt(pg["head_brush"])}</span>'
    if pg.get("head_display"):
        head += f'<span class="display">{fmt(pg["head_display"])}</span>'
    sub = f'<div class="b-sub">{fmt(pg["sub"])}</div>' if pg.get("sub") else ""
    inner = f"""
      <div class="b-head">{head}</div>
      <div class="body">{fmt_body(pg.get('body'))}</div>
      {sub}
      <div class="body">{fmt_body(pg.get('body2'))}</div>
    """
    return "bridge", inner


def r_cta_closing(pg, A) -> tuple[str, str]:
    mock = A("mock") or A("photo")
    inner = f"""
      <div class="cta-lead">{fmt_body(pg.get('lead'))}</div>
      <div class="cta-headline">{fmt(pg.get('headline'))}</div>
      <div class="cta-lead">{fmt_body(pg.get('body'))}</div>
      {f'<img class="cta-mock" src="{mock}">' if mock else '<div class="ph" style="position:relative;height:80mm">mockup</div>'}
      <div><a class="cta-btn">{fmt(pg.get('button'))}</a></div>
      <div class="cta-foot">{fmt(pg.get('foot'))}</div>
    """
    return "cta_closing", inner


def r_freeform(pg, A) -> tuple[str, str]:
    blocks = []
    for k in ("title", "section_title", "quote", "body"):
        if pg.get(k):
            cls = {"title": "display t-m", "section_title": "section-title",
                   "quote": "display t-s", "body": "body"}[k]
            content = fmt_body(pg[k]) if k == "body" else fmt(pg[k])
            blocks.append(f'<div class="{cls}">{content}</div>')
    for a in pg.get("assets", []) or []:
        url = A(a.get("id", ""))
        if url:
            blocks.append(f'<img src="{url}">')
    return "freeform", "".join(blocks)


RENDERERS = {
    "cover": r_cover, "quote_dark": r_quote_dark, "manifesto_text": r_manifesto_text,
    "statement_object": r_statement_object, "section_opener": r_section_opener,
    "what_is": r_what_is, "split_grid": r_split_grid, "bridge": r_bridge,
    "cta_closing": r_cta_closing, "freeform": r_freeform,
}


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def build_html(content: dict, palette: dict, geom: dict, assets_dir: Path) -> str:
    page_w = "210mm" if geom.get("format") == "A4" else "216mm"
    page_h = "297mm" if geom.get("format") == "A4" else "279mm"
    page_size = "A4" if geom.get("format") == "A4" else "Letter"
    if geom.get("orientation") == "landscape":
        page_size += " landscape"

    faces = C.font_face_css()
    root_vars = ":root{" + "".join(
        f"--{k.replace('_','-')}:{v};" for k, v in palette.items()
    ) + (
        f"--page-w:{page_w};--page-h:{page_h};--page-size:{page_size};"
        f"--f-display:{C.role_family('display_serif', 'Georgia, serif')};"
        f"--f-brush:{C.role_family('brush_script', 'cursive')};"
        f"--f-sign:{C.role_family('signature_script', 'cursive')};"
        f"--f-hand:{C.role_family('hand_marker', 'cursive')};"
        f"--f-body:{C.role_family('body_sans', 'Helvetica, Arial, sans-serif')};"
    ) + "}"

    base_css = (C.TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")

    pages_html = []
    for pg in content.get("pages", []):
        arche = pg.get("archetype", "freeform")
        renderer = RENDERERS.get(arche, r_freeform)

        # Per-page asset lookup. Accepts either a page FIELD name (e.g. "portrait",
        # whose value is an id/path) OR a direct asset id (e.g. a split_grid cell).
        def A(key: str, _pg=pg):
            if isinstance(key, str) and isinstance(_pg.get(key), str):
                return resolve_asset(_pg[key], assets_dir)
            return resolve_asset(key, assets_dir)

        cls, inner = renderer(pg, A)
        pages_html.append(f'<section class="page {cls}">{inner}</section>')

    return f"""<!DOCTYPE html>
<html lang="{content.get('meta', {}).get('language', 'es')}">
<head><meta charset="utf-8">
<style>
{faces}
{root_vars}
{base_css}
</style></head>
<body>
{''.join(pages_html)}
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Render content.json to a premium PDF using the mold")
    ap.add_argument("--content", required=True)
    ap.add_argument("--blueprint", help="blueprint.json for palette/geometry defaults")
    ap.add_argument("--assets-dir", help="Assets dir (default <content dir>/assets)")
    ap.add_argument("-o", "--output", help="Output PDF path (default <content dir>/output.pdf)")
    ap.add_argument("--html-only", action="store_true", help="Write the .html and stop (fast iteration)")
    args = ap.parse_args()

    content_path = Path(args.content).expanduser()
    content = json.loads(content_path.read_text(encoding="utf-8"))
    assets_dir = Path(args.assets_dir) if args.assets_dir else (content_path.parent / "assets")

    palette = dict(DEFAULT_PALETTE)
    geom = {"format": "A4", "orientation": "portrait"}
    if args.blueprint and Path(args.blueprint).exists():
        bp = json.loads(Path(args.blueprint).read_text(encoding="utf-8"))
        palette.update({k: v for k, v in bp.get("design_system", {}).get("palette", {}).items()
                        if k in palette})
        geom.update(bp.get("geometry", {}))
    palette.update(content.get("brand", {}).get("palette_override", {}) or {})

    out_html = content_path.parent / (content_path.stem + ".render.html")
    html_str = build_html(content, palette, geom, assets_dir)
    out_html.write_text(html_str, encoding="utf-8")
    print(f"HTML -> {out_html}", file=sys.stderr)

    if args.html_only:
        return

    out_pdf = Path(args.output) if args.output else (content_path.parent / "output.pdf")
    if C.html_to_pdf(out_html, out_pdf):
        print(json.dumps({"pdf": str(out_pdf), "pages": len(content.get("pages", []))},
                         indent=2, ensure_ascii=False))
    else:
        print("PDF render failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
