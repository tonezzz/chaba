#!/usr/bin/env python3
"""L0 deterministic solver for storage-dryrun. df + bounded find; deletes
nothing; writes evals/shadow/task/artifacts/storage-dryrun.json."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def _df(path):
    try:
        out = subprocess.run(["df", "-P", path], capture_output=True,
                             text=True, timeout=15).stdout.splitlines()
        parts = out[-1].split()
        return {"fs": parts[0], "total_gb": round(int(parts[1]) / 1e6, 2),
                "used_pct": int(parts[4].rstrip("%"))}
    except Exception:
        st = os.statvfs(path)
        return {"fs": "?", "total_gb": round(st.f_blocks * st.f_frsize / 1e9, 2),
                "used_pct": int(round(100 * (st.f_blocks - st.f_bfree)
                                      / max(st.f_blocks, 1)))}


def _dir_size(path, cap=200):
    try:
        out = subprocess.run(["du", "-s", "-b", "--max-count", str(cap), path]
                             if False else ["du", "-s", "-b", path],
                             capture_output=True, text=True, timeout=30)
        return int(out.stdout.split()[0])
    except Exception:
        try:
            return os.path.getsize(path)
        except Exception:
            return 0


def main():
    task_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    spec_path = os.path.join(task_dir,
                             "evals/shadow/task/inputs/storage-roots.json")
    with open(spec_path) as f:
        spec = json.load(f)
    roots = []
    for r in spec.get("roots", []):
        p = r["path"] if os.path.isabs(r["path"]) else os.path.join(
            task_dir, r["path"])
        e = os.path.exists(p)
        row = {"path": r["path"], "label": r.get("label"), "exists": e}
        if e:
            row.update(_df(p))
        else:
            row.update({"fs": None, "total_gb": None, "used_pct": None})
        roots.append(row)

    scan = spec.get("candidate_scan", {})
    scan_root = scan.get("root", ".")
    sr = scan_root if os.path.isabs(scan_root) else os.path.join(
        task_dir, scan_root)
    max_entries = int(scan.get("max_entries", 5000))
    cands, seen = [], 0
    for base, dirs, files in os.walk(sr):
        for d in list(dirs):
            if seen >= max_entries:
                break
            if d == "__pycache__":
                p = os.path.join(base, d)
                cands.append({"path": os.path.relpath(p, sr), "kind": "pycache",
                              "bytes": _dir_size(p),
                              "reason": "python bytecode cache — safe to regenerate"})
                seen += 1
        for fn in files:
            if seen >= max_entries:
                break
            if fn.endswith(".pyc"):
                p = os.path.join(base, fn)
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    sz = 0
                cands.append({"path": os.path.relpath(p, sr), "kind": "pyc",
                              "bytes": sz, "reason": "stale bytecode file"})
                seen += 1
        if seen >= max_entries:
            break

    art = {"host": os.uname().nodename,
           "collected_at": datetime.now(timezone.utc).isoformat(),
           "roots": roots, "stale_candidates": cands,
           "candidate_scan_truncated": seen >= max_entries,
           "deletions": [], "dry_run": True}
    out = os.path.join(task_dir, "evals/shadow/task/artifacts")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "storage-dryrun.json"), "w") as f:
        json.dump(art, f, indent=1)
    print(json.dumps({"wrote": out + "/storage-dryrun.json",
                      "candidates": len(cands)}))


if __name__ == "__main__":
    main()
