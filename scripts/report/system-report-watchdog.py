#!/usr/bin/env python3
"""system-report freshness watchdog (KNB-0786).

Runs OUTSIDE the pipeline it watches: hourly timer on tony_dell, the
report chain lives on idc02. If the chain dies, this still fires —
that is the whole point (the Oct-19 freeze served 3-day-old data for
days with zero alerting).

Check: ssh into idc02 and read `generated_at` from the exec checkout's
system-report.yml — the same file report-api serves. Alerts when:
  * idc02 is unreachable over ssh, or
  * generated_at is missing/unparseable, or
  * generated_at is older than --stale-h (default 26h; daily 06:45 run
    + slack).

Alert channel: board-api /inbox (unified write door) — lands a
deduped focus-inbox entry that surfaces in the focus inbox and the
daily brief. Re-alerts at most once per --repeat-h (default 12h) for
the same condition; recovers silently (no resolve API — the next
healthy run just stops alerting, and a recovered stamp goes to the
journal).

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


def read_generated_at() -> tuple[str | None, str | None]:
    """(generated_at, error) — parse the yml line over ssh."""
    cmd = ["ssh", "-o", "BatchMode=yes",
           "-o", f"ConnectTimeout={SSH_TIMEOUT}", TARGET_HOST,
           f"grep -m1 '^generated_at' ~/{SUMMARY_REL}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=SSH_TIMEOUT + 10)
    except Exception as e:
        return None, f"ssh failed: {e}"
    if r.returncode != 0:
        return None, f"ssh rc={r.returncode}: {(r.stderr or '').strip()[:200]}"
    line = r.stdout.strip()
    # generated_at: '2026-10-23T06:55:47+07:00' (quoted or bare)
    val = line.split(":", 1)[1].strip().strip("'\"") if ":" in line else ""
    return (val or None), (None if val else f"unparseable line: {line[:120]}")


def age_hours(iso: str) -> float | None:
    try:
        t = dt.datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return None


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(cond: str) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(
        {"condition": cond,
         "alerted_at": dt.datetime.now(dt.timezone.utc).isoformat()}))


def recently_alerted(cond: str, repeat_h: float) -> bool:
    st = load_state()
    if st.get("condition") != cond or not st.get("alerted_at"):
        return False
    try:
        at = dt.datetime.fromisoformat(st["alerted_at"])
        return (dt.datetime.now(dt.timezone.utc)
                - at).total_seconds() < repeat_h * 3600
    except Exception:
        return False


def file_inbox(cond: str, findings: list[str]) -> bool:
    body = {
        "text": "System-report monitor is unhealthy: " + "; ".join(findings)
                + ". Page shows last-known data — verify the idc02 report "
                  "chain (chaba-system-report.service, chaba-report-api) "
                  "and the web-srv data sync.",
        "label": "Monitor stale — system-report pipeline",
        "priority": "high",
        "tags": ["ops", "monitor", "system-report", "knb-0786"],
        "owner": "tony",
    }
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

    gen, err = read_generated_at()
    findings = []
    if err:
        findings.append(f"idc02 unreachable/check failed — {err}")
        cond = "unreachable"
    else:
        h = age_hours(gen)
        if h is None:
            findings.append(f"generated_at unparseable: {gen!r}")
            cond = "unparseable"
        elif h > args.stale_h:
            findings.append(f"system-report data is {h:.1f}h old "
                            f"(generated_at {gen}, threshold {args.stale_h}h)")
            cond = f"stale:{gen}"
        else:
            print(f"ok — generated {h:.1f}h ago ({gen})")
            return 0

    if recently_alerted(cond, args.repeat_h):
        print(f"alerting suppressed (dedupe): {findings[0]}")
        return 1
    posted = args.no_alert or file_inbox(cond, findings)
    save_state(cond)
    print(f"ALERT{' (inbox filed)' if posted else ''}: {findings[0]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
