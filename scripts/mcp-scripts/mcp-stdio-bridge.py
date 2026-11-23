#!/usr/bin/env python3
"""Generic stdio <-> streamable-HTTP MCP bridge.

Devin/Windsurf can declare remote MCP servers directly via a ``url:``
config entry — but then no client-side tool filtering is possible. This
bridge lets a remote streamable-HTTP MCP server sit BEHIND
mcp-allowlist.py as a stdio child:

    "alphavantage": {
      "command": "/usr/bin/python3",
      "args": [".../mcp-allowlist.py", "--allowfile",
               ".../allowlist.alphavantage.json"]
    }

and inside ``allowlist.alphavantage.json``:

    "command": ["/usr/bin/python3", ".../mcp-stdio-bridge.py",
                "https://mcp.alphavantage.co/mcp?apikey=..."]

Behaviour:
  * each stdin line is one JSON-RPC message -> POST to the remote endpoint
  * request messages (with ``id``) -> response messages echoed to stdout
  * notifications (no ``id``) -> POST, nothing emitted
  * reply bodies may be ``application/json`` or ``text/event-stream``
    (``data:`` lines) — every payload is forwarded
  * ``mcp-session-id`` is captured from response headers and resent on
    subsequent requests; ``MCP-Protocol-Version`` is sent after initialize
  * on transport failure a JSON-RPC error is synthesized for requests so
    the client never hangs waiting for a reply

URL source: argv[1], or ``MCP_BRIDGE_URL`` env when argv is absent —
prefer the env form when the URL embeds a credential so the secret does
not appear in ``ps`` output.
"""

import json
import os
import sys

import requests

TIMEOUT = 120


def _sse_payloads(text):
    """Yield JSON payloads from data: lines of an SSE response body."""
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    continue


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MCP_BRIDGE_URL", "")
    if not url:
        print("[mcp-stdio-bridge] no URL: pass argv[1] or set MCP_BRIDGE_URL", file=sys.stderr)
        sys.exit(2)

    session_id = None
    protocol_version = None

    def post(msg):
        nonlocal session_id, protocol_version
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            headers["mcp-session-id"] = session_id
        if protocol_version:
            headers["MCP-Protocol-Version"] = protocol_version
        try:
            resp = requests.post(url, json=msg, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            return None, f"bridge transport error: {e}"
        sid = resp.headers.get("mcp-session-id")
        if sid:
            session_id = sid
        if "text/event-stream" in resp.headers.get("content-type", ""):
            return list(_sse_payloads(resp.text)), None
        body = resp.text.strip()
        if not body:
            return [], None
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None, f"bridge bad reply ({resp.status_code}): {body[:200]}"
        return data if isinstance(data, list) else [data], None

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        is_request = "id" in msg
        msgs, err = post(msg)
        if isinstance(msg, dict) and msg.get("method") == "initialize":
            result = (msgs or [{}])[-1] if msgs else {}
            pv = result.get("result", {}).get("protocolVersion") if isinstance(result, dict) else None
            protocol_version = pv or msg.get("params", {}).get("protocolVersion")
        if not is_request:
            continue
        if err:
            out = {"jsonrpc": "2.0", "id": msg.get("id"),
                   "error": {"code": -32000, "message": err}}
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
        elif msgs:
            for m in msgs:
                sys.stdout.write(json.dumps(m) + "\n")
            sys.stdout.flush()
        else:
            out = {"jsonrpc": "2.0", "id": msg.get("id"),
                   "error": {"code": -32000, "message": "bridge: empty reply from remote"}}
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
