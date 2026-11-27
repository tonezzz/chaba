#!/usr/bin/env python3
"""Re-embed every mddb collection so the in-memory vector index is repopulated.

mddb loads its RAM vector index from the persisted `vectors` bucket at
startup — but any doc whose embedding was dropped (provider outage, queue
overflow, crash before flush) leaves the index incomplete, and plain
restarts have been observed to come up with `indexSize=0` even though
documents exist (2026-09-30). vector-reindex skips docs whose stored
content-hash already matches, so a full sweep is cheap once vectors are
healthy: the cost is one embedding call per missing/changed chunk.

Trigger paths:
  - mddb.container ExecStartPost (every start; skips already-embedded docs)
  - mddb-embed-probe.service when it sees indexSize≈0 or a down→up recovery
  - con01 mddb-vector-reindex.timer daily 05:40 (45-min unit budget)

Drives ASYNC reindex jobs (mddb >=2.18.4; deployed 2.18.10 verified
2026-11-27): POST /v1/vector-reindex {collection, async:true} -> 202
{jobId}, then poll GET /v1/vector-reindex/jobs/{id}. The HTTP request no
longer bounds the work, so the old 64 x sync-call timeout blowout
(OPS-1515) is gone. The sweep is still bounded client-side: collections
run in /v1/stats documentCount ASCENDING order (the 149k-doc
ada-ha-bank-devin-handoff last), no new jobs launch inside the last
MDDB_REINDEX_LAUNCH_MARGIN seconds of MDDB_REINDEX_SWEEP_BUDGET, and a
job still running at its deadline is marked deferred — jobs are
in-memory server-side and continue regardless; the next run attaches to
them via GET /v1/vector-reindex/jobs instead of hitting 409.

Writes ops-event docs to ada-ha-events-tony — the reindex itself must
stay on the leader :11023 (the ops instance has no vector index).
Per-collection failures emit immediately (an errors[] sample is kept —
the old sync path discarded it); one summary event lands at the end and
lists per-collection results plus unattempted/deferred collections
explicitly, so an incomplete sweep is never silent.

Env (all optional):
  MDDB_BASE_URL / MDDB_OPS_URL / ADA_OPS_COLLECTION  — unchanged
  MDDB_REINDEX_HEALTH_WAIT    health gate, seconds         (default 300)
  MDDB_REINDEX_SWEEP_BUDGET   total sweep window, seconds  (default 2400 —
                              inside the 45-min unit budget with margin)
  MDDB_REINDEX_LAUNCH_MARGIN  stop launching jobs this many seconds
                              before the sweep deadline    (default 300)
  MDDB_REINDEX_JOB_TIMEOUT    per-job poll deadline, secs  (default 900;
                              falls back to legacy MDDB_REINDEX_TIMEOUT)
  MDDB_REINDEX_POLL_INTERVAL  seconds between job polls    (default 15)
  NOTE: MDDB_REINDEX_MAX_CONCURRENT is deliberately unused — GO-054
  server-side slots need mddb >=2.19.8; deployed is 2.18.10 with
  unlimited concurrency, so this client keeps its own serialization.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# Reindex target stays the leader — the vector index only exists there
# (mddb-ops is no-embed by design). Ops-event emits go to mddb-ops.
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11023")
MDDB = MDDB.removesuffix("/v1").removesuffix("/")
MDDB_OPS = os.environ.get("MDDB_OPS_URL", "http://100.123.163.11:11025")
MDDB_OPS = MDDB_OPS.removesuffix("/v1").removesuffix("/")
EVENTS_COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
HEALTH_DEADLINE_S = int(os.environ.get("MDDB_REINDEX_HEALTH_WAIT", "300"))
SWEEP_BUDGET_S = int(os.environ.get("MDDB_REINDEX_SWEEP_BUDGET", "2400"))
LAUNCH_MARGIN_S = int(os.environ.get("MDDB_REINDEX_LAUNCH_MARGIN", "300"))
JOB_TIMEOUT_S = int(os.environ.get("MDDB_REINDEX_JOB_TIMEOUT")
                    or os.environ.get("MDDB_REINDEX_TIMEOUT") or "900")
POLL_INTERVAL_S = int(os.environ.get("MDDB_REINDEX_POLL_INTERVAL", "15"))
ACTIVE_STATUSES = ("queued", "running")


def _post(path: str, payload: dict, timeout: int = 30,
          attempts: int = 3, base: str = MDDB) -> dict:
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    err = None
    for attempt in range(attempts):
        try:
            return json.loads(urllib.request.urlopen(
                req, timeout=timeout).read())
        except Exception as exc:
            err = exc
            if attempt + 1 < attempts:
                time.sleep(2 * (attempt + 1))
    raise err


def _get(path: str, timeout: int = 30, attempts: int = 3) -> dict:
    err = None
    for attempt in range(attempts):
        try:
            return json.loads(urllib.request.urlopen(
                MDDB + path, timeout=timeout).read())
        except Exception as exc:
            err = exc
            if attempt + 1 < attempts:
                time.sleep(2 * (attempt + 1))
    raise err


def _emit(ev_type: str, detail: str, meta_extra: dict | None = None) -> None:
    now = datetime.now(timezone.utc).astimezone()
    meta = {"kind": ["ops-event"], "type": [ev_type],
            "instance": ["tony"], "session_id": ["vector-reindex"],
            "ts": [now.isoformat(timespec="seconds")]}
    if meta_extra:
        meta.update(meta_extra)
    try:
        _post("/v1/add", {
            "collection": EVENTS_COLLECTION,
            "key": f"ops-vector-reindex-{ev_type}-{now:%Y%m%d%H%M%S}-{int(now.timestamp()*1000)%100000}",
            "lang": "en", "contentMd": detail,
            "meta": meta,
        }, base=MDDB_OPS)
    except Exception as exc:
        print(f"ops event write failed: {exc}", file=sys.stderr)


def _wait_healthy() -> bool:
    deadline = time.time() + HEALTH_DEADLINE_S
    while time.time() < deadline:
        try:
            if _get("/v1/health", timeout=5).get("status") == "healthy":
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def _active_jobs() -> dict:
    """collection -> job summary for queued|running reindex jobs.

    Jobs are in-memory server-side; a leader restart forgets them, so a
    collection can also vanish between list and poll (handled as 'lost').
    """
    try:
        jobs = (_get("/v1/vector-reindex/jobs", timeout=15).get("jobs") or [])
    except Exception as exc:
        print(f"active-job list unavailable: {exc}", file=sys.stderr)
        return {}
    return {j["collection"]: j for j in jobs
            if j.get("collection") and j.get("status") in ACTIVE_STATUSES}


def _job_counts(job: dict) -> dict:
    """Normalize a job's result block; errors[] kept for failure events."""
    r = job.get("result") or {}
    errs = r.get("errors") or job.get("errors") or []
    if not isinstance(errs, list):
        errs = [errs]
    return {
        "total": int(r.get("total") or job.get("done") or 0),
        "embedded": int(r.get("embedded") or 0),
        "skipped": int(r.get("skipped") or 0),
        "failed": int(r.get("failed") or 0),
        "totalChunks": int(r.get("totalChunks") or 0),
        "errors": errs,
    }


def _poll_job(job_id: str, deadline: float) -> dict:
    """Poll a job until terminal status or `deadline` (epoch seconds).

    Returns the terminal job dict, or a synthetic {"status": ...} record:
      "deferred" — deadline hit while still queued/running; the job keeps
                   running server-side (no cancel endpoint exists).
      "lost"     — GET 404: leader restart forgot the in-memory job.
    Transient poll errors are tolerated until the deadline.
    """
    last_err = None
    while True:
        try:
            job = _get(f"/v1/vector-reindex/jobs/{job_id}", timeout=15)
            if job.get("status") not in ACTIVE_STATUSES:
                return job
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"jobId": job_id, "status": "lost",
                        "error": "job not found — leader restart forgets "
                                 "in-memory jobs"}
            last_err = exc
        except Exception as exc:
            last_err = exc
        if time.time() >= deadline:
            return {"jobId": job_id, "status": "deferred",
                    "error": (f"poll deadline reached"
                              + (f" (last poll error: {last_err})"
                                 if last_err else "")
                              + " — job continues server-side")}
        time.sleep(POLL_INTERVAL_S)


def _err_sample(errors: list, limit: int = 3, width: int = 160) -> str:
    sample = []
    for e in errors[:limit]:
        s = e if isinstance(e, str) else json.dumps(e, default=str)
        sample.append(s[:width])
    more = f" (+{len(errors) - limit} more)" if len(errors) > limit else ""
    return "; ".join(sample) + more


def _collection_failure(name: str, docs: int, job: dict) -> None:
    """Per-collection ops event the moment a job lands with failures —
    fires immediately, not batched into the end-of-sweep summary."""
    c = _job_counts(job)
    errs = c["errors"]
    detail = (f"{name} ({docs} docs): job {job.get('status')} — "
              f"embedded={c['embedded']} skipped={c['skipped']} "
              f"failed={c['failed']} totalChunks={c['totalChunks']}"
              + (f" jobError={str(job.get('error'))[:200]}"
                 if job.get("error") else "")
              + (f" | errors[{len(errs)}]: {_err_sample(errs)}"
                 if errs else ""))
    print(f"  {name}: FAILED — {detail}", file=sys.stderr)
    _emit("vector_reindex_failed", detail,
          meta_extra={"collection": [name]})


def main() -> int:
    started = time.time()
    sweep_deadline = started + SWEEP_BUDGET_S
    launch_deadline = sweep_deadline - LAUNCH_MARGIN_S
    if not _wait_healthy():
        print("mddb never became healthy — aborting reindex", file=sys.stderr)
        return 1
    collections = sorted(
        (c for c in (_get("/v1/stats").get("collections") or [])
         if c.get("name")),
        key=lambda c: int(c.get("documentCount") or 0))
    print(f"reindexing {len(collections)} collections via async jobs "
          f"(sweep budget {SWEEP_BUDGET_S}s, launch cutoff in "
          f"{max(0, launch_deadline - time.time()):.0f}s, "
          f"job timeout {JOB_TIMEOUT_S}s)")

    active = _active_jobs()
    if active:
        print(f"attaching to {len(active)} already-active job(s): "
              f"{', '.join(sorted(active))[:200]}")

    results = []
    totals = {"embedded": 0, "skipped": 0, "failed": 0}
    bad = []
    n_attached = n_launched = n_unattempted = n_deferred = 0

    for coll in collections:
        name = coll["name"]
        docs = int(coll.get("documentCount") or 0)
        rec = {"name": name, "docs": docs}
        results.append(rec)

        job = active.pop(name, None)
        if job is not None:
            rec["attached"] = True
            n_attached += 1
            print(f"  {name}: attaching to active job {job.get('jobId')}")
        else:
            if time.time() >= launch_deadline:
                rec["status"] = "unattempted"
                n_unattempted += 1
                continue
            try:
                job = _post("/v1/vector-reindex",
                            {"collection": name, "async": True}, timeout=30)
            except urllib.error.HTTPError as exc:
                if exc.code != 409:
                    rec["status"] = "error"
                    rec["reason"] = f"launch HTTP {exc.code}"
                    bad.append(f"{name}: {exc}")
                    print(f"  {name}: launch ERROR {exc}", file=sys.stderr)
                    continue
                # Lost a launch race — attach to the winner's job.
                job = _active_jobs().get(name)
                if job is None:
                    rec["status"] = "error"
                    rec["reason"] = "409 but no active job found"
                    bad.append(f"{name}: 409 no active job")
                    continue
                rec["attached"] = True
                n_attached += 1
                print(f"  {name}: 409 — attaching to {job.get('jobId')}")
            except Exception as exc:
                rec["status"] = "error"
                rec["reason"] = str(exc)[:200]
                bad.append(f"{name}: {exc}")
                print(f"  {name}: launch ERROR {exc}", file=sys.stderr)
                continue
            else:
                n_launched += 1

        job_id = job.get("jobId")
        if not job_id:
            rec["status"] = "error"
            rec["reason"] = "launch response missing jobId"
            bad.append(f"{name}: no jobId")
            continue

        if job.get("status") in ACTIVE_STATUSES or job.get("status") is None:
            wait_deadline = min(time.time() + JOB_TIMEOUT_S, sweep_deadline)
            job = _poll_job(job_id, wait_deadline)

        st = job.get("status")
        if st == "deferred":
            rec["status"] = "deferred"
            rec["reason"] = str(job.get("error"))[:200]
            n_deferred += 1
            print(f"  {name}: deferred — {rec['reason']}")
        elif st == "lost":
            rec["status"] = "error"
            rec["reason"] = str(job.get("error"))[:200]
            bad.append(f"{name}: {rec['reason']}")
        elif st == "failed":
            rec["status"] = "failed"
            rec["reason"] = str(job.get("error") or "job failed")[:300]
            bad.append(f"{name}: {rec['reason']}")
            _collection_failure(name, docs, job)
        else:
            c = _job_counts(job)
            rec.update({k: c[k] for k in
                        ("total", "embedded", "skipped", "failed",
                         "totalChunks")})
            rec["errors"] = c["errors"]
            for k in totals:
                totals[k] += c[k]
            if c["failed"] or c["errors"]:
                rec["status"] = "failed"
                bad.append(f"{name}:{c['failed']}"
                           + (f"+{len(c['errors'])}err" if c["errors"] else ""))
                _collection_failure(name, docs, job)
            else:
                rec["status"] = "ok"
            print(f"  {name}: embedded={c['embedded']} "
                  f"skipped={c['skipped']} failed={c['failed']} "
                  f"totalChunks={c['totalChunks']}"
                  + (" (attached)" if rec.get("attached") else ""))

    # ---- summary ops event: per-collection results + gaps explicit ----
    attempted = [r for r in results
                 if r.get("status") in ("ok", "failed")]
    lines = []
    for r in results:
        st = r.get("status")
        if st in ("ok", "failed") and "embedded" in r:
            lines.append(
                f"{r['name']}({r['docs']}d): e={r['embedded']} "
                f"s={r['skipped']} f={r['failed']}"
                + (" ERR" if st == "failed" else ""))
        elif st == "deferred":
            lines.append(f"{r['name']}({r['docs']}d): DEFERRED {r.get('reason','')[:80]}")
        elif st == "unattempted":
            lines.append(f"{r['name']}({r['docs']}d): UNATTEMPTED (launch deadline)")
        elif st == "error":
            lines.append(f"{r['name']}({r['docs']}d): ERROR {r.get('reason','')[:80]}")
        elif st == "failed":
            lines.append(f"{r['name']}({r['docs']}d): FAILED {r.get('reason','')[:80]}")
        else:
            lines.append(f"{r['name']}({r['docs']}d): {st}")
    unattempted = [r["name"] for r in results if r.get("status") == "unattempted"]
    deferred = [r["name"] for r in results if r.get("status") == "deferred"]
    detail = (
        f"vector-reindex sweep {'complete' if not unattempted and not deferred else 'PARTIAL'} — "
        f"collections={len(collections)} attempted={len(attempted)} "
        f"attached={n_attached} launched={n_launched} "
        f"deferred={n_deferred} unattempted={n_unattempted} | "
        f"embedded={totals['embedded']} skipped={totals['skipped']} "
        f"failed={totals['failed']}"
        + (f" | unattempted: {', '.join(unattempted)[:400]}"
           if unattempted else "")
        + (f" | deferred(still running server-side): {', '.join(deferred)[:400]}"
           if deferred else "")
        + (f" | failures: {', '.join(bad)[:400]}" if bad else "")
        + "\n" + "\n".join(lines))
    print(detail)
    _emit("vector_reindex", detail)

    if not attempted and collections:
        return 1  # nothing reached a terminal state — treat as failed run
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
