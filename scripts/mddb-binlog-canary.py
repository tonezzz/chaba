#!/usr/bin/env python3
"""mddb binlog canary — flags sustained replication/binlog breaches to the focus inbox.

Runs inside the tony-dell chaba health loop (tony-dell-monitor.sh, 2-min timer).
GETs {url} (default http://<idc01>:11023/v1/replication/status) and flags when:

  - binlog_size_bytes > 1_073_741_824 (1 GiB)
  - current_lsn - binlog_oldest_lsn > 5_000_000
  - any followers[].status != "healthy"

A breach must persist for more than --breach-seconds (default 600 = 10 min)
before a focus-inbox item is written, and only one item is written per breach
episode (tracked in --state-file). Prints one JSON check-result line on stdout
in the same shape as the other tony-dell-monitor checks; the caller folds it
into the monitor log. file:// URLs are accepted for testing.
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
DEFAULT_URL = "http://100.74.146.0:11023/v1/replication/status"
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


def evaluate(data):
    """Return (reasons, metrics). reasons is empty when healthy."""
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
    for i, f in enumerate(followers):
        if not isinstance(f, dict):
            continue
        if f.get("status") != "healthy":
            name = f.get("node_id") or f.get("id") or f.get("name") or f"index {i}"
            unhealthy.append(name)
            reasons.append(f"follower {name} status={f.get('status')!r}")
    metrics["followers_seen"] = len(followers)
    metrics["followers_unhealthy"] = len(unhealthy)
    return reasons, metrics


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


def existing_inbox(inbox_dir):
    for p in inbox_dir.glob("*.yml"):
        if p.name.startswith("TEMPLATE"):
            continue
        if p.name.endswith("-health.yml") and INBOX_STEM in p.name:
            return p
    return None


def dump_yaml(item):
    try:
        import yaml
        return yaml.safe_dump(item, sort_keys=False, allow_unicode=True, width=120)
    except ImportError:
        # JSON is a valid YAML subset; safe fallback when pyyaml is absent.
        return json.dumps(item, indent=2, ensure_ascii=False) + "\n"


def make_inbox_item(reasons, metrics, breach_secs, now):
    ts = ts_iso(now)
    return {
        "title": "Focus Inbox Item",
        "subtitle": "Health alert for mddb binlog (replication canary)",
        "focus": {
            "label": "mddb-binlog health",
            "text": (
                f"mddb binlog canary on tony-dell flagged a sustained breach "
                f"({int(breach_secs)}s > 600s) at {ts}. Reasons: {'; '.join(reasons)}. "
                f"binlog_size_bytes={metrics.get('binlog_size_bytes')}, "
                f"lsn_gap={metrics.get('lsn_gap')} "
                f"(current_lsn={metrics.get('current_lsn')} - "
                f"binlog_oldest_lsn={metrics.get('binlog_oldest_lsn')}). "
                "The retention janitor on idc01 may have stalled — check "
                "mddb.service before the disk fills."
            ),
            "status": "draft",
            "priority": "high",
            "tags": ["health", "inbox", "mddb", "binlog"],
            "missing_info": [
                "Is the retention janitor still running on idc01 (journalctl --user -u mddb.service)?",
                "Is the tony-dell follower (100.68.142.13:11023) still connected and caught up?",
            ],
        },
        "source": {"session": "mddb-binlog-canary", "date": ts[:10]},
    }


def write_inbox(inbox_dir, reasons, metrics, breach_secs, now):
    path = inbox_dir / f"{now.strftime('%Y-%m-%d-%H%M%S')}-{INBOX_STEM}-health.yml"
    path.write_text(dump_yaml(make_inbox_item(reasons, metrics, breach_secs, now)))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--inbox-dir", default=None,
                        help="focus-inbox dir; autodetected from ~/CascadeProjects/chaba* if omitted")
    parser.add_argument("--breach-seconds", type=float, default=600,
                        help="sustained-breach duration before alerting (default 600s)")
    args = parser.parse_args()

    now = utcnow()
    result = {
        "timestamp": ts_iso(now),
        "service": "mddb-binlog",
        "source": "idc01",
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

    reasons, metrics = evaluate(data)
    result["metrics"] = metrics

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

        if breach_secs > args.breach_seconds and not state.get("alerted"):
            inbox_dir = find_inbox_dir(args.inbox_dir)
            existing = existing_inbox(inbox_dir) if inbox_dir else None
            if existing:
                result["detail"] += f" | inbox already open: {existing.name}"
                state["alerted"] = True
            elif inbox_dir:
                try:
                    path = write_inbox(inbox_dir, reasons, metrics, breach_secs, now)
                    result["detail"] += f" | inbox written: {path.name}"
                    result["alerted"] = True
                    state["alerted"] = True
                    state["alerted_at"] = ts_iso(now)
                    state["alerted_file"] = path.name
                except Exception as e:
                    result["detail"] += f" | inbox write failed: {e}"
            else:
                result["detail"] += " | no focus-inbox dir found"
    else:
        state["breach_since_epoch"] = None
        state["breach_since"] = None
        state["alerted"] = False
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
