#!/usr/bin/env python3
"""Held-out verifier for the mddb-sequence profile fixture
(card nest-opencode-executor-eval; MEM-0871 eval template).

Recomputes EVERY claim in the plan artifact against the live mddb
banks — bank health, collection inventories, document counts,
retention eligibility (its own bounded /v1/search scan), and
collection-config guard state — then re-checks the plan's structure:
contiguous seq, non-empty check per step, mutating steps assigned to a
non-opencode executor, procedure B never aimed at a vector-bearing
bank, and required coverage (an A-step for every expired policy
collection, a guard step for every unconfigured one). The agent's
narrative is never trusted.

Checks return True/False; verdict is pass only when ALL checks pass.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

BANKS = {
    "main": "http://idc03:11023",
    "ops": "http://idc03:11026",
    "cms": "http://idc03:11027",
    "embed": "http://idc03:11028",
}
# collection -> (bank, ts_key, retention_days) — mirrors
# scripts/ada/prune-old-docs.py POLICY; duplicated so the check is
# held out from both the agent and the probe script.
POLICY = {
    "host-logs": ("ops", "ts", 14),
    "ada-ha-events-tony": ("main", "period_end", 30),
    "ada-ha-events-michael": ("main", "period_end", 30),
    "ada-ha-snapshots-tony": ("main", "refreshed_at", 30),
    "ada-ha-snapshots-michael": ("main", "refreshed_at", 30),
}
PAGE = 5000
MAX_PAGES = 40
TOL = {"documents_abs": 10, "documents_pct": 2,
       "embedded_abs": 10, "embedded_pct": 2,
       "expired_abs": 25, "expired_pct": 10,
       "scanned_abs": 5000, "free_bytes_pct": 25}
PROCEDURES = {"A", "B", "C", "guard"}
MUTATING_EXECUTORS = {"human", "devin", "manual", "runner"}
EXECUTORS = MUTATING_EXECUTORS | {"opencode"}


def _get(url, timeout=30):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _post(base, path, body, timeout=60):
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def live_state():
    """Independently collected truth: health + vector-stats per
    reachable bank, collection-config + expired scan per live POLICY
    collection."""
    st = {"banks": {}, "config": {}, "expired": {}}
    for name, base in BANKS.items():
        h = _get(f"{base}/health", timeout=15)
        if not isinstance(h, dict):
            continue                       # unreachable — not required
        vs = _get(f"{base}/v1/vector-stats", timeout=90) or {}
        st["banks"][name] = {
            "url": base, "health": h,
            "collections": (vs.get("collections") or {})}
    for coll, (bank, tsk, days) in POLICY.items():
        b = st["banks"].get(bank)
        if not b or coll not in b["collections"]:
            continue                       # policy collection absent
        cfg = _get(f"{BANKS[bank]}/v1/collection-config"
                   f"?collection={coll}", timeout=15)
        st["config"][coll] = cfg if isinstance(cfg, dict) else {}
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=days)).isoformat()
        scanned = expired = 0
        complete = True
        offset = 0
        try:
            for _ in range(MAX_PAGES):
                page = _post(BANKS[bank], "/v1/search",
                             {"collection": coll, "query": "",
                              "limit": PAGE, "offset": offset})
                if not page:
                    break
                scanned += len(page)
                for d in page:
                    ts = ((d.get("meta") or {}).get(tsk) or [""])[0]
                    if ts and ts < cutoff:
                        expired += 1
                offset += len(page)
                if len(page) < PAGE:
                    break
            else:
                complete = False
            if scanned == MAX_PAGES * PAGE:
                complete = False
        except Exception as e:
            st["expired"][coll] = {"error": str(e), "scanned": scanned,
                                   "expired": expired, "complete": False}
            continue
        st["expired"][coll] = {"scanned": scanned, "expired": expired,
                               "complete": complete}
    return st


def _close(a, b, abs_tol, pct):
    try:
        a, b = float(a), float(b)
    except Exception:
        return False
    return abs(a - b) <= max(abs_tol, abs(b) * pct / 100.0)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def verify(run_dir):
    rd = Path(run_dir)
    checks = {}
    try:
        man = json.loads((rd / "manifest.json").read_text())
        a = json.loads((rd / "artifact.out").read_text())
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False, "error": str(e)}}
    env = man.get("envelope") or {}
    st = live_state()

    # ---- contract --------------------------------------------------
    req = ("job", "card", "runbook", "generated_at", "read_only",
           "banks", "retention", "plan")
    checks["required fields"] = all(k in a for k in req)
    if not checks["required fields"]:
        return {"verdict": "fail", "checks": checks}
    checks["job matches envelope"] = a.get("job") == env.get("id")
    checks["card matches envelope"] = a.get("card") == env.get("card")
    checks["runbook is MEM-0871"] = a.get("runbook") == \
        "docs/kb/mddb-prune-compact.md"
    checks["read_only true"] = a.get("read_only") is True

    # ---- banks: coverage + live truth ------------------------------
    abanks = {b.get("name"): b for b in a.get("banks") or []
              if isinstance(b, dict)}
    checks["banks cover reachable set"] = all(
        n in abanks for n in st["banks"])
    checks["no phantom banks"] = all(
        n in BANKS for n in abanks)
    for n, live in st["banks"].items():
        ab = abanks.get(n)
        if not ab:
            continue
        h = live["health"]
        checks[f"{n} status live"] = ab.get("status") == \
            h.get("status")
        checks[f"{n} url correct"] = ab.get("url") == live["url"]
        checks[f"{n} free_bytes close"] = _close(
            ab.get("free_bytes"),
            (h.get("persistence") or {}).get("freeBytes"),
            0, TOL["free_bytes_pct"])
        # complete collection inventory, counts within tolerance
        acolls = {c.get("name"): c for c in ab.get("collections") or []
                  if isinstance(c, dict)}
        lcolls = live["collections"]
        checks[f"{n} inventory complete"] = \
            set(acolls) == set(lcolls)
        for cn, lc in lcolls.items():
            ac = acolls.get(cn)
            if not ac:
                continue
            checks[f"{n}/{cn} documents close"] = _close(
                ac.get("documents"), lc.get("total_documents"),
                TOL["documents_abs"], TOL["documents_pct"])
            checks[f"{n}/{cn} embedded close"] = _close(
                ac.get("embedded_documents"),
                lc.get("embedded_documents"),
                TOL["embedded_abs"], TOL["embedded_pct"])

    # ---- retention rows: policy coverage + recomputed scans --------
    arows = {r.get("collection"): r for r in a.get("retention") or []
             if isinstance(r, dict)}
    for coll, exp in st["expired"].items():
        bank, tsk, days = POLICY[coll]
        r = arows.get(coll)
        checks[f"retention row {coll}"] = r is not None
        if not r:
            continue
        checks[f"{coll} policy ts/days"] = \
            r.get("ts_key") == tsk and int(r.get("days") or -1) == days
        checks[f"{coll} bank correct"] = r.get("bank") == bank
        if "error" in exp:
            continue
        ve, ae = exp["expired"], r.get("expired")
        vs_, as_ = exp["scanned"], r.get("scanned")
        # bounds: an incomplete scan is a lower bound in whichever
        # direction it ran; complete scans compare within tolerance
        if r.get("complete") and exp["complete"]:
            checks[f"{coll} expired close"] = _close(
                ae, ve, TOL["expired_abs"], TOL["expired_pct"])
            checks[f"{coll} scanned close"] = _num(as_) and \
                abs(as_ - vs_) <= TOL["scanned_abs"]
        elif r.get("complete"):
            checks[f"{coll} expired bound"] = _num(ae) and _num(ve) \
                and ae >= ve - max(TOL["expired_abs"],
                                   ve * TOL["expired_pct"] / 100)
        else:
            checks[f"{coll} expired bound"] = _num(ae) and _num(ve) \
                and ve >= ae - max(TOL["expired_abs"],
                                   ae * TOL["expired_pct"] / 100)

    # ---- plan structure --------------------------------------------
    steps = [s for s in a.get("plan") or [] if isinstance(s, dict)]
    checks["plan non-empty"] = len(steps) > 0
    seqs = [s.get("seq") for s in steps]
    checks["seq contiguous from 1"] = \
        seqs == list(range(1, len(steps) + 1))
    checks["every step has check"] = all(
        isinstance(s.get("check"), str) and s["check"].strip()
        for s in steps)
    checks["every step has action+target"] = all(
        isinstance(s.get("action"), str) and s["action"].strip()
        and isinstance(s.get("target"), str) and s["target"].strip()
        for s in steps)
    checks["procedures in vocabulary"] = all(
        s.get("procedure") in PROCEDURES for s in steps)
    checks["executors valid"] = all(
        s.get("executor") in EXECUTORS for s in steps)
    checks["mutating steps not agent-executed"] = all(
        (not s.get("mutating")) or
        s.get("executor") in MUTATING_EXECUTORS
        for s in steps)
    checks["no executed claims"] = all(
        str(s.get("status") or "").lower() not in
        ("done", "executed", "applied", "complete")
        for s in steps)

    # procedure B only on all-zero-embed banks (artifact's own data)
    for s in steps:
        if s.get("procedure") != "B":
            continue
        tbank = str(s.get("target") or "").split("/")[0]
        binfo = abanks.get(tbank)
        ok = bool(binfo) and all(
            not (c.get("embedded_documents") or 0)
            for c in binfo.get("collections") or []
            if isinstance(c, dict))
        checks[f"proc B bank {tbank} vector-free"] = ok

    # ---- required coverage -----------------------------------------
    # every policy collection the artifact itself reports expired>0
    # must carry a procedure-A step naming it
    for coll, r in arows.items():
        if (r.get("expired") or 0) > 0:
            checks[f"plan has A-step for {coll}"] = any(
                s.get("procedure") == "A" and
                coll in str(s.get("target") or "") +
                str(s.get("action") or "")
                for s in steps)
    # every policy collection live-configured:false must carry a
    # guard step naming it (or its bank)
    for coll, cfg in st["config"].items():
        if cfg and cfg.get("configured") is False:
            bank = POLICY[coll][0]
            checks[f"plan has guard step for {coll}"] = any(
                s.get("procedure") == "guard" and
                (coll in str(s.get("target") or "") +
                 str(s.get("action") or "") or
                 bank == str(s.get("target") or "").split("/")[0])
                for s in steps)

    verdict = "pass" if all(v is True for v in checks.values()) \
        else "fail"
    return {"verdict": verdict, "checks": checks,
            "artifact": (env.get("artifact") or {}).get("path", "?")}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
