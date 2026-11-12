#!/usr/bin/env python3
"""bge-hybrid-judged.py — final judged-union benchmark for the BGE+BM25
hybrid arm.

The provisional RRF probe only judged BGE's top-10 and a partial BM25
pool, so the .408/.849 numbers were directional. This run retrieves the
full candidate union per query — dense top-50 across every collection
plus BM25 top-100 — LLM-judges every unjudged candidate against
qrels-bge.json, then rescores all arms on the expanded relevance set.

Arms:
  bge_dense     — RRF-merged per-collection dense ranking
  bm25          — lexical ranking over the snapshot
  hybrid_w{25,50,75} — dense(1.0) + lexical(w) RRF fusion

Runs on idc03 (mddb-embed + ~/.config/secrets/gemini-keys.env +
/tmp/embedeval fixture). Read-only against all banks — writes only
qrels-bge-hybrid.json and the report artifacts.

  python3 scripts/ada/bge-hybrid-judged.py \
      --work /tmp/embedeval --out /tmp/embedeval/out \
      --adapter scripts/ada/bge-hybrid-recall.py [--no-judge]
"""
import argparse
import concurrent.futures
import importlib.util
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path


def load_env(path):
    p = Path(path).expanduser()
    if not p.exists():
        return
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def jlines(path):
    return [json.loads(x) for x in open(path) if x.strip()]


def metrics(ranks, rel, qsub):
    out = {}
    for arm, ranked in ranks.items():
        rec = {k: [] for k in (1, 3, 5)}
        rr = []
        for q in qsub:
            relset = set(rel.get(q["qid"]) or [])
            if not relset:
                continue
            got = ranked.get(q["qid"]) or []
            for k in rec:
                rec[k].append(len(set(got[:k]) & relset) / len(relset))
            first = next((i + 1 for i, x in enumerate(got) if x in relset),
                         None)
            rr.append(1.0 / first if first else 0.0)
        out[arm] = {
            **{f"recall@{k}": round(statistics.mean(v), 3)
               for k, v in rec.items()},
            "mrr": round(statistics.mean(rr), 3) if rr else None,
            "n": len(rr),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/embedeval")
    ap.add_argument("--index", default=os.path.expanduser(
        "~/.local/share/bge-hybrid/docs.json"))
    ap.add_argument("--base", default=os.environ.get(
        "BGE_HYBRID_MDDB_URL", "http://100.123.163.11:11028/v1"))
    ap.add_argument("--adapter",
                    default="scripts/ada/bge-hybrid-recall.py")
    ap.add_argument("--evalmod",
                    default="scripts/ada/embed-space-eval.py")
    ap.add_argument("--secrets",
                    default="~/.config/secrets/gemini-keys.env")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dense-k", type=int, default=50)
    ap.add_argument("--lexical-k", type=int, default=100)
    ap.add_argument("--pool-cap", type=int, default=100)
    ap.add_argument("--weights", default="0.25,0.5,0.75")
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args()

    load_env(a.secrets)
    hy = load_module("bge_hybrid", a.adapter)
    work = Path(a.work)

    queries = jlines(work / "queries.jsonl")
    eval_ids = {d["id"] for d in jlines(work / "docs.jsonl")
                if d.get("status") != "retracted"}
    docs_by_id = {d["id"]: d for d in jlines(work / "docs.jsonl")}
    snapshot = json.load(open(a.index))
    bm25 = hy.BM25([d for d in (snapshot.get("docs") or [])
                    if d["id"] in eval_ids])
    colls = snapshot.get("collections") or []
    weights = [float(w) for w in a.weights.split(",")]

    # ---- phase 1: retrieve dense top-50 + lexical top-100 per query ---
    arms_dense, arms_lex, lat, raw = {}, {}, [], {}
    errors = 0
    for n, q in enumerate(queries, 1):
        t0 = time.monotonic()
        text = q["query"]
        lex = [d["id"] for d, _s in bm25.search(text, a.lexical_k)
               if d["id"] in eval_ids]
        dense_hits = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(hy.vector_collection, a.base, c, text,
                                a.dense_k) for c in colls]
            for f in concurrent.futures.as_completed(futs):
                try:
                    _c, hits, _e = f.result()
                    dense_hits.extend(hits)
                except Exception:
                    errors += 1
        # dense arm: merge collections by raw similarity score — each doc
        # lives in exactly one collection, so within-collection rank is
        # not comparable across collections (a rank-3 hit in a junk
        # collection is not a real rank-3). Keep best score per doc.
        best = {}
        for doc_id, _rank, score in dense_hits:
            if doc_id in eval_ids:
                best[doc_id] = max(score or 0, best.get(doc_id, 0))
        dense = [i for i, _s in
                 sorted(best.items(), key=lambda t: -t[1])]
        arms_dense[q["qid"]] = dense
        arms_lex[q["qid"]] = lex
        raw[q["qid"]] = {"dense": [[i, s] for i, s in
                                   sorted(best.items(),
                                          key=lambda t: -t[1])],
                         "lex": lex}
        lat.append(round(time.monotonic() - t0, 3))
        print(f"{n}/{len(queries)} {q['qid']} dense={len(dense)} "
              f"lex={len(lex)} {lat[-1]}s", flush=True)

    # ---- phase 2: judge unjudged candidates -------------------------
    rel = json.load(open(work / "qrels-bge.json"))
    qrels_out = work / "qrels-bge-hybrid.json"
    if (work / "qrels-bge-hybrid.json").exists():
        rel = json.load(open(qrels_out))
    judged_new = 0
    if not a.no_judge:
        ev = load_module("embed_eval", a.evalmod)
        for n, q in enumerate(queries, 1):
            qid = q["qid"]
            known = set(rel.get(qid) or [])
            items = []
            for i in arms_dense[qid] + arms_lex[qid]:
                if i not in known and i not in items and i in docs_by_id:
                    items.append(i)
            items = items[: a.pool_cap]
            if not items:
                continue
            listing = "\n\n".join(
                f"[{j}] bank={docs_by_id[i].get('bank','')} "
                f"key={docs_by_id[i].get('key','')}\n"
                f"{(docs_by_id[i].get('text') or '')[:700]}"
                for j, i in enumerate(items))
            prompt = (
                "You are labeling retrieval candidates for a recall "
                "benchmark. A household voice assistant ran a memory "
                "search. Decide which candidate memory docs would "
                "actually help answer the user's need — topically "
                "relevant, not just sharing a word. When in doubt about "
                "a stale or trivially related doc, leave it out.\n\n"
                f"Search query: {q['query']!r}\n"
                + (f"User said: {q['utterance']!r}\n"
                   if q.get("utterance") else "")
                + f"\nCandidates:\n{listing}\n\n"
                'Output ONLY JSON: {"relevant": [<indices>]}')
            try:
                arr = ev.extract_json(ev.gemini_chat(prompt))
                picked = sorted(
                    {items[j] for j in (arr.get("relevant") or [])
                     if isinstance(j, int) and 0 <= j < len(items)})
                rel[qid] = sorted(set(known) | set(picked))
                judged_new += len(items)
                print(f"judge {n}/{len(queries)} {qid}: {len(items)} "
                      f"new, {len(picked)} relevant", flush=True)
            except Exception as e:
                print(f"judge {qid}: ERR {e}", file=sys.stderr)
            json.dump(rel, open(qrels_out, "w"), ensure_ascii=False)
            time.sleep(2)

    # ---- phase 3: fuse + score --------------------------------------
    ranks = {"bge_dense": arms_dense, "bm25": arms_lex}
    for w in weights:
        fused = {}
        for q in queries:
            qid = q["qid"]
            fs = defaultdict(float)
            for rank, i in enumerate(arms_dense[qid], 1):
                fs[i] += 1.0 / (60 + rank)
            for rank, i in enumerate(arms_lex[qid], 1):
                fs[i] += w / (60 + rank)
            fused[qid] = [i for i, _s in
                          sorted(fs.items(), key=lambda t: -t[1])]
        ranks[f"hybrid_w{int(w * 100)}"] = fused

    report = {
        "run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "queries": len(queries),
        "dense_k": a.dense_k, "lexical_k": a.lexical_k,
        "vector_errors": errors,
        "candidates_judged": judged_new,
        "latency_p50_s": round(statistics.median(lat), 3),
        "latency_p95_s": round(
            sorted(lat)[int(len(lat) * 0.95) - 1], 3),
        "arms": {},
        "read_only": True,
    }
    for label, sub in [("overall", queries),
                       ("english", [q for q in queries
                                    if q.get("lang") == "en"]),
                       ("thai", [q for q in queries
                                 if q.get("lang") == "th"])]:
        report["arms"][label] = metrics(ranks, rel, sub)

    os.makedirs(a.out, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    hp = os.path.join(a.out, f"bge-hybrid-hits-{stamp}.json")
    json.dump(raw, open(hp, "w"), ensure_ascii=False)
    jp = os.path.join(a.out, f"bge-hybrid-judged-{stamp}.json")
    json.dump(report, open(jp, "w"), ensure_ascii=False, indent=2)
    mp = os.path.join(a.out, f"bge-hybrid-judged-{stamp}.md")
    with open(mp, "w") as fh:
        fh.write(f"# BGE hybrid judged-union benchmark — {report['run']}\n\n")
        fh.write(f"- Queries: {report['queries']} "
                 f"(dense top-{a.dense_k} + BM25 top-{a.lexical_k})\n")
        fh.write(f"- New candidates judged: {judged_new}\n")
        fh.write(f"- Vector errors: {errors}\n")
        fh.write(f"- Latency p50/p95: {report['latency_p50_s']}s / "
                 f"{report['latency_p95_s']}s\n\n")
        for label in ("overall", "english", "thai"):
            fh.write(f"## {label}\n\n| arm | r@1 | r@3 | r@5 | mrr | n |\n"
                     "|---|---|---|---|---|---|\n")
            for arm, m in report["arms"][label].items():
                fh.write(f"| {arm} | {m['recall@1']} | {m['recall@3']} "
                         f"| {m['recall@5']} | {m['mrr']} | {m['n']} |\n")
            fh.write("\n")
    print(f"wrote {jp}\nwrote {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
