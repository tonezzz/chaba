#!/usr/bin/env python3
"""mddb binlog canary — flags sustained replication/binlog breaches to the focus inbox.

Runs inside the tony-dell chaba health loop (tony-dell-monitor.sh, 2-min timer).
GETs {url} (default http://<idc03>:11023/v1/replication/status) and flags when:

  - binlog_size_bytes > 1_073_741_824 (1 GiB)
  - current_lsn - binlog_oldest_lsn > 5_000_000
  - any followers[].status != "healthy"

A breach must persist for more than --breach-seconds (default 600 = 10 min)
before a focus-inbox item is written. Alerts re-fire while a breach persists:
every --realert-seconds (default 43200 = 12 h) and immediately when the breach
set escalates (e.g. a second follower joins the unhealthy list — the reason set
changed since the last alert). Episode state lives in --state-file; a return to
healthy resets it. Prints one JSON check-result line on stdout in the same
shape as the other tony-dell-monitor checks; the caller folds it into the
monitor log. file:// URLs are accepted for testing.
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LIMIT_BINLOG_BYTES = 1_073_741_824  # 1 GiB
LIMIT_LSN_GAP = 5_000_000
SEEN_FRESH_SECONDS = 120   # leader last_seen_at younger than this = stream connected
DEFAULT_URL = "http://100.102.134.91:11023/v1/replication/status"
DEFAULT_STATE = Path.home() / "var/chaba/health/mddb-binlog-state.json"
INBOX_CANDIDATES = [
    # served checkout first — kanban-commit.timer only watches this repo
    Path.home() / "CascadeProjects/chaba-tony-dell/docs/ssot/focus-inbox",
    Path.home() / "CascadeProjects/chaba/docs/ssot/focus-inbox",
]
INBOX_STEM = "mddb-binlog"


def utcnow():
    return datetime.now(timezone.utc)


def ts_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url, timeout=6):
    """Return (http_code, data, elapsed_ms, error)."""
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or 200
            body = resp.read()
    except Exception as e:
        return 0, None, round((time.monotonic() - start) * 1000, 1), str(e)
    elapsed = round((time.monotonic() - start) * 1000, 1)
    if code != 200:
        return code, None, elapsed, f"unexpected http {code}"
    try:
        return code, json.loads(body), elapsed, None
    except Exception as e:
        return code, None, elapsed, f"invalid json: {e}"


def follower_key(f, i):
    return (f.get("follower_id") or f.get("node_id") or f.get("id")
            or f.get("name") or f"index {i}")


def evaluate(data, prev_followers, now_epoch, stall_seconds):
    """Return (reasons, metrics, followers_cur). reasons is empty when healthy.

    Beyond the static thresholds this surfaces the silent apply-stall
    signature per follower: confirmed_lsn unchanged across checks while the
    leader still sees the stream connected (last_seen_at fresh) and the
    follower is behind current_lsn. That is the freeze a human used to spot
    by comparing LSNs by hand; here it becomes an explicit reason +
    per-follower stream metrics. followers_cur is the per-follower snapshot
    the caller stores for the next run.
    """
    reasons = []
    metrics = {}
    size = data.get("binlog_size_bytes")
    cur = data.get("current_lsn")
    old = data.get("binlog_oldest_lsn")
    gap = cur - old if isinstance(cur, (int, float)) and isinstance(old, (int, float)) else None
    metrics.update({
        "binlog_size_bytes": size,
        "current_lsn": cur,
        "binlog_oldest_lsn": old,
        "lsn_gap": gap,
        "reported_healthy": data.get("healthy"),
    })
    if isinstance(size, (int, float)) and size > LIMIT_BINLOG_BYTES:
        reasons.append(f"binlog_size_bytes={size} > {LIMIT_BINLOG_BYTES}")
    if gap is not None and gap > LIMIT_LSN_GAP:
        reasons.append(f"lsn_gap={gap} > {LIMIT_LSN_GAP}")

    followers = data.get("followers") or []
    if isinstance(followers, dict):
        followers = list(followers.values())
    unhealthy = []
    followers_cur = {}
    stream_state = {}
    prev_followers = prev_followers or {}
    for i, f in enumerate(followers):
        if not isinstance(f, dict):
            continue
        name = follower_key(f, i)
        if f.get("status") != "healthy":
            unhealthy.append(name)
            reasons.append(f"follower {name} status={f.get('status')!r}")

        # Stream-state surfacing: track confirmed_lsn movement per follower.
        confirmed = f.get("confirmed_lsn")
        seen_at = f.get("last_seen_at")
        seen_age = (now_epoch - seen_at
                    if isinstance(seen_at, (int, float)) else None)
        connected = (seen_age is not None
                     and seen_age <= SEEN_FRESH_SECONDS)
        apply_lag = (cur - confirmed
                     if isinstance(cur, (int, float))
                     and isinstance(confirmed, (int, float)) else None)
        prev = prev_followers.get(name) or {}
        if (isinstance(confirmed, (int, float))
                and confirmed == prev.get("confirmed_lsn")
                and prev.get("frozen_since_epoch")):
            frozen_secs = now_epoch - prev["frozen_since_epoch"]
        else:
            frozen_secs = 0
        followers_cur[name] = {
            "confirmed_lsn": confirmed,
            "frozen_since_epoch": (prev.get("frozen_since_epoch")
                                   if frozen_secs else now_epoch),
        }
        stream_state[name] = {
            "confirmed_lsn": confirmed,
            "apply_lag_lsn": apply_lag,
            "last_seen_age_s": (round(seen_age, 1)
                                if seen_age is not None else None),
            "connected": connected,
            "frozen_seconds": int(frozen_secs),
        }
        if (connected and apply_lag is not None and apply_lag > 0
                and confirmed and frozen_secs > stall_seconds):
            reasons.append(
                f"follower {name} apply-stalled: confirmed_lsn={confirmed} "
                f"frozen {int(frozen_secs)}s while stream connected "
                f"(last_seen {round(seen_age, 1)}s ago), "
                f"lag={apply_lag} LSN — restart mddb-follower.service on "
                f"{name} (or let mddb-follower-watchdog.timer do it)")
    metrics["followers_seen"] = len(followers)
    metrics["followers_unhealthy"] = len(unhealthy)
    metrics["followers_stream"] = stream_state
    return reasons, metrics, followers_cur


def load_state(path):
    try:
        state = json.loads(Path(path).read_text())
        if isinstance(state, dict):
            return state
    except Exception:
        pass
    return {}


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def find_inbox_dir(explicit):
    if explicit:
        return Path(explicit)
    for d in INBOX_CANDIDATES:
        if d.is_dir():
            return d
    return None


def dump_yaml(item):
    try:
        import yaml
        return yaml.safe_dump(item, sort_keys=False, allow_unicode=True, width=120)
    except ImportError:
        # JSON is a valid YAML subset; safe fallback when pyyaml is absent.
        return json.dumps(item, indent=2, ensure_ascii=False) + "\n"


def make_inbox_item(reasons, metrics, breach_secs, now, escalation=None):
    ts = ts_iso(now)
    lead = "mddb binlog canary on tony-dell"
    if escalation == "recurring":
        lead += (f"re-alerted an ONGOING breach (open {int(breach_secs)}s; "
                 "re-alert cadence while unresolved)")
    elif escalation == "escalated":
        lead += ("flagged an ESCALATION — the breach set changed since the "
                 "last alert")
    else:
        lead += "flagged a sustained breach"
    return {
        "title": "Focus Inbox Item",
        "subtitle": "Health alert for mddb binlog (replication canary)",
        "focus": {
            "label": "mddb-binlog health",
            "text": (
                f"{lead} ({int(breach_secs)}s > 600s) at {ts}. "
                f"Reasons: {'; '.join(reasons)}. "
                f"binlog_size_bytes={metrics.get('binlog_size_bytes')}, "
                f"lsn_gap={metrics.get('lsn_gap')} "
                f"(current_lsn={metrics.get('current_lsn')} - "
                f"binlog_oldest_lsn={metrics.get('binlog_oldest_lsn')}). "
                "The retention janitor on idc03 may have stalled — check "
                "mddb.service before the disk fills. If a reason says "
                "'apply-stalled', that follower's stream is connected but "
                "not applying: restart mddb-follower.service on that host "
                "(mddb-follower-watchdog.timer automates it once installed)."
            ),
            "status": "draft",
            "priority": "high",
            "tags": ["health", "inbox", "mddb", "binlog"],
            "missing_info": [
                "Is the retention janitor still running on idc03 (journalctl --user -u mddb.service)?",
                "Are the idc02 (idc02:11023) and idc01 (idc01:11123) followers still connected and caught up?",
                "If apply-stalled: is confirmed_lsn advancing after a follower restart (watchdog logs/journal)?",
            ],
        },
        "source": {"session": "mddb-binlog-canary", "date": ts[:10]},
    }


def write_inbox(inbox_dir, reasons, metrics, breach_secs, now, escalation=None):
    inbox_dir.mkdir(parents=True, exist_ok=True)
    path = inbox_dir / f"{now.strftime('%Y-%m-%d-%H%M%S')}-{INBOX_STEM}-health.yml"
    path.write_text(dump_yaml(make_inbox_item(reasons, metrics, breach_secs,
                                              now, escalation)))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--inbox-dir", default=None,
                        help="focus-inbox dir; autodetected from ~/CascadeProjects/chaba* if omitted")
    parser.add_argument("--breach-seconds", type=float, default=600,
                        help="sustained-breach duration before alerting (default 600s)")
    parser.add_argument("--realert-seconds", type=float, default=43200,
                        help="re-alert cadence while a breach stays open (default 12h)")
    parser.add_argument("--stall-seconds", type=float, default=600,
                        help="confirmed_lsn frozen this long while connected "
                             "= apply-stalled reason (default 600s)")
    args = parser.parse_args()

    now = utcnow()
    result = {
        "timestamp": ts_iso(now),
        "service": "mddb-binlog",
        "source": "idc03",
        "action": "log",
        "url": args.url,
        "http_code": 0,
        "response_time_ms": None,
        "status": "unknown",
        "detail": "",
    }
    state = load_state(args.state_file)

    code, data, elapsed, err = fetch(args.url)
    result["http_code"] = code
    result["response_time_ms"] = elapsed

    if err:
        # Cannot observe the binlog — keep any in-flight breach timer paused
        # (neither reset nor advanced) so a flap can't hide a real breach.
        result["status"] = "error"
        result["detail"] = err
        state.update({"last_check": ts_iso(now), "last_status": "error", "last_error": err})
        save_state(args.state_file, state)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0

    reasons, metrics, followers_cur = evaluate(
        data, state.get("followers_prev"), now.timestamp(), args.stall_seconds)
    result["metrics"] = metrics
    state["followers_prev"] = followers_cur

    if reasons:
        if not state.get("breach_since_epoch"):
            state["breach_since_epoch"] = now.timestamp()
            state["breach_since"] = ts_iso(now)
            state["alerted"] = False
        breach_secs = now.timestamp() - state["breach_since_epoch"]
        result["status"] = "degraded"
        result["breach_seconds"] = int(breach_secs)
        result["breach_reasons"] = reasons
        result["detail"] = f"breach {int(breach_secs)}s: {'; '.join(reasons)}"

        if breach_secs > args.breach_seconds:
            # Alert policy (2026-10-07): the old one-shot latch swallowed real
            # episodes — a stale *-health.yml left in the inbox suppressed every
            # later write, so the idc03-migration follower outage never paged.
            # Now: page on first breach, re-page every --realert-seconds while
            # it stays open, and page immediately when the reason set changes
            # (escalation — e.g. a second follower goes unhealthy).
            alerted_reasons = state.get("alerted_reasons") or []
            first = not state.get("alerted")
            escalated = (not first
                         and sorted(reasons) != sorted(alerted_reasons))
            due = (not first
                   and now.timestamp() - (state.get("alerted_epoch") or 0)
                   > args.realert_seconds)
            if first or escalated or due:
                escalation = "new" if first else ("escalated" if escalated
                                                  else "recurring")
                inbox_dir = find_inbox_dir(args.inbox_dir)
                if inbox_dir:
                    try:
                        path = write_inbox(inbox_dir, reasons, metrics,
                                           breach_secs, now,
                                           None if first else escalation)
                        result["detail"] += (f" | inbox written ({escalation}): "
                                             f"{path.name}")
                        result["alerted"] = True
                        state["alerted"] = True
                        state["alerted_epoch"] = now.timestamp()
                        state["alerted_at"] = ts_iso(now)
                        state["alerted_file"] = path.name
                        state["alerted_reasons"] = list(reasons)
                    except Exception as e:
                        result["detail"] += f" | inbox write failed: {e}"
                else:
                    result["detail"] += " | no focus-inbox dir found"
    else:
        state["breach_since_epoch"] = None
        state["breach_since"] = None
        state["alerted"] = False
        state["alerted_reasons"] = []
        state.pop("alerted_epoch", None)
        result["status"] = "healthy"
        result["detail"] = (
            f"binlog_size_bytes={metrics.get('binlog_size_bytes')} "
            f"lsn_gap={metrics.get('lsn_gap')} "
            f"followers={metrics.get('followers_seen')}"
        )

    state.update({"last_check": ts_iso(now), "last_status": result["status"]})
    save_state(args.state_file, state)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
