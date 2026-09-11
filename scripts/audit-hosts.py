#!/usr/bin/env python3
"""Snapshot service and resource state for a Chaba host and diff against SSOT."""

import argparse
import datetime
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SSOT_DEFAULT = REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.audit.hosts.yml"
OUTPUT_DIR_DEFAULT = REPO_ROOT / "reports" / "audit-hosts"

HOSTS = {
    "tony-dell": {"tailnet": "tony-dell", "os": "linux", "user": "tony"},
    "tony-omen": {"tailnet": "tony-omen", "os": "linux", "user": "tony"},
    "macbook": {"tailnet": "macbook", "os": "macos", "user": "kkkakk"},
}


def run_local(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    return _run(["bash", "-c", cmd], timeout)


def run_ssh(host: str, cmd: str, timeout: int = 60) -> tuple[int, str, str]:
    cfg = HOSTS[host]
    try:
        ip = subprocess.run(
            ["tailscale", "ip", "-4", cfg["tailnet"]],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to tailnet hostname if tailscale binary is missing
        ip = cfg["tailnet"]
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               f"{cfg['user']}@{ip}", cmd]
    return _run(ssh_cmd, timeout)


def _run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        return e.stdout or "", e.stderr or "", 124


def linux_services(host: str, ssh: bool) -> dict:
    def _run(cmd: str, timeout: int = 30):
        return run_ssh(host, cmd, timeout) if ssh else run_local(cmd, timeout)
    run = _run
    active, _err_active, _ = run(
        r"systemctl --user list-units --no-pager --plain | grep -E '\.(service|scope|timer)' | awk '{print $1, $3}'"
    )
    failed_user, _err_user, _ = run(
        r"systemctl --user list-units --failed --no-pager --plain | grep -E '\.(service|scope)' | awk '{print $1}'"
    )
    failed_sys, _err_sys, _ = run(
        r"systemctl list-units --failed --no-pager --plain | grep -E '\.(service|scope)' | awk '{print $1}'"
    )
    free, _err_free, _ = run("free -h | grep -E '^Mem:|^Swap:'")
    df, _err_df, _ = run("df -h / | tail -1")
    uptime, _err_uptime, _ = run("uptime")
    ps, _err_ps, _ = run("ps -eo pid,%mem,%cpu,comm --sort=-%mem | head -10")

    return {
        "active_user_services": _parse_kv(active),
        "failed_user_services": _parse_list(failed_user),
        "failed_system_services": _parse_list(failed_sys),
        "memory": _parse_free(free),
        "disk": _parse_df(df),
        "load": _parse_uptime(uptime),
        "uptime": _raw_uptime(uptime),
        "top_processes": _parse_ps(ps),
    }


def macos_services(host: str, ssh: bool) -> dict:
    def _run(cmd: str, timeout: int = 30):
        return run_ssh(host, cmd, timeout) if ssh else run_local(cmd, timeout)
    run = _run
    launch, _err_launch, _ = run("launchctl list | sed '1,/^PID/d' | head -40")
    vm, _err_vm, _ = run("vm_stat | head -10")
    df, _err_df, _ = run("df -h / | tail -1")
    uptime, _err_uptime, _ = run("uptime")
    ps, _err_ps, _ = run("ps -ax -o pid,%mem,command -r | head -10")

    return {
        "active_services": _parse_launchctl(launch),
        "vm_stat": _parse_vm_stat(vm),
        "disk": _parse_df(df),
        "load": _parse_uptime(uptime),
        "uptime": _raw_uptime(uptime),
        "top_processes": _parse_ps(ps),
    }


def _parse_kv(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            out.append({"unit": parts[0], "state": parts[1]})
    return out


def _parse_list(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_free(text: str) -> dict:
    m = {}
    for line in text.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            m = {
                "total": parts[1],
                "used": parts[2],
                "free": parts[3],
                "shared": parts[4] if len(parts) > 4 else None,
                "buff_cache": parts[5] if len(parts) > 5 else None,
                "available": parts[6] if len(parts) > 6 else None,
            }
    return m


def _parse_df(text: str) -> dict:
    parts = text.split()
    if len(parts) >= 6:
        return {
            "filesystem": parts[0],
            "size": parts[1],
            "used": parts[2],
            "available": parts[3],
            "percent": parts[4].rstrip("%"),
            "mount": parts[5],
        }
    return {}


def _parse_uptime(text: str) -> dict:
    m = re.search(r"load average:\s+([0-9.]+),\s+([0-9.]+),\s+([0-9.]+)", text)
    if m:
        return {"1m": float(m.group(1)), "5m": float(m.group(2)), "15m": float(m.group(3))}
    return {}


def _raw_uptime(text: str) -> str:
    m = re.search(r"up\s+(.+?),\s*\d+\s*user", text)
    return m.group(1).strip() if m else text.strip().split("\n")[0]


def _parse_ps(text: str) -> list[str]:
    lines = text.splitlines()
    return [line.strip() for line in lines if not line.lstrip().startswith("PID")]


def _parse_launchctl(text: str) -> list[str]:
    return [line.strip().split()[-1] for line in text.splitlines() if line.strip()]


def _parse_vm_stat(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _is_local(host: str) -> bool:
    try:
        hn = subprocess.run(["hostname", "-s"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        hn = ""
    return host == "tony-omen" and hn == "tony-omen" or host == "tony-dell" and hn == "tony-dell"


def audit_host(host: str, ssh: bool | None = None) -> dict:
    if ssh is None:
        ssh = not _is_local(host)

    cfg = HOSTS.get(host)
    if not cfg:
        raise SystemExit(f"Unknown host: {host}. Known: {', '.join(HOSTS)}")

    timestamp = datetime.datetime.now().astimezone().isoformat()

    if cfg["os"] == "linux":
        observed = linux_services(host, ssh)
    else:
        observed = macos_services(host, ssh)

    return {
        "host": host,
        "tailscale_ip": _tailscale_ip(host),
        "timestamp": timestamp,
        "ssh_used": ssh,
        **observed,
    }


def _tailscale_ip(host: str) -> str | None:
    cfg = HOSTS[host]
    try:
        return subprocess.run(
            ["tailscale", "ip", "-4", cfg["tailnet"]],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _is_present(expected: str, kind: str, active: set[str]) -> bool:
    if expected in active:
        return True
    if kind == "scope":
        for unit in active:
            if unit.startswith(expected + "-") and unit.endswith(".scope"):
                return True
    return False


def diff_against_ssot(host: str, observed: dict, ssot_path: Path) -> list[str]:
    if not ssot_path.exists():
        return [f"SSOT not found at {ssot_path}"]
    try:
        ssot = yaml.safe_load(ssot_path.read_text())
    except Exception as e:
        return [f"Failed to load SSOT: {e}"]

    host_ssot = ssot.get("hosts", {}).get(host, {})
    expected = host_ssot.get("expected_services", [])
    known_failed = {f["name"] for f in host_ssot.get("known_failed", [])}
    deltas = []

    if cfg := host_ssot.get("expected_resources"):
        mem = observed.get("memory", {})
        if "available" in mem:
            avail = mem["available"]
        else:
            avail = mem.get("free")
        if avail and isinstance(avail, str):
            # Very rough extraction for '913Mi'
            m = re.match(r"([0-9.]+)\s*(\w+)", str(avail))
            if m:
                mb = float(m.group(1))
                unit = m.group(2).lower()
                if unit == "gi":
                    mb *= 1024
                if cfg.get("min_free_ram_mb") and mb < cfg["min_free_ram_mb"]:
                    deltas.append(f"free RAM {avail} below threshold {cfg['min_free_ram_mb']} MiB")

    active_units = {s["unit"] for s in observed.get("active_user_services", []) if "unit" in s}
    for exp in expected:
        exp_name = exp["name"]
        exp_type = exp.get("type", "service")
        if _is_present(exp_name, exp_type, active_units):
            continue
        if exp_name in known_failed:
            continue
        if exp.get("note", "").startswith("Currently disabled"):
            continue
        deltas.append(f"Expected service missing: {exp_name}")

    for fail in observed.get("failed_user_services", []):
        if fail not in known_failed and not fail.startswith("session-"):
            deltas.append(f"Unexpected failed user service: {fail}")
    for fail in observed.get("failed_system_services", []):
        if fail not in known_failed:
            deltas.append(f"Unexpected failed system service: {fail}")

    return deltas


def main():
    parser = argparse.ArgumentParser(description="Snapshot a host's service and resource state")
    parser.add_argument("--host", required=True, choices=list(HOSTS))
    parser.add_argument("--ssot", type=Path, default=SSOT_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--ssh", action="store_true", default=None,
                        help="Force ssh even when running on the target host")
    parser.add_argument("--no-ssh", action="store_true", help="Force local execution")
    args = parser.parse_args()

    ssh = None
    if args.ssh:
        ssh = True
    elif args.no_ssh:
        ssh = False

    observed = audit_host(args.host, ssh)
    deltas = diff_against_ssot(args.host, observed, args.ssot)
    observed["deltas"] = deltas

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = args.output_dir / f"{args.host}-{ts}.yml"
    report_path.write_text(yaml.safe_dump(observed, sort_keys=False, allow_unicode=True))

    print(f"Wrote report: {report_path}")
    print(f"Tailscale IP: {observed.get('tailscale_ip')}")
    if deltas:
        print("Deltas:")
        for d in deltas:
            print(f"  - {d}")
    else:
        print("No deltas against SSOT expected state.")


if __name__ == "__main__":
    main()
