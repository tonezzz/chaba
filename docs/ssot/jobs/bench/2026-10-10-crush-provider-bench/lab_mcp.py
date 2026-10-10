#!/usr/bin/env python3
"""Minimal read-only MCP stdio server for the crush provider bench.
Exposes two tools scoped to the directory containing this file:
lab_list, lab_read. Newline-delimited JSON-RPC 2.0 per MCP stdio."""
import json, os, sys

ROOT = os.path.dirname(os.path.realpath(__file__))

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

def result(id_, res):
    send({"jsonrpc": "2.0", "id": id_, "result": res})

def error(id_, code, msg):
    send({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}})

def safe_path(p):
    real = os.path.realpath(os.path.join(ROOT, p.lstrip("/")))
    if not (real == ROOT or real.startswith(ROOT + os.sep)):
        return None
    return real

TOOLS = [
    {"name": "lab_list",
     "description": "List files in the scratch dir (read-only)",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "lab_read",
     "description": "Read a file inside the scratch dir (read-only)",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string"}},
                     "required": ["path"]}},
]

def call_tool(name, args):
    if name == "lab_list":
        entries = sorted(os.listdir(ROOT))
        return {"content": [{"type": "text", "text": "\n".join(entries) or "(empty)"}]}
    if name == "lab_read":
        real = safe_path(args.get("path", ""))
        if real is None:
            return {"content": [{"type": "text", "text": "path outside scratch dir refused"}], "isError": True}
        try:
            with open(real, "r", encoding="utf-8", errors="replace") as f:
                return {"content": [{"type": "text", "text": f.read()}]}
        except OSError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    return {"content": [{"type": "text", "text": "unknown tool"}], "isError": True}

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = msg.get("method")
    id_ = msg.get("id")
    if method == "initialize":
        result(id_, {"protocolVersion": "2025-06-18",
                     "capabilities": {"tools": {}},
                     "serverInfo": {"name": "lab-ro-mcp", "version": "0.1.0"}})
    elif method == "ping":
        result(id_, {})
    elif method == "tools/list":
        result(id_, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {})
        result(id_, call_tool(params.get("name", ""), params.get("arguments", {})))
    elif id_ is not None:
        error(id_, -32601, "method not found")
