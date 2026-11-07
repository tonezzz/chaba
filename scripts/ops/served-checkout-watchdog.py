#!/usr/bin/env python3
"""served-checkout watchdog (OPS-1117).

Watches the single-writer checkout ~/CascadeProjects/chaba-tony-dell on
idc03 — the tree kanban-commit.timer commits card writes into and
board-api saves through. OPS-1075 lesson: board-api write latency
tracks served-checkout health. The OPS-1074 divergence (~2300 ahead /
~1500 behind / one unresolved conflict) accumulated for days and was
only discovered via >60s write timeouts — nothing monitored it.

Checks (local git, no ssh — the subject is the checkout itself):
  * behind:   rev-list HEAD..origin/master > --behind-max (default 50)
              — pulls aren't landing (divergence / fetch failure)
  * ahead:    rev-list origin/master..HEAD > --ahead-max (default 200)
              — pushes aren't landing (single digits is normal churn)
  * dirty:    status --porcelain lines > --dirty-max (default 50)
              — writer churn is single digits; dozens = incident mess
  * unmerged: ls-files -u count > 0 — unresolved conflict; a pull died
              mid-merge. Always alerts.

A best-effort `git fetch` runs first so `behind` is measured against a
fresh ref (fetch never touches the worktree; failure just means we
measure against the last-known ref).

Alert channel: board-api /inbox (same door as system-report-watchdog) —
a deduped focus-inbox entry that surfaces in the daily brief. Dedupe
per condition, at most once per --repeat-h (default 12h). Recovery is
silent + journaled, matching the inbox's no-resolve semantics.

Exit 0 healthy, 1 when alerting (service-failure semantics so the unit
shows in `systemctl --user failed` too).
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

SERVED = Path.home() / "CascadeProjects/chaba-tony-dell"
BOARD_API = "https://idc03.taila0626a.ts.net:10000"
STATE = Path.home() / ".local/state/served-checkout-watchdog.json"
GIT_TIMEOUT = 30
LABEL = "Served checkout unhealthy — idc03 writer"
TAGS = ["ops", "monitor", "served-checkout", "ops-1117"]


def git(repo: Path, *args: str,
        timeout: int = GIT_TIMEOUT) -> tuple[str, str | None]:
    """(stdout, error) for `git -C <repo> <args>`."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True,
                           timeout=timeout)
    except Exception as e:
        return "", f"git {' '.join(args)} failed: {e}"
    if r.returncode != 0:
        return "", (f"git {' '.join(args)} rc={r.returncode}: "
                    f"{(r.stderr or '').strip()[:200]}")
    return r.stdout.strip(), None


def count(out: str) -> int:
    return int(out) if out.isdigit() else -1


def collect(repo: Path) -> tuple[dict, str | None]:
    """All metrics in one pass. (metrics, fatal_error)."""
    git(repo, "fetch", "-q", "--no-tags", "origin",
        timeout=20)  # best-effort
    m = {}
    out, err = git(repo, "rev-list", "--count", "HEAD..origin/master")
    if err:
        return m, err
    m["behind"] = count(out)
    out, err = git(repo, "rev-list", "--count", "origin/master..HEAD")
    if err:
        return m, err
    m["ahead"] = count(out)
    out, err = git(repo, "status", "--porcelain")
    if err:
        return m, err
    m["dirty"] = len(out.splitlines()) if out else 0
    out, err = git(repo, "ls-files", "-u")
    if err:
        return m, err
    m["unmerged"] = len(out.splitlines()) if out else 0
    return m, None


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"conditions": {}}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st))


def recently_alerted(st: dict, cond: str, repeat_h: float) -> bool:
    at = st.get("conditions", {}).get(cond)
    if not at:
        return False
    try:
        return (dt.datetime.now(dt.timezone.utc)
                - dt.datetime.fromisoformat(at)).total_seconds() < repeat_h * 3600
    except Exception:
        return False


def file_inbox(text: str) -> bool:
    body = {"text": text, "label": LABEL, "priority": "high",
            "tags": TAGS, "owner": "tony"}
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:
        sys.stderr.write(f"watchdog: inbox post failed: {e}\n")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--served-dir", default=str(SERVED),
                    help="served checkout path (testing override)")
    ap.add_argument("--behind-max", type=int, default=50)
    ap.add_argument("--ahead-max", type=int, default=200)
    ap.add_argument("--dirty-max", type=int, default=50)
    ap.add_argument("--repeat-h", type=float, default=12.0,
                    help="min hours between repeat alerts per condition")
    ap.add_argument("--no-alert", action="store_true",
                    help="check only, print verdict")
    args = ap.parse_args()

    served = Path(args.served_dir)
    m, err = collect(served)
    st = load_state()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rc = 0
    problems = []

    if err:
        problems.append(("unreachable", f"served checkout unreadable — {err}"))
    else:
        if m["unmerged"] > 0:
            problems.append((
                "unmerged",
                f"{m['unmerged']} unmerged path(s) — a pull died mid-merge. "
                "Resolve per git-safe-pull.sh / the single-writer rules."))
        if m["behind"] > args.behind_max:
            problems.append((
                "behind",
                f"{m['behind']} commits behind origin/master "
                f"(threshold {args.behind_max}) — pulls aren't landing."))
        if m["ahead"] > args.ahead_max:
            problems.append((
                "ahead",
                f"{m['ahead']} commits ahead of origin/master "
                f"(threshold {args.ahead_max}) — pushes aren't landing."))
        if m["dirty"] > args.dirty_max:
            problems.append((
                "dirty",
                f"{m['dirty']} dirty/untracked paths "
                f"(threshold {args.dirty_max}) — writer churn is normally "
                "single digits."))

    for cond, detail in problems:
        if recently_alerted(st, cond, args.repeat_h):
            print(f"alert suppressed (dedupe): {detail}")
            rc = 1
            continue
        text = (f"Served checkout {served} on idc03 is unhealthy: "
                f"{detail} Metrics: behind={m.get('behind')} "
                f"ahead={m.get('ahead')} dirty={m.get('dirty')} "
                f"unmerged={m.get('unmerged')}. Divergence made board-api "
                "writes take >60s last time (OPS-1074/1075) — check "
                "kanban-commit.timer and the checkout before writes "
                "degrade again.")
        if args.no_alert or file_inbox(text):
            st["conditions"][cond] = now
        print(f"ALERT: {detail}")
        rc = 1

    if not problems:
        print(f"ok — behind={m['behind']} ahead={m['ahead']} "
              f"dirty={m['dirty']} unmerged={m['unmerged']}")
        st["last_ok"] = now

    save_state(st)
    return rc


if __name__ == "__main__":
    sys.exit(main())
