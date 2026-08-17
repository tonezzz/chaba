"""MCP Debug visual capture tools.

These functions back the mcp-debug capture bridge. They use the host's native
tools (screencapture, osascript, pbpaste) and return base64-encoded data so no
raw pixels are leaked to the local filesystem if stdout capture is used.
"""
import base64
import json
import logging
import platform
import re
import shlex
import sys
from pathlib import Path

import yaml

from .config import HOSTS
from .hosts import run_on_host

logger = logging.getLogger(__name__)

CAPTURE_SSOT = Path(__file__).resolve().parents[2] / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.capture.yml"


def _load_capture_config():
    try:
        with open(CAPTURE_SSOT) as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("failed to load capture SSOT: %s", exc)
        return {}


CAPTURE = _load_capture_config()
LIMITS = CAPTURE.get("limits", {})
ALLOWLIST = CAPTURE.get("host_allowlist", {})

SOFT_CAP = LIMITS.get("max_image_bytes_soft", 2097152)
HARD_CAP = LIMITS.get("max_image_bytes_hard", 4194304)


def _allowed(host, key):
    if host not in HOSTS:
        return False
    entry = ALLOWLIST.get(host, {})
    return bool(entry.get(key, False))


def _detect_platform(host):
    if host == "macbook" or host.endswith("mac"):
        return "macos"
    result = run_on_host(host, "uname -s", compact=False, shell=True)
    if not result.get("ok"):
        logger.error("platform detection failed for %s: %s", host, result.get("err"))
        return "unknown"
    out = (result.get("out") or "").strip().lower()
    if out == "darwin":
        return "macos"
    if out == "linux":
        return "linux"
    return "unknown"


def _base64_to_bytes(b64text):
    try:
        return base64.b64decode(b64text, validate=True)
    except Exception:
        return None


def _build_screenshot_cmd(platform, region=None):
    if platform != "macos":
        return None
    if region:
        x = int(region.get("x", 0))
        y = int(region.get("y", 0))
        w = int(region.get("width", 0))
        h = int(region.get("height", 0))
        if w <= 0 or h <= 0:
            return None
        return f"screencapture -R{x},{y},{w},{h} -x - | base64"
    return "screencapture -x - | base64"


def mcp_screenshot(host, region=None, fmt="png"):
    if not _allowed(host, "capture"):
        return {"ok": False, "error": f"capture not enabled for host: {host}"}
    if fmt != "png":
        return {"ok": False, "error": "only png is supported in the first pass"}
    plat = _detect_platform(host)
    if plat == "unknown":
        return {"ok": False, "error": f"could not detect platform for {host}"}
    if plat != "macos":
        return {"ok": False, "error": f"screenshot not yet implemented for {plat}"}
    cmd = _build_screenshot_cmd(plat, region)
    if not cmd:
        return {"ok": False, "error": "invalid region or platform"}
    result = run_on_host(host, cmd, compact=False, shell=True)
    if not result.get("ok"):
        return {"ok": False, "host": host, "error": result.get("err") or "screenshot failed", "rc": result.get("rc")}
    b64 = (result.get("out") or "").strip()
    if not b64:
        return {"ok": False, "error": "no image data returned"}
    raw = _base64_to_bytes(b64)
    if raw is None:
        return {"ok": False, "error": "screenshot returned invalid base64"}
    if len(raw) > HARD_CAP:
        return {"ok": False, "error": f"image exceeds hard cap ({len(raw)} > {HARD_CAP} bytes)"}
    # Basic metadata: sips can read dimensions from stdin with the png - syntax.
    width, height = 0, 0
    try:
        dim = run_on_host(
            host,
            f"python3 - <<'PY'\nimport sys, struct\ndata=sys.stdin.buffer.read()\nif data[:8]==b'\\x89PNG\\r\\n\\x1a\\n':\n    w,h=struct.unpack('>II', data[16:24])\n    print(w, h)\nPY",
            compact=False,
            shell=True,
        )
        if dim.get("ok"):
            parts = (dim.get("out") or "").strip().split()
            if len(parts) == 2:
                width, height = int(parts[0]), int(parts[1])
    except Exception:
        pass
    return {
        "ok": True,
        "host": host,
        "format": "png",
        "content_base64": b64,
        "bytes": len(raw),
        "width": width,
        "height": height,
        "soft_cap_exceeded": len(raw) > SOFT_CAP,
    }


def mcp_window_list(host):
    if not _allowed(host, "capture"):
        return {"ok": False, "error": f"capture not enabled for host: {host}"}
    plat = _detect_platform(host)
    if plat != "macos":
        return {"ok": False, "error": f"window list not yet implemented for {plat}"}
    # List visible, non-background apps and their frontmost status.
    cmd = """osascript -e 'tell application "System Events" to get {name, frontmost} of (every process whose visible is true)'"""
    result = run_on_host(host, cmd, compact=False, shell=True)
    if not result.get("ok"):
        return {"ok": False, "host": host, "error": result.get("err") or "window list failed", "rc": result.get("rc")}
    out = (result.get("out") or "").strip()
    windows = []
    # Parse AppleScript list: {name1, name2, ...}, {frontmost1, frontmost2, ...}
    try:
        match = re.search(r"\\{(.+?)\\},\\s*\\{(.+?)\\}", out)
        if match:
            names = [s.strip().strip('"') for s in match.group(1).split(",")]
            fronts = [s.strip() == "true" for s in match.group(2).split(",")]
            for i, name in enumerate(names):
                windows.append({
                    "id": i,
                    "app": name,
                    "title": name,
                    "pid": None,
                    "focused": fronts[i] if i < len(fronts) else False,
                    "bounds": None,
                })
    except Exception as exc:
        logger.error("failed to parse window list: %s", exc)
    return {"ok": True, "host": host, "windows": windows, "count": len(windows)}


def mcp_clipboard_image_get(host):
    if not _allowed(host, "clipboard_image"):
        return {"ok": False, "error": f"clipboard image not enabled for host: {host}"}
    plat = _detect_platform(host)
    if plat != "macos":
        return {"ok": False, "error": f"clipboard image not yet implemented for {plat}"}
    # Use a fifo-ish approach: osascript writes PNG bytes to a temp file, then
    # we base64 it and delete. This is the most reliable way to get binary data
    # from the macOS pasteboard through AppleScript.
    cmd = """osascript -e '
set tempPath to "/tmp/mcp_clipboard_image_get_" & (do shell script "uuidgen")
set pngData to the clipboard as «class PNGf»
set outFile to open for access file tempPath with write permission
write pngData to outFile
close access outFile
do shell script "base64 " & quoted form of tempPath & "; rm -f " & quoted form of tempPath'
"""
    result = run_on_host(host, cmd, compact=False, shell=True)
    if not result.get("ok"):
        # Clean up on failure if file remains
        run_on_host(host, "rm -f /tmp/mcp_clipboard_image_get_*", compact=False, shell=True)
        return {"ok": False, "host": host, "error": result.get("err") or "clipboard image failed", "rc": result.get("rc")}
    b64 = (result.get("out") or "").strip()
    if not b64:
        return {"ok": False, "error": "no image data in clipboard"}
    raw = _base64_to_bytes(b64)
    if raw is None:
        return {"ok": False, "error": "clipboard returned invalid base64"}
    if len(raw) > HARD_CAP:
        return {"ok": False, "error": f"image exceeds hard cap ({len(raw)} > {HARD_CAP} bytes)"}
    return {"ok": True, "host": host, "format": "png", "content_base64": b64, "bytes": len(raw), "soft_cap_exceeded": len(raw) > SOFT_CAP}
