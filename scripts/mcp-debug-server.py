#!/usr/bin/env python3
"""MCP Debug server: compact and raw command dispatch to tony-omen and tony-dell."""
import difflib
import csv
import io
import json
import logging
import shlex
import subprocess
import sys
import yaml
from datetime import datetime
from pathlib import Path

SSOT = Path(__file__).parent.parent / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.yml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

with open(SSOT) as f:
    CONFIG = yaml.safe_load(f)

HOSTS = CONFIG.get("hosts", {})
DEBUG_COMMANDS = CONFIG.get("debug_commands", {})
RAW_PREFIXES = CONFIG.get("raw_commands", {}).get("allowed_prefixes", [])
PRESETS = CONFIG.get("presets", {})
REPO_DIR = SSOT.parent.parent.parent.parent
REPORTS_SSOT = REPO_DIR / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.reports.yml"


def load_report_config():
    if not REPORTS_SSOT.exists():
        return {}
    with open(REPORTS_SSOT) as f:
        return yaml.safe_load(f) or {}


def reload_config():
    global CONFIG, HOSTS, DEBUG_COMMANDS, RAW_PREFIXES, PRESETS
    with open(SSOT) as f:
        CONFIG = yaml.safe_load(f)
    HOSTS = CONFIG.get("hosts", {})
    DEBUG_COMMANDS = CONFIG.get("debug_commands", {})
    RAW_PREFIXES = CONFIG.get("raw_commands", {}).get("allowed_prefixes", [])
    PRESETS = CONFIG.get("presets", {})


def run_on_host(host, command, compact):
    if host not in HOSTS:
        return {"ok": False, "error": f"unknown host: {host}", "available_hosts": list(HOSTS.keys())}
    h = HOSTS[host]
    if compact and not h.get("compact", True):
        return {"ok": False, "error": f"compact mcp_debug not supported for host: {host}", "host": host, "rc": 1, "out": "", "err": ""}
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
        ssh = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=60", "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes"]
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


def generate_savings_report(savings, report_cfg):
    cfg = report_cfg.get("reports", {}).get("savings_table", {})
    columns = cfg.get("columns", [
        {"key": "command", "label": "Command"},
        {"key": "raw_chars", "label": "Raw chars"},
        {"key": "compact_chars", "label": "Compact chars"},
        {"key": "saved_chars", "label": "Saved chars"},
        {"key": "savings_pct_chars", "label": "Char %"},
        {"key": "savings_pct", "label": "Word %"},
    ])
    sort_by = cfg.get("sort", {}).get("by", "savings_pct_chars")
    sort_desc = cfg.get("sort", {}).get("descending", True)
    neg_marker = cfg.get("negative_marker", "")
    include_totals = cfg.get("include_totals", True)

    headers = [c["label"] for c in columns]
    lines = ["# MCP Debug Savings Report", ""]

    for host, data in savings.get("hosts", {}).items():
        lines.append(f"## {host}")
        lines.append("")
        commands = list(data.get("commands", {}).values())
        commands.sort(key=lambda x: x.get(sort_by, 0), reverse=sort_desc)

        table = [headers]
        for cmd in commands:
            row = []
            for col in columns:
                val = cmd.get(col["key"], "")
                if col["key"] in ("savings_pct_chars", "savings_pct") and isinstance(val, (int, float)):
                    val = f"{val:.1f}"
                    if neg_marker and cmd.get(col["key"], 0) < 0:
                        val = f"{val} {neg_marker}".strip()
                row.append(str(val))
            table.append(row)

        if table:
            widths = [max(len(str(r[i])) for r in table) for i in range(len(headers))]
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
            for row in table[1:]:
                lines.append("| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(row))) + " |")
            lines.append("")

        if include_totals:
            raw = data.get("raw_chars", 0)
            compact = data.get("compact_chars", 0)
            saved = data.get("saved_chars", 0)
            pct = round(saved / raw * 100, 1) if raw else 0.0
            lines.append(f"**{host} totals**: raw={raw}, compact={compact}, saved={saved} ({pct}%)")
            lines.append("")

    if include_totals:
        total_raw = savings.get("total_raw_chars", 0)
        total_compact = savings.get("total_compact_chars", 0)
        total_saved = savings.get("total_saved_chars", 0)
        total_pct = savings.get("total_savings_pct", 0.0)
        lines.append(f"**Overall totals**: raw={total_raw}, compact={total_compact}, saved={total_saved} ({total_pct}%)")
        lines.append("")

    return "\n".join(lines)


def generate_json_report(savings):
    return json.dumps(savings, indent=2, default=str, sort_keys=False)


def generate_csv_report(savings):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["host", "command", "raw_chars", "compact_chars", "saved_chars", "char_pct", "word_pct"])
    for host, data in savings.get("hosts", {}).items():
        for cmd_name, cmd in data.get("commands", {}).items():
            writer.writerow([
                host,
                cmd_name,
                cmd.get("raw_chars", 0),
                cmd.get("compact_chars", 0),
                cmd.get("saved_chars", 0),
                round(cmd.get("savings_pct_chars", 0), 1),
                round(cmd.get("savings_pct", 0), 1),
            ])
        writer.writerow([
            f"{host} totals",
            "",
            data.get("raw_chars", 0),
            data.get("compact_chars", 0),
            data.get("saved_chars", 0),
            round(data.get("saved_chars", 0) / data.get("raw_chars", 0) * 100, 1) if data.get("raw_chars") else 0.0,
            "",
        ])
    writer.writerow([
        "overall totals",
        "",
        savings.get("total_raw_chars", 0),
        savings.get("total_compact_chars", 0),
        savings.get("total_saved_chars", 0),
        round(savings.get("total_savings_pct", 0.0), 1),
        "",
    ])
    return output.getvalue()


def mcp_report(hosts=None, save=False, format="markdown"):
    if hosts is None:
        hosts = []
    savings = mcp_savings(hosts)
    report_cfg = load_report_config()
    if format == "json":
        report = generate_json_report(savings)
    elif format == "csv":
        report = generate_csv_report(savings)
    else:
        report = generate_savings_report(savings, report_cfg)
    saved_path = None
    if save:
        cfg = (report_cfg.get("reports") or {}).get("savings_table", {})
        template = cfg.get("save_path_template", "reports/mcp-savings-{date}.md")
        filename = template.format(date=datetime.now().strftime("%Y-%m-%d"))
        if format in ("json", "csv") and filename.endswith(".md"):
            filename = f"{filename[:-3]}.{format}"
        path = REPO_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report)
        saved_path = str(path)
    return {
        "ok": savings.get("ok", True),
        "report": report,
        "saved_path": saved_path,
        "format": format,
    }


def mcp_focus(request=None):
    focus_current = REPO_DIR / "docs" / "ssot" / "ssot.focus.current.yml"
    if not focus_current.exists():
        return {"ok": False, "error": "ssot.focus.current.yml not found"}
    with open(focus_current) as f:
        doc = yaml.safe_load(f)
    active = {}
    quick_wins = [
        i for s in doc.get("sections", [])
        if s.get("title") == "Quick Wins"
        for i in s.get("items", [])
    ]
    for sec in doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if not item or item.get("status") != "active":
                    continue
                section = sec.get("title")
                if section == "Active Shared Focus":
                    active["shared"] = item
                else:
                    active["branch"] = item

    if not request:
        return {"ok": True, "active": active, "quick_wins": quick_wins}

    # Simple intake suggestion based on the decision_tree in ssot.focus.current.yml
    req = str(request).lower()
    suggestion = {"request": request, "action": "inbox", "reason": "No obvious match; needs triage"}

    for label, it in [("shared", active.get("shared")), ("branch", active.get("branch"))]:
        if not it:
            continue
        if it.get("label", "").lower() in req:
            suggestion = {"action": "active", "section": label, "label": it["label"], "reason": "Request mentions the active focus"}
            break
        for st in it.get("subtasks", []):
            if st.get("label", "").lower() in req:
                suggestion = {"action": "active", "section": label, "label": it["label"], "subtask": st["label"], "reason": "Request matches an active subtask"}
                break
        else:
            continue
        break
    else:
        for q in quick_wins:
            if q.get("label", "").lower() in req:
                suggestion = {"action": "quick_win", "label": q["label"], "reason": "Request matches a completed quick win"}
                break

    for cue, action, reason in [
        ("all", "active", "Request uses 'all' or implies continuing current work"),
        ("focus", "active", "Request is about the focus system; continue active focus"),
        ("quick", "quick_win", "Request sounds small"),
        ("small", "quick_win", "Request sounds small"),
        ("fix", "quick_win", "Request sounds small"),
        ("tweak", "quick_win", "Request sounds small"),
        ("design", "backlog", "Request is new strategic design work"),
        ("workflow", "backlog", "Request is new strategic design work"),
        ("rebuild", "backlog", "Request is new strategic design work"),
        ("implement", "backlog", "Request is multi-step implementation"),
    ]:
        if cue in req:
            suggestion = {"action": action, "reason": reason}
            break

    return {"ok": True, "active": active, "quick_wins": quick_wins, "intake_suggestion": suggestion}


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
        {
            "name": "mcp_health",
            "description": "Check that the mcp-debug binary exists and is reachable on a host. Fails fast if SSH is down.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_preset_list",
            "description": "List available multi-host diagnostic presets.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "mcp_preset_run",
            "description": "Run a named preset. Presets are multi-step, multi-host diagnostic routines.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "preset": {"type": "string", "description": "Preset name, e.g. 'quick-health'"},
                },
                "required": ["preset"],
            },
        },
        {
            "name": "mcp_report",
            "description": "Generate a savings report in markdown, json, or csv from mcp_savings and optionally save it to reports/.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hosts": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(HOSTS.keys())},
                        "description": "Hosts to include (defaults to all)",
                    },
                    "save": {"type": "boolean", "description": "Save the report to reports/mcp-savings-YYYY-MM-DD.{format}", "default": False},
                    "format": {"type": "string", "enum": ["markdown", "json", "csv"], "description": "Output format", "default": "markdown"},
                },
            },
        },
        {
            "name": "mcp_focus",
            "description": "Return the current active focus and suggest an intake action for an optional request.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "Optional user request to classify"},
                },
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
        if not result.get("ok"):
            result["h"] = host
            output = json.dumps(result, separators=(",", ":"))
        else:
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
    elif name == "mcp_health":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_health(h)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_preset_list":
        result = mcp_preset_list()
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_preset_run":
        preset = arguments.get("preset")
        if not preset:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "preset is required"}}
        result = mcp_preset_run(preset)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_report":
        result = mcp_report(arguments.get("hosts"), save=arguments.get("save", False), format=arguments.get("format", "markdown"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_focus":
        result = mcp_focus(request=arguments.get("request"))
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
