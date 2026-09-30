#!/usr/bin/env python3
"""Measure Ada's memory banks against docs/ssot/apps/ssot.apps.ada-memory-
standard.yml — writes one ops-event (memory_standard: PASS|VIOLATION) to
ada-ha-events-<instance> per run, and fires /api/notify when a breach
needs an owner decision. This is the loop-closing actuator: detection ->
ops event -> machine-voice notification -> owner chooses.

Run: python3 scripts/ada/memory-standard.py [--notify]
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1")
INSTANCE = os.environ.get("ADA_INSTANCE_ID", "tony")
OPS_COLLECTION = f"ada-ha-events-{INSTANCE}"
PROFILES = os.path.expanduser("~/.local/share/ada-pi/speaker_profiles.json")
NOTIFY_URL = os.environ.get(
    "ADA_NOTIFY_URL", "http://127.0.0.1:8002/api/notify")
NOTIFY_KEY = os.environ.get("ADA_API_KEY", "")

DRAFT_RATIO_MAX = 2.0
DRAFT_AGE_DAYS = 7
PHANTOM_PER_DAY = 20
CONFIRM_STRIP_PER_DAY = 30
MIN_PRINTS_AFTER_WEEK = 3


def _doc_time(d: dict) -> float:
    """Real event/doc time. addedAt is bulk-write time (imports stamp
    everything with the same value) — meta.ts holds the true timestamp."""
    ts = ((d.get("meta") or {}).get("ts") or [""])[0]
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return float(d.get("addedAt") or 0)


def _post(path: str, payload: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        MDDB + path, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _list_banks() -> list[str]:
    cfg = os.path.expanduser("~/.config/ada/memory-banks.json")
    try:
        banks = json.load(open(cfg)).get("banks") or {}
        return [b["mddb_collection"] for b in banks.values()
                if b.get("mddb_collection")]
    except Exception:
        return ["ada-ha-bank-general", "ada-ha-bank-people",
                "ada-ha-bank-purchase", "ada-ha-bank-personal-kk"]


def _docs(collection: str) -> list[dict]:
    return _post("/search", {"collection": collection, "limit": 2000,
                                "includeContent": False})


def main() -> int:
    notify = "--notify" in sys.argv
    violations: list[str] = []
    notes: list[str] = []

    # 1. lifecycle bars per bank
    for coll in _list_banks():
        try:
            docs = _docs(coll)
        except Exception as exc:
            violations.append(f"{coll}: unreadable ({exc})")
            continue
        status = {}
        oldest_draft = 0.0
        for d in docs:
            s = ((d.get("meta") or {}).get("status") or ["none"])[0]
            status[s] = status.get(s, 0) + 1
            if s == "draft":
                oldest_draft = max(oldest_draft,
                                   time.time() - _doc_time(d))
        active = status.get("active", 0)
        drafts = status.get("draft", 0)
        ratio = drafts / active if active else (0 if drafts == 0 else 99)
        line = (f"{coll.split('bank-')[-1]}: {active} active / "
                f"{drafts} draft / {status.get('superseded', 0)} superseded")
        if ratio > DRAFT_RATIO_MAX and drafts >= 3:
            violations.append(f"draft_ratio {line} = {ratio:.1f}x")
        if oldest_draft > DRAFT_AGE_DAYS * 86400:
            violations.append(
                f"{coll}: oldest draft {oldest_draft / 86400:.0f}d > "
                f"{DRAFT_AGE_DAYS}d")
        notes.append(line)

    # 2. superseded leaking through the recall path — probe with the same
    # status filter _bank_docs() uses; a leak here means mddb's filter is
    # broken, not that a consumer forgot it.
    try:
        res = _post("/vector-search", {
            "collection": "ada-ha-bank-people",
            "query": "household member", "topK": 5,
            "filterMeta": {"status": ["active", "draft"]},
            "includeContent": False})
        hits = res.get("results") or []
        leaked = [h["document"]["key"] for h in hits
                  if ((h.get("document") or {}).get("meta") or {})
                  .get("status") == ["superseded"]]
        if leaked:
            violations.append(
                f"superseded_in_filtered_results: {leaked[:3]}")
    except Exception as exc:
        violations.append(f"vector-search probe failed: {exc}")

    # 3. ops-event budgets (24h)
    try:
        ops = _docs(OPS_COLLECTION)
        day_ago = time.time() - 86400
        phantom = strip = 0
        for d in ops:
            if (d.get("meta") or {}).get("kind") != ["ops-event"]:
                continue
            if _doc_time(d) < day_ago:
                continue
            t = ((d.get("meta") or {}).get("type") or [""])[0]
            phantom += t == "phantom_write_claim"
            strip += t == "confirm_strip"
        if phantom > PHANTOM_PER_DAY:
            violations.append(f"phantom_write_claim {phantom}/24h > "
                              f"{PHANTOM_PER_DAY}")
        if strip > CONFIRM_STRIP_PER_DAY:
            violations.append(f"confirm_strip {strip}/24h > "
                              f"{CONFIRM_STRIP_PER_DAY}")
        notes.append(f"ops 24h: phantom={phantom} strip={strip}")
    except Exception as exc:
        notes.append(f"ops read failed: {exc}")

    # 4. speaker prints
    try:
        profs = json.load(open(PROFILES))
        for name, p in profs.items():
            if p.get("media"):
                continue
            n = p.get("samples") or len(p.get("prints") or []) or 1
            notes.append(f"speaker {name}: {n} prints")
    except OSError:
        notes.append("speaker profiles: unreadable")

    verdict = "PASS" if not violations else "VIOLATION"
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    md = (f"memory-standard {verdict} — {now}\n\n"
          + ("\n".join(f"- VIOLATION: {v}" for v in violations) + "\n"
             if violations else "")
          + "\n".join(f"- {n}" for n in notes))
    try:
        _post("/add", {
            "collection": OPS_COLLECTION,
            "key": f"ops-memory-standard-{now.replace(':', '')}",
            "lang": "en", "contentMd": md,
            "meta": {"kind": ["ops-event"], "type": ["memory_standard"],
                     "instance": [INSTANCE], "verdict": [verdict],
                     "ts": [now]}})
    except Exception as exc:
        print(f"ops write failed: {exc}", file=sys.stderr)

    print(md)
    if notify and violations:
        try:
            req = urllib.request.Request(
                NOTIFY_URL,
                data=json.dumps({
                    "text": f"Memory standard breach: {len(violations)} "
                            f"violation(s) — {violations[0][:80]}",
                    "urgent": False}).encode(),
                headers={"content-type": "application/json",
                         "x-api-key": NOTIFY_KEY}, method="POST")
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as exc:
            print(f"notify failed: {exc}", file=sys.stderr)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
