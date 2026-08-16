#!/usr/bin/env python3
"""TCP/IP link monitor for tony-omen, tony-dell, and macbook.

Loads host definitions from docs/ssot/infrastructure/ssot.host-roles.yml and
policy from docs/ssot/infrastructure/ssot.link-monitor.yml. Runs cheap ICMP or
TCP probes, escalates to scans and safe fixes, and writes focus-inbox alerts
when a link cannot be restored.
"""
import argparse
import datetime
import json
import logging
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SSOT_DIR = REPO / "docs" / "ssot"
LINK_SSOT = SSOT_DIR / "infrastructure" / "ssot.link-monitor.yml"
ROLES_SSOT = SSOT_DIR / "infrastructure" / "ssot.host-roles.yml"
INBOX_DIR = SSOT_DIR / "focus-inbox"
LOG_DIR = Path.home() / "var" / "chaba"
LOG_FILE = LOG_DIR / "mcp-link-monitor.log"
DRIFT_STATE_FILE = LOG_DIR / "mcp-link-monitor-drift-state.json"


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def setup_logging(verbose=False):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s - %(levelname)s - %(message)s"
    handlers = [logging.StreamHandler(sys.stderr)]
    try:
        handlers.append(logging.FileHandler(LOG_FILE))
    except OSError as e:
        logging.warning("Could not open log file: %s", e)
    logging.basicConfig(level=level, format=fmt, handlers=handlers)


def run_cmd(cmd, timeout=30):
    try:
        proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def probe_icmp(address):
    rc, _, _ = run_cmd(f"ping -c 1 -W 2 {address}")
    return rc == 0


def probe_tcp(address, port):
    try:
        with socket.create_connection((address, port), timeout=5):
            return True
    except OSError:
        return False


def get_tailscale_info():
    rc, out, _ = run_cmd("tailscale status --json", timeout=10)
    if rc != 0:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def derive_addresses(host, role, self_name, magic_suffix):
    tailscale_ip = role.get("tailscale_ip")
    tailnet = role.get("tailnet") or role.get("mcp_debug_name", host)
    local_hostname = role.get("local_hostname")

    if self_name and (tailnet == self_name or role.get("mcp_debug_name") == self_name):
        return ["127.0.0.1"], True

    addrs = []
    for pref in ["tailscale_ip", "magic_dns", "local_hostname"]:
        if pref == "tailscale_ip" and tailscale_ip:
            addrs.append(tailscale_ip)
        elif pref == "magic_dns" and magic_suffix and tailnet:
            addrs.append(f"{tailnet}.{magic_suffix}")
        elif pref == "local_hostname" and local_hostname:
            addrs.append(local_hostname)

    seen = set()
    uniq = []
    for a in addrs:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq, False


def build_hosts(link_cfg, roles_cfg, ts_info):
    self_name = ts_info.get("Self", {}).get("HostName", "")
    magic_suffix = ts_info.get("MagicDNSSuffix", os.environ.get("TAILNET_MAGIC_DNS_SUFFIX", ""))
    ports = link_cfg.get("checks", {}).get("probe_methods", {}).get("tcp", {}).get("ports", {})
    scope = set(link_cfg.get("overview", {}).get("scope", []))

    hosts = {}
    for key, role in roles_cfg.get("hosts", {}).items():
        mcp_name = role.get("mcp_debug_name", key)
        tailnet = role.get("tailnet", key)
        if mcp_name not in scope and tailnet not in scope and key not in scope:
            continue
        addrs, is_self = derive_addresses(mcp_name, role, self_name, magic_suffix)
        hosts[mcp_name] = {
            "mcp_name": mcp_name,
            "tailnet": tailnet,
            "tailscale_ip": role.get("tailscale_ip"),
            "addresses": addrs,
            "is_self": is_self,
            "port": ports.get(mcp_name, 22),
            "role": role,
        }
    return hosts


def run_scan(tailnet, commands):
    scan = []
    for tmpl in commands:
        cmd = tmpl.replace("{{name}}", tailnet).replace("{{host}}", tailnet)
        rc, out, err = run_cmd(cmd, timeout=20)
        scan.append({
            "command": cmd,
            "rc": rc,
            "out": out[:2000].strip(),
            "err": err[:1000].strip(),
        })
    return scan


def run_fixes(host, host_cfg, link_cfg, no_fix=False):
    if no_fix:
        return []
    actions = link_cfg.get("fix_actions", {})
    safe = actions.get("safe", [])
    risky = actions.get("risky", []) if os.environ.get("LINK_MONITOR_RISKY") == "1" else []
    results = []
    for action in safe + risky:
        action_hosts = action.get("hosts", [])
        if action_hosts and host not in action_hosts:
            continue
        cmd = action.get("command", "").replace("{{name}}", host_cfg["tailnet"])
        if "{{iface}}" in cmd:
            results.append({
                "label": action.get("label"),
                "skipped": True,
                "reason": "iface placeholder not configured",
            })
            continue
        require_env = action.get("require_env")
        if require_env:
            key, _, val = require_env.partition("=")
            if os.environ.get(key) != val:
                results.append({
                    "label": action.get("label"),
                    "skipped": True,
                    "reason": f"required env {require_env} not set",
                })
                continue
        rc, out, err = run_cmd(cmd, timeout=60)
        results.append({
            "label": action.get("label"),
            "rc": rc,
            "out": out[:1000].strip(),
            "err": err[:500].strip(),
        })
    return results


def write_inbox_alert(host, scan, fixes, dry_run=False):
    if dry_run or os.environ.get("LINK_MONITOR_NO_ALERT") == "1":
        return
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d-%H%M%S")
    path = INBOX_DIR / f"{host}-link-down-{stamp}.yml"

    scan_lines = [f"- {s['command']} (rc={s['rc']})" for s in scan]
    fix_lines = [f"- {f.get('label', 'unknown')} (rc={f.get('rc')})" for f in fixes if not f.get("skipped")]
    skipped_lines = [f"- {f.get('label', 'unknown')}: {f.get('reason', 'skipped')}" for f in fixes if f.get("skipped")]

    text_parts = [f"Link monitor detected {host} is unreachable after scan and safe fixes."]
    if scan_lines:
        text_parts.append("Scan output:\n" + "\n".join(scan_lines))
    if fix_lines:
        text_parts.append("Fix attempts:\n" + "\n".join(fix_lines))
    if skipped_lines:
        text_parts.append("Skipped fixes:\n" + "\n".join(skipped_lines))
    text = "\n\n".join(text_parts)

    doc = {
        "title": "Focus Inbox Item",
        "subtitle": "Link monitor alert",
        "icon": "inbox",
        "focus": {
            "label": f"{host} link down",
            "text": text,
            "branch": "chaba",
            "priority": "high",
            "status": "draft",
            "tags": ["monitoring", "network", "link", "alert"],
            "missing_info": ["Determine if the failure is transient or a hardware/routing issue."],
            "subtasks": [
                {"label": "Review scan output", "status": "not_started"},
                {"label": "Apply manual fix or escalate", "status": "not_started"},
            ],
        },
        "source": {
            "session": "mcp-link-monitor",
            "date": now.strftime("%Y-%m-%d"),
        },
    }
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
    logging.info("Wrote inbox alert: %s", path)


def _load_drift_state():
    if DRIFT_STATE_FILE.exists():
        with open(DRIFT_STATE_FILE) as f:
            return json.load(f)
    return {"tailscale_ips": {}, "local_ip": None}


def _save_drift_state(state):
    DRIFT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DRIFT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def write_drift_inbox(host, kind, expected, actual):
    if os.environ.get("LINK_MONITOR_NO_ALERT") == "1":
        return
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d-%H%M%S")
    path = INBOX_DIR / f"{host}-{kind}-drift-{stamp}.yml"
    text = f"Detected {kind} drift for {host}: expected {expected}, observed {actual}. The monitor will not auto-update SSOT; please verify and edit docs/ssot/infrastructure/ssot.host-roles.yml."
    doc = {
        "title": "Focus Inbox Item",
        "subtitle": "IP drift alert",
        "icon": "inbox",
        "focus": {
            "label": f"{host} {kind} drift",
            "text": text,
            "branch": "chaba",
            "priority": "medium",
            "status": "draft",
            "tags": ["monitoring", "network", "drift", host],
            "missing_info": ["Confirm the new address is stable and correct", "Update docs/ssot/infrastructure/ssot.host-roles.yml if needed"],
            "subtasks": [
                {"label": "Verify new address", "status": "not_started"},
                {"label": "Update SSOT", "status": "not_started"},
            ],
        },
        "source": {
            "session": "mcp-link-monitor",
            "date": now.strftime("%Y-%m-%d"),
        },
    }
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
    logging.info("Wrote drift inbox: %s", path)


class LinkMonitor:
    def __init__(self, hosts, link_cfg, no_fix=False, dry_run=False, threshold=3):
        self.hosts = hosts
        self.link_cfg = link_cfg
        self.no_fix = no_fix
        self.dry_run = dry_run
        self.threshold = threshold
        self.states = {
            h: {
                "state": "healthy",
                "misses": 0,
                "alerted": False,
                "next_check": 0.0,
                "last_address": None,
            }
            for h in hosts
        }
        self.default_interval = link_cfg.get("checks", {}).get("default_interval", 30)
        self.backoff = link_cfg.get("checks", {}).get("down_backoff", [])
        self.scan_commands = link_cfg.get("scan_on_failure", {}).get("commands", [])
        self.drift_state = _load_drift_state()

    def _interval(self, host):
        s = self.states[host]
        if s["state"] == "healthy":
            return self.default_interval
        if s["state"] == "alert":
            return 120
        interval = self.default_interval
        for b in self.backoff:
            if s["misses"] >= b.get("misses", 0):
                interval = b.get("interval", self.default_interval)
        return interval

    def _probe(self, host):
        cfg = self.hosts[host]
        for addr in cfg["addresses"]:
            if probe_icmp(addr) or probe_tcp(addr, cfg["port"]):
                self.states[host]["last_address"] = addr
                return True, addr
        return False, None

    def _check_drift(self, host):
        cfg = self.hosts[host]
        expected_ts = cfg.get("tailscale_ip")
        # Tailscale IP drift
        ts_info = get_tailscale_info()
        if ts_info and expected_ts:
            peers = ts_info.get("Peer", {})
            for peer_id, peer in peers.items():
                name = peer.get("HostName") or (peer.get("DNSName", "").split(".")[0] if peer.get("DNSName") else "")
                if name == cfg["tailnet"]:
                    actual = peer.get("TailAddr")
                    if actual and actual != expected_ts:
                        if self.drift_state.get("tailscale_ips", {}).get(host) != actual:
                            write_drift_inbox(host, "tailscale_ip", expected_ts, actual)
                            self.drift_state.setdefault("tailscale_ips", {})[host] = actual
                            _save_drift_state(self.drift_state)
                    break
        # Local IP drift for the current machine
        if cfg.get("is_self"):
            rc, out, _ = run_cmd("ip -4 -br addr show", timeout=5)
            if rc == 0:
                current = None
                for line in out.splitlines():
                    match = re.search(r"\b(\d+\.\d+\.\d+\.\d+)\/\d+", line)
                    if match:
                        ip = match.group(1)
                        if not ip.startswith("127."):
                            current = ip
                            break
                last = self.drift_state.get("local_ip")
                if current and last and current != last:
                    write_drift_inbox(host, "local_ip", last, current)
                if current:
                    self.drift_state["local_ip"] = current
                    _save_drift_state(self.drift_state)

    def tick(self, host):
        cfg = self.hosts[host]
        state = self.states[host]
        ok, addr = self._probe(host)

        if state["state"] == "healthy":
            if ok:
                logging.debug("%s healthy via %s", host, addr)
                state["misses"] = 0
                state["alerted"] = False
            else:
                logging.info("%s probe failed", host)
                state["state"] = "missing"
                state["misses"] = 1

        elif state["state"] == "missing":
            if ok:
                logging.info("%s recovered to healthy", host)
                state["state"] = "healthy"
                state["misses"] = 0
                state["alerted"] = False
            else:
                state["misses"] += 1
                if state["misses"] >= self.threshold:
                    logging.info("%s reached miss threshold; entering scanning", host)
                    state["state"] = "scanning"

        elif state["state"] == "scanning":
            scan = run_scan(cfg["tailnet"], self.scan_commands)
            for entry in scan:
                logging.info("%s scan: %s (rc=%s)", host, entry["command"], entry["rc"])
            state["scan"] = scan
            state["state"] = "fixing"

        elif state["state"] == "fixing":
            fixes = run_fixes(host, cfg, self.link_cfg, self.no_fix)
            for entry in fixes:
                if entry.get("skipped"):
                    logging.info("%s fix skipped: %s (%s)", host, entry.get("label"), entry.get("reason"))
                else:
                    logging.info("%s fix: %s (rc=%s)", host, entry.get("label"), entry.get("rc"))
            state["fixes"] = fixes
            ok, _ = self._probe(host)
            if ok:
                logging.info("%s fixed and healthy", host)
                state["state"] = "healthy"
                state["misses"] = 0
                state["alerted"] = False
            else:
                logging.warning("%s safe fixes did not restore link; entering alert", host)
                state["state"] = "alert"

        elif state["state"] == "alert":
            if ok:
                logging.info("%s recovered from alert to healthy", host)
                state["state"] = "healthy"
                state["misses"] = 0
                state["alerted"] = False
            else:
                if not state["alerted"]:
                    write_inbox_alert(host, state.get("scan", []), state.get("fixes", []), dry_run=self.dry_run)
                    state["alerted"] = True
                logging.warning("%s still in alert", host)

        self._check_drift(host)
        state["next_check"] = time.time() + self._interval(host)
        return {"host": host, "state": state["state"], "misses": state["misses"]}

    def loop(self):
        now = time.time()
        for host in self.hosts:
            self.states[host]["next_check"] = now

        while True:
            now = time.time()
            ready = [h for h, s in self.states.items() if s["next_check"] <= now]
            if not ready:
                next_check = min(s["next_check"] for s in self.states.values())
                delay = max(0.1, next_check - now)
                logging.debug("Sleeping %.1fs", delay)
                time.sleep(delay)
                continue

            host = min(ready, key=lambda h: self.states[h]["next_check"])
            self.tick(host)

    def one_shot(self):
        results = {}
        for host in self.hosts:
            results[host] = self.tick(host)
        return results


def main():
    parser = argparse.ArgumentParser(description="TCP/IP link monitor")
    parser.add_argument("--one-shot", action="store_true", help="Run a single probe cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not write focus-inbox alerts")
    parser.add_argument("--no-fix", action="store_true", help="Do not run fix actions")
    parser.add_argument("--threshold", type=int, default=3, help="Consecutive misses before scanning")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    link_cfg = load_yaml(LINK_SSOT)
    roles_cfg = load_yaml(ROLES_SSOT)
    ts_info = get_tailscale_info()

    if not ts_info and not os.environ.get("TAILNET_MAGIC_DNS_SUFFIX"):
        logging.warning("Tailscale not available and TAILNET_MAGIC_DNS_SUFFIX not set; falling back to known addresses")

    hosts = build_hosts(link_cfg, roles_cfg, ts_info)
    if not hosts:
        logging.error("No hosts configured")
        sys.exit(1)

    monitor = LinkMonitor(hosts, link_cfg, no_fix=args.no_fix, dry_run=args.dry_run, threshold=args.threshold)

    if args.one_shot:
        print(json.dumps(monitor.one_shot(), indent=2, default=str))
    else:
        logging.info("Starting link monitor for %s", ", ".join(hosts))
        try:
            monitor.loop()
        except KeyboardInterrupt:
            logging.info("Stopping")


if __name__ == "__main__":
    main()
