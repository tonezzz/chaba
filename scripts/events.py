#!/usr/bin/env python3
"""Append-only event bus for the chaba orchestration system."""

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVENTS_FILE = REPO / "reports" / "EVENTS.jsonl"


def log_event(source, etype, severity, data, events_file=None):
    """Append a single event to the event log."""
    path = Path(events_file) if events_file else EVENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "type": etype,
        "severity": severity,
        "data": data,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str, separators=(",", ":")) + "\n")
    return event


def get_events(limit=100, severity=None, source=None, etype=None, events_file=None):
    """Read recent events, optionally filtered."""
    path = Path(events_file) if events_file else EVENTS_FILE
    if not path.exists():
        return []
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if severity and ev.get("severity") != severity:
                continue
            if source and ev.get("source") != source:
                continue
            if etype and ev.get("type") != etype:
                continue
            events.append(ev)
    return events[-limit:]


def get_unprocessed_events(last_ts=None, events_file=None):
    """Return events newer than last_ts."""
    events = get_events(limit=10000, events_file=events_file)
    if not last_ts:
        return events
    if isinstance(last_ts, str):
        from datetime import datetime as dt
        last_ts = dt.fromisoformat(last_ts)
    return [e for e in events if datetime.fromisoformat(e["ts"]) > last_ts]
