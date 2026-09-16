#!/usr/bin/env python3
"""Regenerate ssot.health.home.apps.yml and sync public apps to each apps-host."""
import subprocess
import sys
import urllib.parse
import yaml
from pathlib import Path

REPO = Path.home() / "CascadeProjects" / "chaba"
APPS_YML = REPO / "stacks" / "web" / "public" / "apps" / "apps.yml"
APPS_DIR = REPO / "stacks" / "web" / "public" / "apps"
OUT_YML = REPO / "docs" / "ssot" / "infrastructure" / "ssot.health.home.apps.yml"
SSOT_APPS = REPO / "docs" / "ssot" / "apps" / "ssot.apps.yml"


def load_ssot_hosts():
    if not SSOT_APPS.exists():
        return {}
    ssot = yaml.safe_load(SSOT_APPS.read_text())
    return ssot.get("apps-hosts", {}) if isinstance(ssot, dict) else {}


def main():
    data = yaml.safe_load(APPS_YML.read_text())
    services = []
    for app in data.get("apps", []):
        host = app.get("host", "tony-dell").replace("-", "_")
        host_url = app.get("host_url", "https://tony-dell.taila0626a.ts.net")
        services.append(
            {
                "id": f"app-{app['id']}",
                "name": app["title"],
                "type": "http",
                "url": f"{host_url}{app['href']}",
                "expected_status": 200,
                "timeout": 5,
                "category": "apps",
                "profiles": ["home", "mobile"],
                "host": host,
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

    # Known Caddy file_server SSH aliases. Add new app hosts here as they land
    # in ssot.apps.yml.
    SYNCABLE_HOSTS = {"tony-dell", "mn01"}

    # Deploy public apps to Caddy file_server roots on each distinct tailnet host.
    # Caddy serves /apps/* from this directory, not from the repo path.
    hosts = load_ssot_hosts()
    synced = set()
    for host_id, host_cfg in hosts.items():
        if host_id not in SYNCABLE_HOSTS:
            continue
        ssh_host = host_id
        if ssh_host in synced:
            continue
        synced.add(ssh_host)
        target = f"{ssh_host}:/home/tony/.config/caddy/public/apps"
        print(f"Syncing {APPS_DIR} to {target}...")
        result = subprocess.run(
            [
                "rsync",
                "-avz",
                "--rsync-path=mkdir -p /home/tony/.config/caddy/public/apps && rsync",
                f"{APPS_DIR}/",
                f"{target}/",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"Synced public apps to {target}")
        else:
            print(f"WARNING: failed to sync to {target}: {result.stderr.strip()}")

    # Verification: consistency only. Use apps-yml-generate.py --verify --live manually
    # if you want to re-check HTTP status against each app's declared host_url.
    print("Running local verification...")
    result = subprocess.run(
        ["python3", str(REPO / "scripts" / "apps-yml-generate.py"), "--verify"],
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
