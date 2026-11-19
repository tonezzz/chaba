#!/usr/bin/env python3
"""Held-out verifier for info-find: required fields present, every
claimed citation is well-formed (repo paths must resolve in the
checkout, mddb:// and http(s) refs are format-checked), and the source
accounting is honest — a rung the plan deferred cannot appear in
sources_consulted. The citation contract is checked, not trusted."""
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]

MDDB_REF = re.compile(r"^mddb://[\w.-]+/\S+$")
URL_REF = re.compile(r"^https?://\S+$")


def _ref_kind(ref: str) -> str:
    if MDDB_REF.match(ref):
        return "mddb"
    if URL_REF.match(ref):
        return "url"
    return "repo"


def verify(run_dir):
    rd = Path(run_dir)
    checks = {}
    try:
        a = json.loads((rd / "artifact.out").read_text())
        man = json.loads((rd / "manifest.json").read_text())
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False, "error": str(e)}}

    req = ("question", "answer", "citations", "sources_consulted",
           "unavailable_sources", "deferred_rungs", "read_only")
    checks["required fields"] = all(k in a for k in req)
    checks["read_only true"] = a.get("read_only") is True
    checks["answer non-empty"] = bool(str(a.get("answer") or "").strip())

    cits = a.get("citations") or []
    checks["citations >= 2"] = len(cits) >= 2
    checks["citations are {source,ref,note} objects"] = all(
        isinstance(c, dict) and c.get("ref") and c.get("source")
        for c in cits)

    resolved = 0
    bad = []
    for c in cits:
        ref = str((c or {}).get("ref") or "").strip()
        kind = _ref_kind(ref)
        if kind == "mddb" or kind == "url":
            resolved += 1
            continue
        path = re.split(r":(\d+)$", ref)[0].lstrip("/")
        if ".." in path:
            bad.append(ref)
            continue
        if (REPO / path).is_file():
            resolved += 1
        else:
            bad.append(ref)
    checks["every citation resolves or is a valid external ref"] = \
        resolved == len(cits) and not bad
    if bad:
        checks["bad citations"] = False

    consulted = [str(s) for s in (a.get("sources_consulted") or [])]
    checks["sources_consulted non-empty"] = bool(consulted)
    deferred = {str(s) for s in (a.get("deferred_rungs") or [])}
    checks["no deferred rung claimed as consulted"] = \
        not (set(consulted) & deferred)

    task = str((man.get("envelope") or {}).get("task") or "").strip()
    if task:
        q = str(a.get("question") or "")
        echoed = q.strip()[:80] == task[:80] or \
            task[:40].lower() in q.lower()
        if not echoed and (man.get("envelope") or {}).get("dispatch_card"):
            words = lambda s: set(re.findall(r"[a-z0-9]{3,}", s.lower()))
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
