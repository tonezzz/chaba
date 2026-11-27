#!/usr/bin/env python3
"""Read-only Chaba memory/feed freshness check.

Checks timer/service, context/session-memory freshness, hook markers, and helper presence.
No writes, no fake events. Supports local mode and SSH fanout.
"""
from __future__ import annotations

import argparse, json, os, shlex, subprocess, sys, time
from datetime import datetime, timezone

DEFAULT_HOSTS = ["tony-dell", "tony-omen", "idc03"]
HOOKS = [
    "~/.config/devin/scripts/devin-session-end.sh",
    "~/.config/devin/scripts/notebooklm-compaction.sh",
    "~/.config/devin/scripts/notebooklm-recall.sh",
]
FILES = {
    "context": "~/.local/share/chaba/context.md",
    "events": "~/.local/share/chaba/events.md",
    "session_memory": "~/.local/share/devin/notebook-summaries/session-memory.md",
    "helper": "~/.local/bin/chaba-session-capture",
}
MARKERS = {
    "devin-session-end.sh": "Phase B+ session capture",
    "notebooklm-compaction.sh": "Phase B+ session capture (compaction",
    "notebooklm-recall.sh": "CHABA_CONTEXT",
}


def _q(path: str, host: str | None) -> str:
    if host and host not in ("local", "localhost"):
        # remote bash -lc: ~ expands when unquoted; these paths have no spaces
        return path
    return shlex.quote(os.path.expanduser(path))


def sh(cmd: str, host: str | None = None, timeout: int = 30) -> tuple[int, str]:
    if host and host not in ("local", "localhost"):
        pre = 'export HOME="${HOME:-$(getent passwd "$(id -un)" | cut -d: -f6)}" >/dev/null 2>&1; '
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, "bash", "-lc", pre + cmd]
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    else:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    return p.returncode, out.strip()


def stat_epoch(path: str, host: str | None) -> int | None:
    q = _q(path, host)
    rc, out = sh(f"stat -c %Y {q} 2>/dev/null || stat -f %m {q} 2>/dev/null", host)
    if rc == 0 and out.strip().isdigit():
        return int(out.strip())
    return None


def exists(path: str, host: str | None) -> bool:
    q = _q(path, host)
    rc, _ = sh(f"test -e {q} && echo yes || echo no", host)
    return "yes" in _


def age_h(epoch: int | None) -> float | None:
    if epoch is None:
        return None
    return round((time.time() - epoch) / 3600, 2)


def check_host(host: str | None) -> dict:
    H = host or "local"
    res = {"host": H, "checks": {}, "issues": [], "status": "FRESH"}
    # timer
    rc, out = sh("systemctl --user is-active chaba-render-memory.timer 2>&1 | tail -1", host)
    timer_active = rc == 0 and out.strip() == "active"
    rc2, out2 = sh("systemctl --user show chaba-render-memory.service -p ExecMainStatus -p ActiveState -p ExecMainExitTimestamp --no-pager 2>&1 | head -5", host)
    res["checks"]["timer_active"] = timer_active
    res["checks"]["render_service"] = out2
    if not timer_active:
        res["issues"].append("chaba-render-memory.timer not active")

    # files
    epochs = {}
    for k, p in FILES.items():
        ep = stat_epoch(p, host)
        epochs[k] = ep
        res["checks"][f"{k}_exists"] = ep is not None or exists(p, host)
        res["checks"][f"{k}_age_h"] = age_h(ep)
    if not res["checks"]["context_exists"]:
        res["issues"].append("context.md missing")
    if not res["checks"]["session_memory_exists"]:
        res["issues"].append("session-memory.md missing")

    # freshness heuristic: context should not be much older than session_memory if session_memory is recent
    ca, sa = epochs.get("context"), epochs.get("session_memory")
    if ca and sa and sa - ca > 3600:
        res["issues"].append(f"context.md older than session-memory.md by {round((sa-ca)/3600,1)}h")
    if ca and age_h(ca) is not None and age_h(ca) > 48:
        res["issues"].append(f"context.md stale ({age_h(ca)}h old)")

    # hooks
    hook_res = {}
    for hp in HOOKS:
        name = os.path.basename(hp)
        present = exists(hp, host)
        marker = MARKERS.get(name)
        has_marker = False
        if present and marker:
            q = _q(hp, host)
            rc, out = sh(f"grep -F {shlex.quote(marker)} {q} >/dev/null && echo yes || echo no", host)
            has_marker = "yes" in out
        hook_res[name] = {"present": present, "marker": has_marker if marker else None}
        if not present:
            res["issues"].append(f"hook missing: {name}")
        elif marker and not has_marker:
            res["issues"].append(f"hook marker missing: {name}")
    res["checks"]["hooks"] = hook_res

    # helper
    rc, out = sh("test -x ~/.local/bin/chaba-session-capture && echo yes || echo no", host)
    res["checks"]["helper_executable"] = "yes" in out
    if "yes" not in out:
        res["issues"].append("chaba-session-capture helper missing/not executable")

    # status
    if any("missing" in i.lower() and "events" not in i.lower() for i in res["issues"]):
        # events.md missing is mild; others more serious
        serious = [i for i in res["issues"] if "events.md" not in i]
        res["status"] = "STALE" if serious else "FRESH"
    if any("not active" in i for i in res["issues"]):
        res["status"] = "STALE"
    if not timer_active and not res["checks"]["helper_executable"]:
        res["status"] = "ERROR"
    # refine: stale if context stale
    if any("context.md stale" in i or "older than session-memory" in i for i in res["issues"]):
        res["status"] = "STALE" if res["status"] == "FRESH" else res["status"]
    return res


def main():
    ap = argparse.ArgumentParser(description="Read-only Chaba memory freshness check")
    ap.add_argument("--hosts", default="local", help="Comma-separated hosts or 'local' (default: local)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()
    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    results = [check_host(h) for h in hosts]
    if args.json:
        print(json.dumps({"as_of": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2))
        return 0
    for r in results:
        print(f"== {r['host']} == {r['status']}")
        for k in ["timer_active", "helper_executable", "context_age_h", "session_memory_age_h", "events_age_h"]:
            if k in r["checks"]:
                print(f"  {k}: {r['checks'][k]}")
        for name, hr in r["checks"].get("hooks", {}).items():
            print(f"  hook {name}: present={hr['present']} marker={hr['marker']}")
        for i in r["issues"]:
            print(f"  - {i}")
    return 0 if all(r["status"] != "ERROR" for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
