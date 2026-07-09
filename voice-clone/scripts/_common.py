#!/usr/bin/env python3
"""Shared utilities for the voice-clone skill.

Wraps MiniMax voice-cloning on Replicate (minimax/voice-cloning). Token
discovery is shared with the other Replicate-based skills: it checks the
REPLICATE_API_TOKEN env var, this skill's config.json, then the configs of the
sibling skills (avatar-video-reel, gpt-image-2, bg-music, ...).
"""

import contextlib
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SKILL_DIR / "config.json"

# Sibling skills that may hold the shared Replicate token.
FALLBACK_CONFIGS = [
    Path.home() / ".cursor/skills/avatar-video-reel/config.json",
    Path.home() / ".cursor/skills/gpt-image-2/config.json",
    Path.home() / ".cursor/skills/brand-asset-studio/config.json",
    Path.home() / ".cursor/skills/bg-music-hq/config.json",
    Path.home() / ".cursor/skills/bg-music/config.json",
    Path.home() / ".cursor/skills/sound-effects/config.json",
    Path.home() / ".cursor/skills/video-compose/config.json",
]


def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def get_replicate_token():
    """Resolve the Replicate API token: env -> local config -> sibling skills."""
    token = os.environ.get("REPLICATE_API_TOKEN")
    if token:
        return token

    token = load_config().get("replicate_api_token", "")
    if token:
        return token

    for path in FALLBACK_CONFIGS:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                t = cfg.get("replicate_api_token", "")
                if t:
                    return t
            except (json.JSONDecodeError, OSError):
                continue

    print("Error: No Replicate API token found.", file=sys.stderr)
    print(f"  Run: python3 {SCRIPT_DIR}/setup_key.py YOUR_REPLICATE_API_TOKEN", file=sys.stderr)
    print("  Get a token at: https://replicate.com/account/api-tokens", file=sys.stderr)
    sys.exit(1)


def _require_replicate():
    try:
        import replicate  # noqa: F401
    except ImportError:
        print("Error: the 'replicate' package is required. Run:", file=sys.stderr)
        print(f"  pip3 install -r {SCRIPT_DIR.parent}/requirements.txt", file=sys.stderr)
        sys.exit(1)
    return __import__("replicate")


def _post_multipart(url, *, fields=None, file_field=None, file_path=None, timeout=180):
    """Minimal stdlib multipart/form-data POST. Returns the response body text."""
    import mimetypes
    import uuid

    boundary = "----voiceclone" + uuid.uuid4().hex
    parts = []
    for key, value in (fields or {}).items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    if file_field and file_path:
        fname = Path(file_path).name
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            data = f.read()
        parts.append(
            (
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{file_field}"; filename="{fname}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def upload_to_public_host(path):
    """Upload a local file to a public host and return a fetchable URL.

    Fallback for when no local tunnel (cloudflared/ngrok) is available. The file
    leaves the machine. Primary: tmpfiles.org (auto-expires ~1h). Fallback:
    catbox.moe (permanent).
    """
    path = Path(path)
    last = None
    try:
        resp = _post_multipart(
            "https://tmpfiles.org/api/v1/upload", file_field="file", file_path=str(path)
        )
        page_url = json.loads(resp)["data"]["url"]
        return page_url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
    except Exception as e:  # noqa: BLE001
        last = e

    try:
        resp = _post_multipart(
            "https://catbox.moe/user/api.php",
            fields={"reqtype": "fileupload"},
            file_field="fileToUpload",
            file_path=str(path),
        ).strip()
        if resp.startswith("http"):
            return resp
        raise RuntimeError(f"unexpected catbox response: {resp[:200]}")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Public upload failed (tmpfiles.org: {last}; catbox.moe: {e})"
        )


# --------------------------------------------------------------------------
# Local tunnel: serve the file from this machine, exposed via a public URL
# (preferred — the file never leaves your machine, only a transient URL does).
# --------------------------------------------------------------------------
class NoTunnel(Exception):
    """Raised when no local tunnel tool (cloudflared/ngrok) is available."""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence request logging
        pass


class _QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):  # ignore client disconnects
        pass


def _serve_dir(directory):
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = _QuietServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _start_cloudflared(port):
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m:
            url = m.group(0)
            break
    if not url:
        with contextlib.suppress(Exception):
            proc.terminate()
        raise RuntimeError("cloudflared did not expose a tunnel URL")
    # Keep draining stdout so the pipe never blocks the process.
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
    return url, proc


def _start_ngrok(port):
    # Parse ngrok's own JSON stdout (not the global :4040 API) so a stale agent
    # can't hand back another session's URL.
    proc = subprocess.Popen(
        ["ngrok", "http", str(port), "--log", "stdout", "--log-format", "json"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        try:
            obj = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        u = obj.get("url", "")
        if isinstance(u, str) and u.startswith("https") and "ngrok" in u:
            url = u
            break
        blob = (str(obj.get("msg", "")) + str(obj.get("err", ""))).lower()
        if obj.get("lvl") in {"error", "eror", "crit"} and "session" in blob:
            with contextlib.suppress(Exception):
                proc.terminate()
            raise RuntimeError(
                "ngrok session limit hit (another ngrok agent is running). "
                "Stop it, or rely on cloudflared."
            )
    if not url:
        with contextlib.suppress(Exception):
            proc.terminate()
        raise RuntimeError(
            "ngrok did not expose a tunnel (configure it once with "
            "`ngrok config add-authtoken <token>`)."
        )
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
    return url, proc


def _public_dns_ip(host):
    """Resolve ``host`` via public resolvers, bypassing the system resolver.

    Some networks block tunnel domains (e.g. *.trycloudflare.com) at the local
    resolver while the record is perfectly valid in public DNS — which is what
    the remote model (MiniMax) actually uses.
    """
    for resolver in ("1.1.1.1", "8.8.8.8"):
        try:
            out = subprocess.run(
                ["dig", "+short", f"@{resolver}", host, "A"],
                capture_output=True, text=True, timeout=8,
            ).stdout.split()
            ips = [x for x in out if x and x[0].isdigit()]
            if ips:
                return ips[0]
        except Exception:  # noqa: BLE001
            pass
    return None


def _verify_url(url, *, attempts=25, delay=3):
    # Quick tunnels can take 20-40s before they answer. Verify external
    # reachability the way the remote model will see it.
    host = urllib.parse.urlsplit(url).hostname
    last = None
    for _ in range(attempts):
        # Path 1: system resolver (works for ngrok-free.app on most networks).
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return True
        except Exception as e:  # noqa: BLE001
            last = e
        # Path 2: bypass a blocked local resolver — resolve via public DNS and
        # fetch with that IP + correct SNI. This mirrors what MiniMax can reach.
        ip = _public_dns_ip(host)
        if ip:
            try:
                c = subprocess.run(
                    ["curl", "-sS", "-o", os.devnull, "-w", "%{http_code}", "-m", "12",
                     "--resolve", f"{host}:443:{ip}", url],
                    capture_output=True, text=True, timeout=20,
                )
                if c.stdout.strip() == "200":
                    return True
                last = RuntimeError(f"curl http={c.stdout.strip()} {c.stderr.strip()}")
            except Exception as e:  # noqa: BLE001
                last = e
        time.sleep(delay)
    raise RuntimeError(f"public URL not reachable: {url} ({last})")


@contextlib.contextmanager
def serve_public(path):
    """Context manager: serve ``path`` over a public tunnel; yields the URL.

    Tries cloudflared (no account, no interstitial) then ngrok. The local HTTP
    server and tunnel stay up for the duration of the ``with`` block (the model
    fetches the file during that window) and are torn down on exit.
    Raises NoTunnel if neither tool is installed.
    """
    path = Path(path)
    tmp = Path(tempfile.mkdtemp(prefix="voiceclone_"))
    shutil.copy(path, tmp / path.name)
    httpd = _serve_dir(tmp)
    port = httpd.server_address[1]
    proc = None
    try:
        if shutil.which("cloudflared"):
            base, proc = _start_cloudflared(port)
        elif shutil.which("ngrok"):
            base, proc = _start_ngrok(port)
        else:
            raise NoTunnel("no tunnel tool found (install cloudflared or ngrok)")
        url = base.rstrip("/") + "/" + urllib.parse.quote(path.name)
        _verify_url(url)
        yield url
    finally:
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.terminate()
        with contextlib.suppress(Exception):
            httpd.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


def run_replicate(model, inputs, *, token=None):
    """Run a Replicate model and return the raw output."""
    replicate = _require_replicate()

    if token:
        os.environ["REPLICATE_API_TOKEN"] = token
    elif "REPLICATE_API_TOKEN" not in os.environ:
        os.environ["REPLICATE_API_TOKEN"] = get_replicate_token()

    print(f"  Running Replicate model: {model} ...", file=sys.stderr)
    return replicate.run(model, input=inputs)


def to_url(value):
    """Pull a URL string out of a Replicate FileOutput-like object or string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    u = getattr(value, "url", None)
    if isinstance(u, str):
        return u
    if callable(u):
        try:
            return u()
        except Exception:
            return None
    return None


def download_file(url, output_path):
    """Download a URL to a local path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(str(url), str(output_path))
    return str(output_path)
