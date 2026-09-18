#!/usr/bin/env python3
"""Verify all configured MCP servers by attempting a tools/list call."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = Path(os.environ.get("MCP_CONFIG", Path.home() / ".config" / "devin" / "mcp_config.json"))
TIMEOUT = 20


def _extract_sse_json(text):
    """Parse a streamable-HTTP (SSE) response body into a JSON-RPC message."""
    data_lines = [l[5:].strip() for l in text.splitlines() if l.startswith("data:")]
    if not data_lines:
        return None
    try:
        return json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None


def _already_running(name):
    pattern = name.replace("-", "_")
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0


def stdio_verify(name, cmd, args, env):
    env = {**os.environ, **(env or {})}
    proc = subprocess.Popen(
        [cmd, *args],
        cwd=REPO,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    results = {}

    def reader():
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            req_id = msg.get("id")
            if req_id in (1, 2):
                results[req_id] = msg

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    def send(req_id, method, params=None):
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            msg["params"] = params
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    send(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-mcp", "version": "0.1"}})
    deadline = time.time() + 10
    while 1 not in results and time.time() < deadline:
        time.sleep(0.1)
    if 1 not in results:
        proc.terminate()
        # Some launchers (e.g. mcp-debug.sh) exit 0 silently when reusing an
        # already-running server — that IS the healthy state for this check.
        if proc.wait(timeout=5) == 0 and _already_running(name):
            return {"ok": True, "status": "already running"}
        return {"ok": False, "error": "no initialize response"}

    send(2, "tools/list")
    deadline = time.time() + TIMEOUT
    while 2 not in results and time.time() < deadline:
        time.sleep(0.1)

    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if 2 not in results:
        return {"ok": False, "error": "no tools/list response"}
    res = results[2]
    if "error" in res:
        return {"ok": False, "error": res["error"]}
    tools = res.get("result", {}).get("tools", [])
    return {"ok": True, "tool_count": len(tools), "tools": [t["name"] for t in tools[:10]]}


def url_verify(name, url):
    try:
        # Streamable-HTTP MCP servers require this Accept pair and reply in
        # SSE format; Accept: */* gets a 406 from strict servers.
        mcp_headers = {
            "Content-Type": "application/json",
            "User-Agent": "curl/8.0.0",
            "Accept": "application/json, text/event-stream",
        }
        init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify"}}}).encode()
        req1 = urllib.request.Request(url, data=init, method="POST", headers=mcp_headers)
        session_id = None
        with urllib.request.urlopen(req1, timeout=TIMEOUT) as resp:
            session_id = resp.headers.get("mcp-session-id")
            resp.read()
        list_ = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
        headers = dict(mcp_headers)
        if session_id:
            headers["mcp-session-id"] = session_id
        req2 = urllib.request.Request(url, data=list_, method="POST", headers=headers)
        with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp:
            body = resp.read().decode()
            if (resp.headers.get_content_type() or "") == "text/event-stream":
                data = _extract_sse_json(body)
            else:
                data = json.loads(body)
            if not isinstance(data, dict):
                return {"ok": False, "error": "unparseable response body"}
            tools = data.get("result", {}).get("tools", [])
            return {"ok": True, "tool_count": len(tools)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    if not CONFIG.exists():
        print(f"MCP config not found: {CONFIG}", file=sys.stderr)
        return 1
    config = json.loads(CONFIG.read_text())
    results = {}
    for name, spec in config["mcpServers"].items():
        if "url" in spec:
            results[name] = url_verify(name, spec["url"])
        elif "command" in spec:
            env = spec.get("env")
            results[name] = stdio_verify(name, spec["command"], spec.get("args", []), env)
        else:
            results[name] = {"ok": False, "error": "unknown transport"}

    ok = sum(1 for r in results.values() if r["ok"])
    print(f"\nVerified {ok}/{len(results)} MCP servers")
    print("-" * 60)
    for name, r in sorted(results.items()):
        if r["ok"]:
            extra = r.get("tool_count", r.get("status", ""))
            print(f"  {name}: OK ({extra})")
        else:
            print(f"  {name}: FAIL {r.get('error', '')}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
