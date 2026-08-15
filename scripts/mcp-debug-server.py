#!/usr/bin/env python3
"""MCP Debug server: compact and raw command dispatch to tony-omen and tony-dell."""
import difflib
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


def reload_config():
    global CONFIG, HOSTS, DEBUG_COMMANDS, RAW_PREFIXES
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


def mcp_stats(host, command):
    raw_result = run_on_host(host, command, compact=False)
    compact_result = run_on_host(host, command, compact=True)

    raw_out = raw_result.get("out", "") or ""
    compact_out = compact_result.get("out", "") or ""

    raw_words = len(raw_out.split())
    compact_words = len(compact_out.split())
    raw_chars = len(raw_out)
    compact_chars = len(compact_out)

    saved_words = raw_words - compact_words
    savings_pct = round((saved_words / raw_words * 100), 1) if raw_words > 0 else 0.0
    saved_chars = raw_chars - compact_chars
    savings_pct_chars = round((saved_chars / raw_chars * 100), 1) if raw_chars > 0 else 0.0

    return {
        "ok": raw_result.get("rc") == 0 and compact_result.get("rc") == 0,
        "host": host,
        "command": command,
        "raw_words": raw_words,
        "compact_words": compact_words,
        "saved_words": saved_words,
        "savings_pct": savings_pct,
        "raw_chars": raw_chars,
        "compact_chars": compact_chars,
        "saved_chars": saved_chars,
        "savings_pct_chars": savings_pct_chars,
        "raw_rc": raw_result.get("rc"),
        "compact_rc": compact_result.get("rc"),
    }


def mcp_vet(command, add=False):
    stats = {}
    all_positive = True
    for host in HOSTS:
        s = mcp_stats(host, command)
        stats[host] = s
        if not s.get("ok") or s.get("savings_pct_chars", 0) <= 0:
            all_positive = False
    result = {"ok": all_positive, "command": command, "stats": stats, "added": False}

    if add and all_positive:
        with open(SSOT) as f:
            data = yaml.safe_load(f)

        if "debug_commands" not in data:
            data["debug_commands"] = {}
        if "efficiency" not in data:
            data["efficiency"] = {"tracked_by": "mcp_stats", "commands": {}}
        if "commands" not in data["efficiency"]:
            data["efficiency"]["commands"] = {}

        data["debug_commands"][command] = {"description": f"Vetted {command}", "compact": True, "expected_output": "auto"}

        # Use tony_omen as the baseline for the SSOT efficiency entry.
        baseline = stats.get("tony_omen", stats.get(list(HOSTS.keys())[0]))
        data["efficiency"]["commands"][command] = {
            "raw_words": baseline["raw_words"],
            "compact_words": baseline["compact_words"],
            "savings_pct": baseline["savings_pct"],
            "raw_chars": baseline["raw_chars"],
            "compact_chars": baseline["compact_chars"],
            "savings_pct_chars": baseline["savings_pct_chars"],
            "recommended": True,
        }

        with open(SSOT, "w") as f:
            yaml.dump(data, f, width=200, sort_keys=False, default_flow_style=False)

        reload_config()
        result["added"] = True

    return result


def mcp_savings(hosts):
    if not hosts:
        hosts = list(HOSTS.keys())
    commands = list(DEBUG_COMMANDS.keys())
    per_host = {}
    total_raw = 0
    total_compact = 0
    for host in hosts:
        if host not in HOSTS:
            continue
        per_host[host] = {"commands": {}, "raw_chars": 0, "compact_chars": 0, "saved_chars": 0}
        for command in commands:
            s = mcp_stats(host, command)
            per_host[host]["commands"][command] = s
            per_host[host]["raw_chars"] += s["raw_chars"]
            per_host[host]["compact_chars"] += s["compact_chars"]
            per_host[host]["saved_chars"] += s["saved_chars"]
            total_raw += s["raw_chars"]
            total_compact += s["compact_chars"]
    saved = total_raw - total_compact
    pct = round(saved / total_raw * 100, 1) if total_raw > 0 else 0.0
    return {
        "ok": True,
        "hosts": per_host,
        "total_raw_chars": total_raw,
        "total_compact_chars": total_compact,
        "total_saved_chars": saved,
        "total_savings_pct": pct,
    }


def mcp_diff(command, hosts, compact):
    if len(hosts) != 2:
        return {"ok": False, "error": "mcp_diff requires exactly 2 hosts"}
    h1, h2 = hosts
    r1 = run_on_host(h1, command, compact=compact)
    r2 = run_on_host(h2, command, compact=compact)
    if not r1.get("ok") or not r2.get("ok"):
        return {"ok": False, "error": "one or both host commands failed", h1: r1, h2: r2}
    lines1 = r1.get("out", "").splitlines()
    lines2 = r2.get("out", "").splitlines()
    diff = list(difflib.unified_diff(lines1, lines2, fromfile=h1, tofile=h2, lineterm=""))
    return {
        "ok": True,
        "command": command,
        "hosts": [h1, h2],
        "same": lines1 == lines2,
        "diff_lines": diff,
    }


def mcp_logs(host, unit=None, file=None, lines=50):
    if not unit and not file:
        return {"ok": False, "error": "unit or file required"}
    if unit:
        command = f"journalctl -u {shlex.quote(unit)} -n {int(lines)} --no-pager"
        return run_on_host(host, command, compact=True)
    command = f"tail -n {int(lines)} {shlex.quote(file)}"
    return run_on_host(host, command, compact=False)


def mcp_net(host, port=None):
    if port:
        command = f"ss -tlnp sport = :{int(port)}"
    else:
        command = "ss -tlnp"
    return run_on_host(host, command, compact=False)


def mcp_env(host, pattern=None):
    result = run_on_host(host, "env", compact=False)
    if not result.get("ok"):
        return result
    lines = result.get("out", "").splitlines()
    if pattern:
        pat = pattern.lower()
        lines = [l for l in lines if pat in l.lower()]
    result["out"] = "\n".join(lines)
    return result


def mcp_gpu(host):
    for cmd in ["nvidia-smi", "rocm-smi"]:
        r = run_on_host(host, cmd, compact=False)
        if r.get("ok"):
            r["gpu_tool"] = cmd
            return r
    return {"ok": False, "error": "no supported GPU tool found (nvidia-smi or rocm-smi)", "host": host}


def handle_initialize(id_):
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-debug", "version": "2"},
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
        {
            "name": "mcp_stats",
            "description": "Compare raw and compact output for a command and report word/character savings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "command": {"type": "string", "description": "Command to compare, e.g. 'df -h'"},
                },
                "required": ["host", "command"],
            },
        },
        {
            "name": "mcp_vet",
            "description": "Vet a candidate command on all hosts and optionally add it to the SSOT.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Candidate command to vet"},
                    "add": {"type": "boolean", "description": "Add to SSOT if all hosts pass", "default": False},
                },
                "required": ["command"],
            },
        },
        {
            "name": "mcp_savings",
            "description": "Compute live total raw/compact/savings across all debug commands on one or more hosts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hosts": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(HOSTS.keys())},
                        "description": "Hosts to include (defaults to all)",
                    },
                },
            },
        },
        {
            "name": "mcp_diff",
            "description": "Run the same command on two hosts and return a unified diff.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to diff"},
                    "hosts": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(HOSTS.keys())},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Two hosts to compare",
                    },
                    "compact": {"type": "boolean", "description": "Use compact output for both hosts", "default": False},
                },
                "required": ["command", "hosts"],
            },
        },
        {
            "name": "mcp_logs",
            "description": "Tail a file or fetch journalctl logs for a service on a host.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "unit": {"type": "string", "description": "systemd unit for journalctl"},
                    "file": {"type": "string", "description": "File path for tail"},
                    "lines": {"type": "integer", "description": "Number of lines", "default": 50},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_net",
            "description": "Show listening sockets with ss -tlnp, optionally filtered by port.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "port": {"type": "integer", "description": "Optional port filter"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_env",
            "description": "Dump remote environment variables, optionally filtered by a substring.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "pattern": {"type": "string", "description": "Optional substring filter (case-insensitive)"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_gpu",
            "description": "Run nvidia-smi or rocm-smi on a host and return the output.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                },
                "required": ["host"],
            },
        },
    ]
    return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}


def handle_tools_call(id_, params):
    name = params.get("name")
    arguments = params.get("arguments", {})
    host = arguments.get("host")
    command = arguments.get("command")

    if name == "mcp_debug":
        if not host or not command:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}
        result = run_on_host(host, command, compact=True)
        try:
            data = json.loads(result.get("out", "") or "{}")
            data["h"] = host
            output = json.dumps(data, separators=(",", ":"))
        except json.JSONDecodeError:
            result["h"] = host
            output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_raw":
        if not host or not command:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}
        result = run_on_host(host, command, compact=False)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_stats":
        if not host or not command:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}
        result = mcp_stats(host, command)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_vet":
        cmd = arguments.get("command")
        if not cmd:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "command is required"}}
        result = mcp_vet(cmd, add=arguments.get("add", False))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_savings":
        result = mcp_savings(arguments.get("hosts"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_diff":
        cmd = arguments.get("command")
        hosts = arguments.get("hosts", [])
        compact = arguments.get("compact", False)
        if not cmd or len(hosts) != 2:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "command and exactly 2 hosts are required"}}
        result = mcp_diff(cmd, hosts, compact)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_logs":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_logs(h, unit=arguments.get("unit"), file=arguments.get("file"), lines=arguments.get("lines", 50))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_net":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_net(h, port=arguments.get("port"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_env":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_env(h, pattern=arguments.get("pattern"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_gpu":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_gpu(h)
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
