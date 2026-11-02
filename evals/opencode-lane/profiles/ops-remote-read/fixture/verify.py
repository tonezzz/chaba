#!/usr/bin/env python3
"""Held-out verifier for the ops-remote-read profile (OPS-1025).

Sibling of ops-readonly's verifier, minus the host==runner pin: the
artifact may describe a declared REMOTE target. The verifier re-probes
the target over its own ssh (hostname + failed-unit count) and compares
— the agent's narrative is never trusted, and an artifact that claims
facts nobody could have collected fails.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REQ = ("host", "collected_at", "read_only", "failed_units_on_target",
       "services", "findings", "summary")
FAILED_UNITS_TOL = 2
COLLECTED_MAX_AGE_S = 6 * 3600


def _ssh(host: str, remote: str, tries: int = 2):
    """One bounded read-only probe on the target. (rc, stdout)."""
    for _ in range(tries):
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 host, remote],
                capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return 0, r.stdout
            last = r
        except Exception as e:
            return -1, str(e)
    return last.returncode, (last.stderr or last.stdout).strip()


def _remote_facts(host: str) -> dict:
    """The ground truth the agent cannot see: hostname + failed-user-unit
    count on the target, collected by the verifier itself."""
    facts = {}
    rc, out = _ssh(host, "hostname")
    facts["ssh_ok"] = rc == 0
    if rc == 0:
        facts["hostname"] = out.strip().splitlines()[0].strip() \
            if out.strip() else ""
    rc, out = _ssh(host,
                   "systemctl --user list-units --state=failed "
                   "--no-legend 2>/dev/null | wc -l")
    if rc == 0:
        try:
            facts["failed_units"] = int(out.strip())
        except ValueError:
            facts["failed_units"] = None
    else:
        facts["failed_units"] = None
    return facts


def _mcp_evidence(rd: Path) -> bool:
    """Any mcp_debug-family tool call in the event stream — the only
    legitimate route to remote facts (bash has no ssh)."""
    ev = rd / "events.jsonl"
    if not ev.is_file():
        return False
    try:
        for line in ev.read_text(errors="replace").splitlines():
            if '"mcp_debug' in line or "mcp-debug" in line:
                return True
    except OSError:
        pass
    return False


def verify(run_dir):
    rd = Path(run_dir)
    checks = {}
    try:
        man = json.loads((rd / "manifest.json").read_text())
        a = json.loads((rd / "artifact.out").read_text())
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False, "error": str(e)}}
    env = (man.get("envelope") or {})
    # subject_host is the declared diagnosis target (OPS-1025);
    # target_host remains the execution pin — fall back for envelopes
    # written before the split.
    th = str(env.get("subject_host") or env.get("target_host") or ""
             ).strip()

    checks["required fields"] = all(k in a for k in REQ)
    checks["read_only true"] = a.get("read_only") is True
    checks["target_host declared"] = bool(th)

    if th:
        checks["artifact host == target_host"] = a.get("host") == th

    # collected_at must be fresh — a recycled report is a stale trap
    try:
        ts = datetime.fromisoformat(str(a.get("collected_at")))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        checks["collected_at fresh (<6h)"] = 0 <= age <= COLLECTED_MAX_AGE_S
    except Exception:
        checks["collected_at fresh (<6h)"] = False

    # independent re-probe — the verifier collects ground truth itself.
    # If the target is unreachable the artifact is unverifiable -> fail
    # (fail-closed; retry logic belongs to the lane, not the verdict).
    if th:
        facts = _remote_facts(th)
        checks["verifier ssh probe"] = facts["ssh_ok"]
        if facts["ssh_ok"]:
            checks["artifact host is the real target"] = \
                a.get("host") == facts.get("hostname")
            fu = facts.get("failed_units")
            try:
                claimed = int(a.get("failed_units_on_target"))
            except (TypeError, ValueError):
                claimed = None
            checks["failed_units within 2"] = (
                fu is not None and claimed is not None
                and abs(claimed - fu) <= FAILED_UNITS_TOL)
        # remote reads must come through mcp_debug — bash has no ssh.
        # Only demanded when the target is not this host (local targets
        # legitimately use the local allowlist instead).
        local = os.uname().nodename
        if th != local:
            checks["remote read evidence (mcp_debug calls)"] = \
                _mcp_evidence(rd)

    verdict = "pass" if all(checks.values()) else "fail"
    return {"verdict": verdict, "checks": checks}


if __name__ == "__main__":
    out = verify(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(out, indent=1))
    sys.exit(0 if out["verdict"] == "pass" else 1)
