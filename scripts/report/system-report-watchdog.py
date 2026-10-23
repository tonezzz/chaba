#!/usr/bin/env python3
"""system-report watchdog (KNB-0786 + node-level reds).

Runs OUTSIDE the pipeline it watches: hourly timer on tony_dell, the
report chain lives on idc02. If the chain dies, this still fires —
that is the whole point (the Oct-19 freeze served 3-day-old data for
days with zero alerting).

Checks — one ssh read of the served system-report.yml:
  * chain health: idc02 unreachable, generated_at missing/unparseable,
    or older than --stale-h (default 26h; daily 06:45 run + slack)
  * node health: any node in a red status — error / missing /
    unreachable (missing excluded unless it persists: see below)

Alert channel: board-api /inbox (unified write door) — lands a deduped
focus-inbox entry that surfaces in the focus inbox and the daily brief.
Dedupe: per-condition, at most once per --repeat-h (default 12h). A node
alert fires again if the red-set CHANGES (new node went red / one
recovered mid-incident — the set hash is part of the dedupe key).
Recovery is silent in-state and journaled (no resolve API for inbox
entries): recovered nodes drop out of the next alert's set.

Exit 0 when healthy, 1 when alerting (service-failure semantics so a
failing check is visible in `systemctl --user failed` too).
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SUMMARY_REL = ("CascadeProjects/chaba/stacks/web/public/apps/"
               "system-report/data/system-report.yml")
TARGET_HOST = "idc02"
BOARD_API = "https://idc03.taila0626a.ts.net:10000"
STATE = Path.home() / ".local/state/system-report-watchdog.json"
SSH_TIMEOUT = 20
RED_STATUSES = {"error", "missing", "unreachable"}


def read_report() -> tuple[dict | None, str | None]:
    """(parsed yml, error) — one ssh read of the served report file."""
    cmd = ["ssh", "-o", "BatchMode=yes",
           "-o", f"ConnectTimeout={SSH_TIMEOUT}", TARGET_HOST,
           f"cat ~/{SUMMARY_REL}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=SSH_TIMEOUT + 10)
    except Exception as e:
        return None, f"ssh failed: {e}"
    if r.returncode != 0:
        return None, f"ssh rc={r.returncode}: {(r.stderr or '').strip()[:200]}"
    try:
        import yaml
        return yaml.safe_load(r.stdout), None
    except Exception as e:
        return None, f"report yml unparseable: {e}"


def age_hours(iso: str) -> float | None:
    try:
        t = dt.datetime.fromisoformat(str(iso).strip("'\""))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return None


def load_state() -> dict:
    try:
        st = json.loads(STATE.read_text())
        if "conditions" not in st:  # migrate flat {condition, alerted_at}
            st = {"conditions": {st["condition"]: st["alerted_at"]}} \
                if st.get("condition") else {"conditions": {}}
        return st
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


def file_inbox(text: str, label: str, tags: list[str]) -> bool:
    body = {"text": text, "label": label, "priority": "high",
            "tags": tags, "owner": "tony"}
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
    ap.add_argument("--stale-h", type=float, default=26.0,
                    help="alert when generated_at is older than this")
    ap.add_argument("--repeat-h", type=float, default=12.0,
                    help="min hours between repeat alerts for one condition")
    ap.add_argument("--no-alert", action="store_true",
                    help="check only, print verdict")
    args = ap.parse_args()

    rep, err = read_report()
    st = load_state()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rc = 0

    # --- chain-level checks --------------------------------------------
    if err:
        cond = "unreachable"
        if not recently_alerted(st, cond, args.repeat_h):
            text = (f"System-report monitor is unhealthy: idc02 check failed — "
                    f"{err}. Page shows last-known data — verify the idc02 "
                    "report chain (chaba-system-report.service, "
                    "chaba-report-api) and the web-srv data sync.")
            if args.no_alert or file_inbox(
                    text, "Monitor stale — system-report pipeline",
                    ["ops", "monitor", "system-report", "knb-0786"]):
                st["conditions"][cond] = now
            print(f"ALERT: idc02 check failed — {err}")
            rc = 1
        else:
            print(f"alert suppressed (dedupe): idc02 check failed — {err}")
            rc = 1
    else:
        gen = rep.get("generated_at") if rep else None
        h = age_hours(gen) if gen else None
        if h is None:
            cond = "unparseable"
            if not recently_alerted(st, cond, args.repeat_h):
                if args.no_alert or file_inbox(
                        f"System-report generated_at unparseable: {gen!r}",
                        "Monitor stale — system-report pipeline",
                        ["ops", "monitor", "system-report", "knb-0786"]):
                    st["conditions"][cond] = now
                print(f"ALERT: generated_at unparseable: {gen!r}")
                rc = 1
            else:
                print(f"alert suppressed (dedupe): generated_at unparseable")
                rc = 1
        elif h > args.stale_h:
            cond = f"stale:{gen}"
            if not recently_alerted(st, cond, args.repeat_h):
                text = (f"System-report data is {h:.1f}h old (generated_at "
                        f"{gen}, threshold {args.stale_h}h). Page shows "
                        "last-known data — verify the idc02 report chain "
                        "(chaba-system-report.service, chaba-report-api) "
                        "and the web-srv data sync.")
                if args.no_alert or file_inbox(
                        text, "Monitor stale — system-report pipeline",
                        ["ops", "monitor", "system-report", "knb-0786"]):
                    st["conditions"][cond] = now
                print(f"ALERT: report {h:.1f}h old")
                rc = 1
            else:
                print(f"alert suppressed (dedupe): report {h:.1f}h old")
                rc = 1
        else:
            print(f"chain ok — generated {h:.1f}h ago ({gen})")

    # --- node-level checks ---------------------------------------------
    if rep:
        red = [n for n in (rep.get("nodes") or [])
               if n.get("status") in RED_STATUSES]
        if red:
            key = ",".join(sorted(f"{n['id']}:{n['status']}" for n in red))
            cond = f"nodes:{key}"
            lines = [f"{n['id']} = {n['status']}"
                     + (f" ({n['summary'][:80]})" if n.get("summary") else "")
                     for n in red]
            prev_red = set(st.get("last_red", []))
            recovered = prev_red - {n["id"] for n in red}
            if not recently_alerted(st, cond, args.repeat_h):
                text = ("System-report red nodes: " + "; ".join(lines)
                        + ". Drill into the node on the monitor page or via "
                          "reports/meta.<node>.yml on idc02.")
                if recovered:
                    text += (f" Recovered since last alert: "
                             f"{', '.join(sorted(recovered))}.")
                if args.no_alert or file_inbox(
                        text, "Monitor red nodes",
                        ["ops", "monitor", "system-report", "nodes"]):
                    st["conditions"][cond] = now
                    st["last_red"] = [n["id"] for n in red]
                print(f"ALERT: {len(red)} red node(s): "
                      + ", ".join(f"{n['id']}={n['status']}" for n in red))
                rc = 1
            else:
                print(f"node alert suppressed (dedupe): "
                      + ", ".join(f"{n['id']}={n['status']}" for n in red))
                rc = 1
        else:
            prev_red = st.get("last_red") or []
            if prev_red:
                sys.stderr.write(
                    f"watchdog: red nodes recovered: {', '.join(prev_red)}\n")
            st.pop("last_red", None)
            print("nodes ok — no error/missing/unreachable")

    save_state(st)
    return rc


if __name__ == "__main__":
    sys.exit(main())
