#!/usr/bin/env python3
"""MCP Debug server: compact and raw command dispatch to tony-omen and tony-dell."""
import json
import logging
import shlex
import subprocess
import sys
import yaml
from pathlib import Path

SSOT = Path(__file__).parent.parent / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.yml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

with open(SSOT) as f:
    CONFIG = yaml.safe_load(f)

HOSTS = CONFIG.get("hosts", {})
DEBUG_COMMANDS = CONFIG.get("debug_commands", {})
RAW_PREFIXES = CONFIG.get("raw_commands", {}).get("allowed_prefixes", [])


def run_on_host(host, command, compact):
    if host not in HOSTS:
        return {"ok": False, "error": f"unknown host: {host}", "available_hosts": list(HOSTS.keys())}
    h = HOSTS[host]
    mcp_debug = h.get("mcp_debug_path", "/home/tony/.local/bin/mcp-debug")

    if not compact:
        base = shlex.split(command)[0]
        base_name = base.split("/")[-1]
        if base_name not in RAW_PREFIXES:
            return {"ok": False, "error": f"raw command base '{base_name}' not in allowed_prefixes", "allowed": RAW_PREFIXES}

    if h.get("local"):
        if compact:
            argv = [mcp_debug] + shlex.split(command)
        else:
            argv = shlex.split(command)
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    else:
        ssh = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=60", "-o", "ServerAliveCountMax=3"]
        user = h.get("ssh_user", "tony")
        hostname = h.get("hostname", host)
        target = f"{user}@{hostname}"
        if compact:
            remote = " ".join([shlex.quote(mcp_debug)] + [shlex.quote(a) for a in shlex.split(command)])
        else:
            remote = command
        proc = subprocess.run(ssh + [target, remote], capture_output=True, text=True, timeout=300)

    return {
        "ok": proc.returncode == 0,
        "host": host,
        "rc": proc.returncode,
        "out": proc.stdout,
        "err": proc.stderr,
    }


def handle_initialize(id_):
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "mcp-debug", "version": "1"},
        },
    }


def handle_tools_list(id_):
    known = ", ".join(DEBUG_COMMANDS.keys())
    tools = [
        {
            "name": "mcp_debug",
            "description": f"Run a compact debug command on a host. Known commands: {known}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "command": {"type": "string", "description": "Debug command, e.g. 'systemctl list-units'"},
                },
                "required": ["host", "command"],
            },
        },
        {
            "name": "mcp_raw",
            "description": "Run a raw command on a host with allowed prefixes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "command": {"type": "string", "description": "Raw shell command"},
                },
                "required": ["host", "command"],
            },
        },
    ]
    return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}


def handle_tools_call(id_, params):
    name = params.get("name")
    arguments = params.get("arguments", {})
    host = arguments.get("host")
    command = arguments.get("command")
    if not host or not command:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}

    if name == "mcp_debug":
        result = run_on_host(host, command, compact=True)
        try:
            json.loads(result.get("out", "") or "{}")
            output = result["out"].strip()
        except json.JSONDecodeError:
            output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_raw":
        result = run_on_host(host, command, compact=False)
        output = json.dumps(result, separators=(",", ":"))
    else:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"unknown tool: {name}"}}

    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {"content": [{"type": "text", "text": output}]},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            method = msg.get("method")
            id_ = msg.get("id")
            if method == "initialize":
                print(json.dumps(handle_initialize(id_)))
            elif method == "tools/list":
                print(json.dumps(handle_tools_list(id_)))
            elif method == "tools/call":
                print(json.dumps(handle_tools_call(id_, msg.get("params", {}))))
            elif "id" in msg:
                print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}))
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            logger.error("invalid json: %s", e)


if __name__ == "__main__":
    main()
