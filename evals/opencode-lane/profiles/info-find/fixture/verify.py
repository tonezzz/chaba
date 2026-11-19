#!/usr/bin/env python3
"""Held-out verifier for info-find: required fields, per-source status
hygiene, citation resolvability, rank order, and session isolation —
the citation and fail-safe contracts are checked, not trusted."""
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
INTENTS = {"mcp", "service-health", "ssot", "code", "web", "explore",
           "general-doc"}
SOURCES = {"ssot", "code", "health", "mddb", "mcp", "web", "github"}
STATUSES = {"ok", "skipped", "deferred", "unavailable", "error"}
RANK = {"mddb": 0, "web": 1, "github": 2, "ssot": 3, "health": 3,
        "mcp": 4, "code": 5}


def verify(run_dir):
    rd = Path(run_dir)
    checks = {}
    try:
        a = json.loads((rd / "artifact.out").read_text())
        man = json.loads((rd / "manifest.json").read_text())
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False,
                           "error": str(e)}}

    req = ("question", "intent", "answer", "session", "sources",
           "results", "read_only")
    checks["required fields"] = all(k in a for k in req)
    checks["read_only true"] = a.get("read_only") is True
    checks["intent known"] = a.get("intent") in INTENTS
    checks["session non-empty"] = bool(str(a.get("session") or "")
                                       .strip())
    checks["answer non-empty"] = bool(str(a.get("answer") or "")
                                      .strip())

    # --- fail-safe contract: every planned source has an explicit
    # status; unavailable/error carry a reason; at least one source
    # actually ran or every routed source explained itself
    srcs = a.get("sources") or {}
    checks["sources is map"] = isinstance(srcs, dict) and bool(srcs)
    checks["sources known"] = all(s in SOURCES for s in srcs)
    checks["statuses valid"] = all(
        isinstance(v, dict) and v.get("status") in STATUSES
        for v in srcs.values())
    checks["unavailable/error explained"] = all(
        v.get("reason") or v.get("spec")
        for v in srcs.values()
        if isinstance(v, dict)
        and v.get("status") in ("unavailable", "error", "deferred"))
    ran = [v for v in srcs.values() if isinstance(v, dict)
           and v.get("status") in ("ok", "unavailable", "error")]
    checks["at least one source attempted"] = bool(ran)

    # --- citation contract: every result carries a citation that
    # resolves — repo paths must exist in the checkout, mddb needs
    # collection+id, web needs a url
    results = a.get("results") or []
    checks["results is list"] = isinstance(results, list)

    def cit_ok(r):
        c = (r or {}).get("citation") or {}
        if c.get("url"):
            return str(c["url"]).startswith(("http://", "https://"))
        if (r or {}).get("source") == "mddb" or c.get("collection"):
            return bool(c.get("collection") and
                        (c.get("id") or c.get("key")))
        p = str(c.get("path") or "").strip().lstrip("/")
        return bool(p) and ".." not in p.split("/") and \
            (REPO / p).exists()

    checks["every result has source+citation"] = all(
        isinstance(r, dict) and r.get("source") in SOURCES
        and isinstance(r.get("citation"), dict) and r["citation"]
        for r in results)
    checks["every citation resolves"] = all(cit_ok(r) for r in results) \
        if results else True
    checks["rank order holds"] = all(
        RANK.get((results[i] or {}).get("source"), 9)
        <= RANK.get((results[i + 1] or {}).get("source"), 9)
        for i in range(len(results) - 1)) if len(results) > 1 else True

    # --- session isolation: cache/audit live under
    # ~/.cache/devin/info-find/, never inside the checkout
    cd = str(a.get("cache_dir") or "")
    if cd:
        checks["cache outside repo"] = ".cache" in cd and \
            not str(Path(cd).resolve()).startswith(str(REPO))
        checks["cache names the session"] = str(a.get("session")) in cd

    # --- question echoes the envelope task
    task = str((man.get("envelope") or {}).get("task") or "").strip()
    if task:
        q = str(a.get("question") or "")
        echoed = q.strip()[:80] == task[:80] or \
            task[:40].lower() in q.lower()
        if not echoed:
            words = lambda s: set(
                re.findall(r"[a-z0-9]{3,}", s.lower()))
            tw, qw = words(task), words(q)
            ov = len(tw & qw)
            echoed = bool(tw) and bool(qw) and (
                ov / len(tw) >= 0.4 or ov / len(qw) >= 0.6)
        checks["question echoed"] = echoed

    verdict = "pass" if all(v is True for v in checks.values()) \
        else "fail"
    return {"verdict": verdict, "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
