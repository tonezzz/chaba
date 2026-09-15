#!/usr/bin/env python3
"""Regenerate ssot.health.home.apps.yml and sync public apps to tony-dell."""
import subprocess
import sys
import yaml
from pathlib import Path

REPO = Path.home() / "CascadeProjects" / "chaba"
APPS_YML = REPO / "stacks" / "web" / "public" / "apps" / "apps.yml"
APPS_DIR = REPO / "stacks" / "web" / "public" / "apps"
OUT_YML = REPO / "docs" / "ssot" / "infrastructure" / "ssot.health.home.apps.yml"
BASE_URL = "https://tony-dell.taila0626a.ts.net"
CADDY_APPS_DIR = "tony-dell:/home/tony/.config/caddy/public/apps"


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

    # Deploy public apps to tony-dell Caddy file_server root.
    # Caddy serves /apps/* from this directory, not from the repo path.
    print(f"Syncing {APPS_DIR} to {CADDY_APPS_DIR}...")
    subprocess.run(
        [
            "rsync",
            "-avz",
            "--rsync-path=mkdir -p /home/tony/.config/caddy/public/apps && rsync",
            f"{APPS_DIR}/",
            f"{CADDY_APPS_DIR}/",
        ],
        check=True,
    )
    print(f"Synced public apps to {CADDY_APPS_DIR}")

    # Auto-verification: every app in apps.yml must return 200 from tony-dell.
    print("Running live verification...")
    result = subprocess.run(
        ["python3", str(REPO / "scripts" / "apps-yml-generate.py"), "--verify", "--live"],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print("Live verification found failures; see above.", file=sys.stderr)
    else:
        print("Live verification passed.")


if __name__ == "__main__":
    main()
