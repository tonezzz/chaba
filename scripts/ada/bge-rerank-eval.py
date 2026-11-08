#!/usr/bin/env python3
"""Rerank experiment — rescore hybrid candidate pools with a cross-encoder.

Loads raw dense/lexical hit lists from the judged-union run, rescores the
union pool (dense top-50 + BM25 top-100) with bge-reranker-v2-m3, and
recomputes recall@k/MRR against qrels-bge-hybrid.json. This is the modern
retrieve->rerank pipeline: it replaces RRF, it does not fuse with it.
"""
import json, math, statistics, sys, time
from collections import defaultdict

WORK = "/tmp/embedeval"
HITS = "/tmp/embedeval/out/bge-hybrid-hits-20261107-053130.json"
INDEX = "/home/tony/.local/share/bge-hybrid/docs.json"
QRELS = "/tmp/embedeval/qrels-bge-hybrid.json"
MODEL = "BAAI/bge-reranker-v2-m3"
OUT = "/tmp/embedeval/out"


def jlines(p): return [json.loads(x) for x in open(p) if x.strip()]


def metrics(ranks, rel, qsub):
    rec = {k: [] for k in (1, 3, 5)}
    rr = []
    for q in qsub:
        relset = set(rel.get(q["qid"]) or [])
        if not relset:
            continue
        got = ranks.get(q["qid"]) or []
        for k in rec:
            rec[k].append(len(set(got[:k]) & relset) / len(relset))
        first = next((i + 1 for i, x in enumerate(got) if x in relset), None)
        rr.append(1.0 / first if first else 0.0)
    return {**{f"recall@{k}": round(statistics.mean(v), 3)
               for k, v in rec.items()},
            "mrr": round(statistics.mean(rr), 3) if rr else None,
            "n": len(rr)}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default="0/1",
                    help="i/N — run only this slice of the 48 queries")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    a = ap.parse_args()
    queries = jlines(f"{WORK}/queries.jsonl")
    if a.end:
        queries = queries[a.start:a.end]
        print(f"range {a.start}:{a.end}: {len(queries)} queries", flush=True)
    else:
        i, n = (int(x) for x in a.shard.split("/"))
        queries = queries[i * len(queries) // n:(i + 1) * len(queries) // n]
        print(f"shard {i}/{n}: {len(queries)} queries", flush=True)
    eval_ids = {d["id"] for d in jlines(f"{WORK}/docs.jsonl")
                if d.get("status") != "retracted"}
    text_of = {d["id"]: (d.get("text") or "") for d in jlines(f"{WORK}/docs.jsonl")}
    hits = json.load(open(HITS))
    rel = json.load(open(QRELS))

    pools = {}
    for q in queries:
        qid = q["qid"]
        dense = [i for i, _s in hits[qid]["dense"][:50] if i in eval_ids]
        lex = [i for i in hits[qid]["lex"][:100] if i in eval_ids]
        union = []
        for i in dense + lex:
            if i not in union:
                union.append(i)
        pools[qid] = {"dense": dense, "union": union}

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()
    print(f"device={device}", flush=True)

    def predict(pairs, batch_size=16):
        out = []
        with torch.no_grad():
            for i in range(0, len(pairs), batch_size):
                batch = tok(pairs[i:i + batch_size], padding=True,
                            truncation=True, max_length=512,
                            return_tensors="pt")
                batch = {k: v.to(device) for k, v in batch.items()}
                out += model(**batch).logits.view(-1).tolist()
        return out
    ranks_dense, ranks_union, lat = {}, {}, []
    for n, q in enumerate(queries, 1):
        qid = q["qid"]
        t0 = time.monotonic()
        for pool_name, pool_ids, out in (
                ("dense", pools[qid]["dense"], ranks_dense),
                ("union", pools[qid]["union"], ranks_union)):
            pairs = [[q["query"], text_of.get(i, "")[:900]] for i in pool_ids]
            scores = predict(pairs)
            out[qid] = [i for i, _s in sorted(
                zip(pool_ids, scores), key=lambda t: -t[1])]
        lat.append(time.monotonic() - t0)
        print(f"{n}/48 {qid} dense={len(pools[qid]['dense'])} "
              f"union={len(pools[qid]['union'])} {lat[-1]:.1f}s", flush=True)

    ranks = {"rerank_dense50": ranks_dense, "rerank_union": ranks_union}
    shard_tag = a.shard.replace("/", "-") +         (f"-{a.start}-{a.end}" if a.end else "")
    report = {"run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "model": MODEL, "queries": 48,
              "rerank_p50_s": round(statistics.median(lat), 3),
              "rerank_total_s": round(sum(lat), 1), "arms": {}}
    for label, sub in [("overall", queries),
                       ("english", [q for q in queries if q["lang"] == "en"]),
                       ("thai", [q for q in queries if q["lang"] == "th"])]:
        for arm, ranked in ranks.items():
            report["arms"].setdefault(label, {})[arm] = metrics(
                ranked, rel, sub)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-s{shard_tag}"
    jp = f"{OUT}/bge-rerank-{stamp}.json"
    json.dump(report, open(jp, "w"), ensure_ascii=False, indent=2)
    json.dump(ranks, open(f"{OUT}/bge-rerank-ranks-{stamp}.json", "w"))
    with open(f"{OUT}/bge-rerank-{stamp}.md", "w") as fh:
        fh.write(f"# Rerank benchmark — {MODEL} — {report['run']}\n\n")
        fh.write(f"- Rerank p50/total: {report['rerank_p50_s']}s / "
                 f"{report['rerank_total_s']}s\n\n")
        for label in ("overall", "english", "thai"):
            fh.write(f"## {label}\n\n| arm | r@1 | r@3 | r@5 | mrr |\n"
                     "|---|---|---|---|---|\n")
            for arm, m in report["arms"][label].items():
                fh.write(f"| {arm} | {m['recall@1']} | {m['recall@3']} "
                         f"| {m['recall@5']} | {m['mrr']} |\n")
            fh.write("\n")
    print(f"wrote {jp}")


if __name__ == "__main__":
    main()
