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

import yaml
from mcp.server.fastmcp import FastMCP
import mcp.types as mcp_types

mcp = FastMCP("mcp-playlive")

DAEMON_URL = os.environ.get("PLAYLIVE_URL", "http://192.168.1.42:9230")

_PLAYLIVE_HOSTS_RAW = os.environ.get("PLAYLIVE_HOSTS", "{}")
try:
    PLAYLIVE_HOSTS = json.loads(_PLAYLIVE_HOSTS_RAW)
except json.JSONDecodeError:
    PLAYLIVE_HOSTS = {}

_DEFAULT_HOSTS_FILE = "/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/playlive-hosts.yml"
_DEFAULT_CDP_PORT = 9223


def _load_hosts_from_yaml() -> dict:
    """Reload the YAML host registry into a {name: cdp_url} dict."""
    hosts_file = os.environ.get("PLAYLIVE_HOSTS_FILE", _DEFAULT_HOSTS_FILE)
    try:
        with open(hosts_file) as f:
            data = yaml.safe_load(f)
        return {
            name: info["cdp"]
            for name, info in data.get("hosts", {}).items()
            if info.get("cdp")
        }
    except Exception as exc:
        return {"_error": str(exc)}


def _resolve_remote_url(host: str | None, remote_url: str | None) -> str | None:
    """Resolve a host alias or bare hostname into a CDP remote_url.

    Explicit remote_url always wins. A host value that is already a full
    URL is used as-is. Bare hostnames are mapped to http://<host>:<port>.
    """
    if remote_url:
        return remote_url
    if not host:
        return None
    if host in PLAYLIVE_HOSTS:
        return PLAYLIVE_HOSTS[host]
    if host.startswith("http://") or host.startswith("https://"):
        return host
    return f"http://{host}:{_DEFAULT_CDP_PORT}"


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
def playlive_create_chrome_live(target: str = "remote", host: str | None = None, remote_url: str | None = None, reuse_context: bool = False, attach_url: str | None = None) -> str:
    """Create a CDP-attached live Chrome session. Use `host` (a PLAYLIVE_HOSTS alias, bare hostname, or full URL) or `remote_url` for a different CDP endpoint per session."""
    body = {"type": "chrome-live", "target": target}
    resolved = _resolve_remote_url(host, remote_url)
    if resolved:
        body["remote_url"] = resolved
    if reuse_context:
        body["reuse_context"] = True
    if attach_url:
        body["attach_url"] = attach_url
    return json.dumps(_request("POST", "/sessions", body), indent=2)


@mcp.tool()
def playlive_create_playwright_chrome(target: str = "remote", host: str | None = None, remote_url: str | None = None, reuse_context: bool = False, attach_url: str | None = None) -> str:
    """Create a Playwright session attached to an existing Chrome over CDP. Use `host` (a PLAYLIVE_HOSTS alias, bare hostname, or full URL) or `remote_url` for a different CDP endpoint per session."""
    body = {"type": "playwright-chrome", "target": target}
    resolved = _resolve_remote_url(host, remote_url)
    if resolved:
        body["remote_url"] = resolved
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
def playlive_status() -> str:
    """Return the playlived daemon health and active session count."""
    return json.dumps(_request("GET", "/health"), indent=2)


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
def playlive_reload_hosts() -> str:
    """Reload the playlive host registry from the YAML file without restarting the server."""
    global PLAYLIVE_HOSTS
    try:
        PLAYLIVE_HOSTS = _load_hosts_from_yaml()
        return json.dumps({"ok": True, "hosts": PLAYLIVE_HOSTS}, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, indent=2)


def _cdp_version(remote_url: str) -> dict:
    """Probe a Chrome CDP endpoint and return its /json/version data."""
    url = remote_url.rstrip("/") + "/json/version"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "cdp_url": remote_url, **json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "cdp_url": remote_url, "http_code": exc.code, "error": exc.read().decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"ok": False, "cdp_url": remote_url, "error": str(exc)}


@mcp.tool()
def playlive_verify_host(host: str | None = None, remote_url: str | None = None) -> str:
    """Verify that a Chrome CDP endpoint is reachable.

    Resolves `host` against PLAYLIVE_HOSTS (or uses an explicit `remote_url`) and
    hits the CDP /json/version endpoint.
    """
    resolved = _resolve_remote_url(host, remote_url)
    if not resolved:
        return json.dumps({"ok": False, "error": "No host or remote_url provided"}, indent=2)
    return json.dumps(_cdp_version(resolved), indent=2)


@mcp.tool()
def playlive_discover_hosts() -> str:
    """Probe every host in PLAYLIVE_HOSTS and report which CDP endpoints are reachable."""
    results = {name: _cdp_version(cdp) for name, cdp in PLAYLIVE_HOSTS.items()}
    all_ok = all(v.get("ok") for v in results.values())
    return json.dumps({"ok": all_ok, "hosts": results}, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
