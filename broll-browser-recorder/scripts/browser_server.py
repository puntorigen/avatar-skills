#!/usr/bin/env python3
"""Interactive browser recording server.

Launches a Playwright browser with optional video recording and exposes
an HTTP API for adaptive, step-by-step interaction. The AI agent controls
the browser via curl, seeing page state after each action.

Supports a two-phase workflow:
  Practice mode (--no-record): No video capture, records HAR for network
    analysis, produces a playbook.json with action plan, element bounds,
    timing, crop recommendations, and network insights.
  Record mode (default): Full video recording with cursor indicator.

Usage:
    python3 browser_server.py https://example.com --viewport 1920x1080 --port 9222 -o /tmp/rec/
    python3 browser_server.py https://example.com --no-record -o /tmp/practice/

Endpoints:
    GET  /status    - Server health check
    GET  /snapshot  - Screenshot + page state + interactive elements
    POST /action    - Execute browser action, returns fresh snapshot
    POST /discover  - Lightweight element bounds query (no screenshot)
    POST /stop      - Stop recording, save video/playbook, shut down
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Cache lives alongside the skill (works both in-repo and once installed under
# .cursor/skills/broll-browser-recorder/).
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright not installed. Run:", file=sys.stderr)
    print("  pip3 install playwright && playwright install chromium", file=sys.stderr)
    sys.exit(1)


CURSOR_INDICATOR_JS = """
(() => {
    if (window.__cursorIndicatorInjected) return;
    window.__cursorIndicatorInjected = true;

    const el = document.createElement('div');
    el.id = '__recording_cursor';
    el.innerHTML = `<svg width="28" height="34" viewBox="0 0 28 34" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M2 2L12 28L16 18L26 14L2 2Z" fill="white" stroke="#222" stroke-width="2" stroke-linejoin="round"/>
    </svg>`;
    Object.assign(el.style, {
        position: 'fixed',
        zIndex: '2147483647',
        pointerEvents: 'none',
        transition: 'left 0.35s cubic-bezier(0.4,0,0.2,1), top 0.35s cubic-bezier(0.4,0,0.2,1), opacity 0.2s ease',
        left: '-50px',
        top: '-50px',
        filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.35))',
        opacity: '1',
    });
    document.body.appendChild(el);

    const INPUT_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
    const isOverInput = (x, y) => {
        const target = document.elementFromPoint(x, y);
        if (!target) return false;
        if (INPUT_TAGS.has(target.tagName)) return true;
        if (target.isContentEditable) return true;
        return !!target.closest('input, textarea, select, [contenteditable="true"]');
    };

    window.__moveCursorTo = (x, y) => {
        el.style.left = x + 'px';
        el.style.top = y + 'px';
        el.style.opacity = isOverInput(x, y) ? '0' : '1';
    };

    window.__cursorPulse = () => {
        if (el.style.opacity === '0') return;
        const r = document.createElement('div');
        Object.assign(r.style, {
            position: 'fixed',
            left: el.style.left, top: el.style.top,
            width: '30px', height: '30px', borderRadius: '50%',
            background: 'rgba(59,130,246,0.35)',
            transform: 'translate(-50%,-50%) scale(0.5)',
            pointerEvents: 'none', zIndex: '2147483646',
            transition: 'transform 0.35s ease-out, opacity 0.35s ease-out',
        });
        document.body.appendChild(r);
        requestAnimationFrame(() => {
            r.style.transform = 'translate(-50%,-50%) scale(2.5)';
            r.style.opacity = '0';
        });
        setTimeout(() => r.remove(), 400);
    };

    window.__hideCursor = () => { el.style.opacity = '0'; };
    window.__showCursor = () => { el.style.opacity = '1'; };
})();
"""

DEVICE_SHORTCUTS = {
    "desktop-hd": {"width": 1280, "height": 720},
    "desktop-fhd": {"width": 1920, "height": 1080},
    "desktop-2k": {"width": 2560, "height": 1440},
}


class BrowserState:
    """Holds the Playwright browser, context, page, and recording metadata."""

    def __init__(self, url, output_dir, viewport, device, dark_mode,
                 hide_scrollbar, show_cursor, wait_seconds, wait_until,
                 locale, use_chrome, playwright_devices, no_record=False,
                 cache_name=None, clean=False):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.snap_counter = 0
        self.action_log = []
        self.start_time = time.time()
        self.recording = not no_record
        self.show_cursor = show_cursor and self.recording
        self.stopped = False
        self.url = url
        self.cache_name = cache_name
        self.locale = locale
        self.use_chrome = use_chrome

        self.pw = sync_playwright().start()
        launch_kwargs = {"headless": True}
        if use_chrome:
            launch_kwargs["channel"] = "chrome"
            launch_kwargs["args"] = [
                "--disable-infobars",
                "--disable-blink-features=AutomationControlled",
            ]
        self.browser = self.pw.chromium.launch(**launch_kwargs)

        context_kwargs = {}

        if clean:
            context_kwargs["storage_state"] = {
                "cookies": [], "origins": []
            }
            context_kwargs["service_workers"] = "block"

        if self.recording:
            context_kwargs["record_video_dir"] = str(self.output_dir)
        else:
            context_kwargs["record_har_path"] = str(self.output_dir / "practice.har")
            context_kwargs["record_har_url_filter"] = "**/*"

        if device and device in playwright_devices:
            context_kwargs.update(playwright_devices[device])
        elif device and device.lower() in DEVICE_SHORTCUTS:
            vp = DEVICE_SHORTCUTS[device.lower()]
            context_kwargs["viewport"] = vp

        if viewport:
            context_kwargs["viewport"] = viewport
            if self.recording:
                context_kwargs["record_video_size"] = viewport

        if dark_mode:
            context_kwargs["color_scheme"] = "dark"

        if locale:
            context_kwargs["locale"] = locale

        actual_vp = context_kwargs.get("viewport", {"width": 1920, "height": 1080})
        if self.recording and "record_video_size" not in context_kwargs:
            context_kwargs["record_video_size"] = actual_vp

        self.viewport = actual_vp
        self.chrome_bar_height = 0
        self._response_log = []
        self.context = self.browser.new_context(**context_kwargs)
        self.page = self.context.new_page()
        self.page.on("response", self._on_network_response)

        if hide_scrollbar:
            self.page.add_init_script("""
                document.addEventListener('DOMContentLoaded', () => {
                    const s = document.createElement('style');
                    s.textContent = '::-webkit-scrollbar{display:none!important}*{scrollbar-width:none!important}';
                    document.head.appendChild(s);
                });
            """)

        if use_chrome:
            self._force_viewport_via_cdp(actual_vp)

        mode_label = "practice" if not self.recording else "recording"
        print(f"Navigating to: {url} ({mode_label} mode)", file=sys.stderr)
        self.page.goto(url, wait_until=wait_until, timeout=60000)

        self._wait_for_media(timeout_ms=15000)

        if wait_seconds > 0:
            print(f"Waiting {wait_seconds}s after load...", file=sys.stderr)
            self.page.wait_for_timeout(int(wait_seconds * 1000))

        if self.show_cursor:
            self._inject_cursor()

    def _force_viewport_via_cdp(self, desired_vp):
        """Use CDP to force the full viewport, bypassing Chrome's automation bar."""
        cdp = self.context.new_cdp_session(self.page)
        cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": desired_vp["width"],
            "height": desired_vp["height"],
            "deviceScaleFactor": 1,
            "mobile": False,
        })
        actual_h = self.page.evaluate("() => window.innerHeight")
        if actual_h >= desired_vp["height"]:
            print(f"  CDP viewport override: {desired_vp['width']}x{actual_h}",
                  file=sys.stderr)
        else:
            bar_h = desired_vp["height"] - actual_h
            print(f"  CDP override partial (bar still {bar_h}px), "
                  f"inner: {actual_h}", file=sys.stderr)
            self.chrome_bar_height = bar_h

    def _on_network_response(self, response):
        """Track all network responses for wait_for_response."""
        try:
            self._response_log.append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
                "timestamp": round(time.time() - self.start_time, 3),
            })
        except Exception:
            pass

    def _wait_for_media(self, timeout_ms=15000):
        """Wait for all video/img elements to load, including hidden ones."""
        try:
            result = self.page.evaluate("""(timeoutMs) => {
                return new Promise((resolve) => {
                    // Force all video elements to start loading
                    document.querySelectorAll('video').forEach(v => {
                        v.preload = 'auto';
                        v.load();
                    });
                    // Preload video sources found in source elements
                    document.querySelectorAll('video source').forEach(s => {
                        if (s.src) fetch(s.src, { mode: 'no-cors' }).catch(() => {});
                    });

                    const deadline = Date.now() + timeoutMs;
                    const check = () => {
                        const videos = Array.from(document.querySelectorAll('video'));
                        const readyCount = videos.filter(v => v.readyState >= 2).length;

                        const imgs = Array.from(document.querySelectorAll('img'));
                        const visible = imgs.filter(i => {
                            const r = i.getBoundingClientRect();
                            return r.width > 0 && r.height > 0
                                && r.bottom > 0 && r.top < window.innerHeight;
                        });
                        const imgsReady = visible.every(i => i.complete && i.naturalWidth > 0);

                        if ((readyCount === videos.length && imgsReady) || Date.now() > deadline) {
                            resolve({
                                videos: videos.length,
                                videosReady: readyCount,
                                imgs: visible.length,
                                imgsReady: visible.filter(i => i.complete).length,
                                timedOut: Date.now() > deadline,
                            });
                        } else {
                            setTimeout(check, 300);
                        }
                    };
                    setTimeout(check, 500);
                });
            }""", timeout_ms + 5000)
            status = "OK" if not result.get("timedOut") else "partial"
            print(f"  Media: {status} ({result['videosReady']}/{result['videos']} videos, "
                  f"{result['imgsReady']}/{result['imgs']} images)", file=sys.stderr)
        except Exception as e:
            print(f"  Media wait warning: {e}", file=sys.stderr)

    def _inject_cursor(self):
        try:
            self.page.evaluate(CURSOR_INDICATOR_JS)
        except Exception:
            pass

    def _move_cursor_to_element(self, selector):
        if not self.show_cursor:
            return
        try:
            self._inject_cursor()
            box = self.page.locator(selector).first.bounding_box(timeout=3000)
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                self.page.evaluate(f"window.__moveCursorTo && window.__moveCursorTo({cx}, {cy})")
                self.page.wait_for_timeout(400)
        except Exception:
            pass

    def _move_cursor_to_xy(self, x, y):
        if not self.show_cursor:
            return
        try:
            self._inject_cursor()
            self.page.evaluate(f"window.__moveCursorTo && window.__moveCursorTo({x}, {y})")
            self.page.wait_for_timeout(400)
        except Exception:
            pass

    def _pulse_cursor(self):
        if not self.show_cursor:
            return
        try:
            self.page.evaluate("window.__cursorPulse && window.__cursorPulse()")
            self.page.wait_for_timeout(250)
        except Exception:
            pass

    def _hide_cursor(self):
        if not self.show_cursor:
            return
        try:
            self.page.evaluate("window.__hideCursor && window.__hideCursor()")
        except Exception:
            pass

    def _show_cursor(self):
        if not self.show_cursor:
            return
        try:
            self.page.evaluate("window.__showCursor && window.__showCursor()")
        except Exception:
            pass

    def take_snapshot(self):
        self.snap_counter += 1
        filename = f"snap_{self.snap_counter:04d}.png"
        filepath = self.output_dir / filename
        self.page.screenshot(path=str(filepath))

        elements = self._discover_elements()

        return {
            "url": self.page.url,
            "title": self.page.title(),
            "screenshot": str(filepath),
            "viewport": self.viewport,
            "snap_number": self.snap_counter,
            "elapsed": round(time.time() - self.start_time, 1),
            "elements": elements,
        }

    def _discover_elements(self):
        try:
            return self.page.evaluate("""() => {
                const selectors = 'a, button, input, textarea, select, [role="button"], [role="link"], [role="tab"], [tabindex], [onclick]';
                const els = Array.from(document.querySelectorAll(selectors));
                const results = [];
                for (const el of els.slice(0, 50)) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    const isVisible = rect.top < window.innerHeight && rect.bottom > 0
                                   && rect.left < window.innerWidth && rect.right > 0;
                    if (!isVisible) continue;

                    let selector = '';
                    if (el.id) selector = '#' + el.id;
                    else if (el.className && typeof el.className === 'string') {
                        const cls = el.className.trim().split(/\\s+/).filter(c => c && !c.includes(':')).slice(0, 3).join('.');
                        if (cls) selector = el.tagName.toLowerCase() + '.' + cls;
                    }
                    if (!selector) {
                        const tag = el.tagName.toLowerCase();
                        const type = el.getAttribute('type');
                        const name = el.getAttribute('name');
                        const role = el.getAttribute('role');
                        if (name) selector = tag + '[name="' + name + '"]';
                        else if (role) selector = tag + '[role="' + role + '"]';
                        else if (type) selector = tag + '[type="' + type + '"]';
                        else selector = tag;
                    }

                    results.push({
                        selector: selector,
                        tag: el.tagName.toLowerCase(),
                        text: (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').slice(0, 100).trim(),
                        bbox: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    });
                }
                return results;
            }""")
        except Exception:
            return []

    def execute_action(self, action_data):
        action = action_data.get("action", "")
        selector = action_data.get("selector", "")
        timestamp = round(time.time() - self.start_time, 2)
        log_entry = {"action": action, "timestamp": timestamp, **action_data}

        try:
            if action == "click":
                if selector:
                    self._move_cursor_to_element(selector)
                    self._pulse_cursor()
                    self.page.locator(selector).first.click(timeout=action_data.get("timeout", 10000))
                elif "x" in action_data and "y" in action_data:
                    x, y = action_data["x"], action_data["y"]
                    self._move_cursor_to_xy(x, y)
                    self._pulse_cursor()
                    self.page.mouse.click(x, y)

            elif action == "type":
                delay = action_data.get("delay", 60)
                text = action_data.get("text", "")
                if selector:
                    self._move_cursor_to_element(selector)
                    self._pulse_cursor()
                    self.page.locator(selector).first.press_sequentially(text, delay=delay)
                else:
                    self.page.keyboard.type(text, delay=delay)

            elif action == "fill":
                if selector:
                    self._move_cursor_to_element(selector)
                text = action_data.get("text", action_data.get("value", ""))
                self.page.locator(selector).first.fill(text)

            elif action == "press":
                key = action_data.get("key", "Enter")
                if selector:
                    self.page.locator(selector).first.press(key)
                else:
                    self.page.keyboard.press(key)

            elif action == "scroll":
                if selector:
                    self.page.locator(selector).first.scroll_into_view_if_needed()
                else:
                    x = action_data.get("x", 0)
                    y = action_data.get("y", 500)
                    self.page.mouse.wheel(x, y)

            elif action == "hover":
                if selector:
                    self._move_cursor_to_element(selector)
                    self.page.locator(selector).first.hover(timeout=action_data.get("timeout", 10000))
                elif "x" in action_data and "y" in action_data:
                    self._move_cursor_to_xy(action_data["x"], action_data["y"])
                    self.page.mouse.move(action_data["x"], action_data["y"])

            elif action == "wait":
                seconds = action_data.get("seconds", 1)
                self.page.wait_for_timeout(int(seconds * 1000))

            elif action == "wait_for":
                if selector:
                    state = action_data.get("state", "visible")
                    timeout = action_data.get("timeout", 30000)
                    self.page.locator(selector).first.wait_for(state=state, timeout=timeout)
                elif "text" in action_data:
                    timeout = action_data.get("timeout", 30000)
                    self.page.get_by_text(action_data["text"]).first.wait_for(state="visible", timeout=timeout)

            elif action == "wait_for_response":
                url_pattern = action_data.get("url_pattern", "")
                method_filter = action_data.get("method", "").upper()
                timeout_s = action_data.get("timeout", 30)
                since = timestamp
                deadline = time.time() + timeout_s
                matched = None

                while time.time() < deadline:
                    for entry in reversed(self._response_log):
                        if entry["timestamp"] < since:
                            break
                        url_ok = url_pattern in entry["url"]
                        method_ok = (not method_filter
                                     or entry["method"] == method_filter)
                        if url_ok and method_ok:
                            matched = entry
                            break
                    if matched:
                        break
                    self.page.wait_for_timeout(200)

                if matched:
                    log_entry["result"] = (
                        f"matched {matched['method']} {matched['url'].split('?')[0][-60:]} "
                        f"status={matched['status']} at {matched['timestamp']:.1f}s"
                    )
                else:
                    log_entry["result"] = f"timeout after {timeout_s}s"

            elif action == "wait_for_text_stable":
                target = selector or action_data.get("target", "body")
                timeout_s = action_data.get("timeout", 60)
                stable_s = action_data.get("stable", 3)
                min_growth = action_data.get("min_growth", 0)
                poll_ms = action_data.get("poll_ms", 500)
                js_get = f'document.querySelector("{target}")?.innerText?.length || 0'
                baseline_len = self.page.evaluate(js_get)
                last_len = baseline_len
                stable_since = None
                deadline = time.time() + timeout_s

                while time.time() < deadline:
                    self.page.wait_for_timeout(poll_ms)
                    cur_len = self.page.evaluate(js_get)
                    grew = cur_len - baseline_len >= min_growth
                    if cur_len == last_len and grew:
                        if stable_since is None:
                            stable_since = time.time()
                        elif time.time() - stable_since >= stable_s:
                            break
                    else:
                        stable_since = None
                    last_len = cur_len

                log_entry["result"] = f"stable len={last_len} (was {baseline_len})"

            elif action == "wait_for_text_contains":
                target = selector or action_data.get("target", "body")
                text_match = action_data.get("text", "")
                timeout_s = action_data.get("timeout", 60)
                poll_ms = action_data.get("poll_ms", 500)
                js_check = f'(document.querySelector("{target}")?.innerText || "").includes("{text_match}")'
                deadline = time.time() + timeout_s
                found = False

                while time.time() < deadline:
                    if self.page.evaluate(js_check):
                        found = True
                        break
                    self.page.wait_for_timeout(poll_ms)

                log_entry["result"] = f"found={found}"

            elif action == "navigate":
                url = action_data.get("url", "")
                wait_until = action_data.get("wait_until", "load")
                self.page.goto(url, wait_until=wait_until, timeout=60000)
                if self.show_cursor:
                    self._inject_cursor()

            elif action == "evaluate":
                expression = action_data.get("expression", "")
                result = self.page.evaluate(expression)
                log_entry["result"] = str(result)[:500]

            elif action == "select":
                value = action_data.get("value", "")
                self.page.locator(selector).first.select_option(value)

            elif action == "camera":
                if "center" in action_data and "region" not in action_data:
                    cx, cy = action_data["center"]
                    zoom = action_data.get("zoom", 1.0)
                    vw = self.page.viewport_size["width"]
                    vh = self.page.viewport_size["height"]
                    zw = max(1, int(vw / zoom))
                    zh = max(1, int(vh / zoom))
                    log_entry["region"] = [
                        max(0, cx - zw // 2), max(0, cy - zh // 2), zw, zh
                    ]
                log_entry["result"] = "camera hint recorded"

            else:
                log_entry["error"] = f"Unknown action: {action}"

        except Exception as e:
            log_entry["error"] = str(e)[:300]
            print(f"  Action error ({action}): {e}", file=sys.stderr)

        self.action_log.append(log_entry)
        snapshot = self.take_snapshot()
        snapshot["action_result"] = log_entry
        return snapshot

    def discover_element(self, selector):
        """Return bounding box and child count for a selector without taking a screenshot."""
        try:
            loc = self.page.locator(selector).first
            box = loc.bounding_box(timeout=5000)
            count = self.page.locator(selector).count()
            children = self.page.evaluate(
                f'(document.querySelector("{selector}")?.children.length) ?? 0'
            )
            return {
                "selector": selector,
                "bounds": {
                    "x": round(box["x"]), "y": round(box["y"]),
                    "w": round(box["width"]), "h": round(box["height"]),
                } if box else None,
                "count": count,
                "children": children,
            }
        except Exception as e:
            return {"selector": selector, "error": str(e)[:200]}

    def _analyze_har(self):
        """Parse practice.har and extract network insights for the playbook."""
        har_path = self.output_dir / "practice.har"
        if not har_path.exists():
            return None

        try:
            har = json.loads(har_path.read_text())
        except Exception:
            return None

        entries = har.get("log", {}).get("entries", [])
        if not entries:
            return None

        api_calls = []
        page_resources = []
        first_entry_start = None

        for entry in entries:
            req = entry.get("request", {})
            resp = entry.get("response", {})
            url = req.get("url", "")
            method = req.get("method", "GET")
            status = resp.get("status", 0)
            mime = resp.get("content", {}).get("mimeType", "")
            total_time_ms = entry.get("time", 0)
            started = entry.get("startedDateTime", "")

            if first_entry_start is None:
                first_entry_start = started

            is_streaming = (
                "text/event-stream" in mime
                or resp.get("headers", []) and any(
                    h.get("name", "").lower() == "transfer-encoding"
                    and "chunked" in h.get("value", "").lower()
                    for h in resp.get("headers", [])
                )
            )

            if (method == "POST" and status >= 200 and "json" in mime) or is_streaming:
                body_text = resp.get("content", {}).get("text", "")
                api_calls.append({
                    "url": url,
                    "method": method,
                    "status": status,
                    "duration_s": round(total_time_ms / 1000, 2),
                    "streaming": is_streaming,
                    "response_size": len(body_text),
                    "response_text_preview": body_text[:300] if body_text else "",
                })
            else:
                parsed_url = urlparse(url)
                filename = parsed_url.path.split("/")[-1] if parsed_url.path else url
                page_resources.append({
                    "url": url,
                    "filename": filename,
                    "mime": mime,
                    "duration_s": round(total_time_ms / 1000, 2),
                    "status": status,
                })

        chat_api_calls = [c for c in api_calls if c["duration_s"] > 1.0]
        if not chat_api_calls and api_calls:
            chat_api_calls = api_calls

        chat_api = None
        if chat_api_calls:
            url_pattern = chat_api_calls[0]["url"]
            parsed = urlparse(url_pattern)
            avg_time = sum(c["duration_s"] for c in chat_api_calls) / len(chat_api_calls)
            chat_api = {
                "url_pattern": parsed.path,
                "method": chat_api_calls[0]["method"],
                "streaming": any(c["streaming"] for c in chat_api_calls),
                "avg_response_time_s": round(avg_time, 1),
                "responses": [
                    {
                        "duration_s": c["duration_s"],
                        "response_size": c["response_size"],
                    }
                    for c in chat_api_calls
                ],
            }

        media_urls = [
            r["url"] for r in page_resources
            if any(ext in r.get("mime", "") for ext in ["video", "audio"])
        ]

        load_resources = sorted(page_resources, key=lambda r: r["duration_s"], reverse=True)
        total_load = max((r["duration_s"] for r in page_resources), default=0)

        return {
            "chat_api": chat_api,
            "page_load": {
                "total_load_time_s": round(total_load, 1),
                "media_urls": media_urls,
                "slowest_resources": [
                    {"filename": r["filename"], "duration_s": r["duration_s"]}
                    for r in load_resources[:5]
                ],
            },
            "total_api_calls": len(api_calls),
            "total_resources": len(page_resources),
        }

    def _generate_playbook(self, duration):
        """Build a playbook from the practice session's action log, snapshots, and HAR."""
        clean_actions = []
        element_bounds = {}
        message_count = 0

        for entry in self.action_log:
            action = entry.get("action", "")
            if action == "evaluate":
                continue

            clean_entry = {
                "action": action,
                "timestamp": entry.get("timestamp"),
            }

            if action == "click":
                if entry.get("selector"):
                    clean_entry["selector"] = entry["selector"]
                if "x" in entry and "y" in entry:
                    clean_entry["x"] = entry["x"]
                    clean_entry["y"] = entry["y"]

            elif action == "type":
                clean_entry["selector"] = entry.get("selector", "")
                clean_entry["text"] = entry.get("text", "")
                clean_entry["delay"] = entry.get("delay", 60)

            elif action == "press":
                clean_entry["key"] = entry.get("key", "Enter")
                if entry.get("selector"):
                    clean_entry["selector"] = entry["selector"]
                if entry.get("key", "Enter") == "Enter":
                    message_count += 1

            elif action == "fill":
                clean_entry["selector"] = entry.get("selector", "")
                clean_entry["text"] = entry.get("text", "")

            elif action in ("scroll", "hover"):
                if entry.get("selector"):
                    clean_entry["selector"] = entry["selector"]
                if "x" in entry:
                    clean_entry["x"] = entry["x"]
                if "y" in entry:
                    clean_entry["y"] = entry["y"]

            elif action in ("wait", "wait_for", "navigate", "select"):
                for k in ("seconds", "selector", "state", "timeout",
                           "text", "url", "wait_until", "value"):
                    if k in entry:
                        clean_entry[k] = entry[k]

            if entry.get("error"):
                clean_entry["error"] = entry["error"]

            clean_actions.append(clean_entry)

        meaningful_ts = [
            e["timestamp"] for e in self.action_log
            if e.get("action") not in ("evaluate", "wait")
        ]
        content_start = min(meaningful_ts) if meaningful_ts else 0
        content_end = max(meaningful_ts) + 5.0 if meaningful_ts else duration

        for entry in self.action_log:
            sel = entry.get("selector", "")
            if not sel:
                continue
            try:
                box = self.page.locator(sel).first.bounding_box(timeout=1000)
                if box:
                    element_bounds[sel] = {
                        "x": round(box["x"]), "y": round(box["y"]),
                        "w": round(box["width"]), "h": round(box["height"]),
                    }
            except Exception:
                pass

        crop_recommendation = None
        if element_bounds:
            all_boxes = list(element_bounds.values())
            min_x = min(b["x"] for b in all_boxes)
            min_y = min(b["y"] for b in all_boxes)
            max_x = max(b["x"] + b["w"] for b in all_boxes)
            max_y = max(b["y"] + b["h"] for b in all_boxes)
            crop_recommendation = f"{min_x}:{min_y}:{max_x - min_x}:{max_y - min_y}"

        scroll_needed = any(
            (e.get("action") == "scroll")
            or (e.get("action") == "evaluate"
                and "scrollTop" in str(e.get("expression", "")))
            for e in self.action_log
        )

        self._playbook_data = {
            "element_bounds": element_bounds,
            "clean_actions": clean_actions,
            "message_count": message_count,
            "content_start": content_start,
            "content_end": content_end,
            "crop_recommendation": crop_recommendation,
            "scroll_needed": scroll_needed,
        }

    def _finalize_playbook(self, duration):
        """Write the playbook using pre-collected data and the now-available HAR."""
        data = self._playbook_data
        network = self._analyze_har()

        playbook = {
            "url": self.url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "settings": {
                "viewport": f"{self.viewport['width']}x{self.viewport['height']}",
                "locale": self.locale,
                "chrome": self.use_chrome,
            },
            "discoveries": {
                "element_bounds": data["element_bounds"],
                "scroll_needed": data["scroll_needed"],
                "message_count": data["message_count"],
            },
            "action_plan": data["clean_actions"],
            "timing": {
                "content_start_s": round(data["content_start"], 1),
                "content_end_s": round(data["content_end"], 1),
                "total_duration_s": round(duration, 1),
            },
            "crop_recommendation": data["crop_recommendation"],
        }

        if network:
            playbook["network"] = network

        playbook_path = self.output_dir / "playbook.json"
        playbook_path.write_text(json.dumps(playbook, indent=2))

        if self.cache_name:
            cache_path = CACHE_DIR / self.cache_name
            cache_path.mkdir(parents=True, exist_ok=True)
            (cache_path / "playbook.json").write_text(json.dumps(playbook, indent=2))
            print(f"  Cached playbook: {cache_path / 'playbook.json'}",
                  file=sys.stderr)

        return str(playbook_path)

    def stop(self):
        if self.stopped:
            return None
        self.stopped = True
        duration = round(time.time() - self.start_time, 1)

        video_path = None
        if self.recording:
            try:
                video_path = self.page.video.path()
            except Exception:
                pass

        if not self.recording:
            try:
                self._generate_playbook(duration)
            except Exception as e:
                print(f"  Playbook pre-collection error: {e}", file=sys.stderr)

        self.context.close()
        self.browser.close()
        self.pw.stop()

        playbook_path = None
        if not self.recording and hasattr(self, '_playbook_data'):
            try:
                playbook_path = self._finalize_playbook(duration)
            except Exception as e:
                print(f"  Playbook finalization error: {e}", file=sys.stderr)

        video_offset = 0.0
        if video_path and Path(video_path).exists():
            video_offset = self._probe_video_offset(video_path, duration)

        manifest = {
            "video": str(video_path) if video_path else None,
            "duration": duration,
            "viewport": self.viewport,
            "snapshots": self.snap_counter,
            "actions": self.action_log,
        }
        if video_path:
            manifest["video_offset"] = round(video_offset, 2)
        if playbook_path:
            manifest["playbook"] = playbook_path
        manifest_path = self.output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        result = {
            "duration": duration,
            "snapshots": self.snap_counter,
            "manifest": str(manifest_path),
        }
        if video_path:
            result["video"] = str(video_path)
            result["video_offset"] = round(video_offset, 2)
        if playbook_path:
            result["playbook"] = playbook_path

        return result

    @staticmethod
    def _probe_video_offset(video_path, manifest_duration):
        """Return the seconds offset between video start and manifest time zero.

        Video recording starts when the Playwright context is created (before
        navigation), while manifest timestamps begin after the page loads.
        The offset = video_duration - manifest_duration.  To convert a manifest
        timestamp to a video timestamp: video_ts = manifest_ts + offset.
        """
        import subprocess
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", str(video_path)],
                capture_output=True, text=True, timeout=10)
            vid_dur = float(json.loads(r.stdout)["format"]["duration"])
            return vid_dur - manifest_duration
        except Exception as e:
            print(f"  ffprobe offset error: {e}", file=sys.stderr)
            return 0.0


class RecorderHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the recording server."""

    def __init__(self, browser_state, *args, **kwargs):
        self.state = browser_state
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        print(f"  [HTTP] {format % args}", file=sys.stderr)

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/status":
            self._send_json({
                "alive": True,
                "url": self.state.page.url if not self.state.stopped else None,
                "title": self.state.page.title() if not self.state.stopped else None,
                "mode": "recording" if self.state.recording else "practice",
                "running": not self.state.stopped,
                "elapsed": round(time.time() - self.state.start_time, 1),
            })

        elif path == "/snapshot":
            if self.state.stopped:
                self._send_json({"error": "Server is stopped"}, 410)
                return
            snapshot = self.state.take_snapshot()
            self._send_json(snapshot)

        elif path == "/responses":
            params = parse_qs(parsed.query)
            last_n = int(params.get("last", [20])[0])
            pattern = params.get("pattern", [""])[0]
            entries = self.state._response_log
            if pattern:
                entries = [e for e in entries if pattern in e["url"]]
            entries = entries[-last_n:]
            self._send_json({"count": len(entries), "responses": entries})

        else:
            self._send_json({"error": "Not found", "endpoints": [
                "/status", "/snapshot", "/responses", "/action", "/discover", "/stop"
            ]}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/action":
            if self.state.stopped:
                self._send_json({"error": "Server is stopped"}, 410)
                return
            action_data = self._read_body()
            result = self.state.execute_action(action_data)
            self._send_json(result)

        elif path == "/discover":
            if self.state.stopped:
                self._send_json({"error": "Server is stopped"}, 410)
                return
            body = self._read_body()
            selector = body.get("selector", "")
            if not selector:
                self._send_json({"error": "selector is required"}, 400)
                return
            result = self.state.discover_element(selector)
            self._send_json(result)

        elif path == "/stop":
            result = self.state.stop()
            self._send_json(result or {"error": "Already stopped"})
            threading.Thread(target=self._shutdown_server, daemon=True).start()

        else:
            self._send_json({"error": "Not found"}, 404)

    def _shutdown_server(self):
        time.sleep(0.5)
        self.server.shutdown()


def _clean_environment(port):
    """Free the port for a clean start. NEVER kills the user's personal browser."""
    import subprocess as _sp
    print("Cleaning environment...", file=sys.stderr)
    try:
        r = _sp.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        for pid in r.stdout.strip().split("\n"):
            if pid.strip():
                _sp.run(["kill", "-9", pid.strip()], capture_output=True)
                print(f"  Killed PID {pid.strip()} on port {port}", file=sys.stderr)
    except Exception:
        pass
    import time as _t
    _t.sleep(0.5)
    print("  Environment clean.", file=sys.stderr)


def parse_viewport(s):
    parts = s.lower().split("x")
    if len(parts) != 2:
        print(f"Error: Invalid viewport '{s}'. Use WxH (e.g. 1920x1080)", file=sys.stderr)
        sys.exit(1)
    return {"width": int(parts[0]), "height": int(parts[1])}


def main():
    parser = argparse.ArgumentParser(description="Interactive browser recording server")
    parser.add_argument("url", help="URL to navigate to")
    parser.add_argument("--output", "-o", default="/tmp/browser_recording/",
                        help="Output directory for video and snapshots")
    parser.add_argument("--viewport", "-v", default="1920x1080",
                        help="Viewport size WxH (default: 1920x1080)")
    parser.add_argument("--port", "-p", type=int, default=9222,
                        help="HTTP server port (default: 9222)")
    parser.add_argument("--device", "-d", help="Device preset")
    parser.add_argument("--dark-mode", action="store_true", help="Emulate dark color scheme")
    parser.add_argument("--hide-scrollbar", action="store_true", help="Hide scrollbars")
    parser.add_argument("--no-cursor", action="store_true", help="Disable cursor indicator")
    parser.add_argument("--wait", "-w", type=float, default=0,
                        help="Wait N seconds after page load")
    parser.add_argument("--wait-until", default="load",
                        choices=["load", "domcontentloaded", "networkidle", "commit"],
                        help="Navigation wait strategy")
    parser.add_argument("--locale", "-l", metavar="LOCALE",
                        help="Browser locale/language (e.g. 'es-ES', 'pt-BR', 'en-US')")
    parser.add_argument("--chrome", action="store_true",
                        help="Use system Chrome instead of bundled Chromium (enables H.264 video)")
    parser.add_argument("--no-record", "--practice", action="store_true",
                        help="Practice mode: no video recording, captures HAR, produces playbook")
    parser.add_argument("--cache-name", metavar="NAME",
                        help="Cache playbook under this name for reuse (in the skill's cache/ dir)")
    parser.add_argument("--clean", action="store_true",
                        help="Kill leftover browsers, free the port, and ensure a fresh session (no cookies/storage)")

    args = parser.parse_args()

    if args.clean:
        _clean_environment(args.port)

    viewport = parse_viewport(args.viewport)

    pw_temp = sync_playwright().start()
    pw_devices = pw_temp.devices
    pw_temp.stop()

    mode = "PRACTICE" if args.no_record else "RECORDING"
    print(f"Starting browser server ({mode} mode)...", file=sys.stderr)
    print(f"  URL: {args.url}", file=sys.stderr)
    print(f"  Viewport: {viewport['width']}x{viewport['height']}", file=sys.stderr)
    print(f"  Output: {args.output}", file=sys.stderr)
    print(f"  Port: {args.port}", file=sys.stderr)
    if args.locale:
        print(f"  Locale: {args.locale}", file=sys.stderr)
    if args.cache_name:
        print(f"  Cache: {args.cache_name}", file=sys.stderr)

    state = BrowserState(
        url=args.url,
        output_dir=args.output,
        viewport=viewport,
        device=args.device,
        dark_mode=args.dark_mode,
        hide_scrollbar=args.hide_scrollbar,
        show_cursor=not args.no_cursor,
        wait_seconds=args.wait,
        wait_until=args.wait_until,
        locale=args.locale,
        use_chrome=args.chrome,
        playwright_devices=pw_devices,
        no_record=args.no_record,
        cache_name=args.cache_name,
        clean=args.clean,
    )

    handler = partial(RecorderHandler, state)
    server = HTTPServer(("0.0.0.0", args.port), handler)
    server.timeout = 1

    print(f"\nREADY http://localhost:{args.port}", file=sys.stderr)
    print(f"READY http://localhost:{args.port}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...", file=sys.stderr)
        if not state.stopped:
            result = state.stop()
            if result:
                print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
