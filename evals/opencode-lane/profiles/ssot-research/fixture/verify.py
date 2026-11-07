#!/usr/bin/env python3
"""Held-out verifier for ssot-research: required fields present and
every claimed citation resolves to a real file in the checkout — the
citation contract is checked, not trusted."""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]


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
           "read_only")
    checks["required fields"] = all(k in a for k in req)
    checks["read_only true"] = a.get("read_only") is True
    checks["answer non-empty"] = bool(str(a.get("answer") or "").strip())

    cits = a.get("citations") or []
    checks["citations >= 2"] = len(cits) >= 2
    # contract is {path, note} objects — anything else is malformed and
    # fails cleanly (never crash on agent-shaped input)
    checks["citations are {path,note} objects"] = all(
        isinstance(c, dict) and c.get("path") for c in cits)
    resolved = 0
    bad = []
    for c in cits:
        p = str((c or {}).get("path") if isinstance(c, dict) else c) \
            .strip().lstrip("/")
        if p and (REPO / p).is_file():
            resolved += 1
        else:
            bad.append(p or "?")
    checks["every cited path exists"] = resolved == len(cits) and not bad
    checks["no bare/outside citations"] = all(
        ".." not in str((c or {}).get("path") if isinstance(c, dict)
                        else c)
        for c in cits)
    if bad:
        checks["bad citations"] = False

    srcs = a.get("sources_consulted") or []
    checks["sources under docs/"] = any(
        str(s).lstrip("/").startswith("docs/") for s in srcs)
    checks["consulted paths exist"] = all(
        (REPO / str(s).lstrip("/")).exists() for s in srcs) \
        if srcs else False

    # the question in the artifact echoes the envelope's task text
    task = str((man.get("envelope") or {}).get("task") or "").strip()
    if task:
        q = str(a.get("question") or "")
        checks["question echoed"] = q.strip()[:80] == task[:80] or \
            task[:40].lower() in q.lower()

    verdict = "pass" if all(v is True for v in checks.values()) \
        else "fail"
    return {"verdict": verdict, "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
