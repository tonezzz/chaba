#!/usr/bin/env python3
"""Read-only Chaba memory/feed freshness check.

Checks timer/service, context/session-memory freshness, feed inputs, hook
markers, and helper presence. No writes, no fake events.

Modes: --hosts all (default fleet fanout over SSH), --hosts local, or a
comma-separated host list. JSON via --json; exit 0 unless any host is ERROR.
"""
from __future__ import annotations

import argparse, json, os, re, shlex, subprocess, sys, time
from datetime import datetime, timezone

DEFAULT_HOSTS = ["tony-dell", "tony-omen", "idc03"]
HOOKS = [
    "~/.config/devin/scripts/devin-session-end.sh",
    "~/.config/devin/scripts/notebooklm-compaction.sh",
    "~/.config/devin/scripts/notebooklm-recall.sh",
]
# rendered outputs (required)
FILES = {
    "context": "~/.local/share/chaba/context.md",
    "session_memory": "~/.local/share/devin/notebook-summaries/session-memory.md",
}
# feed inputs (hide_empty sources — absence is normal, age is evidence)
FEED_INPUTS = {
    "events": "~/.local/share/chaba/events.md",
    "immediate": "~/.local/share/chaba/immediate.yml",
    "recent_events": "~/.local/share/chaba/recent-events.yml",
}
MARKERS = {
    "devin-session-end.sh": "Phase B+ session capture",
    "notebooklm-compaction.sh": "Phase B+ session capture (compaction",
    "notebooklm-recall.sh": "CHABA_CONTEXT",
}
SESSION_MEMORY_TAIL = 400


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
    rc, out = sh(f"test -e {q} && echo yes || echo no", host)
    return "yes" in out


def age_h(epoch: int | None) -> float | None:
    if epoch is None:
        return None
    return round((time.time() - epoch) / 3600, 2)


def reachable(host: str | None) -> tuple[bool, str]:
    if not host or host in ("local", "localhost"):
        return True, ""
    rc, out = sh("echo chaba-freshness-ok", host, timeout=25)
    return rc == 0 and "chaba-freshness-ok" in out, out[:200]


def session_memory_markers(host: str | None) -> dict:
    """Scan the tail of session-memory.md for SessionEnd/Compaction headers."""
    p = FILES["session_memory"]
    q = _q(p, host)
    rc, out = sh(
        f"tail -n {SESSION_MEMORY_TAIL} {q} 2>/dev/null "
        "| grep -nE '^##[[:space:]]+(Session end|Compaction)' | tail -3",
        host,
    )
    found = []
    if rc == 0 and out:
        for line in out.splitlines():
            m = re.search(r"##\s+(Session end|Compaction)\s+(\S+)", line)
            if m:
                found.append({"kind": m.group(1), "name": m.group(2), "tail_line": line.split(":", 1)[0]})
    return {"found": found, "count_tail": len(found), "scanned_lines": SESSION_MEMORY_TAIL}


def service_state(host: str | None) -> dict:
    rc, out = sh(
        "systemctl --user show chaba-render-memory.service "
        "-p ActiveState -p ExecMainStatus -p ExecMainExitTimestamp -p Result "
        "--no-pager 2>&1 | head -8",
        host,
    )
    fields = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k.strip()] = v.strip()
    ts = fields.get("ExecMainExitTimestamp", "")
    return {
        "raw": out,
        "active_state": fields.get("ActiveState", ""),
        "last_exit_status": fields.get("ExecMainStatus", ""),
        "last_exit_at": ts,
        "result": fields.get("Result", ""),
    }


def check_host(host: str | None) -> dict:
    H = host or "local"
    res = {"host": H, "checks": {}, "issues": [], "status": "FRESH"}

    ok, probe = reachable(host)
    res["checks"]["reachable"] = ok
    if not ok:
        res["checks"]["probe"] = probe
        res["issues"].append(f"host unreachable via ssh ({probe or 'no output'})")
        res["status"] = "ERROR"
        return res

    # timer + last service run
    rc, out = sh("systemctl --user is-active chaba-render-memory.timer 2>&1 | tail -1", host)
    timer_active = rc == 0 and out.strip() == "active"
    svc = service_state(host)
    res["checks"]["timer_active"] = timer_active
    res["checks"]["render_service"] = svc
    if not timer_active:
        res["issues"].append("chaba-render-memory.timer not active")
    if svc["last_exit_status"] not in ("", "0"):
        res["issues"].append(
            f"chaba-render-memory.service last exit={svc['last_exit_status']} "
            f"at {svc['last_exit_at'] or '?'}"
        )

    # rendered outputs
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
    else:
        res["checks"]["session_memory_markers"] = session_memory_markers(host)

    # feed inputs — reported as evidence; absence is normal (hide_empty sources)
    feed = {}
    for k, p in FEED_INPUTS.items():
        ep = stat_epoch(p, host)
        feed[k] = {"exists": ep is not None or exists(p, host), "age_h": age_h(ep)}
    res["checks"]["feed_inputs"] = feed

    # freshness heuristic: context should not be much older than session_memory if session_memory is recent
    ca, sa = epochs.get("context"), epochs.get("session_memory")
    if ca and sa and sa - ca > 3600:
        res["issues"].append(f"context.md older than session-memory.md by {round((sa-ca)/3600,1)}h")
    if ca and age_h(ca) is not None and age_h(ca) > 48:
        res["issues"].append(f"context.md stale ({age_h(ca)}h old)")

    # session-memory tail should show capture markers when the feed is alive
    sm = res["checks"].get("session_memory_markers")
    if sm is not None and sm["count_tail"] == 0 and (age_h(sa) or 0) < 24 * 30:
        res["issues"].append(
            f"session-memory.md: no SessionEnd/Compaction markers in last {SESSION_MEMORY_TAIL} lines"
        )

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

    # status: ERROR when the pipeline is absent entirely or host is down;
    # STALE on any freshness/capture issue; FRESH otherwise.
    if not timer_active and not res["checks"]["helper_executable"]:
        res["status"] = "ERROR"
    elif res["issues"]:
        res["status"] = "STALE"
    return res


def main():
    ap = argparse.ArgumentParser(description="Read-only Chaba memory freshness check")
    ap.add_argument(
        "--hosts",
        default="all",
        help="'all' (default fleet), 'local', or comma-separated hosts",
    )
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()
    if args.hosts.strip().lower() in ("all", "fleet"):
        hosts = list(DEFAULT_HOSTS)
    else:
        hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    results = [check_host(h) for h in hosts]
    if args.json:
        print(json.dumps({"as_of": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2))
        return 0
    for r in results:
        print(f"== {r['host']} == {r['status']}")
        for k in ["timer_active", "helper_executable", "context_age_h", "session_memory_age_h"]:
            if k in r["checks"]:
                print(f"  {k}: {r['checks'][k]}")
        svc = r["checks"].get("render_service") or {}
        if svc:
            print(
                f"  render-service: state={svc.get('active_state')} "
                f"last_exit={svc.get('last_exit_status')} at {svc.get('last_exit_at') or '?'}"
            )
        feed = r["checks"].get("feed_inputs") or {}
        if feed:
            print("  feed-inputs: " + ", ".join(f"{k}={v['age_h']}h" for k, v in feed.items()))
        sm = r["checks"].get("session_memory_markers")
        if sm is not None:
            last = sm["found"][-1] if sm["found"] else None
            print(f"  session-memory markers(tail): {sm['count_tail']}" + (f" last={last['kind']} {last['name']}" if last else ""))
        for name, hr in r["checks"].get("hooks", {}).items():
            print(f"  hook {name}: present={hr['present']} marker={hr['marker']}")
        for i in r["issues"]:
            print(f"  - {i}")
    return 0 if all(r["status"] != "ERROR" for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
