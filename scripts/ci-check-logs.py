#!/usr/bin/env python3
"""Validate log and systemd unit references in SSOT, and optionally fetch recent logs."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: pip install pyyaml")

REPO = Path(__file__).resolve().parent.parent
SSOT_DIR = REPO / "docs" / "ssot" / "infrastructure"
REPORTS_DIR = REPO / "reports"


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def collect_health_units():
    units = []
    home = load_yaml(SSOT_DIR / "ssot.health.home.yml")
    for cat in home.get("categories", []):
        cat_file = REPO / cat.get("file", "")
        if not cat_file.exists():
            continue
        data = load_yaml(cat_file)
        for item in data.get("services", []):
            if item.get("type") == "systemd" and item.get("service"):
                units.append({
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "host": item.get("host", "tony_omen"),
                    "service": item["service"],
                    "source": str(cat_file.relative_to(REPO)),
                })
    return units


def collect_automation_logs():
    data = load_yaml(SSOT_DIR / "ssot.automation.yml")
    logs = []
    for key, item in data.get("automation", {}).items():
        if item.get("log_file"):
            logs.append({
                "id": key,
                "log_file": item["log_file"],
                "source": "docs/ssot/infrastructure/ssot.automation.yml",
            })
    for key, item in data.get("data_locations", {}).items():
        for subkey in ["usage_log", "alert_log", "maintenance_log", "automation_log", "log"]:
            if item.get(subkey):
                logs.append({
                    "id": f"{key}.{subkey}",
                    "log_file": item[subkey],
                    "source": "docs/ssot/infrastructure/ssot.automation.yml",
                })
    return logs


def validate(units, logs):
    issues = []
    for u in units:
        if not u["service"] or re.search(r"\s", u["service"]):
            issues.append({"type": "invalid_service", **u})
    for l in logs:
        p = l["log_file"]
        if not p:
            issues.append({"type": "empty_log_file", **l})
        elif p.startswith("/") and not p.startswith(("/var/log/", "/home/", REPO.as_posix())):
            issues.append({"type": "unexpected_absolute_path", **l})
    return issues


def fetch_logs_for_units(units, lines=20):
    try:
        sys.path.insert(0, str(REPO / "scripts" / "mcp_debug"))
        from tools import mcp_logs
    except Exception as e:
        print(f"Cannot import mcp_debug tools: {e}", file=sys.stderr)
        return []

    results = []
    for u in units[:20]:
        try:
            res = mcp_logs(u["host"], unit=u["service"], lines=lines)
            text = res.get("out", "") + res.get("error", "")
            bad = any(w in text.lower() for w in ["error", "failed", "fatal"])
            results.append({
                **u,
                "ok": res.get("ok", False),
                "has_error_keywords": bad,
                "chars": len(text),
            })
        except Exception as e:
            results.append({**u, "ok": False, "error": str(e)})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true", help="Only validate SSOT references, do not fetch logs.")
    parser.add_argument("--lines", type=int, default=20)
    parser.add_argument("--output", default="reports/LOG_CHECK.json")
    args = parser.parse_args()

    units = collect_health_units()
    logs = collect_automation_logs()
    issues = validate(units, logs)
    fetched = [] if args.check_only else fetch_logs_for_units(units, args.lines)

    REPORTS_DIR.mkdir(exist_ok=True)
    out = {
        "ok": len(issues) == 0,
        "timestamp": None,
        "check_only": args.check_only,
        "units": units,
        "log_files": logs,
        "issues": issues,
        "fetched": fetched,
    }
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = REPO / out_path
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)

    print(f"Units: {len(units)}, Log files: {len(logs)}, Issues: {len(issues)}, Fetched: {len(fetched)}")
    for i in issues:
        print(f"  {i['type']}: {i}")
    if issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
