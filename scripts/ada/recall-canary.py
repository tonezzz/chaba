#!/usr/bin/env python3
"""Recall canary — known-answer questions over the memory banks.

Runs the same retrieval path ada_memory_search uses (per-bank
/v1/vector-search, threshold 0.45, status=active filter on writable
banks), then checks whether the expected doc surfaces in the aggregated
top-N. Exits non-zero if any canary misses — usable as a weekly
correctness metric (see ssot.apps.ada-memory-progress.yml).

  recall-canary.py                # human report
  recall-canary.py --json out.json
  recall-canary.py --top 3        # stricter: must be in top 3
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml

MDDB = os.environ.get(
    "ADA_MEMORY_MDDB_URL", "http://100.68.142.13:11023/v1"
).rstrip("/")
BANKS_FILE = Path(os.environ.get(
    "ADA_MEMORY_BANKS_FILE", "~/.config/ada/memory-banks.json"
)).expanduser()
CANARY = Path(__file__).with_suffix(".yml")
THRESHOLD = float(os.environ.get("ADA_BANK_SEARCH_THRESHOLD", "0.45"))


def load_banks() -> dict:
    """bank name -> {collection, writable} from the rendered registry.
    {instance} expands like backend/memory_banks.MemoryBankRegistry —
    via ADA_INSTANCE_ID (default 'tony')."""
    inst = os.environ.get("ADA_INSTANCE_ID", "tony")
    data = json.loads(BANKS_FILE.read_text())
    banks = data.get("banks") or data
    out = {}
    for name, b in banks.items():
        coll = (b.get("mddb_collection") or b.get("collection") or "")
        coll = coll.replace("{instance}", inst)
        out[name] = {"collection": coll,
                     "writable": bool(b.get("writable", True))}
    return out


def vector_search(coll: str, query: str, writable: bool) -> list[dict]:
    """Mirror of backend/memory_ops.memory_search: writable banks filter
    status=active; read-only banks post-filter instead."""
    payload = {"collection": coll, "query": query, "topK": 15,
               "includeContent": True, "threshold": THRESHOLD}
    if writable:
        payload["filterMeta"] = {"status": ["active"]}
    req = urllib.request.Request(
        f"{MDDB}/vector-search", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            results = json.loads(r.read()).get("results") or []
    except Exception as e:
        print(f"    ! {coll}: vector-search failed: {e}", file=sys.stderr)
        return []
    return [(it.get("document") or {}) | {"score": it.get("score")}
            for it in results]


def status_of(doc: dict) -> str:
    v = (doc.get("meta") or {}).get("status")
    if isinstance(v, list):
        v = v[0] if v else None
    return str(v or "active")


def matched(doc: dict, c: dict) -> bool:
    if c.get("expect_key") and doc.get("key") == c["expect_key"]:
        return True
    meta = doc.get("meta") or {}
    subj = meta.get("subject")
    subj = subj[0] if isinstance(subj, list) else subj
    if c.get("expect_subject") and subj == c["expect_subject"]:
        return True
    if c.get("expect_text") and c["expect_text"].lower() in str(
            doc.get("contentMd") or "").lower():
        return True
    if c.get("expect_any"):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5,
                    help="hit must appear in the aggregated top-N")
    ap.add_argument("--json", metavar="PATH", help="write JSON report")
    args = ap.parse_args()

    banks = load_banks()
    canaries = yaml.safe_load(CANARY.read_text()).get("canaries") or []
    report = {"mddb": MDDB, "threshold": THRESHOLD, "top": args.top,
              "total": len(canaries), "pass": 0, "results": []}

    for c in canaries:
        q = c["q"]
        want = c.get("banks") or list(banks)
        hits = []
        for name in want:
            b = banks.get(name)
            if not b or not b["collection"]:
                continue
            for d in vector_search(b["collection"], q, b["writable"]):
                if b["writable"] or status_of(d) == "active":
                    d["_bank"] = name
                    hits.append(d)
        hits.sort(key=lambda d: d.get("score") or 0, reverse=True)
        top = hits[:args.top]
        ok = any(matched(d, c) for d in top)
        report["pass"] += int(ok)
        report["results"].append({
            "q": q, "ok": ok,
            "hits": [{"key": d.get("key"), "bank": d.get("_bank"),
                      "score": round(d.get("score") or 0, 3)}
                     for d in top]})
        mark = "PASS" if ok else "MISS"
        tops = ", ".join(f"{d.get('_bank')}:{d.get('key')}"
                         f"({d.get('score'):.2f})" for d in top[:3])
        print(f"[{mark}] {q}\n      {tops or 'no hits'}")

    report["pass_rate"] = round(report["pass"] / max(1, report["total"]), 3)
    print(f"\n{report['pass']}/{report['total']} canaries pass "
          f"({report['pass_rate']:.0%})")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["pass"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
