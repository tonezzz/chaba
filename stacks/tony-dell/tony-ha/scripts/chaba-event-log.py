#!/usr/bin/env python3
"""Append/ack events for the chaba-admin Events tab.

Store: /config/www/chaba-events.json (served at /local/chaba-events.json)
- JSON array, newest first
- Events older than 24h are pruned on every write
- Cap: 300 entries

Usage:
  chaba-event-log.py add '<json>'            # payload object or base64 via add -
  chaba-event-log.py add -                   # read JSON from stdin
  chaba-event-log.py ack <event-id>          # mark responded=true
  chaba-event-log.py list                    # print the current feed

Record fields (producers only need title):
  id, ts, source, category, severity, title, body, link,
  requires_response, responded, responded_ts, confidence
"""
import base64
import fcntl
import json
import os
import sys
import time
import uuid

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(BASE, "www", "chaba-events.json")
LOCK = FEED + ".lock"
MAX_AGE_S = 24 * 3600
MAX_EVENTS = 300


def _api_token():
    try:
        import yaml
        with open(os.path.join(BASE, "secrets.yaml")) as f:
            return (yaml.safe_load(f) or {}).get("chaba_event_api_token")
    except Exception:
        return None


def _run_action(ev):
    """Execute an approved event action: {'domain': d, 'service': s, 'data': {...}}"""
    act = ev.get("action")
    if not (isinstance(act, dict) and act.get("domain") and act.get("service")):
        return "no-action"
    token = _api_token()
    if not token:
        return "no-token"
    import urllib.request
    url = f"http://localhost:8123/api/services/{act['domain']}/{act['service']}"
    body = json.dumps(act.get("data") or {}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return f"action:{r.status}"
    except Exception as e:
        return f"action-fail:{e}"


def _load():
    try:
        with open(FEED) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _prune(events, now):
    cutoff = now - MAX_AGE_S
    out = []
    for e in events:
        try:
            ts = e.get("_epoch") or time.mktime(
                time.strptime(str(e.get("ts", ""))[:19], "%Y-%m-%dT%H:%M:%S")
            )
        except (ValueError, OverflowError):
            ts = now
        if ts >= cutoff:
            out.append(e)
    return out[:MAX_EVENTS]


def _write(events):
    tmp = FEED + ".tmp"
    with open(tmp, "w") as f:
        json.dump(events, f, indent=1)
        f.write("\n")
    os.replace(tmp, FEED)


def _payload(arg):
    if arg == "-":
        raw = sys.stdin.read()
    else:
        raw = arg
    raw = raw.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return json.loads(base64.b64decode(raw))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    os.makedirs(os.path.dirname(FEED), exist_ok=True)
    lock = open(LOCK, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        events = _load()
        now = time.time()
        if action == "add":
            p = _payload(sys.argv[2] if len(sys.argv) > 2 else "-")
            ts = p.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S%z")
            ev = {
                "id": p.get("id") or f"{int(now)}-{uuid.uuid4().hex[:8]}",
                "ts": ts,
                "_epoch": now,
                "source": str(p.get("source") or "manual")[:64],
                "category": str(p.get("category") or "system")[:32],
                "severity": p.get("severity")
                if p.get("severity") in ("info", "warn", "fail")
                else "info",
                "title": str(p.get("title") or "(untitled)")[:200],
                "body": str(p.get("body") or "")[:2000],
                "link": str(p.get("link") or "")[:300],
                "requires_response": bool(p.get("requires_response")),
                "responded": False,
            }
            if p.get("confidence") is not None:
                try:
                    ev["confidence"] = max(0.0, min(1.0, float(p["confidence"])))
                except (TypeError, ValueError):
                    pass
            act = p.get("action")
            if isinstance(act, dict) and act.get("domain") and act.get("service"):
                ev["action"] = {
                    "domain": str(act["domain"])[:32],
                    "service": str(act["service"])[:64],
                    "data": act.get("data") if isinstance(act.get("data"), dict) else {},
                }
            events = [ev] + _prune(events, now)
            _write(events)
            print(ev["id"])
            return 0
        if action in ("ack", "dismiss") and len(sys.argv) > 2:
            target = sys.argv[2]
            found = None
            for e in events:
                if e.get("id") == target:
                    e["responded"] = True
                    e["responded_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    found = e
            _write(_prune(events, now))
            if not found:
                print("not-found")
                return 1
            print("acked " + _run_action(found))
            return 0
        if action == "list":
            print(json.dumps(_prune(events, now), indent=1))
            return 0
        print(__doc__)
        return 2
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
