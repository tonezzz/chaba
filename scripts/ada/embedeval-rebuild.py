#!/usr/bin/env python3
"""embedeval-rebuild.py — rebuild the /tmp/embedeval teacher fixture.

The original embed-space-eval workdir (/tmp/embedeval on idc03) was lost
(tmp cleanup). This rebuilds ONLY what the BGE-M3 distillation pilot
needs, skipping the nomic/translate/prod/label arms:

  docs.jsonl              — full doc pool via stage_fetch (mddb reads)
  queries.jsonl           — 48 judged-eval queries via stage_select
  vec-gemini.jsonl        — gemini-embedding-2 doc vectors (teacher)
  vec-gemini-queries.jsonl— gemini-embedding-2 query vectors

Usage (idc03):

    cd ~/CascadeProjects/chaba && set -a && \
      source ~/.config/secrets/gemini-keys.env && set +a && \
      python3 scripts/ada/embedeval-rebuild.py --work /tmp/embedeval

All stages are resumable: vec-*.jsonl append per batch and skip ids
already present. Doc embedding uses batchEmbedContents in chunks of
--batch (default 50) — larger than embed-space-eval's 25 to halve the
API round-trips; the 5s inter-batch sleep from the original is kept to
stay inside free-tier rate limits.
"""
import argparse
import importlib.util
import json
import os
import sys
import time


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/embedeval")
    ap.add_argument("--corpus",
                    default="experiments/query-cache-phase0/"
                            "bankq-corpus-20261008.jsonl")
    ap.add_argument("--evalmod", default="scripts/ada/embed-space-eval.py")
    ap.add_argument("--n-en", type=int, default=30)
    ap.add_argument("--n-th", type=int, default=14)
    ap.add_argument("--n-ctrl", type=int, default=4)
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--sleep", type=float, default=5.0)
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--embed-only", action="store_true")
    a = ap.parse_args()

    ev = load_module("embed_eval", a.evalmod)
    if not ev.GEMINI_KEY:
        sys.exit("need GEMINI_API_KEY[_FREE] (gemini-keys.env)")
    os.makedirs(a.work, exist_ok=True)

    docs_path = os.path.join(a.work, "docs.jsonl")
    queries_path = os.path.join(a.work, "queries.jsonl")

    if not a.embed_only:
        ev.stage_fetch(a.work)
        ev.stage_select(a.work, a.corpus, a.n_en, a.n_th, a.n_ctrl)
    if a.fetch_only:
        print("fetch-only: done")
        return

    docs = ev.jlines(docs_path)
    queries = ev.jlines(queries_path)
    print(f"rebuild: {len(docs)} docs, {len(queries)} queries")

    # ---- doc teacher vectors -------------------------------------
    vpath = os.path.join(a.work, "vec-gemini.jsonl")
    done = {r["id"] for r in ev.jlines(vpath)}
    todo = [d for d in docs if d["id"] not in done]
    print(f"vec-gemini: {len(todo)} docs to embed ({len(done)} cached)")
    for i in range(0, len(todo), a.batch):
        chunk = todo[i:i + a.batch]
        texts = [d["text"] for d in chunk]
        for attempt in range(6):
            try:
                vs = ev.embed_gemini(texts)
                break
            except Exception as e:
                print(f"  batch {i} try{attempt}: {e}", file=sys.stderr)
                time.sleep(30 * (attempt + 1))
        else:
            raise SystemExit(f"gemini embed failed at {i}")
        ev._save_vecs(vpath, {d["id"]: v for d, v in zip(chunk, vs)})
        print(f"  vec-gemini: {min(i + a.batch, len(todo))}/{len(todo)}",
              flush=True)
        time.sleep(a.sleep)

    # ---- query teacher vectors -----------------------------------
    qpath = os.path.join(a.work, "vec-gemini-queries.jsonl")
    qdone = {r["id"] for r in ev.jlines(qpath)}
    for q in queries:
        if q["qid"] in qdone:
            continue
        v = ev.embed_gemini([q["query"]])[0]
        with open(qpath, "a") as f:
            f.write(json.dumps({"id": q["qid"], "v": ev.b64e(v)}) + "\n")
        print(f"  qvec {q['qid']}", flush=True)
        time.sleep(1)

    print("rebuild: done")


if __name__ == "__main__":
    main()
