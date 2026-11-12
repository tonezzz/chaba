#!/usr/bin/env python3
"""Shadow-check due Education lessons against the local BGE hybrid bank.

Read-only: it reads lessons through board-api and writes a local JSON/Markdown
report. It does not mutate the due page, lessons, or Ada memory banks.
"""
import argparse
import importlib.util
import json
import os
import time
import urllib.request
from datetime import date


BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")


def post(url, payload, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def due_lessons():
    rows = post(f"{BOARD_API}/lesson", {"op": "list", "from": "devin"})
    today = date.today().isoformat()
    return [
        row for row in rows.get("lessons") or []
        if row.get("status") != "learned"
        and row.get("next_review")
        and row["next_review"] <= today
    ]


def load_adapter(path):
    spec = importlib.util.spec_from_file_location("bge_hybrid", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--base",
                        default="http://100.123.163.11:11028/v1")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--collections", default="bge-lessons-shadow",
        help="comma-separated collection allowlist for the dense leg "
             "(default: bge-lessons-shadow — only lesson/* hits are "
             "consumed downstream, so fanning out to the whole bank "
             "wastes ~24x embed calls and saturates the pool)")
    args = parser.parse_args()
    colls = [c for c in (s.strip() for s in args.collections.split(","))
             if c] or None
    adapter = load_adapter(args.adapter)
    with open(args.index) as source:
        snapshot = json.load(source)
    bm25 = adapter.BM25(snapshot.get("docs") or [])
    rows = due_lessons()
    started = time.time()
    results = []
    for row in rows:
        query = row.get("topic") or row.get("slug") or ""
        result = adapter.query_loaded(
            args.base, snapshot, bm25, query, 30, 50, 5, 1.0, 0.75,
            collections=colls)
        results.append({
            "slug": row.get("slug"),
            "topic": row.get("topic"),
            "next_review": row.get("next_review"),
            "result": result,
        })
    report = {
        "run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "due_lessons": len(results),
        "vector_errors": sum(r["result"]["vector_errors"] for r in results),
        "wall_seconds": round(time.time() - started, 1),
        "results": results,
        "read_only": True,
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({
        key: report[key] for key in
        ("due_lessons", "vector_errors", "wall_seconds")
    }))


if __name__ == "__main__":
    main()
