#!/usr/bin/env python3
"""Snapshot service and resource state for a Chaba host and diff against SSOT."""

import argparse
import datetime
import fnmatch
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import yaml

# Units in the user session that are desktop/OS plumbing, not fleet
# services — unexpected-running skips these (host-level extras go in the
# SSOT `allowed_running` list, fnmatch globs allowed).
USER_SESSION_NOISE = re.compile(
    r"^(init\.scope|session-.*|run-.*|app-.*|dbus\.service|at-spi-.*|"
    r"gcr-ssh-agent.*|gnome-keyring.*|gpg-agent.*|gvfs-.*|mpris.*|"
    r"pipewire.*|wireplumber.*|xdg-.*|filter-chain.*|plasma-.*|"
    r"org\.gnome.*|org\.freedesktop.*|gsd-.*|evolution.*|tracker.*|"
    r"ssh-agent.*|snap\..*|pk-.*|colord.*|obex.*|speech-dispatcher.*|"
    r"kdeconnect.*|gnome-remote.*|rygel.*|systemd-.*|dconf\.service|"
    r"localsearch.*|xfce4-notifyd.*|xfconfd.*|gnome-session-.*|"
    r"chrome-remote-desktop-environment.*|podman-user-wait.*|"
    r"screen-timeout-daemon.*|barriers\.service|devin-task-.*|"
    r"[0-9a-f]{40,64}(-[0-9a-f]{8,20})?\.service)$")

# Podman/systemd hash-named transient units — a 40-64 hex name is never a
# declared fleet service (matches in either scope).
HASH_UNIT_RE = re.compile(r"^[0-9a-f]{40,64}(-[0-9a-f]{8,20})?\.service$")

# System-scope units are too numerous to whitelist — flag only units that
# *look* fleet-managed (a stale fleet unit at system scope still surfaces).
FLEET_SYS_RE = re.compile(
    r"(chaba|ada[-_.]|home-?assist|michael|ollama|mddb|vcast|go2rtc|nest|jev|"
    r"kanban|cms|mcp[-_.]|cloudflared|cast-|camwall|sunsynk|devin|litellm|"
    r"openjev|caddy|rclone|notebooklm|workflows|yomi|obsidian|input-bridge|"
    r"barrier|gods-eye|gev[-_.]|playwright|yolo|xmeye|vms|raceman|helm|"
    r"node-red|dnsmasq|gesture|plug-watch|secrets-console|status-data|"
    r"trade-api|websockify|xvfb|bserver|redis|postgres|weaviate)")

# Failed units that are generic desktop/OS flakiness on essentially every
# Linux host — never a fleet signal.
FAILED_NOISE = re.compile(
    r"^(apport.*|NetworkManager-wait-online.*|xdg-desktop-portal.*|"
    r"xfce4-notifyd.*|snapd\..*|grub-initrd-fallback.*)$")

ESCALATE_H = 12

REPO_ROOT = Path(__file__).resolve().parents[1]
SSOT_DEFAULT = REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.audit.hosts.yml"
OUTPUT_DIR_DEFAULT = REPO_ROOT / "reports" / "audit-hosts"

HOSTS = {
    "tony-dell": {"tailnet": "tony-dell", "os": "linux", "user": "tony"},
    "tony-omen": {"tailnet": "tony-omen", "os": "linux", "user": "tony"},
    "mn01": {"tailnet": "mn01", "os": "linux", "user": "tony"},
    "idc01": {"tailnet": "idc01", "os": "linux", "user": "tony"},
    "idc02": {"tailnet": "idc02", "os": "linux", "user": "tony"},
    "idc03": {"tailnet": "idc03", "os": "linux", "user": "tony"},
    "con01": {"tailnet": "con01", "os": "linux", "user": "tony"},
    "macbook": {"tailnet": "tony-macbook", "os": "linux", "user": "tony"},
}


def run_local(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    return _run(["bash", "-c", cmd], timeout)


def run_ssh(host: str, cmd: str, timeout: int = 60) -> tuple[int, str, str]:
    cfg = HOSTS[host]
    # Try the tailnet name first — ssh config / MagicDNS resolve it and the
    # host key is usually in known_hosts under the name. Raw IPs often fail
    # host-key verification (mn01 does).
    target = cfg["tailnet"]
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               f"{cfg['user']}@{target}", cmd]
    out, err, rc = _run(ssh_cmd, timeout)
    if rc == 0 or out.strip():
        return out, err, rc
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
    if ip == target:
        return out, err, rc
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
    active_sys, _err_active_sys, _ = run(
        r"systemctl list-units --state=active --no-pager --plain | grep -E '\.(service|scope|timer)' | awk '{print $1, $3}'"
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
    oom_user, _err_oom_user, _ = run(
        "journalctl --user --since '-24 hours ago' --no-pager -o cat 2>/dev/null | grep -ciF 'OOM killer'"
    )
    oom_sys, _err_oom_sys, _ = run(
        "journalctl --since '-24 hours ago' --no-pager -o cat 2>/dev/null | grep -ciE 'oom-kill|OOM killer|Out of memory'"
    )

    return {
        "active_user_services": _parse_kv(active),
        "active_system_services": _parse_kv(active_sys),
        "failed_user_services": _parse_list(failed_user),
        "failed_system_services": _parse_list(failed_sys),
        "oom_kills_24h": {"user": _to_int(oom_user), "system": _to_int(oom_sys)},
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


def _to_int(text: str) -> int:
    try:
        return int(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


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
        primary = ("active_user_services", "memory", "uptime")
    else:
        observed = macos_services(host, ssh)
        primary = ("active_services", "vm_stat", "uptime")
    # An SSH probe that returns nothing at all means the host is unreachable —
    # an empty snapshot must not read as "clean".
    observed["unreachable"] = bool(ssh) and not any(
        observed.get(k) for k in primary)

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
    if host_ssot.get("retired"):
        return []   # out of the placement contract entirely
    if observed.get("unreachable"):
        if host_ssot.get("offline_ok"):
            return []
        return ["host unreachable via ssh — empty snapshot "
                "(mark offline_ok/retired in ssot.audit.hosts.yml if intended)"]
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

    # `present` = unit listed in any state (failed counts — the failed-unit
    # loop reports it separately). `running` = ACTIVE column is "active".
    active_user_units = {s["unit"] for s in observed.get("active_user_services", []) if "unit" in s}
    active_system_units = {s["unit"] for s in observed.get("active_system_services", []) if "unit" in s}
    running_user = {s["unit"] for s in observed.get("active_user_services", [])
                    if s.get("state") == "active" and "unit" in s}
    running_sys = {s["unit"] for s in observed.get("active_system_services", [])
                   if s.get("state") == "active" and "unit" in s}
    expected_names = set()
    for exp in expected:
        exp_name = exp["name"]
        expected_names.add(exp_name)
        exp_type = exp.get("type", "service")
        scope = exp.get("scope", "user")
        present_in = active_system_units if scope == "system" else active_user_units
        running_in = running_sys if scope == "system" else running_user
        want = exp.get("expected_state") or "active"
        present = _is_present(exp_name, exp_type, present_in)
        running = _is_present(exp_name, exp_type, running_in)
        if running and want in ("inactive", "absent"):
            deltas.append(f"Declared-{want} service is running: {exp_name}")
            continue
        if present:
            continue
        if want in ("inactive", "absent"):
            continue
        if exp_name in known_failed:
            continue
        if exp.get("note", "").startswith("Currently disabled"):
            continue
        if exp_name in observed.get("failed_user_services", []) or \
                exp_name in observed.get("failed_system_services", []):
            continue   # failed-units loop reports it — don't double-delta
        deltas.append(f"Expected service missing: {exp_name}")

    absent_names = set()
    for a in host_ssot.get("expected_absent", []):
        name = a["name"] if isinstance(a, dict) else a
        scope = a.get("scope", "user") if isinstance(a, dict) else "user"
        absent_names.add(name)
        if name in expected_names:
            continue   # expected_state:absent on the service entry already covers it
        running = running_sys if scope == "system" else running_user
        if name in running:
            note = a.get("note", "") if isinstance(a, dict) else ""
            deltas.append(f"Declared-absent service still running: {name}"
                          + (f" — {note}" if note else ""))
        elif name in (active_system_units if scope == "system" else active_user_units):
            deltas.append(f"Declared-absent unit tried to start (failed): {name}")

    allow = [a if isinstance(a, str) else a.get("name", "")
             for a in host_ssot.get("allowed_running", [])]
    def allowed(unit):
        return any(fnmatch.fnmatch(unit, p) for p in allow)

    for s in observed.get("active_user_services", []):
        unit, state = s.get("unit"), s.get("state")
        if not unit or not unit.endswith(".service") or state != "active":
            continue
        if unit in expected_names or unit in absent_names or \
                allowed(unit) or USER_SESSION_NOISE.match(unit) or \
                HASH_UNIT_RE.match(unit):
            continue
        deltas.append(f"Unexpected running user service: {unit} "
                      "(declare in expected_services, whitelist in "
                      "allowed_running, or stop it)")
    for s in observed.get("active_system_services", []):
        unit, state = s.get("unit"), s.get("state")
        if not unit or not unit.endswith(".service") or state != "active":
            continue
        if unit in expected_names or unit in absent_names or allowed(unit) \
                or HASH_UNIT_RE.match(unit):
            continue
        if FLEET_SYS_RE.search(unit):
            deltas.append(f"Unexpected fleet-looking system service: {unit}")

    for fail in observed.get("failed_user_services", []):
        if fail not in known_failed and not fail.startswith("session-") \
                and not FAILED_NOISE.match(fail):
            deltas.append(f"Unexpected failed user service: {fail}")
    for fail in observed.get("failed_system_services", []):
        if fail not in known_failed and not FAILED_NOISE.match(fail):
            deltas.append(f"Unexpected failed system service: {fail}")

    oom = observed.get("oom_kills_24h") or {}
    oom_user_n, oom_sys_n = oom.get("user") or 0, oom.get("system") or 0
    oom_total = oom_user_n + oom_sys_n
    oom_tolerance = int(host_ssot.get("oom_kills_tolerance") or 0)
    if oom_total > oom_tolerance:
        deltas.append(
            f"OOM kills in last 24h: {oom_total} "
            f"(user={oom_user_n}, system={oom_sys_n}, tolerance={oom_tolerance})"
        )

    return deltas


# ---------------------------------------------------------- kanban cards
# audit-auto-<host> lifecycle mirrors scripts/board/runner-fleet-health.py:
# deltas -> review card, clean -> auto-close, >=12h open -> priority bump,
# retired/offline_ok hosts never get cards. Only enabled via --cards (the
# chaba-system-report chain on tony-dell); ad-hoc runs never touch cards.

CARDS_DIR = Path(os.environ.get(
    "CHABA_AUDIT_CARDS_DIR",
    str(REPO_ROOT / "docs" / "ssot" / "kanban" / "cards")))


def _audit_card_path(host: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in host)
    return CARDS_DIR / f"audit-auto-{safe}.yml"


def _load_card(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def emit_audit_card(host: str, deltas: list, host_ssot: dict) -> str:
    """Upsert/close audit-auto-<host> from today's deltas."""
    path = _audit_card_path(host)
    today = time.strftime("%Y-%m-%d")
    if not deltas:
        card = _load_card(path)
        if path.exists() and card.get("column") == "review" and \
                card.get("generated") == "audit-hosts":
            card["column"] = "done"
            card["note"] = f"Auto-recovered {today}: audit clean."
            card["updated"] = today
            path.write_text(yaml.safe_dump(card, sort_keys=False,
                                           allow_unicode=True))
            return "closed"
        return "clean"
    card = _load_card(path)
    opened = card.get("updated") if card.get("column") == "review" else today
    try:
        age_h = (time.time() - time.mktime(
            time.strptime(str(opened), "%Y-%m-%d"))) / 3600
    except (ValueError, TypeError):
        age_h = 0
    card.update({
        "id": f"audit-auto-{host}",
        "title": f"Audit drift on `{host}`: {len(deltas)} delta(s) "
                 "vs expected state",
        "brief": ("Daily audit-hosts diff found service/placement drift "
                  "on this host. Deltas become work: fix the drift, or "
                  "fix the SSOT declaration (expected_services, "
                  "expected_absent, allowed_running, known_failed)."),
        "column": "review",
        "review_kind": "triage",
        "generated": "audit-hosts",
        "program": "chaba-ci",
        "area": "fleet-ops",
        "priority": "high" if age_h >= ESCALATE_H else "medium",
        "note": "\n".join(f"- {d}" for d in deltas)[:1400],
        "help": ("ssot: docs/ssot/infrastructure/ssot.audit.hosts.yml "
                 f"hosts.{host}. A delta means declared != observed: "
                 "either restore the expected state, or amend the SSOT so "
                 "the declaration matches intent (this file IS the "
                 "placement contract)."),
        "updated": opened,
    })
    if path.exists() and card == _load_card(path):
        return "unchanged"
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))
    return "updated"


def sweep_audit_cards(audited: set, ssot: dict) -> int:
    """Close audit-auto cards for hosts dropped from the audit fleet."""
    n = 0
    for path in CARDS_DIR.glob("audit-auto-*.yml"):
        host = path.stem.removeprefix("audit-auto-")
        if host in audited:
            continue
        card = _load_card(path)
        if card.get("column") == "review" and \
                card.get("generated") == "audit-hosts":
            card["column"] = "done"
            card["note"] = ("Auto-closed: host left the audit fleet "
                            "(retired or removed from ssot.audit.hosts.yml).")
            card["updated"] = time.strftime("%Y-%m-%d")
            path.write_text(yaml.safe_dump(card, sort_keys=False,
                                           allow_unicode=True))
            n += 1
    return n


def audited_hosts(ssot_path: Path) -> list:
    """Hosts to audit: SSOT `hosts:` entries minus retired ones."""
    try:
        ssot = yaml.safe_load(ssot_path.read_text()) or {}
    except Exception:
        return [h for h in HOSTS if h != "idc01"]
    out = []
    for h in HOSTS:
        hs = ssot.get("hosts", {}).get(h)
        if hs is None:  # not declared in audit SSOT — skip
            continue
        if hs.get("retired"):
            continue
        out.append(h)
    return out


def consolidate(output_dir: Path) -> int:
    """Fleet L2 rollup: resolve audit-hosts/* + health-monitor node state,
    render reports/fleet/FLEET-REPORT.md, write meta + timeline event."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.report import (append_timeline, latest_artifact, now_iso,
                            registry_nodes, resolve_all, write_meta)

    nodes = registry_nodes()
    children = [n for n in nodes
                if str(n.get("id", "")).startswith("audit-hosts/")
                or n.get("id") == "health-monitor"]
    states = resolve_all(children)

    fleet_dir = REPO_ROOT / "reports" / "fleet"
    fleet_dir.mkdir(parents=True, exist_ok=True)

    # Pull headline resources from each host's newest snapshot artifact.
    rows = []
    attention = []
    for s in states:
        host = s["id"].split("/", 1)[-1]
        res = {}
        art = latest_artifact(output_dir, f"{host}-*.yml") \
            if s["id"].startswith("audit-hosts/") else None
        if art:
            try:
                snap = yaml.safe_load(art.read_text()) or {}
                mem = snap.get("memory") or {}
                res = {
                    "ram_avail": mem.get("available") or mem.get("free") or "-",
                    "disk_pct": (snap.get("disk") or {}).get("percent", "-"),
                    "load1": (snap.get("load") or {}).get("1m", "-"),
                    "uptime": snap.get("uptime", "-"),
                }
            except Exception:
                pass
        deltas = []
        meta_path = s.get("meta_path")
        if meta_path:
            try:
                meta = yaml.safe_load(Path(meta_path).read_text()) or {}
                deltas = (meta.get("extra") or {}).get("deltas") or []
            except Exception:
                pass
        rows.append({"state": s, "res": res, "n_deltas": len(deltas)})
        if s["status"] in ("delta", "stale", "missing", "error", "unreachable"):
            attention.append(f"{s['id']}={s['status']}")
        for d in deltas:
            attention.append(f"{host}: {d}")

    status = "delta" if attention else "ok"
    bad = [f"{s['id']}={s['status']}" for s in states
           if s["status"] in ("delta", "stale", "missing", "error", "unreachable")]
    summary = f"{len(states)} nodes; " + (", ".join(bad) or "all clean")

    def fmt_ts(iso):
        if not iso:
            return "-"
        try:
            return datetime.datetime.fromisoformat(
                str(iso)).astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return str(iso)[:16]

    md = [
        "# Fleet Report",
        "",
        f"- Generated: {now_iso()} by `scripts/audit-hosts.py --consolidate`",
        f"- Status: **{status}** — {summary}",
        "",
        "| Node | Status | Last run | Deltas | RAM avail | Disk % | Load 1m | Uptime |",
        "|------|--------|----------|--------|-----------|--------|---------|--------|",
        *[f"| `{r['state']['id']}` | {r['state']['status']} | "
          f"{fmt_ts(r['state']['last_run'])} | {r['n_deltas']} | "
          f"{r['res'].get('ram_avail', '-')} | {r['res'].get('disk_pct', '-')} | "
          f"{r['res'].get('load1', '-')} | {r['res'].get('uptime', '-')} |"
          for r in rows],
        "",
    ]
    if attention:
        md += ["## Attention", "",
               *[f"- {a}" for a in attention], ""]
    md += ["_Generated file — do not hand-edit._", ""]
    report_path = fleet_dir / "FLEET-REPORT.md"
    report_path.write_text("\n".join(md), encoding="utf-8")

    write_meta(
        fleet_dir / "meta.yml",
        node="fleet",
        layer="L2-domain",
        purpose="Cross-host rollup — delta trend + resource min/max over window",
        generated_by="scripts/audit-hosts.py --consolidate",
        status=status,
        summary=summary,
        sources=[r["state"]["meta_path"] or "" for r in rows],
        children=[s["id"] for s in states],
        extra={"attention": attention},
    )
    append_timeline("fleet", "L2", status, summary, ref=report_path)
    print(f"Wrote {report_path}")
    print(f"Status: {status} — {summary}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Snapshot a host's service and resource state")
    parser.add_argument("--host", choices=list(HOSTS))
    parser.add_argument("--all", action="store_true",
                        help="Audit every non-retired host declared in the SSOT")
    parser.add_argument("--consolidate", action="store_true",
                        help="Render the fleet L2 rollup instead of auditing a host")
    parser.add_argument("--cards", action="store_true",
                        help="Upsert/close audit-auto-<host> kanban cards "
                             "(served-checkout runs only — tony-dell chain)")
    parser.add_argument("--ssot", type=Path, default=SSOT_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--ssh", action="store_true", default=None,
                        help="Force ssh even when running on the target host")
    parser.add_argument("--no-ssh", action="store_true", help="Force local execution")
    parser.add_argument("--save-to-ssot", action="store_true",
                        help="Write the observed live state back into the SSOT")
    args = parser.parse_args()

    if args.consolidate:
        raise SystemExit(consolidate(args.output_dir))
    if args.all:
        rc = 0
        for h in audited_hosts(args.ssot):
            try:
                rc |= run_one(h, args)
            except Exception as e:
                print(f"audit {h} crashed: {e}")
                rc = 1
        if args.cards:
            n = sweep_audit_cards(set(audited_hosts(args.ssot)), None)
            if n:
                print(f"swept {n} stale audit-auto card(s)")
        raise SystemExit(rc)
    if not args.host:
        parser.error("--host or --all is required unless --consolidate is given")
    raise SystemExit(run_one(args.host, args))


def run_one(host: str, args) -> int:
    ssh = None
    if args.ssh:
        ssh = True
    elif args.no_ssh:
        ssh = False

    observed = audit_host(host, ssh)
    deltas = diff_against_ssot(host, observed, args.ssot)
    observed["deltas"] = deltas

    if args.save_to_ssot:
        save_to_ssot(host, observed, args.ssot)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = args.output_dir / f"{host}-{ts}.yml"
    report_path.write_text(yaml.safe_dump(observed, sort_keys=False, allow_unicode=True))
    emit_meta(host, observed, deltas, report_path, args.output_dir)

    if args.cards:
        try:
            ssot = yaml.safe_load(args.ssot.read_text()) or {}
            host_ssot = ssot.get("hosts", {}).get(host, {})
            rc = emit_audit_card(host, deltas, host_ssot)
            print(f"audit-auto-{host}: {rc}")
        except Exception as e:
            print(f"audit-auto-{host}: card emit failed: {e}")

    print(f"Wrote report: {report_path}")
    print(f"Tailscale IP: {observed.get('tailscale_ip')}")
    if observed.get("unreachable"):
        print("Host unreachable — snapshot is empty (ssh failed)")
    if deltas:
        print("Deltas:")
        for d in deltas:
            print(f"  - {d}")
    else:
        print("No deltas against SSOT expected state.")
    return 0


def emit_meta(host: str, observed: dict, deltas: list[str],
              report_path: Path, output_dir: Path):
    """Write the node's meta.yml + timeline event (ssot.reports.yml L1)."""
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from lib.report import append_timeline, write_meta
    except Exception as e:
        print(f"meta emit skipped (lib.report unavailable): {e}")
        return
    if observed.get("unreachable"):
        # target-side condition, not a producer crash — nodes with
        # offline_ok tolerate it (laptops sleep), others flag as sustained
        status, summary = "unreachable", "unreachable — empty snapshot (ssh failed)"
    else:
        status = "delta" if deltas else "ok"
        summary = f"{len(deltas)} delta(s)" if deltas else "clean"
    try:
        write_meta(
            output_dir / f"meta.{host}.yml",
            node=f"audit-hosts/{host}",
            layer="L1-producer",
            purpose="Host snapshot + delta vs expected services/resources",
            generated_by=f"scripts/audit-hosts.py --host {host}",
            status=status,
            summary=summary,
            sources=[report_path.name],
            extra={
                "deltas": deltas,
                "tailscale_ip": observed.get("tailscale_ip"),
                "ssh_used": observed.get("ssh_used"),
            },
        )
        append_timeline(f"audit-hosts/{host}", "L1", status, summary,
                        ref=report_path)
    except Exception as e:
        print(f"meta/timeline emit failed (report still written): {e}")


def save_to_ssot(host: str, observed: dict, ssot_path: Path):
    if not ssot_path.exists():
        print(f"SSOT not found at {ssot_path}; skipping --save-to-ssot")
        return
    ssot = yaml.safe_load(ssot_path.read_text())
    if "hosts" not in ssot or host not in ssot.get("hosts", {}):
        print(f"Host {host} not found in SSOT; skipping --save-to-ssot")
        return

    disk = observed.get("disk", {})
    if "size" in disk and "total" not in disk:
        disk["total"] = disk["size"]

    ssot["hosts"][host]["last_observed"] = {
        "observed_at": observed.get("timestamp"),
        "active_user_services": [
            s["unit"] for s in observed.get("active_user_services", []) if "unit" in s
        ],
        "active_system_services": [
            s["unit"] for s in observed.get("active_system_services", []) if "unit" in s
        ],
        "failed_user_services": observed.get("failed_user_services", []),
        "failed_system_services": observed.get("failed_system_services", []),
        "oom_kills_24h": observed.get("oom_kills_24h", {}),
        "memory": observed.get("memory", {}),
        "swap": observed.get("swap", {}),
        "disk": disk,
        "load": observed.get("load", {}),
        "uptime": observed.get("uptime", ""),
        "top_processes": observed.get("top_processes", []),
        "notes": [f"Live snapshot from audit-hosts.py at {observed.get('timestamp', '?')}"],
    }
    ssot_path.write_text(yaml.safe_dump(ssot, sort_keys=False, allow_unicode=True))
    print(f"Updated SSOT last_observed for {host}")


if __name__ == "__main__":
    main()
