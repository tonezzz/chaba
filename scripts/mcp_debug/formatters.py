"""Compact-to-table formatters for mcp_debug output."""
import csv
import io
import json
import time
from datetime import datetime
from .config import DEBUG_COMMANDS, TABLE_SCHEMAS, logger


def _lookup_schema(command):
    meta = DEBUG_COMMANDS.get(command, {})
    expected = meta.get("expected_output", "auto")
    return expected, TABLE_SCHEMAS.get(expected)


def _array_key(data, schema):
    key = schema.get("array_key")
    if key:
        return data.get(key)
    for k, v in data.items():
        if isinstance(v, list):
            return v
    return None


def to_csv(command, data):
    """Return CSV string with header for a table command, or a dict with error."""
    if not data.get("ok"):
        return {"ok": False, "error": data.get("error", "command failed"), "command": command}

    expected, schema = _lookup_schema(command)
    if not schema:
        return {"ok": False, "error": f"no table schema for {command} (expected_output={expected})"}

    rows = _array_key(data, schema)
    if rows is None:
        return {"ok": False, "error": f"no table array found for {command}"}
    if not isinstance(rows, list):
        return {"ok": False, "error": f"compact output for {command} is not a list"}

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(schema["headers"])
    fields = schema["fields"]
    for row in rows:
        writer.writerow([row.get(f, "") for f in fields])

    return {"ok": True, "csv": out.getvalue(), "command": command, "expected": expected}


def to_envelope(command, data):
    """Return the proxy_envelope JSON dict for a table command."""
    result = to_csv(command, data)
    if not result.get("ok"):
        return result

    csv_text = result["csv"].strip()
    if not csv_text:
        return {"ok": True, "headers": [], "rows": [], "command": command}

    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return {"ok": True, "headers": [], "rows": [], "command": command}

    return {
        "ok": True,
        "headers": rows[0],
        "rows": rows[1:],
        "command": command,
    }


def mcp_table(host, command):
    """Run a compact debug command on a host and return a proxy_envelope table."""
    from .tools import mcp_debug

    start = time.perf_counter()
    try:
        raw = mcp_debug(host, command)
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"invalid compact JSON: {e}", "command": command, "host": host}
    except Exception as e:
        return {"ok": False, "error": str(e), "command": command, "host": host}
    duration_ms = (time.perf_counter() - start) * 1000

    envelope = to_envelope(command, data)
    envelope["host"] = host
    envelope["freshness"] = {
        "collected_at": datetime.now().isoformat(),
        "duration_ms": round(duration_ms, 2),
        "cache_age_ms": 0,
    }
    return envelope
