#!/usr/bin/env python3
"""Create focus-inbox drafts from mcp-health status for later triage."""
import argparse
import json
import re
import subprocess
import sys
import yaml
from datetime import datetime
from pathlib import Path

REPO = Path("/home/tony/CascadeProjects/chaba")
CLIENT = REPO / "scripts" / "mcp-health-client.py"
INBOX_DIR = REPO / "docs" / "ssot" / "focus-inbox"
HEALTH_SSOT = REPO / "docs" / "ssot" / "infrastructure" / "ssot.health.yml"


def load_health_config():
    with open(HEALTH_SSOT) as f:
        return yaml.safe_load(f) or {}


def service_key(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_criticality_map():
    cfg = load_health_config()
    crit = cfg.get("alerts", {}).get("service_criticality", {})
    mapping = {}
    for level, services in crit.items():
        for s in services:
            mapping[s] = level
    return mapping


def get_health_status():
    result = subprocess.run(
        [sys.executable, str(CLIENT), "get_health_status"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "mcp-health-client failed")
    return json.loads(result.stdout)


def flatten_services(data):
    by_cat = data.get("services_by_category", {})
    services = []
    for cat, items in by_cat.items():
        for it in items:
            it["category"] = cat
            services.append(it)
    return services


def is_actionable(status):
    return status in ("unknown", "error", "degraded", "failed")


def priority_for(service, status, crit_map):
    crit = crit_map.get(service_key(service), "optional")
    if status in ("error", "failed") or (status == "unknown" and crit == "critical"):
        return "high"
    if status == "degraded" or (status == "unknown" and crit == "important"):
        return "medium"
    return "low"


def existing_inbox_for(service):
    stem = service_key(service)
    for p in INBOX_DIR.glob("*.yml"):
        if p.name.startswith("TEMPLATE") or p.name.startswith("processed"):
            continue
        if p.name.endswith("-health.yml") and stem in p.name:
            return p
    return None


def make_inbox_item(service, status, error, criticality, priority):
    now = datetime.now().isoformat(timespec="seconds")
    text = f"mcp-health reported status '{status}' for {service} at {now}."
    if error:
        text += f" Error: {error}"
    return {
        "title": "Focus Inbox Item",
        "subtitle": f"Health alert for {service}",
        "focus": {
            "label": f"{service} health",
            "text": text,
            "status": "draft",
            "priority": priority,
            "tags": ["health", "inbox", criticality],
            "missing_info": [
                "Is this a hard failure or transient?",
                "Which other systems depend on this service?",
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    crit_map = load_criticality_map()
    data = get_health_status()
    services = flatten_services(data)

    created = 0
    for s in services:
        name = s.get("service")
        status = s.get("status")
        if not is_actionable(status):
            continue
        crit = crit_map.get(service_key(name), "optional")
        if crit == "optional" and status == "unknown":
            continue
        priority = priority_for(name, status, crit_map)
        existing = existing_inbox_for(name)
        if existing:
            print(f"skip {name}: existing {existing}")
            continue

        item = make_inbox_item(name, status, s.get("error"), crit, priority)
        filename = f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}-{service_key(name)}-health.yml"
        path = INBOX_DIR / filename

        if args.dry_run:
            print(f"would create {path} for {name} ({status}, {crit}, {priority})")
        else:
            path.write_text(
                yaml.safe_dump(
                    item,
                    sort_keys=False,
                    allow_unicode=True,
                    width=120,
                    default_flow_style=False,
                )
            )
            print(f"created {path} for {name} ({status}, {crit}, {priority})")
        created += 1

    print(f"{'would create' if args.dry_run else 'created'} {created} inbox item(s)")


if __name__ == "__main__":
    main()
