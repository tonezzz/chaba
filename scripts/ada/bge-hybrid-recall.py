#!/usr/bin/env python3
"""Read-only BGE-M3 + BM25 hybrid recall over the local MDDB bank.

This is a shadow/sidecar query path. It never writes to MDDB and never
changes the production Gemini index. Build a local lexical snapshot once,
then query the BGE bank and fuse both rankings with reciprocal rank fusion.

Examples:
  python3 scripts/ada/bge-hybrid-recall.py --build
  python3 scripts/ada/bge-hybrid-recall.py --query "what changed on idc02"
"""
import argparse
import concurrent.futures
import json
import math
import os
import re
import statistics
import time
import urllib.request
from collections import Counter, defaultdict


DEFAULT_BASE = os.environ.get("BGE_HYBRID_MDDB_URL",
                              "http://100.123.163.11:11028/v1").rstrip("/")
DEFAULT_INDEX = os.path.expanduser(
    os.environ.get("BGE_HYBRID_INDEX",
                   "~/.local/share/bge-hybrid/docs.json"))
TOKEN_RE = re.compile(r"[\wก-๙]+", re.UNICODE)
RRF_K = 60


def request_json(url, payload, timeout=60, attempts=3):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    err = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read())
        except Exception as e:  # transient pool hiccups — bounded retry
            err = e
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise err


def tokens(text):
    return TOKEN_RE.findall((text or "").lower())


def collections(base):
    stats = request_json(f"{base}/vector-stats", {}, timeout=90)
    return sorted((stats.get("collections") or {}).keys())


def fetch_collection(base, collection):
    payload = request_json(
        f"{base}/search",
        {"collection": collection, "limit": 10000,
         "include_content": True},
        timeout=90)
    rows = payload if isinstance(payload, list) else (
        payload.get("results") or payload.get("documents") or [])
    out = []
    for row in rows:
        text = row.get("contentMd") or row.get("content") or ""
        doc_id = row.get("id") or (
            f"{collection}|{row.get('key')}|{row.get('lang') or 'en'}")
        if len(text.strip()) < 20:
            continue
        out.append({
            "id": doc_id,
            "collection": collection,
            "key": row.get("key"),
            "lang": row.get("lang"),
            "text": text,
        })
    return out


def build_index(base, path):
    colls = collections(base)
    docs = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_collection, base, c): c for c in colls}
        for future in concurrent.futures.as_completed(futures):
            collection = futures[future]
            try:
                docs.extend(future.result())
            except Exception as exc:
                errors.append({"collection": collection, "error": str(exc)})
    docs.sort(key=lambda row: row["id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as output:
        json.dump({"created": time.time(), "base": base, "collections": colls,
                   "docs": docs, "errors": errors},
                  output, ensure_ascii=False)
    print(json.dumps({"ok": not errors, "path": path,
                      "collections": len(colls), "documents": len(docs),
                      "errors": errors}, ensure_ascii=False))
    return 0 if docs else 1


class BM25:
    def __init__(self, docs):
        self.docs = docs
        self.term_docs = defaultdict(list)
        self.term_freqs = []
        self.doc_freq = Counter()
        lengths = []
        for index, doc in enumerate(docs):
            freq = Counter(tokens(doc["text"]))
            self.term_freqs.append(freq)
            lengths.append(sum(freq.values()))
            for term in freq:
                self.term_docs[term].append(index)
                self.doc_freq[term] += 1
        self.avg_len = statistics.fmean(lengths) if lengths else 1

    def search(self, query, limit):
        scores = defaultdict(float)
        query_terms = tokens(query)
        count = len(self.docs)
        for term in query_terms:
            if term not in self.term_docs:
                continue
            idf = math.log(1 + (count - self.doc_freq[term] + 0.5) /
                           (self.doc_freq[term] + 0.5))
            for index in self.term_docs[term]:
                freq = self.term_freqs[index][term]
                length = sum(self.term_freqs[index].values())
                denominator = freq + 1.2 * (
                    1 - 0.75 + 0.75 * length / self.avg_len)
                scores[index] += idf * freq * 2.2 / denominator
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        return [(self.docs[index], score) for index, score in ranked[:limit]]


def vector_collection(base, collection, query, limit):
    started = time.monotonic()
    payload = None
    last_exc = None
    for attempt in range(3):
        if attempt:
            time.sleep(min(2.0, 0.5 * attempt))
        try:
            payload = request_json(
                f"{base}/vector-search",
                {"collection": collection, "query": query, "topK": limit,
                 "includeContent": False},
                timeout=45)
            break
        except Exception as exc:
            last_exc = exc
    else:
        raise last_exc
    hits = []
    for rank, hit in enumerate(payload.get("results") or [], start=1):
        document = hit.get("document") or {}
        if document.get("id"):
            hits.append((document["id"], rank, hit.get("score")))
    return collection, hits, time.monotonic() - started


def query_loaded(base, snapshot, bm25, text, dense_k, lexical_k, top_k,
                 dense_weight, lexical_weight, collections=None):
    docs = snapshot.get("docs") or []
    by_id = {doc["id"]: doc for doc in docs}
    started = time.monotonic()
    lexical = bm25.search(text, lexical_k)
    dense = []
    errors = []
    latencies = []
    colls = collections if collections is not None else (
        snapshot.get("collections") or [])
    # Keep fan-out below MDDB's search concurrency ceiling. Eight parallel
    # collection calls intermittently return 503 under a warm local bank.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(vector_collection, base, collection, text,
                                dense_k)
                   for collection in colls]
        for future in concurrent.futures.as_completed(futures):
            try:
                _collection, hits, elapsed = future.result()
                dense.extend(hits)
                latencies.append(elapsed)
            except Exception as exc:
                errors.append(str(exc))

    fused = defaultdict(float)
    dense_best = {}
    for doc_id, rank, score in dense:
        fused[doc_id] += dense_weight / (RRF_K + rank)
        dense_best[doc_id] = max(score or 0, dense_best.get(doc_id, 0))
    for rank, (doc, _score) in enumerate(lexical, start=1):
        fused[doc["id"]] += lexical_weight / (RRF_K + rank)
    ranked = sorted(fused.items(), key=lambda item: -item[1])[:top_k]
    results = []
    for doc_id, fused_score in ranked:
        doc = by_id.get(doc_id, {"id": doc_id})
        results.append({
            "id": doc_id,
            "collection": doc.get("collection"),
            "key": doc.get("key"),
            "score": fused_score,
            "dense_score": dense_best.get(doc_id),
            "text": doc.get("text", "")[:500],
        })
    return {
        "query": text,
        "results": results,
        "latency_s": round(time.monotonic() - started, 3),
        "vector_p50_s": round(statistics.median(latencies), 3)
        if latencies else None,
        "vector_errors": len(errors),
        "errors": errors[:5],
        "weights": {"dense": dense_weight, "lexical": lexical_weight},
    }


def query(base, index_path, text, dense_k, lexical_k, top_k,
          dense_weight, lexical_weight, collections=None):
    with open(index_path) as source:
        snapshot = json.load(source)
    return query_loaded(
        base, snapshot, BM25(snapshot.get("docs") or []), text, dense_k,
        lexical_k, top_k, dense_weight, lexical_weight,
        collections=collections)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--query")
    parser.add_argument("--dense-k", type=int, default=50)
    parser.add_argument("--lexical-k", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--lexical-weight", type=float, default=0.75)
    parser.add_argument("--collections", default="",
                        help="comma-separated collection allowlist "
                             "(default: all collections in the snapshot)")
    args = parser.parse_args()
    colls = [c for c in (s.strip() for s in args.collections.split(","))
             if c] or None
    if args.build:
        return build_index(args.base, args.index)
    if not args.query:
        parser.error("--build or --query is required")
    if not os.path.exists(args.index):
        parser.error(f"index missing; run --build first: {args.index}")
    print(json.dumps(query(
        args.base, args.index, args.query, args.dense_k, args.lexical_k,
        args.top_k, args.dense_weight, args.lexical_weight,
        collections=colls),
        ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
