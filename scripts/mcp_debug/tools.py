"""MCP Debug tool functions.

These functions back the `mcp-debug` MCP server. Consumers should call `mcp-debug` tools rather than importing this module directly."""
import base64
import difflib
import json
import os
import re
import shlex
import time
import yaml
from datetime import datetime
from .config import HOSTS, FILE_LIMITS, DEBUG_COMMANDS, RAW_PREFIXES, RAW_CATEGORIES, PRESETS, SSOT, BASELINES, logger
from .hosts import run_on_host


def _section_yaml(key, data):
    """Dump a single top-level section, returning text that starts with key:."""
    return yaml.safe_dump({key: data}, sort_keys=False, allow_unicode=True, width=120,
                          default_flow_style=False)


def _replace_section(text, key, new_section):
    """Replace a top-level YAML section using a regex that anchors on the next top-level key."""
    pattern = rf"^{re.escape(key)}:.*?^(?=(?:[a-zA-Z0-9_]+):|\Z)"
    return re.sub(pattern, new_section, text, count=1, flags=re.MULTILINE | re.DOTALL)


def mcp_debug(host, command):
    result = run_on_host(host, command, compact=True)
    if not result.get("ok"):
        result["h"] = host
        return json.dumps(result, separators=(",", ":"))
    try:
        data = json.loads(result.get("out", "") or "{}")
        if isinstance(data, dict):
            data["h"] = host
            return json.dumps(data, separators=(",", ":"))
        return json.dumps({"h": host, "data": data}, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        result["h"] = host
        return json.dumps(result, separators=(",", ":"))


def mcp_raw(host, command):
    result = run_on_host(host, command, compact=False)
    result["h"] = host
    return json.dumps(result, separators=(",", ":"))


def mcp_system(host, command):
    """Run a raw systemctl/system command if it is an exact allowed command."""
    if not command or not command.lstrip().startswith(("systemctl ", "systemctl\t")):
        return json.dumps({"ok": False, "error": "mcp_system only supports systemctl commands", "host": host}, separators=(",", ":"))
    result = run_on_host(host, command, compact=False)
    result["h"] = host
    result["tool"] = "mcp_system"
    return json.dumps(result, separators=(",", ":"))


def _resolve_input(source, results, captured):
    if source is None:
        return None
    if isinstance(source, (int, float)):
        idx = int(source)
        if 0 <= idx < len(results):
            return results[idx]
        return None
    if isinstance(source, str) and source.startswith("$"):
        return captured.get(source[1:])
    return source


def _get_path(obj, path):
    if not path:
        return obj
    parts = str(path).split(".") if isinstance(path, str) else []
    for p in parts:
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(p)
        elif isinstance(obj, list):
            try:
                obj = obj[int(p)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return obj


def mcp_transform(input=None, op="identity", params=None, results=None, captured=None):
    """Transform a previous step result: filter, sort, capture, or pick a value."""
    data = _resolve_input(input, results or [], captured or {})
    if data is None:
        return {"ok": False, "error": "input not found"}
    params = params or {}
    if op == "capture":
        return {"ok": True, "captured": {params.get("as"): _get_path(data, params.get("path"))}}
    if op == "filter":
        if not isinstance(data, list):
            return {"ok": False, "error": "filter input must be a list"}
        key = params.get("key")
        value = params.get("value")
        return {"ok": True, "items": [x for x in data if _get_path(x, key) == value]}
    if op == "sort":
        if not isinstance(data, list):
            return {"ok": False, "error": "sort input must be a list"}
        key = params.get("key")
        reverse = params.get("reverse", False)
        return {"ok": True, "items": sorted(data, key=lambda x: _get_path(x, key) or "", reverse=reverse)}
    if op == "pick":
        return {"ok": True, "value": _get_path(data, params.get("path"))}
    return {"ok": False, "error": f"unknown transform op: {op}"}


def mcp_stats(host, command):
    raw_cmd = DEBUG_COMMANDS.get(command, {}).get("raw_command", command)
    raw_result = run_on_host(host, raw_cmd, compact=False)
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
        # Update canonical policy SSOT with the new debug command.
        with open(SSOT) as f:
            ssot_text = f.read()
        data_ssot = yaml.safe_load(ssot_text)
        if "debug_commands" not in data_ssot:
            data_ssot["debug_commands"] = {}
        data_ssot["debug_commands"][command] = {
            "description": f"Vetted {command}",
            "compact": True,
            "expected_output": "auto",
        }
        ssot_text = _replace_section(ssot_text, "debug_commands", _section_yaml("debug_commands", data_ssot["debug_commands"]))
        with open(SSOT, "w") as f:
            f.write(ssot_text)

        # Update the runtime baselines SSOT with the new efficiency numbers.
        if not BASELINES.exists():
            from datetime import datetime
            baseline_text = (
                f"title: MCP Debug Baselines\n"
                f"subtitle: Generated per-host raw/compact savings baselines for mcp_debug commands\n"
                f"icon: bug\n"
                f"version: 1\n"
                f"note: Generated by mcp_vet and mcp-debug-refresh-baselines.py. This is runtime data, not canonical policy.\n\n"
            )
            BASELINES.parent.mkdir(parents=True, exist_ok=True)
            BASELINES.write_text(baseline_text)
        else:
            baseline_text = BASELINES.read_text()

        data_baseline = yaml.safe_load(baseline_text)
        if "efficiency" not in data_baseline:
            data_baseline["efficiency"] = {"tracked_by": "mcp_stats", "commands": {}}
        if "commands" not in data_baseline["efficiency"]:
            data_baseline["efficiency"]["commands"] = {}
        if "workflow" not in data_baseline:
            data_baseline["workflow"] = {"recommended": [], "not_recommended": []}

        # Use tony_omen as the baseline for the efficiency entry.
        baseline = stats.get("tony_omen", stats.get(list(HOSTS.keys())[0]))
        data_baseline["efficiency"]["commands"][command] = {
            "raw_words": baseline["raw_words"],
            "compact_words": baseline["compact_words"],
            "savings_pct": baseline["savings_pct"],
            "raw_chars": baseline["raw_chars"],
            "compact_chars": baseline["compact_chars"],
            "savings_pct_chars": baseline["savings_pct_chars"],
            "recommended": True,
        }

        commands = data_baseline["efficiency"]["commands"]
        data_baseline["workflow"]["recommended"] = [c for c, d in commands.items() if d.get("recommended")]
        data_baseline["workflow"]["not_recommended"] = [c for c, d in commands.items() if not d.get("recommended")]

        baseline_text = _replace_section(baseline_text, "efficiency", _section_yaml("efficiency", data_baseline["efficiency"]))
        baseline_text = _replace_section(baseline_text, "workflow", _section_yaml("workflow", data_baseline["workflow"]))
        with open(BASELINES, "w") as f:
            f.write(baseline_text)

        reload_config()
        result["added"] = True

    return result

def mcp_savings(hosts):
    if not hosts:
        hosts = list(HOSTS.keys())
    started = time.time()
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
            if s.get("ok"):
                per_host[host]["raw_chars"] += s["raw_chars"]
                per_host[host]["compact_chars"] += s["compact_chars"]
                per_host[host]["saved_chars"] += s["saved_chars"]
                total_raw += s["raw_chars"]
                total_compact += s["compact_chars"]
    saved = total_raw - total_compact
    pct = round(saved / total_raw * 100, 1) if total_raw > 0 else 0.0
    ended = time.time()
    raw_allowed = [
        {
            "prefix": p,
            "example": DEBUG_COMMANDS.get(p, {}).get("raw_command") or f"{p} ...",
            "category": RAW_CATEGORIES.get(p, "other"),
        }
        for p in RAW_PREFIXES
    ]
    recursive_tools = {"mcp_debug_audit", "mcp_savings", "mcp_preset_run", "mcp_preset_savings"}
    presets = []
    for name in sorted(PRESETS.keys()):
        steps = PRESETS[name].get("steps", [])
        if any(step.get("tool") in recursive_tools for step in steps):
            presets.append({
                "name": name,
                "description": PRESETS[name].get("description", ""),
                "n_steps": len(steps),
                "ok": False,
                "error": "recursive: skipped to avoid calling mcp_savings",
            })
            continue
        ps = mcp_preset_savings(name)
        presets.append({
            "name": name,
            "description": PRESETS[name].get("description", ""),
            "n_steps": ps.get("n_steps", 0),
            "ok": ps.get("ok", False),
            "raw_chars": ps.get("raw_chars", 0),
            "compact_chars": ps.get("compact_chars", 0),
            "preset_score": ps.get("preset_score", 0.0),
        })
    return {
        "ok": True,
        "timeframe": {
            "started": datetime.fromtimestamp(started).isoformat(),
            "ended": datetime.fromtimestamp(ended).isoformat(),
            "duration_ms": round((ended - started) * 1000, 1),
        },
        "hosts": per_host,
        "raw_allowed": raw_allowed,
        "presets": presets,
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


def mcp_adaptive(host, command):
    """Run compact and raw, returning whichever is smaller for the LLM payload."""
    raw_result = run_on_host(host, command, compact=False)
    compact_result = run_on_host(host, command, compact=True)

    if compact_result.get("ok") and raw_result.get("ok"):
        compact_len = len(compact_result.get("out", ""))
        raw_len = len(raw_result.get("out", ""))
        if compact_len <= raw_len:
            data = json.loads(compact_result.get("out", "") or "{}")
            data["h"] = host
            data["adaptive"] = "compact"
            return json.dumps(data, separators=(",", ":"))
        raw_result["h"] = host
        raw_result["adaptive"] = "raw"
        return json.dumps(raw_result, separators=(",", ":"))

    if compact_result.get("ok"):
        data = json.loads(compact_result.get("out", "") or "{}")
        data["h"] = host
        data["adaptive"] = "compact"
        return json.dumps(data, separators=(",", ":"))

    raw_result["h"] = host
    raw_result["adaptive"] = "raw_fallback"
    return json.dumps(raw_result, separators=(",", ":"))


def _file_max_bytes(requested):
    hard = FILE_LIMITS.get("max_bytes", {}).get("hard", 262144)
    default = FILE_LIMITS.get("max_bytes", {}).get("default", 65536)
    if requested is None:
        return default
    try:
        n = int(requested)
    except (TypeError, ValueError):
        return default
    return min(n, hard)


def _allowed_prefixes(host):
    return FILE_LIMITS.get("allowed_path_prefixes", {}).get(host, [])


def _normalize_path(path):
    if not path:
        return None
    path = os.path.expanduser(str(path))
    if not path.startswith("/"):
        path = os.path.abspath(path)
    return path


def _check_path_allowed(host, path):
    path = _normalize_path(path)
    if path is None:
        return None, "path is required"
    if ".." in path:
        return None, "path contains '..'"
    for prefix in _allowed_prefixes(host):
        expanded = _normalize_path(prefix)
        if not expanded:
            continue
        if path == expanded or path.startswith(expanded + "/"):
            return path, None
    return None, f"path not in allowed prefixes for {host}"


def _realpath_check(host, path):
    """Use readlink -f on the remote host to resolve symlinks; then vet the target."""
    real = run_on_host(host, f"readlink -f {shlex.quote(path)} || echo {shlex.quote(path)}", compact=False)
    if not real.get("ok") or not real.get("out"):
        return path
    resolved = real.get("out").strip().splitlines()[0]
    return _normalize_path(resolved) if resolved.startswith("/") else path


def mcp_get_file(host, path, max_bytes=None):
    if host not in HOSTS:
        return {"ok": False, "error": f"unknown host: {host}", "path": path}
    allowed, err = _check_path_allowed(host, path)
    if err:
        return {"ok": False, "error": err, "path": path}

    # Resolve symlinks and ensure the target is also allowed.
    real_path = _realpath_check(host, allowed)
    allowed, err = _check_path_allowed(host, real_path)
    if err:
        return {"ok": False, "error": err, "path": path}

    size = _file_max_bytes(max_bytes)
    # Check it is a regular file and get exact size before reading.
    stat = run_on_host(host, f"if [ -f {shlex.quote(allowed)} ]; then stat -c%s {shlex.quote(allowed)}; elif [ -d {shlex.quote(allowed)} ]; then echo 'dir'; else echo 'missing'; fi", compact=False, shell=True)
    if not stat.get("ok"):
        return {"ok": False, "error": stat.get("err", "stat failed"), "path": path}
    status = stat.get("out", "").strip()
    if status == "dir":
        return {"ok": False, "error": "path is a directory", "path": path}
    if status == "missing":
        return {"ok": False, "error": "file not found", "path": path}
    try:
        file_size = int(status)
    except ValueError:
        file_size = size

    read_size = min(file_size, size)
    base64_cmd = f"head -c {read_size} {shlex.quote(allowed)} | base64 -w0 2>/dev/null || head -c {read_size} {shlex.quote(allowed)} | base64"
    result = run_on_host(host, base64_cmd, compact=False, shell=True)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("err", "read failed"), "path": path}
    b64 = result.get("out", "").strip()
    try:
        decoded = base64.b64decode(b64)
    except Exception as e:
        return {"ok": False, "error": f"base64 decode failed: {e}", "path": path}
    return {
        "ok": True,
        "path": allowed,
        "size": len(decoded),
        "truncated": file_size > size,
        "encoding": "base64",
        "content_base64": b64,
    }


def mcp_put_file(host, path, content_base64, mode="644", overwrite=False):
    if host not in HOSTS:
        return {"ok": False, "error": f"unknown host: {host}", "path": path}
    allowed, err = _check_path_allowed(host, path)
    if err:
        return {"ok": False, "error": err, "path": path}

    target_dir = os.path.dirname(allowed) or "/"
    dir_check = run_on_host(host, f"test -d {shlex.quote(target_dir)} && readlink -f {shlex.quote(target_dir)}", compact=False, shell=True)
    if not dir_check.get("ok") or not dir_check.get("out"):
        return {"ok": False, "error": "target directory does not exist or is not allowed", "path": path}
    real_dir = _normalize_path(dir_check.get("out").strip().splitlines()[0])
    if _check_path_allowed(host, real_dir)[1]:
        return {"ok": False, "error": "resolved target directory is not in allowed prefixes", "path": path}

    if not overwrite:
        exists = run_on_host(host, f"test -e {shlex.quote(allowed)} && echo yes || echo no", compact=False, shell=True)
        if exists.get("ok") and exists.get("out", "").strip() == "yes":
            return {"ok": False, "error": "file exists and overwrite=false", "path": allowed}

    try:
        data = base64.b64decode(content_base64)
    except Exception as e:
        return {"ok": False, "error": f"invalid content_base64: {e}", "path": path}

    b64 = base64.b64encode(data).decode()
    max_arg = 200000
    if len(b64) > max_arg:
        return {"ok": False, "error": f"payload exceeds safe ssh argument size ({max_arg})", "path": path}

    temp = f"/tmp/mcp-put-{host}-{int(time.time() * 1000)}.tmp"
    script = (
        f"echo {shlex.quote(b64)} | base64 -d > {shlex.quote(temp)} && "
        f"chmod {shlex.quote(str(mode))} {shlex.quote(temp)} && "
        f"mv -f {shlex.quote(temp)} {shlex.quote(allowed)}"
    )
    result = run_on_host(host, script, compact=False, shell=True)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("err", "write failed"), "path": allowed}
    return {
        "ok": True,
        "path": allowed,
        "bytes_written": len(data),
        "mode": mode,
    }


def _clipboard_enabled(host):
    return HOSTS.get(host, {}).get(
        "clipboard",
        FILE_LIMITS.get("clipboard", {}).get(host, False),
    )


def mcp_clipboard_get(host):
    if host not in HOSTS:
        return {"ok": False, "error": f"unknown host: {host}", "host": host}
    if not _clipboard_enabled(host):
        return {"ok": False, "error": "clipboard not enabled for this host", "host": host}

    cmd = (
        "set -o pipefail; "
        "( pbpaste 2>/dev/null | base64 | tr -d '\\n' ) 2>/dev/null || "
        "( [ -n \"$DISPLAY\" ] && timeout -k 1 2 xclip -o -selection clipboard 2>/dev/null | base64 | tr -d '\\n' ) 2>/dev/null || "
        "( [ -n \"$DISPLAY\" ] && timeout -k 1 2 xsel -b 2>/dev/null | base64 | tr -d '\\n' ) 2>/dev/null || "
        "( [ -n \"$WAYLAND_DISPLAY\" ] && timeout -k 1 2 wl-paste 2>/dev/null | base64 | tr -d '\\n' ) 2>/dev/null || "
        "echo CLIPBOARD_UNAVAILABLE"
    )
    result = run_on_host(host, cmd, compact=False, shell=True)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("err", "clipboard read failed"), "host": host}
    b64 = result.get("out", "").strip()
    if b64 == "CLIPBOARD_UNAVAILABLE":
        return {"ok": False, "error": "no clipboard tool found on host", "host": host}
    try:
        text = base64.b64decode(b64).decode("utf-8", "replace")
    except Exception as e:
        return {"ok": False, "error": f"clipboard decode failed: {e}", "host": host}
    return {"ok": True, "text": text, "host": host}


def mcp_clipboard_set(host, text):
    if host not in HOSTS:
        return {"ok": False, "error": f"unknown host: {host}", "host": host}
    if not _clipboard_enabled(host):
        return {"ok": False, "error": "clipboard not enabled for this host", "host": host}

    try:
        b64 = base64.b64encode(text.encode("utf-8")).decode()
    except Exception as e:
        return {"ok": False, "error": f"text encoding failed: {e}", "host": host}

    max_arg = 200000
    if len(b64) > max_arg:
        return {"ok": False, "error": f"clipboard payload exceeds safe ssh argument size ({max_arg})", "host": host}

    cmd = (
        "set -o pipefail; "
        "DATA=$(printf '%s' " + shlex.quote(b64) + " | base64 -d); "
        "( printf '%s' \"$DATA\" | pbcopy ) 2>/dev/null || "
        "( [ -n \"$DISPLAY\" ] && printf '%s' \"$DATA\" | timeout -k 1 2 xclip -selection clipboard ) 2>/dev/null || "
        "( [ -n \"$DISPLAY\" ] && printf '%s' \"$DATA\" | timeout -k 1 2 xsel -b ) 2>/dev/null || "
        "( [ -n \"$WAYLAND_DISPLAY\" ] && printf '%s' \"$DATA\" | timeout -k 1 2 wl-copy ) 2>/dev/null || "
        "{ echo CLIPBOARD_UNAVAILABLE; exit 1; }"
    )
    result = run_on_host(host, cmd, compact=False, shell=True)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("err", "clipboard write failed"), "host": host}
    return {"ok": True, "bytes_written": len(text.encode("utf-8")), "host": host}

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
    captured = {}
    all_ok = True
    for step in steps:
        host = step.get("host")
        tool = step.get("tool")
        command = step.get("command")
        if not tool:
            results.append({"ok": False, "error": "step missing tool", "step": step})
            all_ok = False
            continue
        if tool not in ("mcp_diff", "mcp_debug_audit", "mcp_transform") and not host:
            results.append({"ok": False, "error": "step missing host", "step": step})
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
        elif tool == "mcp_diff":
            if not command:
                results.append({"ok": False, "error": "mcp_diff step missing command", "step": step})
                all_ok = False
                continue
            hosts = step.get("hosts", [])
            if len(hosts) != 2:
                results.append({"ok": False, "error": "mcp_diff step requires exactly 2 hosts", "step": step})
                all_ok = False
                continue
            r = mcp_diff(command, hosts, step.get("compact", True))
            results.append(r)
            if not r.get("ok"):
                all_ok = False
        elif tool == "mcp_debug_audit":
            r = mcp_debug_audit(hosts=step.get("hosts"), threshold=float(step.get("threshold", 0.0)))
            results.append(r)
            if not r.get("ok"):
                all_ok = False
        elif tool == "mcp_system":
            if not command:
                results.append({"ok": False, "error": "mcp_system step missing command", "step": step})
                all_ok = False
                continue
            r = json.loads(mcp_system(host, command))
            results.append(r)
            if not r.get("ok"):
                all_ok = False
        elif tool == "mcp_transform":
            r = mcp_transform(
                input=step.get("input"),
                op=step.get("op", "identity"),
                params=step.get("params", {}),
                results=results,
                captured=captured,
            )
            if r.get("ok") and r.get("captured"):
                captured.update(r.get("captured"))
            results.append(r)
            if not r.get("ok"):
                all_ok = False
        else:
            results.append({"ok": False, "error": f"unsupported tool: {tool}", "step": step})
            all_ok = False
    return {
        "ok": all_ok,
        "preset": name,
        "description": preset.get("description", ""),
        "results": results,
    }


def mcp_debug_audit(hosts=None, threshold=0.0):
    """Fetch the live mcp_savings report and return only negative/failed commands, sorted by savings."""
    if hosts is None:
        hosts = list(HOSTS.keys())
    report = mcp_savings(hosts)
    if not report.get("ok"):
        return report
    flagged = []
    for h, hd in report.get("hosts", {}).items():
        for c, cd in hd.get("commands", {}).items():
            pct = cd.get("savings_pct_chars", 0)
            if not cd.get("ok") or pct < threshold:
                flagged.append({
                    "h": h,
                    "c": c,
                    "ok": cd.get("ok"),
                    "pct": pct,
                    "raw": cd.get("raw_chars"),
                    "compact": cd.get("compact_chars"),
                })
    flagged.sort(key=lambda x: (0 if not x["ok"] else 1, x["pct"]))
    raw_full = json.dumps(report, separators=(",", ":"))
    compact = json.dumps({"ok": True, "threshold": threshold, "n": len(flagged), "f": flagged}, separators=(",", ":"))
    return {
        "ok": True,
        "threshold": threshold,
        "n_total": sum(len(hd.get("commands", {})) for hd in report.get("hosts", {}).values()),
        "n_flagged": len(flagged),
        "f": flagged,
        "raw_chars": len(raw_full),
        "compact_chars": len(compact),
        "savings_pct_chars": round((len(raw_full) - len(compact)) / len(raw_full) * 100, 1) if raw_full else 0.0,
    }


from .registry import mcp_registry_lookup as mcp_ssot_query, mcp_registry_get as mcp_ssot_get


def mcp_preset_savings(name):
    """Compare running a preset as one call vs running each step as a separate MCP tool call."""
    if name not in PRESETS:
        return {"ok": False, "error": f"unknown preset: {name}", "available_presets": list(PRESETS.keys())}
    preset = PRESETS[name]
    steps = preset.get("steps", [])
    compact_result = mcp_preset_run(name)
    if not compact_result.get("ok") and not compact_result.get("results"):
        return compact_result
    compact_text = json.dumps(compact_result, separators=(",", ":"), default=str)
    step_results = compact_result.get("results", [])
    step_texts = [json.dumps(r, separators=(",", ":"), default=str) for r in step_results]
    step_data = sum(len(t) for t in step_texts)
    per_step_overhead = 80
    raw_text = (len(steps) * per_step_overhead) + step_data
    n_steps = len(steps) if steps else 1
    message_savings_pct = round((1 - (2 / (2 * n_steps))) * 100, 1)
    payload_savings_pct = round((1 - len(compact_text) / raw_text) * 100, 1) if raw_text > 0 else 0.0
    combined_score = round(0.6 * message_savings_pct + 0.4 * payload_savings_pct, 1)
    return {
        "ok": True,
        "preset": name,
        "n_steps": n_steps,
        "raw_chars": raw_text,
        "compact_chars": len(compact_text),
        "message_savings_pct": message_savings_pct,
        "payload_savings_pct": payload_savings_pct,
        "preset_score": combined_score,
    }

