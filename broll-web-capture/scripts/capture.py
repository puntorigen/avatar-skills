#!/usr/bin/env python3
"""Capture web pages / GitHub repos as high-DPI stills for broll-web-capture.

Shares the Playwright (headless Chromium) stack with the `web-screenshot` skill,
but adds what the motion engine needs: a retina device-scale-factor for crisp
zooms, full-page (tall) capture for scroll-reveal, element bounding boxes for
spotlight, and GitHub-aware "money-shot" capture + live star counts via the API.

Importable (capture_page / capture_element / github_stats / github_shots) and a
CLI for one-off stills.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    print("Error: playwright not installed. Run:\n"
          "  pip3 install -r .cursor/skills/broll-web-capture/scripts/requirements.txt\n"
          "  playwright install chromium", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_VIEWPORT = (1440, 900)
GITHUB_VIEWPORT = (1280, 860)
HIDE_CSS_TEMPLATE = "{sel} {{ display: none !important; visibility: hidden !important; }}"
# Best-effort consent/cookie/banner removal so captures are clean.
DEFAULT_HIDE = [
    "[id*='cookie' i]", "[class*='cookie' i]", "[id*='consent' i]",
    "[class*='consent' i]", "[aria-label*='cookie' i]", ".cookie-banner",
]


def _apply_hide(page, selectors: list[str]) -> None:
    if not selectors:
        return
    css = "\n".join(HIDE_CSS_TEMPLATE.format(sel=s) for s in selectors)
    try:
        page.add_style_tag(content=css)
    except Exception:
        pass


def capture_page(
    url: str,
    out_png: Path,
    *,
    viewport: tuple[int, int] = DEFAULT_VIEWPORT,
    scale: int = 2,
    full_page: bool = False,
    selector: str | None = None,
    focus_selector: str | None = None,
    dark_mode: bool = False,
    wait: float = 1.2,
    wait_until: str = "networkidle",
    hide: list[str] | None = None,
    locale: str | None = None,
) -> dict:
    """Capture a page (or one element) to a PNG. Returns metadata incl. dims.

    If `selector` is set, the capture is cropped to that element and its bounding
    box (image px) is returned as "bbox". If `focus_selector` is set instead, the
    full viewport is captured and the focus element's bbox is measured (for a
    spotlight push-in) without cropping. Boxes are in *image pixels*
    (CSS px * device_scale_factor): [x, y, w, h].
    """
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    hide = (hide if hide is not None else []) + DEFAULT_HIDE
    bbox = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_kwargs = {
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "device_scale_factor": scale,
        }
        if dark_mode:
            ctx_kwargs["color_scheme"] = "dark"
        if locale:
            ctx_kwargs["locale"] = locale
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        # Kill scrollbars so they don't show up in the capture.
        page.add_init_script(
            "document.addEventListener('DOMContentLoaded',()=>{"
            "const s=document.createElement('style');"
            "s.textContent='::-webkit-scrollbar{display:none!important}"
            "*{scrollbar-width:none!important}';document.head.appendChild(s);});"
        )
        print(f"[capture] {url}", file=sys.stderr)
        try:
            page.goto(url, wait_until=wait_until, timeout=60000)
        except Exception:
            page.goto(url, wait_until="load", timeout=60000)
        if wait > 0:
            page.wait_for_timeout(int(wait * 1000))
        _apply_hide(page, hide)
        page.wait_for_timeout(150)

        shot_kwargs = {"path": str(out_png), "animations": "disabled"}
        if selector:
            el = page.locator(selector).first
            el.wait_for(state="visible", timeout=15000)
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            box = el.bounding_box()
            el.screenshot(path=str(out_png))
            if box:
                bbox = [box["x"] * scale, box["y"] * scale,
                        box["width"] * scale, box["height"] * scale]
        else:
            if focus_selector:
                try:
                    fb = page.locator(focus_selector).first
                    fb.wait_for(state="visible", timeout=10000)
                    fb.scroll_into_view_if_needed()
                    page.wait_for_timeout(150)
                    box = fb.bounding_box()
                    if box:
                        bbox = [box["x"] * scale, box["y"] * scale,
                                box["width"] * scale, box["height"] * scale]
                except Exception as e:
                    print(f"[capture] focus selector not found ({e})", file=sys.stderr)
            shot_kwargs["full_page"] = full_page
            page.screenshot(**shot_kwargs)

        context.close()
        browser.close()

    from PIL import Image
    with Image.open(out_png) as im:
        w, h = im.size
    meta = {"url": url, "path": str(out_png), "width": w, "height": h,
            "full_page": full_page, "selector": selector}
    if bbox:
        # clamp bbox to image
        x, y, bw, bh = bbox
        x = max(0, min(x, w)); y = max(0, min(y, h))
        bw = max(1, min(bw, w - x)); bh = max(1, min(bh, h - y))
        meta["bbox"] = [round(x), round(y), round(bw), round(bh)]
    print(f"[capture] -> {out_png} ({w}x{h})", file=sys.stderr)
    return meta


# ------------------------------- GitHub preset -------------------------------

def parse_repo(url_or_slug: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a github URL or 'owner/repo' slug."""
    s = url_or_slug.strip()
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", s)
    if m:
        return m.group(1), re.sub(r"\.git$", "", m.group(2))
    m = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", s)
    if m:
        return m.group(1), m.group(2)
    return None


def parse_owner(url_or_handle: str) -> str | None:
    s = url_or_handle.strip().lstrip("@")
    m = re.search(r"github\.com/([^/\s#?]+)", s)
    if m:
        return m.group(1)
    m = re.fullmatch(r"[A-Za-z0-9_-]+", s)
    return s if m else None


def github_stats(owner: str, repo: str, token: str | None = None) -> dict:
    """Fetch live repo stats from the GitHub API (no auth needed for low volume)."""
    api = f"https://api.github.com/repos/{owner}/{repo}"
    req = urllib.request.Request(api, headers={
        "User-Agent": "broll-web-capture",
        "Accept": "application/vnd.github+json",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"[github] stats unavailable ({e}); continuing without counters",
              file=sys.stderr)
        return {}
    return {
        "owner": owner, "repo": repo,
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "language": data.get("language"),
        "description": data.get("description"),
        "full_name": data.get("full_name", f"{owner}/{repo}"),
    }


def github_shots(owner: str, repo: str, out_dir: Path, *, dark: bool = True,
                 shots: list[str] | None = None) -> dict[str, dict]:
    """Capture GitHub 'money-shots'. Returns {shot_name: capture_meta}.

    shots subset of: header (repo landing), readme, contrib (profile calendar).
    Selectors are kept overridable-friendly and fall back to a full viewport
    grab if a selector vanishes (GitHub's DOM changes over time).
    """
    out_dir = Path(out_dir)
    shots = shots or ["header", "readme", "contrib"]
    repo_url = f"https://github.com/{owner}/{repo}"
    results: dict[str, dict] = {}

    if "header" in shots:
        # Repo landing viewport: name + description + stars + README top.
        results["header"] = capture_page(
            repo_url, out_dir / "gh_header.png",
            viewport=GITHUB_VIEWPORT, dark_mode=dark, full_page=False)
    if "readme" in shots:
        try:
            results["readme"] = capture_page(
                repo_url, out_dir / "gh_readme.png", viewport=GITHUB_VIEWPORT,
                dark_mode=dark, selector="article.markdown-body")
        except Exception as e:
            print(f"[github] readme selector failed ({e}); using full page",
                  file=sys.stderr)
    if "contrib" in shots:
        try:
            results["contrib"] = capture_page(
                f"https://github.com/{owner}", out_dir / "gh_contrib.png",
                viewport=GITHUB_VIEWPORT, dark_mode=dark,
                selector=".js-calendar-graph, .ContributionCalendar, "
                         "div[class*='graph-before-activity-overview']")
        except Exception as e:
            print(f"[github] contrib selector failed ({e}); skipping",
                  file=sys.stderr)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture a web page / element to PNG.")
    ap.add_argument("url")
    ap.add_argument("-o", "--out", type=Path, default=Path("capture.png"))
    ap.add_argument("--viewport", default="1440x900", help="WxH (default 1440x900)")
    ap.add_argument("--scale", type=int, default=2, help="device scale factor")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--selector", default=None)
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--wait", type=float, default=1.2)
    ap.add_argument("--hide", action="append", default=[], help="CSS selector to hide (repeatable)")
    ap.add_argument("--locale", default=None)
    args = ap.parse_args()
    vw = tuple(int(x) for x in args.viewport.lower().split("x"))
    meta = capture_page(
        args.url, args.out, viewport=vw, scale=args.scale, full_page=args.full_page,
        selector=args.selector, dark_mode=args.dark, wait=args.wait,
        hide=args.hide, locale=args.locale)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
