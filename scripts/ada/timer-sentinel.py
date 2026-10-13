#!/usr/bin/env python3
"""timer-sentinel.py — independent timer watchdog.

Runs under its own systemd timer (timer-sentinel.timer, 10min) — NOT a
chaba-jobs dispatcher job. A watchdog cannot depend on the thing it
watches (OPS-0531: dispatcher silently disabled for 2 days).

Reads the sweep state written by timer-timeline-update.py
(STATE_DIR/state.json), applies suspicion rules, and fires deterministic
kanban cards via board-api:

    timer-alert-<host>-<timer>   per-timer condition
    timer-alert-collector        sweep stale / collector dead
    timer-alert-host-<host>      host newly unreachable

Dedup: an open card with the same id is commented, never duplicated.
Also writes a heartbeat so drift-reconcile can catch a dead sentinel.

Env:
    BOARD_API       default http://127.0.0.1:8787 (loopback on tony-dell)
    TT_STATE_DIR    default ~/.local/share/chaba/timer-timeline
    REPO            default = this checkout root

Usage: timer-sentinel.py [--dry-run] [--inject <spec>]
    --inject disabled:tony-dell:chaba-jobs   synthetic fault for tests
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
BOARD_API = os.environ.get("BOARD_API", "http://127.0.0.1:8787").rstrip("/")
STATE_DIR = Path(os.environ.get(
    "TT_STATE_DIR", str(Path.home() / ".local/share/chaba/timer-timeline")))
STATE = STATE_DIR / "state.json"
HEARTBEAT = STATE_DIR / "sentinel-heartbeat.json"
SWEEP_STALE_MIN = 30
ACTOR = "devin"  # board-api allowlist: ada|chaba|devin|tony

# timers whose silence must always card — the load-bearing ones
CRITICAL = {"chaba-jobs", "kanban-commit", "kanban-dispatch",
            "timer-timeline-update", "timer-sentinel"}

# hosts that are EXPECTED to be off regularly — unreachable ≠ suspicious
OPTIONAL_HOSTS = {"tony-macbook"}


def api(path, payload=None, timeout=30):
    if payload is None:
        return json.load(urllib.request.urlopen(
            f"{BOARD_API}/{path}", timeout=timeout))
    req = urllib.request.Request(
        f"{BOARD_API}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def open_card_ids():
    """ids of cards not in a closed column."""
    try:
        data = api("cards")
    except Exception:
        return None  # board unreachable — sentinel is blind
    cards = data.get("cards", data) if isinstance(data, dict) else data
    out = set()
    for c in cards:
        col = str(c.get("column") or "").lower()
        if col not in ("done", "closed", "cancelled", "archive"):
            out.add(str(c.get("id")))
    return out


def fire(card_id, title, body, dry_run, open_ids):
    """Create card if no open one; else comment on it."""
    if open_ids is None:
        print(f"SKIP {card_id}: board unreachable")
        return
    if card_id in open_ids:
        if not dry_run:
            api("comment", {"id": card_id, "from": ACTOR,
                            "text": f"[still suspicious] {body}"})
        print(f"COMMENT {card_id}: {body[:80]}")
        return
    if not dry_run:
        api("card", {"id": card_id, "title": title, "column": "backlog",
                     "priority": "high", "from": ACTOR,
                     "tags": ["timer-alert", "auto", "by:timer-sentinel"],
                     "note": body})
    print(f"CARD {card_id}: {body[:80]}")


def _recent(last_us, now, hours=48):
    """A failed Result is sticky — only card it if the last run was
    recent (or the service sits in `failed` right now, handled by the
    caller). Ancient one-off failures shouldn't card forever."""
    if not last_us:
        return False
    age = now.timestamp() - last_us / 1e6
    return age < hours * 3600


def expected_timers():
    """{host: {timer_name: expected_state}} from audit census."""
    try:
        import yaml
        doc = yaml.safe_load(
            (REPO / "docs/ssot/infrastructure/ssot.audit.hosts.yml")
            .read_text()) or {}
        out = {}
        for host, blk in (doc.get("hosts") or {}).items():
            for e in (blk.get("expected_services") or []):
                name = str(e.get("name") or "")
                if name.endswith(".timer"):
                    out.setdefault(host, {})[name[:-6]] = str(
                        e.get("expected_state") or "active")
        return out
    except Exception as e:
        print(f"warn: audit census unreadable ({e})", file=sys.stderr)
        return {}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--inject", metavar="KIND:HOST:TIMER",
                    help="synthetic condition for verification")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    findings = []

    # --- load sweep state ---
    sweep = None
    sweep_age_min = None
    if STATE.exists():
        try:
            sweep = json.loads(STATE.read_text())
            ts = datetime.fromisoformat(sweep["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            sweep_age_min = (now - ts).total_seconds() / 60
        except Exception as e:
            findings.append(("timer-alert-collector",
                             "Timer timeline collector state unreadable",
                             f"state.json parse failed: {e}"))
    if sweep is None or sweep_age_min is None or \
            sweep_age_min > SWEEP_STALE_MIN:
        age = ("never ran" if sweep is None
               else f"{sweep_age_min:.0f}min ago")
        findings.append((
            "timer-alert-collector",
            "Timer timeline sweep stale — collector may be dead",
            f"Last successful sweep {age} (threshold {SWEEP_STALE_MIN}min). "
            f"Check chaba-timer-timeline.timer and "
            f"scripts/ada/timer-timeline-update.py on tony-dell."))

    expected = expected_timers()

    if sweep:
        host_ok = sweep.get("host_ok") or {}
        timers = sweep.get("timers") or {}
        for host, ok in host_ok.items():
            if not ok and host not in OPTIONAL_HOSTS:
                findings.append((
                    f"timer-alert-host-{host}",
                    f"Timer sweep cannot reach {host}",
                    f"{host} unreachable in the 15min timer sweep — "
                    f"timers there are unobserved (this is host-down or "
                    f"ssh-fail, not a timer failure)."))
        for host, tt in timers.items():
            for name, t in tt.items():
                cid = f"timer-alert-{host}-{name}"[:120]
                exp = (expected.get(host) or {}).get(name)
                enabled = str(t.get("enabled") or "")
                crit = name in CRITICAL or exp == "active"
                if enabled in ("disabled", "masked") and crit:
                    findings.append((
                        cid, f"Timer {name} on {host} disabled",
                        f"`{name}.timer` on `{host}` is {enabled} but "
                        f"expected active (audit census / critical list). "
                        f"Deliberate? If not: `systemctl --user enable "
                        f"--now {name}.timer`. See CMS `timer-timeline`."))
                elif enabled == "missing" and exp:
                    findings.append((
                        cid, f"Timer {name} on {host} missing",
                        f"`{name}.timer` on `{host}` declared in audit "
                        f"census but unit is absent. See CMS "
                        f"`timer-timeline`."))
                if t.get("failed_now") or (
                        t.get("result") in ("failed", "exit-code",
                                            "timeout") and
                        _recent(t.get("last_us"), now)):
                    when = t.get("last") or "?"
                    findings.append((
                        cid, f"Timer {name} on {host} failing",
                        f"Last run ({when}) of `{name}.service` on "
                        f"`{host}` result={t.get('result')} — "
                        f"investigate journal: `journalctl --user -u "
                        f"{name}.service` on the host. See CMS "
                        f"`timer-timeline-{host}`."))

    # synthetic fault for verification runs
    if args.inject:
        kind, host, name = args.inject.split(":", 2)
        cid = f"timer-alert-{host}-{name}"[:120]
        findings.append((cid, f"[synthetic] {kind} {name} on {host}",
                         f"Injected test condition: {kind}. This card "
                         f"proves the sentinel pipeline works; close it."))

    open_ids = open_card_ids()
    for cid, title, body in findings:
        fire(cid, title, body, args.dry_run, open_ids)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(json.dumps({
        "at": now.isoformat(timespec="seconds"),
        "findings": len(findings),
        "sweep_age_min": sweep_age_min,
        "cards_fired": [f[0] for f in findings],
    }, indent=1))
    print(f"timer-sentinel: {len(findings)} findings, "
          f"sweep_age={sweep_age_min and round(sweep_age_min)}min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
