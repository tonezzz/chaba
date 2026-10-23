#!/usr/bin/env python3
"""webgpu-mddb-job — generate a real semantic-rerank job for the iPhone
WebGPU worker (OPS-0779, /apps/webgpu-bench).

Pulls real devin-session docs from the mddb bank, samples K of them,
and writes job.json into the served statics dir. The phone's worker
mode picks it up, embeds query+docs on the GPU, cosine-ranks, and posts
the result back to the kanban card.

Usage:
  webgpu-mddb-job.py "your recall question" [--k 8] [--out <job.json path>]
"""
import json
import random
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

MDDB = "http://100.102.134.91:11023/v1"
COLLECTION = "ada-ha-bank-devin-tony"
SERVED = Path("/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/"
              "public/apps/webgpu-bench/job.json")


def post(path, payload, timeout=30):
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    query = args[0]
    k = int(args[args.index("--k") + 1]) if "--k" in args else 8
    out = Path(args[args.index("--out") + 1]) if "--out" in args else SERVED

    out_resp = post("/search", {"collection": COLLECTION, "limit": 5000,
                                "include_content": True})
    docs = out_resp if isinstance(out_resp, list) else (
        out_resp.get("results") or out_resp.get("documents") or [])
    docs = [d for d in docs
            if d.get("contentMd") and len(d["contentMd"]) > 120]
    random.shuffle(docs)
    picks = docs[:k]
    if not picks:
        print("no usable docs in bank")
        return 1

    job = {
        "id": "mddb-rerank-" + datetime.now().strftime("%Y%m%d-%H%M%S"),
        "status": "pending",
        "query": query,
        "docs": [{"key": d["key"],
                  "text": d["contentMd"][:480]} for d in picks],
    }
    out.write_text(json.dumps(job, ensure_ascii=False, indent=2))
    print(f"wrote {out} — {len(picks)} docs, query: {query!r}")
    for p in picks:
        print("  -", p["key"], "|", p["contentMd"][:70].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
