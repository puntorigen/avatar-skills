#!/usr/bin/env python3
"""Shared helpers for the pdf-remix skill.

pdf-remix analyzes the *design + narrative mold* of a reference PDF (a marketing
lead-magnet, brochure, editorial piece) and regenerates NEW content that reuses
that exact mold — palette, typographic roles, emphasis rules, per-page layout
archetypes and narrative arc — producing a crisp, professional multi-page PDF.

This module centralizes everything the three stages share:
  - Credential reuse (Gemini key from asset-generator, Apify token from reel-discovery).
  - PDF rendering + structural extraction via PyMuPDF (fitz).
  - Dominant-color extraction via Pillow.
  - A robust Gemini vision -> JSON wrapper.
  - A subprocess bridge to the asset-generator skill.
  - Font-role resolution (bundled OFL fonts) and HTML -> PDF via Playwright.

Sibling-skill / sibling-config resolution mirrors the rest of avatar-skills:
prefer the project-local repo copy, then the user-level `~/.cursor/skills`
install (so the skill works both when run from the repo and after
`npx skills add ...`).

Stdlib-only except for optional google-genai / Pillow / fitz / playwright used
by callers (all degrade gracefully when missing).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Optional

HOME = Path.home()
SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
FONTS_DIR = SKILL_DIR / "fonts"
TEMPLATES_DIR = SKILL_DIR / "templates"
CONFIG_FILE = SKILL_DIR / "config.json"           # this skill's own (optional) config
USER_SKILLS = HOME / ".cursor" / "skills"


# --------------------------------------------------------------------------- #
# Sibling-skill resolution (repo-local first, then the global install)
# --------------------------------------------------------------------------- #
def _skills_root() -> Path:
    """The skills root that contains our siblings (asset-generator, reel-discovery).

    Prefer the repo copy (SKILL_DIR.parent) when the bundled asset-generator is
    present there; otherwise fall back to the user-level `~/.cursor/skills`.
    """
    local = SKILL_DIR.parent
    if (local / "asset-generator" / "scripts" / "generate_asset.py").exists():
        return local
    return USER_SKILLS


SKILLS_ROOT = _skills_root()


def skill_path(rel: str) -> Path:
    """Resolve a sibling path, preferring the project-local skills root."""
    for root in (SKILLS_ROOT, USER_SKILLS):
        cand = root / rel
        if cand.exists():
            return cand
    return SKILLS_ROOT / rel


ASSET_GEN_SCRIPT = skill_path("asset-generator/scripts/generate_asset.py")

# Text+vision model used to read page images. Override with env if needed.
VISION_MODEL = os.environ.get("PDF_REMIX_VISION_MODEL", "gemini-flash-latest")


# --------------------------------------------------------------------------- #
# Credentials (reuse — never store new secrets in the repo)
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _sibling_configs(sibling: str) -> list[Path]:
    """Candidate config.json paths for a sibling skill across both roots."""
    out: list[Path] = []
    for root in (SKILLS_ROOT, USER_SKILLS):
        p = root / sibling / "config.json"
        if p not in out:
            out.append(p)
    return out


def _discover(env_keys: list[str], cfg_keys: list[str], sibling: str) -> Optional[str]:
    """env var -> this skill's own config.json -> the sibling skill's config.json."""
    for ev in env_keys:
        v = os.environ.get(ev)
        if v:
            return v
    own = _read_json(CONFIG_FILE)
    for ck in cfg_keys:
        if own.get(ck):
            return own[ck]
    for path in _sibling_configs(sibling):
        cfg = _read_json(path)
        for ck in cfg_keys:
            if cfg.get(ck):
                return cfg[ck]
    return None


def gemini_key() -> Optional[str]:
    """Resolve the Gemini API key (env -> own config -> asset-generator config)."""
    return _discover(["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                     ["gemini_api_key"], "asset-generator")


def apify_token() -> Optional[str]:
    """Resolve the Apify token (env -> own config -> reel-discovery config)."""
    return _discover(["APIFY_TOKEN"],
                     ["APIFY_TOKEN", "apify_token"], "reel-discovery")


def genai_client():
    """Return a configured google-genai client, or None if unavailable."""
    key = gemini_key()
    if not key:
        print("Warning: no Gemini key found (asset-generator/config.json). "
              "Vision analysis will fall back to heuristics.", file=sys.stderr)
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:  # noqa: BLE001
        print(f"Warning: google-genai unavailable ({e}).", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Gemini vision -> JSON
# --------------------------------------------------------------------------- #
def _coerce_json(text: str) -> Optional[Any]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except Exception:  # noqa: BLE001
                return None
    return None


def vision_json(client, instruction: str, images: list[Path],
                extra: Optional[str] = None) -> Optional[Any]:
    """Send instruction + images to the vision model and parse a JSON reply.

    Returns the parsed object (dict/list) or None on any failure.
    """
    if client is None:
        return None
    try:
        from PIL import Image as PILImage
    except Exception:  # noqa: BLE001
        return None
    contents: list = [instruction]
    if extra:
        contents.append(extra)
    n = 0
    for p in images:
        try:
            contents.append(PILImage.open(str(p)))
            n += 1
        except Exception:  # noqa: BLE001
            continue
    if n == 0:
        return None
    try:
        resp = client.models.generate_content(model=VISION_MODEL, contents=contents)
        return _coerce_json(resp.text or "")
    except Exception as e:  # noqa: BLE001
        print(f"  ! vision error: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# PDF rendering + structural extraction (PyMuPDF)
# --------------------------------------------------------------------------- #
def _fitz():
    import fitz  # PyMuPDF
    return fitz


def page_geometry(pdf_path: str | Path) -> dict:
    """Return page count + size (pt) + A-format guess + orientation."""
    fitz = _fitz()
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        w, h = page.rect.width, page.rect.height
    finally:
        pass
    fmt = _guess_format(w, h)
    doc_count = doc.page_count
    doc.close()
    return {
        "page_count": doc_count,
        "w_pt": round(w, 1),
        "h_pt": round(h, 1),
        "format": fmt,
        "orientation": "portrait" if h >= w else "landscape",
    }


def _guess_format(w: float, h: float) -> str:
    a4 = (595, 842)
    letter = (612, 792)
    lo, hi = sorted((w, h))
    for name, (fw, fh) in (("A4", a4), ("Letter", letter)):
        if abs(lo - fw) < 6 and abs(hi - fh) < 6:
            return name
    return "custom"


def render_pages(pdf_path: str | Path, out_dir: str | Path, dpi: int = 120,
                 max_pages: Optional[int] = None) -> list[Path]:
    """Render each PDF page to a PNG. Returns the list of image paths in order."""
    fitz = _fitz()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    paths: list[Path] = []
    total = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
    for i in range(total):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        dest = out_dir / f"page-{i + 1:02d}.png"
        pix.save(str(dest))
        paths.append(dest)
    doc.close()
    return paths


def extract_structure(pdf_path: str | Path) -> list[dict]:
    """Per-page programmatic signals: text, embedded font names, image boxes."""
    fitz = _fitz()
    doc = fitz.open(str(pdf_path))
    pages: list[dict] = []
    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text("text") or ""
        fonts = []
        try:
            for f in page.get_fonts(full=True):
                # (xref, ext, type, basefont, name, encoding, ...)
                base = f[3] if len(f) > 3 else ""
                if base and base not in fonts:
                    fonts.append(base)
        except Exception:  # noqa: BLE001
            pass
        images = []
        try:
            for info in page.get_image_info():
                bbox = info.get("bbox")
                if bbox:
                    images.append([round(v, 1) for v in bbox])
        except Exception:  # noqa: BLE001
            pass
        pages.append({
            "n": i + 1,
            "text": text.strip(),
            "fonts": fonts,
            "image_boxes": images,
            "image_count": len(images),
        })
    doc.close()
    return pages


# --------------------------------------------------------------------------- #
# Color extraction (Pillow)
# --------------------------------------------------------------------------- #
def dominant_colors(img_path: str | Path, k: int = 6) -> list[str]:
    """Return up to k dominant colors as #hex, ordered by frequency."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return []
    try:
        im = Image.open(str(img_path)).convert("RGB")
        im.thumbnail((200, 200))
        q = im.quantize(colors=max(k, 2), method=Image.Quantize.FASTOCTREE)
        pal = q.getpalette() or []
        counts = q.getcolors() or []  # list of (count, palette_index)
        counts.sort(reverse=True)
        out: list[str] = []
        for _, idx in counts[:k]:
            r, g, b = pal[idx * 3: idx * 3 + 3]
            out.append(f"#{r:02x}{g:02x}{b:02x}")
        return out
    except Exception:  # noqa: BLE001
        return []


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(h: str) -> float:
    r, g, b = hex_to_rgb(h)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def saturation(h: str) -> float:
    r, g, b = (v / 255.0 for v in hex_to_rgb(h))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return 0.0
    return (mx - mn) / mx


# --------------------------------------------------------------------------- #
# Text utilities
# --------------------------------------------------------------------------- #
def slugify(text: str, maxlen: int = 60, default: str = "doc") -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:maxlen] or default


# --------------------------------------------------------------------------- #
# asset-generator bridge
# --------------------------------------------------------------------------- #
def run_asset_generator(prompt: str, output: str | Path, *, style: Optional[str] = None,
                        aspect_ratio: Optional[str] = None, resolution: str = "2K",
                        refs: Optional[list[str]] = None, transparent: bool = False,
                        thinking: str = "high", raw_prompt: bool = False,
                        timeout: int = 600) -> bool:
    """Invoke the asset-generator skill to produce one image. Returns success."""
    if not ASSET_GEN_SCRIPT.exists():
        print(f"Error: asset-generator not found at {ASSET_GEN_SCRIPT}", file=sys.stderr)
        return False
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ASSET_GEN_SCRIPT), prompt, "-o", str(output),
           "-r", resolution, "--thinking", thinking]
    if style:
        cmd += ["-s", style]
    if aspect_ratio:
        cmd += ["-ar", aspect_ratio]
    if transparent:
        cmd += ["-t"]
    if raw_prompt:
        cmd += ["--raw-prompt"]
    for r in refs or []:
        cmd += ["--ref", str(r)]
    print("  $ " + " ".join(shlex.quote(c) for c in cmd[:2]) + " ... -o " + str(output),
          file=sys.stderr)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"  ! asset-generator timed out after {timeout}s", file=sys.stderr)
        return False
    if res.returncode != 0:
        print(f"  ! asset-generator failed: {res.stderr.strip()[-500:]}", file=sys.stderr)
        return False
    return output.exists()


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #
def load_font_manifest() -> dict:
    """Return the fonts.json role->family/files manifest (may be empty)."""
    return _read_json(FONTS_DIR / "fonts.json")


def font_face_css() -> str:
    """Emit @font-face rules for every bundled font file (absolute file:// src)."""
    manifest = load_font_manifest()
    faces: list[str] = []
    for fam in manifest.get("families", []):
        for face in fam.get("faces", []):
            path = FONTS_DIR / face["file"]
            if not path.exists():
                continue
            faces.append(
                "@font-face{"
                f"font-family:'{fam['css_family']}';"
                f"font-style:{face.get('style', 'normal')};"
                f"font-weight:{face.get('weight', '400')};"
                f"src:url('file://{path}') format('truetype');"
                "font-display:block;}"
            )
    return "\n".join(faces)


def role_family(role: str, fallback: str = "serif") -> str:
    """Map a typographic role (display_serif, brush_script, hand_marker, body_sans)
    to a CSS font-family stack from the manifest."""
    manifest = load_font_manifest()
    roles = manifest.get("roles", {})
    fam = roles.get(role)
    if fam:
        generic = {"display_serif": "serif", "body_sans": "sans-serif"}.get(role, "cursive")
        return f"'{fam}', {generic}"
    return fallback


# --------------------------------------------------------------------------- #
# HTML -> PDF (Playwright / Chromium)
# --------------------------------------------------------------------------- #
def html_to_pdf(html_file: str | Path, out_pdf: str | Path) -> bool:
    """Render an on-disk HTML file (loaded via file://) to a PDF using Chromium.

    The HTML must define its own @page size (we pass prefer_css_page_size=True)
    and rely on print_background=True for full-bleed color/photo pages.
    """
    html_file = Path(html_file).resolve()
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        print(f"Error: playwright unavailable ({e}). "
              "Run: pip3 install playwright && python3 -m playwright install chromium",
              file=sys.stderr)
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--force-color-profile=srgb"])
            page = browser.new_page()
            page.goto(f"file://{html_file}", wait_until="networkidle")
            page.emulate_media(media="print")
            # Give web fonts a beat to load before printing.
            try:
                page.evaluate("document.fonts && document.fonts.ready")
                page.wait_for_timeout(400)
            except Exception:  # noqa: BLE001
                pass
            page.pdf(path=str(out_pdf), prefer_css_page_size=True,
                     print_background=True, margin={"top": "0", "bottom": "0",
                                                     "left": "0", "right": "0"})
            browser.close()
        return out_pdf.exists()
    except Exception as e:  # noqa: BLE001
        print(f"Error rendering PDF: {e}", file=sys.stderr)
        return False


def esc(text: Any) -> str:
    """HTML-escape a value for safe insertion into templates."""
    if text is None:
        return ""
    s = str(text)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
