#!/usr/bin/env python3
"""Promote overnight/optimization reports into focus-inbox drafts for triage."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
INBOX_DIR = REPO / "docs" / "ssot" / "focus-inbox"
REPORTS_DIR = REPO / "reports"

sys.path.insert(0, str(REPO / "scripts"))
import events


def slugify(text):
    return re.sub(r"[^a-z0-9_-]", "", text.lower().replace(" ", "-").replace("/", "-"))[:40]


def make_inbox_path(prefix):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    return INBOX_DIR / f"{ts}-{prefix}.yml"


def write_draft(path, label, text, subtasks, tags, source_file, triage_score=0.5):
    INBOX_DIR.mkdir(exist_ok=True)
    indented_text = text.replace("\n", "\n    ")
    subtask_lines = "\n".join(f"    - label: {json.dumps(s)}" for s in subtasks)
    body = f"""title: Focus Inbox Item
subtitle: Auto-drafted from {source_file}
icon: inbox

focus:
  label: {json.dumps(label)}
  text: |
    {indented_text}
  branch: chaba
  priority: medium
  status: draft
  triage_score: {triage_score}
  tags: {json.dumps(tags)}
  safe_to_parallel:
    value: true
    reason: Report-generated item; can be triaged independently.
  subtasks:
{subtask_lines}

ownership:
  owner: tony
  session: ""
  locked: false
  lock_reason: ""

source:
  session: ""
  date: '{datetime.now(timezone.utc).strftime("%Y-%m-%d")}'
"""
    path.write_text(body, encoding="utf-8")
    print(f"Drafted: {path}")


def promote_service_errors():
    path = REPORTS_DIR / "SERVICE_ERRORS.json"
    if not path.exists():
        return
    data = json.loads(path.read_text())
    if not data.get("services_with_errors"):
        return
    services = data.get("services_with_errors", 0)
    occurrences = data.get("total_error_occurrences", 0)
    top = data.get("top_error_patterns", [])[:3]
    text = f"{services} service(s) logged {occurrences} error pattern(s).\n"
    text += "Source: reports/SERVICE_ERRORS.json\n"
    if top:
        text += "Top patterns:\n"
        for p in top:
            text += f"- {p.get('count', '?')}x {p.get('pattern', '')}\n"
    subtasks = [
        f"Review reports/SERVICE_ERRORS.md",
        f"Triage top error pattern: {top[0]['pattern'] if top else 'unknown'}",
        f"Schedule fixes or restarts",
    ]
    out = make_inbox_path("service-log-errors")
    write_draft(out, "Service log errors from overnight sweep", text, subtasks, ["overnight", "logs", "errors"], "reports/SERVICE_ERRORS.json", triage_score=0.8)


def promote_dev_system():
    path = REPORTS_DIR / "DEV_SYSTEM_ASSESSMENT.json"
    if not path.exists():
        return
    data = json.loads(path.read_text())
    open_cons = [c for c in data.get("cons", []) if c.get("status") == "open" and c.get("severity") in ("high", "medium")]
    if not open_cons:
        return
    text = f"Dev-system trend is {data.get('trend', 'unknown')}. Open cons:\n"
    for c in open_cons:
        text += f"- {c['label']} ({c['severity']}): {c['evidence']}\n"
    text += "Source: reports/DEV_SYSTEM_ASSESSMENT.json\n"
    subtasks = [
        f"Review reports/DEV_SYSTEM_ASSESSMENT.md",
        f"Address highest severity con: {open_cons[0]['label']}",
        f"Update docs/ssot/ssot.dev-system.assessment.yml when resolved",
    ]
    out = make_inbox_path("dev-system-regression")
    write_draft(out, "Dev-system regression", text, subtasks, ["dev-system", "assessment"], "reports/DEV_SYSTEM_ASSESSMENT.json", triage_score=0.6)


def promote_ssot_optimization():
    path = REPORTS_DIR / "SSOT_OPTIMIZATION_METRICS.json"
    if not path.exists():
        return
    data = json.loads(path.read_text())
    issues = []
    for key in ["bloat", "data_isolation", "other"]:
        if data.get(key, 0) > 0:
            issues.append(f"{key}: {data[key]}")
    logs = data.get("logs", {})
    if logs.get("issues", 0) > 0:
        issues.append(f"log issues: {logs['issues']}")
    if not issues:
        return
    text = "SSOT optimization detected issues:\n" + "\n".join(f"- {i}" for i in issues)
    text += "\nSource: reports/SSOT_OPTIMIZATION_METRICS.json\n"
    subtasks = ["Open reports/SSOT_OPTIMIZATION_SUGGESTIONS.md", "Fix highest priority warning", "Re-run ssot-validate-all"]
    out = make_inbox_path("ssot-optimization-issues")
    write_draft(out, "SSOT optimization warnings", text, subtasks, ["ssot", "optimization"], "reports/SSOT_OPTIMIZATION_METRICS.json", triage_score=0.4)


def promote_events():
    evs = events.get_events(limit=50, severity="error")
    if not evs:
        return
    by_type = {}
    for e in evs:
        by_type.setdefault(e["type"], 0)
        by_type[e["type"]] += 1
    text = "Orchestration events with error severity:\n"
    for t, c in by_type.items():
        text += f"- {c}x {t}\n"
    text += "Source: reports/EVENTS.jsonl\n"
    subtasks = ["Open reports/EVENTS.jsonl", "Identify repeating failure source", "Run or schedule remediation"]
    out = make_inbox_path("orchestration-errors")
    write_draft(out, "Orchestration errors", text, subtasks, ["orchestration", "events"], "reports/EVENTS.jsonl", triage_score=0.7)


def main():
    promote_service_errors()
    promote_dev_system()
    promote_events()
    promote_ssot_optimization()


if __name__ == "__main__":
    main()
