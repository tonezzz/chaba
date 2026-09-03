#!/usr/bin/env python3
"""playlive-hosts-loader — read playlive-hosts.yml and exec the MCP server.

The SSOT YAML file lives in the repo under:
  /home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/playlive-hosts.yml

It converts the YAML host registry into the JSON PLAYLIVE_HOSTS env var that
playlive-server.py expects, then os.execv's the real server.

Per-host behaviour:
  - On tony-dell, prefer the local playlived (127.0.0.1:9230), with tony-omen
    as the failover.
  - On tony-omen, prefer the tony-dell playlived (tony-dell:9230), falling back
    to the local tony-omen playlived (127.0.0.1:9230).

If the chosen playlived is not reachable and self_heal is enabled in the YAML,
the loader attempts a host-specific systemd restart.  If the primary cannot be
recovered, the loader tries the failover URL.  If neither the primary nor the
failover is reachable and focus is enabled, it drops a focus-inbox item and
continues to start the server.
"""
import datetime
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

# For the repo copy of this script, derive defaults from the script's location.
# When installed to ~/.config/devin/mcp-scripts, PLAYLIVE_HOSTS_FILE is set
# and the server path is computed from that file, so these fallbacks are not used.
_DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_HOSTS_FILE = str(_DEFAULT_REPO / "docs" / "ssot" / "infrastructure" / "playlive-hosts.yml")


def server_path(hosts_file: str) -> str:
    """Derive the path to playlive-server.py from the host registry YAML path."""
    # hosts_file: .../<repo>/docs/ssot/infrastructure/playlive-hosts.yml
    repo = Path(hosts_file).resolve().parents[3]
    return str(repo / "mcp-servers" / "mcp-playlive" / "playlive-server.py")


def current_host() -> str:
    return socket.gethostname().lower().replace("-", "_").split(".")[0]


def load_hosts_data(hosts_file: str) -> dict:
    with open(hosts_file) as f:
        return yaml.safe_load(f)


def focus_already_flagged(window: int = 3600) -> bool:
    """Return True if a playlive self-heal focus item was already written recently."""
    lock_path = "/home/tony/.cache/playlive-focus-flag"
    try:
        with open(lock_path) as f:
            last = float(f.read().strip())
        return (time.time() - last) < window
    except (FileNotFoundError, ValueError):
        return False


def update_focus_lock():
    lock_path = "/home/tony/.cache/playlive-focus-flag"
    try:
        with open(lock_path, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def write_focus_item(inbox_dir: str, host: str, playlive_url: str, error: str, labels: list[str] | None = None):
    if focus_already_flagged():
        return
    try:
        os.makedirs(inbox_dir, exist_ok=True)
    except OSError:
        return
    tags = ["playlive", "infrastructure", "self-heal"]
    if labels:
        tags.extend(labels)
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d-%H%M%S")
    filename = f"{ts}-playlive-failover-unreachable.yml"
    path = os.path.join(inbox_dir, filename)
    payload = {
        "title": "PlayLive daemon not reachable after self-heal and failover",
        "subtitle": f"playlived at {playlive_url} is unreachable on {host}",
        "icon": "inbox",
        "focus": {
            "label": "playlive failover failure",
            "text": f"The PlayLive daemon at {playlive_url} was not reachable. Self-heal and failover were attempted but both failed. Last error: {error}",
            "branch": "topic/tailscale",
            "priority": "high",
            "status": "draft",
            "tags": tags,
            "missing_info": [],
            "safe_to_parallel": {"value": False, "reason": "Requires manual triage of the playlived daemon and failover path."},
            "subtasks": [
                {
                    "label": "Check playlived and Chrome CDP on the primary and failover hosts",
                    "status": "not_started",
                }
            ],
        },
        "ownership": {
            "owner": "tony",
            "session": "",
            "locked": False,
            "lock_reason": "",
        },
        "source": {
            "session": "",
            "date": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
        },
    }
    try:
        with open(path, "w") as f:
            yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False, allow_unicode=True)
        update_focus_lock()
    except OSError:
        pass


def daemon_healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("ok", False)
    except Exception:
        return False


def self_heal(command: list[str], retry_delay: int) -> bool:
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            time.sleep(retry_delay)
            return True
    except (OSError, FileNotFoundError):
        pass
    return False


def resolve_playlive_url(data: dict, host: str) -> tuple[str, bool]:
    """Pick the healthiest playlive_url for this host.

    Returns (url, reachable).  Tries primary, self-heals, then failover and
    self-heals if the failover is local.
    """
    self_heal_cfg = data.get("self_heal", {})
    retry_delay = self_heal_cfg.get("retry_delay", 5)
    command = self_heal_cfg.get("commands", {}).get(host) if self_heal_cfg.get("enabled") else None

    # 1. Primary URL for this host.
    primary = (
        data.get("per_host", {}).get(host, {}).get("playlive_url")
        or data.get("playlive_url")
        or "http://tony-dell:9230"
    )
    if daemon_healthy(primary):
        return primary, True
    if command and self_heal(command, retry_delay) and daemon_healthy(primary):
        return primary, True

    # 2. Failover URL.
    failover = data.get("failover", {}).get(host, {}).get("playlive_url")
    if failover:
        if daemon_healthy(failover):
            return failover, True
        # If the failover is the local daemon, try the same self-heal command.
        if command and "127.0.0.1" in failover and self_heal(command, retry_delay) and daemon_healthy(failover):
            return failover, True

    # 3. Nothing is reachable; fall back to the primary so the server can report its own errors.
    return primary, False


def main() -> None:
    hosts_file = os.environ.get("PLAYLIVE_HOSTS_FILE", DEFAULT_HOSTS_FILE)
    data = load_hosts_data(hosts_file)
    host = current_host()

    playlive_url, reachable = resolve_playlive_url(data, host)
    os.environ["PLAYLIVE_URL"] = playlive_url

    hosts = data.get("hosts", {})
    hosts_map = {name: info["cdp"] for name, info in hosts.items() if info.get("cdp")}
    os.environ["PLAYLIVE_HOSTS"] = json.dumps(hosts_map)

    if not reachable:
        focus_cfg = data.get("focus", {})
        if focus_cfg.get("enabled"):
            write_focus_item(
                focus_cfg.get("inbox_dir", ""),
                host,
                playlive_url,
                "primary and failover daemons unreachable after self-heal",
                labels=["failover"],
            )

    server = server_path(hosts_file)
    os.execv(sys.executable, [sys.executable, server])


if __name__ == "__main__":
    main()
