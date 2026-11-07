#!/usr/bin/env python3
"""L0 deterministic solver for backup-freshness: walk declared roots,
find newest file per root, compare age to threshold."""
import json
import os
import sys
from datetime import datetime, timezone

MAX_ENTRIES = 200_000


def _newest(root):
    newest, nm = None, 0.0
    seen = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            seen += 1
            if seen > MAX_ENTRIES:
                return newest, nm, True
            p = os.path.join(base, fn)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > nm:
                nm, newest = m, p
    return newest, nm, False


def main():
    task_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    with open(os.path.join(task_dir,
                           "evals/shadow/task/inputs/backup-roots.json")) as f:
        spec = json.load(f)
    now = datetime.now(timezone.utc).timestamp()
    roots, stale = [], []
    for r in spec.get("roots", []):
        p = r["path"] if os.path.isabs(r["path"]) else os.path.join(
            task_dir, r["path"])
        exists = os.path.isdir(p)
        row = {"path": r["path"], "label": r.get("label"),
               "exists": exists, "newest_file": None,
               "newest_mtime": None, "age_hours": None, "fresh": None}
        if exists:
            nf, nm, trunc = _newest(p)
            if nf:
                age = (now - nm) / 3600.0
                fresh = age <= float(r.get("fresh_hours", 720))
                row.update({"newest_file": os.path.relpath(nf, p),
                            "newest_mtime": datetime.fromtimestamp(
                                nm, timezone.utc).isoformat(),
                            "age_hours": round(age, 2), "fresh": fresh,
                            "scan_truncated": trunc})
                if not fresh:
                    stale.append(r.get("label"))
        roots.append(row)
    verdict = "pass" if not stale else "fail"
    art = {"host": os.uname().nodename,
           "collected_at": datetime.now(timezone.utc).isoformat(),
           "roots": roots, "stale_roots": stale, "verdict": verdict,
           "read_only": True}
    out = os.path.join(task_dir, "evals/shadow/task/artifacts")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "backup-freshness.json"), "w") as f:
        json.dump(art, f, indent=1)
    print(json.dumps({"wrote": out + "/backup-freshness.json",
                      "verdict": verdict, "stale": stale}))


if __name__ == "__main__":
    main()
