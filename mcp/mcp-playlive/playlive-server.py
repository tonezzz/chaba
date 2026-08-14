#!/usr/bin/env python3
"""mcp-playlive — FastMCP client for the playlived HTTP daemon.

A single MCP server that can create chrome-live, playwright-chrome, and
playwright-headless sessions, local or remote.  Session state lives in the
long-running playlived daemon, so many AI clients can use it at once.
"""
import json
import os
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP
import mcp.types as mcp_types

mcp = FastMCP("mcp-playlive")

DAEMON_URL = os.environ.get("PLAYLIVE_URL", "http://tony-dell:9230")


def _request(method, path, payload=None):
    url = DAEMON_URL.rstrip("/") + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
        except json.JSONDecodeError:
            err = {"error": body}
        return {"ok": False, "http_code": exc.code, **err}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def playlive_create_chrome_live(target: str = "remote", remote_url: str | None = None, reuse_context: bool = False, attach_url: str | None = None) -> str:
    """Create a CDP-attached live Chrome session."""
    body = {"type": "chrome-live", "target": target}
    if remote_url:
        body["remote_url"] = remote_url
    if reuse_context:
        body["reuse_context"] = True
    if attach_url:
        body["attach_url"] = attach_url
    return json.dumps(_request("POST", "/sessions", body), indent=2)


@mcp.tool()
def playlive_create_playwright_chrome(target: str = "remote", remote_url: str | None = None, reuse_context: bool = False, attach_url: str | None = None) -> str:
    """Create a Playwright session attached to an existing Chrome over CDP."""
    body = {"type": "playwright-chrome", "target": target}
    if remote_url:
        body["remote_url"] = remote_url
    if reuse_context:
        body["reuse_context"] = True
    if attach_url:
        body["attach_url"] = attach_url
    return json.dumps(_request("POST", "/sessions", body), indent=2)


@mcp.tool()
def playlive_create_playwright(target: str = "local", remote_url: str | None = None) -> str:
    """Create a Playwright headless browser session (local only)."""
    if target != "local":
        return json.dumps({"ok": False, "error": "playwright-headless must be local"})
    body = {"type": "playwright-headless", "target": "local"}
    if remote_url:
        body["remote_url"] = remote_url
    return json.dumps(_request("POST", "/sessions", body), indent=2)


@mcp.tool()
def playlive_list_sessions() -> str:
    """List active sessions managed by the daemon."""
    return json.dumps(_request("GET", "/sessions"), indent=2)


@mcp.tool()
def playlive_close_session(session_id: str) -> str:
    """Close a session and free its browser resources."""
    return json.dumps(_request("DELETE", f"/sessions/{session_id}"), indent=2)


@mcp.tool()
def playlive_navigate(session_id: str, url: str) -> str:
    """Navigate a session's current page to a URL."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/navigate", {"url": url}), indent=2)


@mcp.tool()
def playlive_click(session_id: str, selector: str) -> str:
    """Click the element matched by the CSS selector."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/click", {"selector": selector}), indent=2)


@mcp.tool()
def playlive_fill(session_id: str, selector: str, value: str) -> str:
    """Fill an input identified by the CSS selector."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/fill", {"selector": selector, "value": value}), indent=2)


@mcp.tool()
def playlive_select(session_id: str, selector: str, value: str) -> str:
    """Select an option in a dropdown identified by the CSS selector."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/select", {"selector": selector, "value": value}), indent=2)


@mcp.tool()
def playlive_eval(session_id: str, script: str) -> str:
    """Run a JavaScript snippet in the current page and return the result."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/eval", {"script": script}), indent=2)


@mcp.tool()
def playlive_state(session_id: str) -> str:
    """Return the current session page URL and title."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/state", {}), indent=2)


@mcp.tool()
def playlive_screenshot(session_id: str, path: str | None = None, full_page: bool = False) -> str:
    """Take a screenshot of the current page.  Returns base64 unless a path is given."""
    payload = {"fullPage": full_page}
    if path:
        payload["path"] = path
    return json.dumps(_request("POST", f"/sessions/{session_id}/screenshot", payload), indent=2)


@mcp.tool()
def playlive_screenshot_image(session_id: str, full_page: bool = False) -> list:
    """Take a screenshot and return it as an image plus a text note."""
    payload = {"fullPage": full_page}
    res = _request("POST", f"/sessions/{session_id}/screenshot", payload)
    if not res.get("ok") or "base64" not in res:
        return [mcp_types.TextContent(type="text", text=json.dumps(res, indent=2))]
    return [
        mcp_types.TextContent(type="text", text=f"Screenshot of {res.get('url', 'page')}"),
        mcp_types.ImageContent(type="image", data=res["base64"], mimeType="image/png"),
    ]


@mcp.tool()
def playlive_upload_file(session_id: str, selector: str, file_base64: str, filename: str, mime_type: str = "application/octet-stream") -> str:
    """Upload a base64-encoded file to a <input type=file> matched by the CSS selector."""
    return json.dumps(_request(
        "POST",
        f"/sessions/{session_id}/upload",
        {"selector": selector, "base64": file_base64, "filename": filename, "mimeType": mime_type},
    ), indent=2)


@mcp.tool()
def playlive_upload_from_stash(session_id: str, selector: str, stash_id: str) -> str:
    """Upload a previously stashed file by its stash_id to a <input type=file> matched by the CSS selector."""
    return json.dumps(_request(
        "POST",
        f"/sessions/{session_id}/upload",
        {"selector": selector, "stash_id": stash_id},
    ), indent=2)


@mcp.tool()
def playlive_drop_files(session_id: str, selector: str, file_base64: str, filename: str, mime_type: str = "application/octet-stream") -> str:
    """Dispatch synthetic drag-and-drop events with a file onto a drop-zone element matched by the CSS selector."""
    return json.dumps(_request(
        "POST",
        f"/sessions/{session_id}/drop",
        {"selector": selector, "base64": file_base64, "filename": filename, "mimeType": mime_type},
    ), indent=2)


@mcp.tool()
def playlive_drop_from_stash(session_id: str, selector: str, stash_id: str) -> str:
    """Dispatch synthetic drag-and-drop events with a previously stashed file onto a drop-zone element."""
    return json.dumps(_request(
        "POST",
        f"/sessions/{session_id}/drop",
        {"selector": selector, "stash_id": stash_id},
    ), indent=2)


@mcp.tool()
def playlive_stash_file(file_base64: str, filename: str, mime_type: str = "application/octet-stream") -> str:
    """Stash a base64-encoded file on the daemon for later upload. Returns a stash_id."""
    return json.dumps(_request(
        "POST",
        "/stash",
        {"base64": file_base64, "filename": filename, "mimeType": mime_type},
    ), indent=2)


@mcp.tool()
def playlive_get_stash(stash_id: str) -> str:
    """Retrieve a stashed file by its stash_id."""
    return json.dumps(_request("GET", f"/stash/{stash_id}"), indent=2)


@mcp.tool()
def playlive_delete_stash(stash_id: str) -> str:
    """Delete a stashed file by its stash_id."""
    return json.dumps(_request("DELETE", f"/stash/{stash_id}"), indent=2)


@mcp.tool()
def playlive_set_clipboard(session_id: str, text: str) -> str:
    """Write text to the browser's page clipboard via navigator.clipboard."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/set_clipboard", {"text": text}), indent=2)


@mcp.tool()
def playlive_get_clipboard(session_id: str) -> str:
    """Read text from the browser's page clipboard via navigator.clipboard."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/get_clipboard", {}), indent=2)


@mcp.tool()
def playlive_set_auth(session_id: str, username: str, password: str) -> str:
    """Set basic authentication credentials for the session. These credentials will be used for all subsequent navigate requests."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/set_auth", {"username": username, "password": password}), indent=2)


@mcp.tool()
def playlive_clear_auth(session_id: str) -> str:
    """Clear basic authentication credentials from the session."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/clear_auth", {}), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
