#!/usr/bin/env python3
"""Held-out verifier for backup-freshness: re-walks the declared roots
and confirms newest-mtime / freshness claims against reality."""
import json
import os
import sys
from datetime import datetime, timezone

MAX_ENTRIES = 200_000


def _newest(root):
    nm = 0.0
    newest = None
    seen = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            seen += 1
            if seen > MAX_ENTRIES:
                break
            p = os.path.join(base, fn)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > nm:
                nm, newest = m, p
    return newest, nm


def verify(task_dir):
    path = os.path.join(task_dir,
                        "evals/shadow/task/artifacts/backup-freshness.json")
    spec_path = os.path.join(task_dir,
                             "evals/shadow/task/inputs/backup-roots.json")
    try:
        with open(path) as f:
            a = json.load(f)
        with open(spec_path) as f:
            spec = json.load(f)
    except Exception as e:
        return {"verdict": "fail", "checks": {"artifact readable": False,
                                              "error": str(e)}}
    checks = {}
    checks["required fields"] = all(
        k in a for k in ("host", "collected_at", "roots", "stale_roots",
                         "verdict", "read_only"))
    checks["read_only true"] = a.get("read_only") is True

    want = {(r["path"], r.get("label"), float(r.get("fresh_hours", 720)))
            for r in spec.get("roots", [])}
    got_rows = {r.get("path"): r for r in a.get("roots", [])}
    checks["all roots covered"] = all(w[0] in got_rows for w in want)

    truthful = True
    for path_, label, fresh_h in want:
        row = got_rows.get(path_)
        if not row:
            truthful = False
            continue
        p = path_ if os.path.isabs(path_) else os.path.join(task_dir, path_)
        exists = os.path.isdir(p)
        if bool(row.get("exists")) != exists:
            truthful = False
            continue
        if not exists:
            continue
        nf, nm = _newest(p)
        if nf is None:
            if row.get("newest_file") not in (None, ""):
                truthful = False
            continue
        # claimed mtime within 5 min of recomputed, and freshness verdict correct
        try:
            claimed = datetime.fromisoformat(
                str(row.get("newest_mtime"))).timestamp()
        except Exception:
            truthful = False
            continue
        if abs(claimed - nm) > 300:
            truthful = False
            continue
        age = (datetime.now(timezone.utc).timestamp() - nm) / 3600.0
        if bool(row.get("fresh")) != (age <= fresh_h):
            truthful = False
    checks["mtime and freshness claims truthful"] = truthful

    # verdict consistent with stale_roots
    stales = set(a.get("stale_roots", []))
    expected_stale = {r.get("label") for r in a.get("roots", [])
                      if r.get("exists") and r.get("fresh") is False}
    checks["stale_roots consistent"] = stales == expected_stale
    checks["verdict consistent"] = (
        a.get("verdict") == ("pass" if not expected_stale else "fail"))

    verdict = "pass" if all(v is True for v in checks.values()) else "fail"
    return {"verdict": verdict, "checks": checks,
            "artifact": "backup-freshness.json"}


if __name__ == "__main__":
    td = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(json.dumps(verify(td), indent=1))
