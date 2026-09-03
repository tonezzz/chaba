#!/usr/bin/env python3
"""playlive-hosts-loader — read playlive-hosts.yml and exec the MCP server.

The SSOT YAML file lives in the repo under:
  /home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/playlive-hosts.yml

It converts the YAML host registry into the JSON PLAYLIVE_HOSTS env var that
playlive-server.py expects, then os.execv's the real server.

Per-host behaviour:
  - On tony-dell, prefer the local playlived (127.0.0.1:9230).
  - On tony-omen, prefer the tony-dell playlived (tony-dell:9230).

If the chosen playlived is not reachable and self_heal is enabled in the YAML,
the loader attempts a host-specific systemd restart.  If that still fails and
focus is enabled, it drops a focus-inbox item and continues to start the server.
"""
import datetime
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import yaml

DEFAULT_HOSTS_FILE = "/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/playlive-hosts.yml"
SERVER = "/home/tony/CascadeProjects/chaba-tony-dell/mcp-servers/mcp-playlive/playlive-server.py"


def current_host() -> str:
    return socket.gethostname().lower().replace("-", "_").split(".")[0]


def load_hosts_data(hosts_file: str) -> dict:
    with open(hosts_file) as f:
        return yaml.safe_load(f)


def focus_already_flagged(inbox_dir: str, window: int = 3600) -> bool:
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


def write_focus_item(inbox_dir: str, host: str, playlive_url: str, error: str):
    if focus_already_flagged(inbox_dir):
        return
    try:
        os.makedirs(inbox_dir, exist_ok=True)
    except OSError:
        return
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d-%H%M%S")
    filename = f"{ts}-playlive-self-heal-failed.yml"
    path = os.path.join(inbox_dir, filename)
    payload = {
        "title": "PlayLive daemon not reachable after self-heal",
        "subtitle": f"playlived at {playlive_url} is unreachable on {host}",
        "icon": "inbox",
        "focus": {
            "label": "playlive self-heal failure",
            "text": f"The PlayLive daemon at {playlive_url} was not reachable. Self-heal was attempted but failed. Last error: {error}",
            "branch": "topic/tailscale",
            "priority": "high",
            "status": "draft",
            "tags": ["playlive", "infrastructure", "self-heal"],
            "missing_info": [],
            "safe_to_parallel": {"value": False, "reason": "Requires manual triage of the playlived daemon."},
            "subtasks": [
                {
                    "label": "Check playlived and Chrome CDP on the target host",
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


def main() -> None:
    hosts_file = os.environ.get("PLAYLIVE_HOSTS_FILE", DEFAULT_HOSTS_FILE)
    data = load_hosts_data(hosts_file)
    host = current_host()

    # Per-host playlive_url, with tony-dell defaulting to the local daemon.
    playlive_url = (
        data.get("per_host", {}).get(host, {}).get("playlive_url")
        or data.get("playlive_url")
        or "http://tony-dell:9230"
    )
    os.environ["PLAYLIVE_URL"] = playlive_url

    hosts = data.get("hosts", {})
    hosts_map = {name: info["cdp"] for name, info in hosts.items() if info.get("cdp")}
    os.environ["PLAYLIVE_HOSTS"] = json.dumps(hosts_map)

    # Optionally attempt self-heal when the daemon is not reachable.
    self_heal_cfg = data.get("self_heal", {})
    focus_cfg = data.get("focus", {})
    if self_heal_cfg.get("enabled"):
        if not daemon_healthy(playlive_url):
            command = self_heal_cfg.get("commands", {}).get(host)
            retry_delay = self_heal_cfg.get("retry_delay", 5)
            if command and self_heal(command, retry_delay):
                pass  # healthy after restart
            else:
                # Still not healthy. Flag focus if configured, then continue.
                if focus_cfg.get("enabled"):
                    write_focus_item(focus_cfg.get("inbox_dir", ""), host, playlive_url, "daemon unreachable after self-heal")

    os.execv(sys.executable, [sys.executable, SERVER])


if __name__ == "__main__":
    main()
