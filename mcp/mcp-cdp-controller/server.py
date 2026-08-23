#!/usr/bin/env python3
"""mcp-cdp-controller — FastMCP wrapper for the tony-dell CDP HTTP controller.

Runs over stdio for Windsurf/Cascade and forwards each tool call to the
existing Node CDP controller running on tony-dell:9224.
"""
import json
import os
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote, urlencode

from mcp.server.fastmcp import FastMCP
import mcp.types as mcp_types

mcp = FastMCP("mcp-cdp-controller")

CDP_URL = os.environ.get("CDP_CONTROLLER_URL", "http://localhost:3002")


def _call(path: str, params: dict[str, str] | None = None) -> str:
    """Make a GET request to the CDP controller and return a JSON string."""
    url = CDP_URL.rstrip("/") + path
    if params:
        # quote (not quote_plus) so spaces stay %20; the controller decodes with unquote
        query = urlencode(params, quote_via=quote)
        url = f"{url}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return json.dumps({"ok": False, "error": f"HTTP {exc.code}", "body": body})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    try:
        return json.dumps(json.loads(data))
    except json.JSONDecodeError:
        return json.dumps({"ok": True, "text": data})


@mcp.tool()
def cdp_state() -> str:
    """Return the current tab URL and title from the CDP controller."""
    return _call("/state")


@mcp.tool()
def cdp_navigate(url: str) -> str:
    """Navigate the current tab to the given URL."""
    return _call("/navigate", {"url": url})


@mcp.tool()
def cdp_click(selector: str) -> str:
    """Click the first element matching the CSS selector."""
    return _call("/click", {"selector": selector})


@mcp.tool()
def cdp_fill(selector: str, value: str) -> str:
    """Fill an input identified by the CSS selector."""
    return _call("/fill", {"selector": selector, "value": value})


@mcp.tool()
def cdp_select(selector: str, value: str) -> str:
    """Select an option in a dropdown identified by the CSS selector."""
    return _call("/select", {"selector": selector, "value": value})


@mcp.tool()
def cdp_eval(script: str) -> str:
    """Run a JavaScript snippet in the current page."""
    return _call("/eval", {"script": script})


@mcp.tool()
def cdp_screenshot(path: str | None = None) -> str:
    """Take a screenshot and save it to the given path on tony-dell."""
    if not path:
        path = f"/tmp/cdp-screenshot-{uuid.uuid4().hex[:8]}.png"
    return _call("/screenshot", {"path": path})




@mcp.tool()
def cdp_raise() -> str:
    """Raise the Chrome window to the foreground."""
    return _call("/raise")


@mcp.tool()
def cdp_capture_screen(path: str | None = None, mode: str = "window"):
    """Capture the full screen or the active Chrome window and return it as an image."""
    if path is None:
        path = f"/tmp/cdp-screen-{uuid.uuid4().hex[:8]}.png"
    res = _call("/capture", {"path": path, "mode": mode})
    data = json.loads(res)
    if not data.get("ok") or "data" not in data:
        return [mcp_types.TextContent(type="text", text=res)]
    return [
        mcp_types.TextContent(type="text", text=f"Captured {data.get("mode", mode)} screenshot to {data["path"]}"),
        mcp_types.ImageContent(type="image", data=data["data"], mimeType="image/png"),
    ]

if __name__ == "__main__":
    mcp.run(transport="stdio")
