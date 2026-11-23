#!/usr/bin/env python3
"""post-restart-verify.py — check-only host post-restart verification.

Runs as a chained ExecStart of mcp-health-snapshot.service (timer:
OnBootSec=5min / OnUnitActiveSec=15min). Each invocation reads the kernel
boot-id and runs ONE verification pass per boot; repeat timer fires inside
the same boot short-circuit on the recorded state, so there is no spam.

Checks are declarative, gated by SSOT:
  docs/ssot/infrastructure/ssot.operations.yml
    automation.post_restart_verify.checks_common   (every configured host)
    host_notes.<host>.post_restart_checks          (host-specific)

Outputs:
  ~/var/chaba/health/post-restart-verify-<host>-<bootid8>.json  (per-boot report)
  ~/var/chaba/health/post-restart-verify-latest.json           (copy of last)
  ~/var/chaba/reports/timeline.jsonl                           (result record)
  board-api /inbox finding                                     (on failures only)

Check-only: this script NEVER remediates (no restarts, no fixes). Exit 0 on
a completed pass regardless of findings (OPS-0581 finding-reporter
convention); exit 1 only on internal error; exit 2 on bad usage.

  post-restart-verify.py [--host NAME] [--boot-id ID] [--force]
                         [--dry-run] [--exit-code] [--ops FILE]
"""
import argparse
import copy
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
OPS_DEFAULT = REPO / "docs" / "ssot" / "infrastructure" / "ssot.operations.yml"
BOOT_ID_FILE = "/proc/sys/kernel/random/boot_id"
STATE_DIR = Path(os.environ.get(
    "POST_RESTART_STATE_DIR",
    os.path.expanduser("~/var/chaba/post-restart-verify")))
REPORT_DIR = Path(os.environ.get(
    "POST_RESTART_REPORT_DIR",
    os.path.expanduser("~/var/chaba/health")))
TIMELINE = Path(os.environ.get(
    "CHABA_TIMELINE",
    os.path.expanduser("~/var/chaba/reports/timeline.jsonl")))
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000")
CMD_TIMEOUT = 30


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg):
    print(f"{now_iso()} post-restart-verify: {msg}", flush=True)


def host_key(name):
    """tony-omen -> tony_omen (SSOT host_notes keys use underscores)."""
    return name.strip().lower().replace("-", "_")


def read_boot_id(override=None):
    if override:
        return override.strip()
    return Path(BOOT_ID_FILE).read_text().strip()


def load_checks(ops_path, hkey):
    """Return (auto_cfg, checks). checks=[] means the host is not in scope:
    it has no host-specific checks AND is not in configured_hosts."""
    doc = yaml.safe_load(Path(ops_path).read_text()) or {}
    auto = (doc.get("automation") or {}).get("post_restart_verify") or {}
    configured = {host_key(h) for h in auto.get("configured_hosts") or []}
    host_block = (doc.get("host_notes") or {}).get(hkey) or {}
    specific = host_block.get("post_restart_checks") or []
    if not specific and hkey not in configured:
        return auto, []
    common = auto.get("checks_common") or []
    return auto, copy.deepcopy(common) + copy.deepcopy(specific)


def run_cmd(check):
    """type: command — run a shell command, check exit code / stdout regex."""
    shell = check.get("shell") or check.get("command")
    if not shell:
        return "error", "no shell command"
    try:
        r = subprocess.run(["/bin/sh", "-c", shell], capture_output=True,
                           text=True, timeout=check.get("timeout", CMD_TIMEOUT))
    except subprocess.TimeoutExpired:
        return "fail", f"timeout >{check.get('timeout', CMD_TIMEOUT)}s"
    out = (r.stdout or "") + (r.stderr or "")
    expect_exit = check.get("expect_exit", 0)
    if r.returncode != expect_exit:
        return "fail", f"exit {r.returncode} (want {expect_exit}): {out.strip()[-160:]}"
    expect_re = check.get("expect_re")
    if expect_re and not re.search(expect_re, r.stdout or ""):
        return "fail", f"stdout missing /{expect_re}/: {(r.stdout or '').strip()[-160:]}"
    return "pass", (r.stdout or "").strip()[:160]


def run_systemd(check):
    """type: systemd — unit expected active/enabled at user or system scope."""
    unit = check.get("unit")
    scope = check.get("scope", "user")
    expect = check.get("expect", "active")
    verb = "is-enabled" if expect == "enabled" else "is-active"
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + [verb, unit]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "error", "systemctl timeout"
    got = (r.stdout or "").strip() or (r.stderr or "").strip()
    if r.returncode == 0:
        return "pass", f"{unit} {got or expect} ({scope})"
    return "fail", f"{unit} {verb} -> {got or f'rc={r.returncode}'} ({scope})"


def run_http(check):
    """type: http — URL expected to answer with a status code."""
    url = check.get("url")
    expect = check.get("expect_status", 200)
    timeout = check.get("timeout", 10)
    ctx = None
    if check.get("verify_tls") is False:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "post-restart-verify/1"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        return "fail", f"{url} unreachable: {e}"
    ok = code in expect if isinstance(expect, list) else code == expect
    return ("pass" if ok else "fail"), f"{url} -> HTTP {code} (want {expect})"


def run_file(check):
    """type: file — file contents match a literal or regex."""
    path = Path(os.path.expanduser(check.get("path", "")))
    try:
        text = path.read_text().strip()
    except Exception as e:
        return "fail", f"{path}: {e}"
    if check.get("expect") is not None:
        ok = text == str(check["expect"])
        return ("pass" if ok else "fail"), f"{path} = {text!r} (want {check['expect']!r})"
    if check.get("expect_re"):
        ok = re.search(check["expect_re"], text) is not None
        return ("pass" if ok else "fail"), f"{path} = {text[:80]!r} (want /{check['expect_re']}/)"
    return "pass", f"{path} readable"


def run_mount(check):
    """type: mount — a mount matching pattern exists in /proc/mounts."""
    pat = check.get("expect_re") or check.get("pattern") or check.get("path")
    try:
        mounts = Path("/proc/mounts").read_text()
    except Exception as e:
        return "error", f"/proc/mounts: {e}"
    hit = [l.split()[1] for l in mounts.splitlines() if re.search(pat, l)]
    return ("pass" if hit else "fail"), \
        (f"mounted: {', '.join(hit[:4])}" if hit else f"no mount matching /{pat}/")


def run_failed_units(check):
    """type: failed_units — list systemd units in failed state (scope)."""
    scope = check.get("scope", "user")
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + [
        "list-units", "--state=failed", "--no-legend", "--plain"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "error", "systemctl timeout"
    units = [l.split()[0] for l in (r.stdout or "").splitlines() if l.strip()]
    ignore = [re.compile(p) for p in check.get("ignore_re", [])]
    units = [u for u in units if not any(p.search(u) for p in ignore)]
    if not units:
        return "pass", f"no failed {scope} units"
    return "fail", f"failed {scope} units: {', '.join(units[:8])}"


def run_podman(check):
    """type: podman — named containers present in `podman ps`."""
    try:
        r = subprocess.run(["podman", "ps", "--format", "{{.Names}}"],
                           capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return "error", "podman not installed"
    except subprocess.TimeoutExpired:
        return "error", "podman ps timeout"
    running = (r.stdout or "").splitlines()
    missing = [c for c in check.get("containers", [])
               if not any(re.search(c, n) for n in running)]
    if not missing:
        return "pass", f"containers up: {', '.join(running[:8]) or 'none'}"
    return "fail", f"not running: {', '.join(missing)} (up: {', '.join(running[:8]) or 'none'})"


CHECK_TYPES = {
    "command": run_cmd,
    "systemd": run_systemd,
    "http": run_http,
    "file": run_file,
    "mount": run_mount,
    "failed_units": run_failed_units,
    "podman": run_podman,
}


def run_checks(checks):
    results = []
    for c in checks:
        cid = c.get("id", "?")
        ctype = c.get("type", "command")
        sev = c.get("severity", "must")
        fn = CHECK_TYPES.get(ctype)
        if not fn:
            status, evidence = "error", f"unknown check type {ctype!r}"
        else:
            try:
                status, evidence = fn(c)
            except Exception as e:
                status, evidence = "error", f"{type(e).__name__}: {e}"
        results.append({
            "id": cid,
            "label": c.get("label", cid),
            "type": ctype,
            "severity": sev,
            "status": status,
            "evidence": evidence,
        })
        log(f"  [{status:>4}] ({sev}) {cid}: {evidence}")
    return results


def post_inbox(host, boot_id, results):
    """One aggregate focus-inbox finding per boot per changed fail-set."""
    fails = [r for r in results if r["status"] in ("fail", "error")]
    if not fails:
        return False
    must = [r for r in fails if r["severity"] == "must"]
    if not must:
        return False  # warn-only findings stay in the report, no inbox noise
    marker = STATE_DIR / f"inbox-{host}-{boot_id[:8]}.json"
    fp = "|".join(sorted(f"{r['id']}:{r['status']}" for r in must))
    if marker.exists():
        try:
            if json.loads(marker.read_text()).get("fp") == fp:
                log("inbox finding already posted for this boot/fail-set")
                return False
        except Exception:
            pass
    lines = "; ".join(f"{r['id']}: {r['evidence'][:90]}" for r in must)
    warns = [r for r in fails if r["severity"] != "must"]
    body = {
        "from": "devin",
        "label": "post-restart-verify",
        "text": (f"Post-restart verification on {host} (boot {boot_id[:8]}): "
                 f"{len(must)} must-check(s) failed — {lines[:900]}"
                 + (f" | +{len(warns)} warn" if warns else "")),
        "priority": "high",
        "tags": ["ops", "post-restart", host],
        "session": "post-restart-verify",
    }
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        log(f"inbox post failed (report still written): {e}")
        return False
    marker.write_text(json.dumps({"fp": fp, "at": now_iso()}))
    log("posted focus-inbox finding")
    return True


def write_report(host, boot_id, results, started):
    fails = [r for r in results if r["status"] in ("fail", "error")]
    must = [r for r in fails if r["severity"] == "must"]
    overall = "fail" if must else ("warn" if fails else "pass")
    report = {
        "check": "transition.post_restart",
        "host": host,
        "boot_id": boot_id,
        "started_at": started,
        "finished_at": now_iso(),
        "overall": overall,
        "totals": {
            "pass": sum(1 for r in results if r["status"] == "pass"),
            "warn_or_fail": len(fails),
            "must_failed": len(must),
        },
        "checks": results,
        "check_only": True,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"post-restart-verify-{host}-{boot_id[:8]}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    (REPORT_DIR / "post-restart-verify-latest.json").write_text(
        json.dumps(report, indent=2) + "\n")
    log(f"report: {out} (overall={overall})")
    return report


def append_timeline(host, report, duration_ms):
    try:
        TIMELINE.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "name": "post-restart-verify",
            "command": f"post-restart-verify.py --host {host}",
            "ok": report["overall"] != "fail",
            "exit_code": 0,
            "duration_ms": duration_ms,
            "ts": now_iso(),
            "host": host,
            "overall": report["overall"],
            "boot_id": report["boot_id"],
        }
        with open(TIMELINE, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:
        log(f"timeline append failed: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=socket.gethostname().split(".")[0],
                    help="hostname key for SSOT host_notes (default: local hostname)")
    ap.add_argument("--boot-id", help="override kernel boot-id (testing)")
    ap.add_argument("--force", action="store_true",
                    help="re-run the pass even if this boot was already verified")
    ap.add_argument("--dry-run", action="store_true",
                    help="run checks but do not write state/report/inbox")
    ap.add_argument("--exit-code", action="store_true",
                    help="exit 1 when must-severity checks fail (manual runs)")
    ap.add_argument("--ops", default=str(OPS_DEFAULT), help="ssot.operations.yml path")
    a = ap.parse_args()

    t0 = time.monotonic()
    started = now_iso()
    host = host_key(a.host)
    try:
        boot_id = read_boot_id(a.boot_id)
    except Exception as e:
        log(f"cannot read boot-id: {e}")
        return 1

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / "last-boot-id"
    last = state_file.read_text().strip() if state_file.exists() else None
    if last == boot_id and not a.force:
        log(f"boot {boot_id[:8]} already verified — nothing to do")
        return 0

    try:
        auto, checks = load_checks(a.ops, host)
    except Exception as e:
        log(f"cannot load checks from {a.ops}: {e}")
        return 1

    if not checks:
        log(f"{host} not in post-restart-verify scope (ssot.operations.yml "
            f"automation.post_restart_verify) — skipping")
        return 0

    log(f"running post-restart verification for {host} (boot {boot_id[:8]}, "
        f"{len(checks)} checks, check-only)")
    results = run_checks(checks)

    if a.dry_run:
        fails = [r for r in results if r["status"] in ("fail", "error")]
        log(f"dry-run complete: {len(fails)} failing check(s); no state/report/inbox writes")
        return 1 if (a.exit_code and any(r["severity"] == "must" for r in fails)) else 0

    report = write_report(host, boot_id, results, started)
    post_inbox(host, boot_id, results)
    state_file.write_text(boot_id + "\n")
    append_timeline(host, report, int((time.monotonic() - t0) * 1000))
    return 1 if (a.exit_code and report["overall"] == "fail") else 0


if __name__ == "__main__":
    sys.exit(main())
