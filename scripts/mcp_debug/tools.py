"""MCP Debug tool functions."""
import difflib
import json
import shlex
import yaml
from .config import HOSTS, DEBUG_COMMANDS, PRESETS, SSOT, logger
from .hosts import run_on_host


def mcp_debug(host, command):
    result = run_on_host(host, command, compact=True)
    if not result.get("ok"):
        result["h"] = host
        return json.dumps(result, separators=(",", ":"))
    try:
        data = json.loads(result.get("out", "") or "{}")
        data["h"] = host
        return json.dumps(data, separators=(",", ":"))
    except json.JSONDecodeError:
        result["h"] = host
        return json.dumps(result, separators=(",", ":"))


def mcp_raw(host, command):
    result = run_on_host(host, command, compact=False)
    result["h"] = host
    return json.dumps(result, separators=(",", ":"))


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
        if not HOSTS[host].get("compact", True):
            continue
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
        if not HOSTS[host].get("compact", True):
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

def mcp_health(host):
    if host not in HOSTS:
        return {"ok": False, "error": f"unknown host: {host}", "available_hosts": list(HOSTS.keys())}
    h = HOSTS[host]
    mcp_debug = h.get("mcp_debug_path", "/home/tony/.local/bin/mcp-debug")
    return run_on_host(host, f"ls -l {shlex.quote(mcp_debug)}", compact=False)

def mcp_preset_list():
    return {
        "ok": True,
        "presets": [
            {"name": name, "description": data.get("description", "")}
            for name, data in PRESETS.items()
        ],
    }

def mcp_preset_run(name):
    if name not in PRESETS:
        return {"ok": False, "error": f"unknown preset: {name}", "available_presets": list(PRESETS.keys())}
    preset = PRESETS[name]
    steps = preset.get("steps", [])
    results = []
    all_ok = True
    for step in steps:
        host = step.get("host")
        tool = step.get("tool")
        command = step.get("command")
        if not host or not tool:
            results.append({"ok": False, "error": "step missing host or tool", "step": step})
            all_ok = False
            continue
        if tool == "mcp_debug":
            if not command:
                results.append({"ok": False, "error": "mcp_debug step missing command", "step": step})
                all_ok = False
                continue
            r = run_on_host(host, command, compact=True)
            try:
                data = json.loads(r.get("out", "") or "{}")
                data["h"] = host
                r["out"] = json.dumps(data, separators=(",", ":"))
            except json.JSONDecodeError:
                r["h"] = host
            results.append(r)
            if not r.get("ok"):
                all_ok = False
        elif tool == "mcp_raw":
            if not command:
                results.append({"ok": False, "error": "mcp_raw step missing command", "step": step})
                all_ok = False
                continue
            r = run_on_host(host, command, compact=False)
            r["h"] = host
            results.append(r)
            if not r.get("ok"):
                all_ok = False
        elif tool == "mcp_health":
            results.append(mcp_health(host))
        else:
            results.append({"ok": False, "error": f"unsupported tool: {tool}", "step": step})
            all_ok = False
    return {
        "ok": all_ok,
        "preset": name,
        "description": preset.get("description", ""),
        "results": results,
    }

