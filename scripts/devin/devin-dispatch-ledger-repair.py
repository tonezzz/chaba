#!/usr/bin/env python3
"""devin-dispatch-ledger-repair — fix job/<id> docs stuck at status=running.

Root cause (2026-11-26 audit, card
investigate-devin-handoff-job-ledger-ter-408e7a): devin-dispatch-watch's
mddb_job() ended in `return 0`, so a failed /v1/add was indistinguishable
from a landed write — meta.json got notified_fu stamped anyway and the
terminal job/<id> doc was never retried. Hosts without the watch timer at
all (idc02/idc03/con01, and tony-dell whose timer is gone) never wrote
terminal docs either.

This script repairs the FIRST class on one host: task dirs whose
meta.json shows the watch already notified (notified_fu >= latest fu-*.txt)
but whose job/<id> ledger doc still says status=running. It rewrites the
doc with the terminal status the watch would have written.

It deliberately does NOT touch:
  - docs already terminal (done/failed/awaiting-user/superseded/answered)
  - docs that don't exist (the running write itself never landed — a
    different failure; counted as `missing`)
  - tasks with un-notified follow-ups (notified_fu < latest fu) — the
    watch owns those
  - runner-agent/claude-dispatch job docs (different writer, card-id keys)

Usage:
  python3 scripts/devin/devin-dispatch-ledger-repair.py            # dry-run
  python3 scripts/devin/devin-dispatch-ledger-repair.py --apply    # write

Env: MDDB_URL (default http://100.102.134.91:11023/v1),
     DISPATCH_DIR (default ~/.local/share/devin-dispatch).
"""

import argparse
import json
import os
import socket
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COLLECTION = "ada-ha-bank-devin-handoff"
TERMINAL = {"done", "failed", "awaiting-user", "superseded", "answered"}


def mddb_base() -> str:
    return os.environ.get(
        "MDDB_URL", "http://100.102.134.91:11023/v1").rstrip("/")


def post(path: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        mddb_base() + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def get_job(key: str):
    """-> (status, doc) ; status None when the doc doesn't exist."""
    try:
        doc = post("/get", {"collection": COLLECTION, "key": key,
                               "lang": "en", "include_content": False},
                   timeout=30)
    except Exception:
        return None, None
    if not doc:
        return None, None
    meta = doc.get("meta") or {}
    st = (meta.get("status") or [None])[0]
    return st, doc


def latest_fu(task_dir: Path) -> int:
    n = 0
    for f in task_dir.glob("fu-*.txt"):
        try:
            n = max(n, int(f.stem.split("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return n


def planned_status(task_dir: Path, meta: dict) -> str:
    if (task_dir / "needs-input.txt").exists():
        return "awaiting-user"
    return "done" if meta.get("result") == "success" else "failed"


def repair_doc(jid: str, status: str, meta: dict) -> dict:
    host = socket.gethostname()
    finished = meta.get("finished_at") or ""
    result = meta.get("result") or "unknown"
    m = {"kind": ["job"], "status": [status], "job_id": [jid],
         "host": [host],
         "ts": [finished or datetime.now(timezone.utc).isoformat()],
         "subject": ["job-" + jid],
         "source": ["devin-dispatch"],
         "written_by": ["devin-dispatch-ledger-repair"],
         "scope": ["tony"], "bank": ["devin-handoff"],
         "repaired_from": ["running"]}
    body = (f"Job {jid} on {host}: {status}.\n\n"
            "Repaired by devin-dispatch-ledger-repair: the watch had "
            "stamped meta.json notified_fu but the terminal job/<id> "
            f"write never landed (result={result}"
            + (f", finished_at={finished}" if finished else "") + ").")
    return {"collection": COLLECTION, "key": "job/" + jid, "lang": "en",
            "contentMd": body, "meta": m}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="write repairs (default is dry-run)")
    ap.add_argument("--task-root", default=os.path.expanduser(
        os.environ.get("DISPATCH_DIR",
                       "~/.local/share/devin-dispatch") + "/tasks"))
    args = ap.parse_args()

    root = Path(args.task_root)
    counts = {"checked": 0, "already_terminal": 0, "missing_doc": 0,
              "not_running": 0, "would_repair": 0, "repaired": 0,
              "skipped_pending": 0, "errors": 0}
    samples = []

    for mp in sorted(root.glob("*/meta.json")):
        d = mp.parent
        jid = d.name
        try:
            meta = json.loads(mp.read_text())
        except Exception:
            continue
        notified = meta.get("notified_fu")
        if notified is None:
            counts["skipped_pending"] += 1
            continue
        try:
            if int(notified) < latest_fu(d):
                counts["skipped_pending"] += 1
                continue
        except (TypeError, ValueError):
            counts["skipped_pending"] += 1
            continue
        if not meta.get("result"):
            counts["skipped_pending"] += 1
            continue
        counts["checked"] += 1

        status = planned_status(d, meta)
        try:
            cur, _ = get_job("job/" + jid)
        except Exception as exc:
            counts["errors"] += 1
            print(f"ERR {jid}: get failed: {exc}", file=sys.stderr)
            continue
        if cur is None:
            counts["missing_doc"] += 1
            continue
        if cur in TERMINAL:
            counts["already_terminal"] += 1
            continue
        if cur != "running":
            counts["not_running"] += 1
            continue

        if args.apply:
            try:
                post("/add", repair_doc(jid, status, meta), timeout=60)
                counts["repaired"] += 1
            except Exception as exc:
                counts["errors"] += 1
                print(f"ERR {jid}: add failed: {exc}", file=sys.stderr)
                continue
            time.sleep(0.1)
        else:
            counts["would_repair"] += 1
        if len(samples) < 10:
            samples.append({"id": jid, "to": status,
                            "result": meta.get("result"),
                            "finished_at": meta.get("finished_at")})

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"{mode} {root}")
    for k in ("checked", "already_terminal", "missing_doc", "not_running",
              "would_repair", "repaired", "skipped_pending", "errors"):
        print(f"  {k}: {counts[k]}")
    for s in samples:
        print(f"  sample {s['id']} -> {s['to']} (result={s['result']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
