#!/usr/bin/env python3
"""Snapshot a host's security posture and diff against ssot.security.<host>.yml.

Collects: listeners (ss/lsof), firewall (ufw/nft/socketfilterfw), tailscale
serve/funnel, WARP, sshd effective config. Reports DRIFT between declared
posture and live state. Writes reports/audit-security/<host>-<ts>.yml.
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SSOT_DIR = REPO_ROOT / "docs" / "ssot" / "infrastructure"
OUTPUT_DIR_DEFAULT = REPO_ROOT / "reports" / "audit-security"

# tailnet name + ssh user per host (aligned with audit-hosts.py)
HOSTS = {
    "tony-dell": {"tailnet": "tony-dell", "os": "linux", "user": "tony"},
    "tony-omen": {"tailnet": "tony-omen", "os": "linux", "user": "tony"},
    "mn01": {"tailnet": "mn01", "os": "linux", "user": "tony"},
    "idc01": {"tailnet": "idc01", "os": "linux", "user": "tony"},
    "kk-macbook": {"tailnet": "macbook", "os": "macos", "user": "kkkakk"},
}


def _run(cmd: list, timeout: int):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        return e.stdout or "", e.stderr or "", 124


def run_local(cmd: str, timeout: int = 30):
    return _run(["bash", "-c", cmd], timeout)


def run_ssh(host: str, cmd: str, timeout: int = 60):
    cfg = HOSTS[host]
    # Try the tailnet name first — ssh config / MagicDNS resolve it and the
    # host key is usually in known_hosts under the name. Raw IPs often fail
    # host-key verification (mn01 does).
    target = cfg["tailnet"]
    out, err, rc = _run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
         f"{cfg['user']}@{target}", cmd], timeout)
    if rc == 0 or out.strip():
        return out, err, rc
    try:
        ip = subprocess.run(
            ["tailscale", "ip", "-4", cfg["tailnet"]],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        ip = cfg["tailnet"]
    if ip == target:
        return out, err, rc
    return _run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
         f"{cfg['user']}@{ip}", cmd], timeout)


def _is_local(host: str) -> bool:
    try:
        hn = subprocess.run(["hostname", "-s"], capture_output=True,
                            text=True, timeout=5).stdout.strip()
    except Exception:
        hn = ""
    return hn == host or (host == "kk-macbook" and hn.startswith("KKs-MacBook"))


def collect_linux(host: str, ssh: bool) -> dict:
    run = (lambda c, t=30: run_ssh(host, c, t)) if ssh else run_local
    listeners, _, _ = run("ss -tlnH | awk '{print $4}' | sort -u")
    ufw, _, ufw_rc = run("sudo -n ufw status 2>/dev/null || echo UFW_UNAVAILABLE")
    nft, _, _ = run("sudo -n nft list ruleset 2>/dev/null | head -200 || true")
    serve, _, _ = run("tailscale serve status 2>/dev/null || true")
    funnel, _, _ = run("tailscale funnel status 2>/dev/null || true")
    warp, _, warp_rc = run(
        "command -v warp-cli >/dev/null && warp-cli status || echo NO_WARP")
    sshd_t, _, _ = run(
        "sudo -n sshd -T 2>/dev/null | "
        "grep -iE 'passwordauthentication|permitrootlogin|listenaddress' || "
        "grep -ihE '^\\s*(PasswordAuthentication|PermitRootLogin|ListenAddress)' "
        "/etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null || true")
    return {
        "listeners": [l.strip() for l in listeners.splitlines() if l.strip()],
        "ufw_status": ufw.strip() if ufw_rc == 0 else "unavailable",
        "nft_ruleset_head": nft.strip(),
        "tailscale_serve": serve.strip(),
        "tailscale_funnel": funnel.strip(),
        "warp_status": warp.strip() if warp_rc == 0 else "not installed",
        "sshd_effective": sshd_t.strip(),
    }


def collect_macos(host: str, ssh: bool) -> dict:
    run = (lambda c, t=30: run_ssh(host, c, t)) if ssh else run_local
    listeners, _, _ = run(
        "lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $9}' | sort -u")
    alf, _, _ = run(
        "/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null || true")
    return {
        "listeners": [l.strip() for l in listeners.splitlines() if l.strip()],
        "alf_status": alf.strip(),
        "tailscale_serve": "",
        "tailscale_funnel": "",
        "warp_status": "n/a",
        "sshd_effective": "",
    }


def classify(listener: str, tailscale_ip: str | None) -> str:
    addr = listener.rsplit(":", 1)[0].strip("[]").split("%")[0]
    if addr.startswith("127.") or addr in ("::1", "localhost"):
        return "loopback"
    if tailscale_ip and addr == tailscale_ip:
        return "tailnet-only"
    if addr.startswith("100.") or addr.startswith("fd7a:115c:a1e0:"):
        return "tailnet-only"
    if addr.startswith(("192.168.", "10.", "172.", "fe80:", "fc", "fd")):
        return "lan"  # RFC1918 + link-local + ULA (fc00::/7, e.g. lxd bridges)
    if addr in ("0.0.0.0", "::", "*"):
        return "wildcard"
    return "public-ip"


def load_baseline_ports(host: str) -> set:
    """Accepted wildcard endpoints for this host from ssot.audit.baseline.yml."""
    path = SSOT_DIR / "ssot.audit.baseline.yml"
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return set()
    ports = set()
    for e in data.get("accepted_public_endpoints", []):
        if not isinstance(e, dict):
            continue
        if e.get("host") and e["host"] != host:
            continue
        val = str(e.get("value", ""))
        if ":" in val:
            ports.add(val.rsplit(":", 1)[1])
    return ports


def diff(host: str, posture: dict, observed: dict) -> list:
    deltas = []
    tailscale_ip = (posture.get("tailscale") or {}).get("ip")
    expected = {
        e["listener"]: e
        for e in posture.get("expected_exposure", [])
        if not str(e.get("listener", "")).startswith("ts-")
    }

    obs_set = set()
    for l in observed.get("listeners", []):
        obs_set.add(l.replace("*:", "0.0.0.0:"))

    baseline_ports = load_baseline_ports(host)
    expected_ports = {k.rsplit(":", 1)[1] for k in expected if ":" in k}

    # unexpected listeners: wildcard/public listeners not declared
    for l in sorted(obs_set):
        if l in expected:
            continue
        cls = classify(l, tailscale_ip)
        if cls == "wildcard":
            port = l.rsplit(":", 1)[1]
            # wildcard is covered if the port is declared on any bind or
            # accepted in the audit baseline for this host
            if port in expected_ports or port in baseline_ports:
                continue
            deltas.append(f"Undeclared wildcard listener: {l}")
        elif cls == "public-ip":
            deltas.append(f"Undeclared public-ip listener: {l}")

    # missing expected listeners
    for key, e in expected.items():
        if e.get("optional"):
            continue
        port = key.rsplit(":", 1)[1]
        if not any(l.endswith(f":{port}") for l in obs_set):
            deltas.append(
                f"Expected listener missing: {key} ({e.get('service')})")

    # funnel: declared paths vs live funnel status
    live_funnel = observed.get("tailscale_funnel", "") or ""
    declared_funnel = (posture.get("tailscale") or {}).get("funnel", [])
    if not declared_funnel and "funnel on" in live_funnel.lower():
        deltas.append("Funnel is ON but not declared in posture file")
    if declared_funnel and not live_funnel.strip():
        deltas.append(
            "Funnel declared but `tailscale funnel status` returned nothing")

    # WARP
    warp_declared = (posture.get("egress") or {}).get("warp", {}) or {}
    warp_live = observed.get("warp_status", "")
    if warp_declared.get("enabled") and "Connected" not in warp_live:
        deltas.append("WARP declared enabled but warp-cli status is not Connected")
    if not warp_declared.get("enabled") and "Connected" in warp_live:
        deltas.append("WARP is Connected but not declared in posture file")

    # sshd password auth
    sshd_live = (observed.get("sshd_effective", "") or "").lower()
    sshd_declared = (posture.get("remote_access") or {}).get("sshd", {}) or {}
    if "passwordauthentication yes" in sshd_live and sshd_declared.get("password_auth") not in ("deviation", "yes", "needs-verification"):
        deltas.append("sshd PasswordAuthentication yes live but not declared as deviation")

    return deltas


def load_posture(host: str):
    path = SSOT_DIR / f"ssot.security.{host}.yml"
    if not path.exists():
        return {}, path
    return yaml.safe_load(path.read_text()) or {}, path


def audit(host: str, ssh) -> dict:
    cfg = HOSTS[host]
    if ssh is None:
        ssh = not _is_local(host)
    observed = (collect_linux(host, ssh) if cfg["os"] == "linux"
                else collect_macos(host, ssh))
    posture, posture_path = load_posture(host)
    deltas = diff(host, posture, observed) if posture else [
        f"posture file missing: {posture_path}"]
    return {
        "host": host,
        "timestamp": datetime.datetime.now().astimezone().isoformat(),
        "ssh_used": ssh,
        "observed": observed,
        "deltas": deltas,
    }


def save_to_ssot(host: str, result: dict, posture_path: Path):
    if not posture_path.exists():
        return
    posture = yaml.safe_load(posture_path.read_text())
    posture["last_observed"] = {
        "observed_at": result["timestamp"], **result["observed"]}
    posture["deltas"] = result["deltas"]
    posture_path.write_text(
        yaml.safe_dump(posture, sort_keys=False, allow_unicode=True))
    print(f"Updated {posture_path.name} last_observed + deltas")


def main():
    ap = argparse.ArgumentParser(
        description="Audit host security posture vs SSOT")
    ap.add_argument("--host", required=True, choices=list(HOSTS) + ["all"])
    ap.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    ap.add_argument("--ssh", action="store_true", default=None)
    ap.add_argument("--no-ssh", action="store_true")
    ap.add_argument("--save-to-ssot", action="store_true",
                    help="Write last_observed+deltas into posture files "
                         "(rewrites the YAML — comments/formatting are lost)")
    args = ap.parse_args()

    hosts = list(HOSTS) if args.host == "all" else [args.host]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    any_drift = False

    for host in hosts:
        ssh = True if args.ssh else (False if args.no_ssh else None)
        try:
            result = audit(host, ssh)
        except Exception as e:
            result = {
                "host": host,
                "timestamp": datetime.datetime.now().astimezone().isoformat(),
                "ssh_used": ssh,
                "observed": {},
                "deltas": [f"audit error: {e}"],
            }
        report = args.output_dir / f"{host}-{ts}.yml"
        report.write_text(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True))
        _, posture_path = load_posture(host)
        if args.save_to_ssot:
            save_to_ssot(host, result, posture_path)
        deltas = result["deltas"]
        any_drift = any_drift or bool(deltas)
        status = "DRIFT" if deltas else "PASS"
        print(f"{host}: {status} ({report})")
        for d in deltas:
            print(f"  - {d}")

    sys.exit(1 if any_drift else 0)


if __name__ == "__main__":
    main()
