#!/usr/bin/env python3
"""Regenerate ssot.health.home.apps.yml from stacks/web/public/apps/apps.yml."""
import yaml
from pathlib import Path

REPO = Path.home() / "CascadeProjects" / "chaba"
APPS_YML = REPO / "stacks" / "web" / "public" / "apps" / "apps.yml"
OUT_YML = REPO / "docs" / "ssot" / "infrastructure" / "ssot.health.home.apps.yml"
BASE_URL = "https://tony-dell.taila0626a.ts.net"


def main():
    data = yaml.safe_load(APPS_YML.read_text())
    services = []
    for app in data.get("apps", []):
        services.append(
            {
                "id": f"app-{app['id']}",
                "name": app["title"],
                "type": "http",
                "url": f"{BASE_URL}{app['href']}",
                "expected_status": 200,
                "timeout": 5,
                "category": "apps",
                "profiles": ["home", "mobile"],
                "host": "tony_dell",
                "note": f"Auto-generated from {APPS_YML.relative_to(REPO)}",
            }
        )

    out = {
        "title": "Chaba Health Checks (Home Profile) — Apps",
        "subtitle": "HTTP health checks for web apps, generated from apps.yml",
        "icon": "heart-pulse",
        "services": services,
    }

    OUT_YML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_YML, "w") as f:
        yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True)
    print(f"Wrote {len(services)} app health checks to {OUT_YML}")


if __name__ == "__main__":
    main()
