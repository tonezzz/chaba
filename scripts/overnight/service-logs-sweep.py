#!/usr/bin/env python3
"""Overnight sweep of recent systemd logs for all services and emit error report."""

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SSOT_DIR = REPO / "docs" / "ssot" / "infrastructure"
REPORTS_DIR = REPO / "reports"

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: pip install pyyaml")

sys.path.insert(0, str(REPO / "scripts" / "mcp_debug"))
from tools import mcp_logs


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def collect_units():
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
                    "category": item.get("category", ""),
                })
    return units


def check_service(u, lines=50):
    try:
        res = mcp_logs(u["host"], unit=u["service"], lines=lines)
        text = res.get("out", "")
        if res.get("error"):
            text += "\n" + str(res["error"])
        hits = []
        for line in text.splitlines():
            if re.search(r"\b(error|fail|fatal|exception|traceback)\b", line, re.I):
                hits.append(line.strip())
        return {
            **u,
            "ok": res.get("ok", False),
            "chars": len(text),
            "error_count": len(hits),
            "sample_errors": hits[:5],
        }
    except Exception as e:
        return {**u, "ok": False, "error_count": 0, "sample_errors": [str(e)]}


def main():
    units = collect_units()
    results = [check_service(u) for u in units]
    total_errors = sum(r["error_count"] for r in results)
    errored = [r for r in results if r["error_count"] > 0 or not r["ok"]]
    top_errors = Counter(
        re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S*\s*", "", e)
        for r in errored for e in r["sample_errors"]
    ).most_common(10)

    REPORTS_DIR.mkdir(exist_ok=True)
    json_path = REPORTS_DIR / "SERVICE_ERRORS.json"
    md_path = REPORTS_DIR / "SERVICE_ERRORS.md"
    now = datetime.now(timezone.utc).isoformat()

    out = {
        "ok": len(errored) == 0,
        "timestamp": now,
        "services_checked": len(units),
        "services_with_errors": len(errored),
        "total_error_occurrences": total_errors,
        "top_error_patterns": [dict(p) for p in top_errors],
        "results": results,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Service Log Error Sweep\n\n")
        f.write(f"- Generated: {now}\n")
        f.write(f"- Services checked: {len(units)}\n")
        f.write(f"- Services with issues: {len(errored)}\n")
        f.write(f"- Total error occurrences: {total_errors}\n\n")
        if top_errors:
            f.write("## Top error patterns\n\n")
            for pattern, count in top_errors:
                f.write(f"- {count}x: `{pattern}`\n")
            f.write("\n")
        if errored:
            f.write("## Services with errors\n\n")
            for r in errored:
                f.write(f"### {r['name']} ({r['host']}:{r['service']})\n")
                f.write(f"- errors: {r['error_count']}, chars: {r['chars']}, ok: {r['ok']}\n")
                if r["sample_errors"]:
                    f.write("```\n")
                    for line in r["sample_errors"][:5]:
                        f.write(f"{line}\n")
                    f.write("```\n\n")
        else:
            f.write("No service log errors detected.\n")

    print(f"Checked {len(units)} services, {len(errored)} with errors, {total_errors} occurrences.")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")


if __name__ == "__main__":
    main()
