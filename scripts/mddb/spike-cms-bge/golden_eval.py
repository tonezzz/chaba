#!/usr/bin/env python3
"""Golden-set eval for the mddb-cms :11027 embed space (card MEM-0204 /
cms-plane-bge-golden-set-eval-measure-re-cad4f4).

Context: MEM-0193 proved bge-m3 scratch parity on top-10 overlap but showed
rankings shift ~2/3, and noted :11027 was migrated to bge-m3 on 2026-11-19 —
the gemini baseline no longer exists as a live index. This harness therefore
scores THREE arms on the same golden queries + qrels (golden_set.json):

  prod-index   — live :11027 /v1/vector-search (bge-m3 index, chunked,
                 full-collection ranking). This is what users get today.
  gemini-cos   — doc-level cosine: query + pooled candidate docs embedded
                 via gemini-ollama-proxy :11435 (gemini-embedding-2, 768d).
                 The paid-space reference arm — same methodology as
                 docs/ssot/jobs/ada/2026-10-15-embed-space-eval.yml.
  bge-cos      — same pool via embed-pool-shim :11436 (bge-m3, 1024d).

Pool per query = union(:11027 vector-search top-12, qrel keys). Doccos arms
rank within the pool only (pooled-eval caveat — absolute recall is
optimistic vs full-corpus, but arm-vs-arm deltas are apples-to-apples and
the prod-index arm provides the full-corpus number).

Doc text = "<title/meta-title>\n\n<contentMd[:1500]>" — 1500c matches
mddb's chunkSize; prior eval validated doc-cosine ≈ prod index within ~3%.

Usage:
    python3 golden_eval.py [--golden golden_set.json] [--out results.json]
    # gemini proxy must be reachable at GEMINI_PROXY (default
    # http://127.0.0.1:11435 — ssh -L forward to idc03 if needed)
"""
import argparse
import concurrent.futures as cf
import json
import math
import os
import time
import urllib.request

MDDB = os.environ.get("MDDB_CMS_URL", "http://100.102.134.91:11027")
GEMINI = os.environ.get("GEMINI_PROXY", "http://127.0.0.1:11435")
BGE = os.environ.get("BGE_SHIM", "http://100.102.134.91:11436")
POOL_VEC_K = 12
DOC_CHARS = 1500


def post(url, payload, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def vsearch(coll, query, k=10):
    d = post(f"{MDDB}/v1/vector-search",
             {"collection": coll, "query": query, "topK": k,
              "limit": k, "includeContent": False})
    return [((x.get("document") or {}).get("key") or x.get("key"))
            for x in (d.get("results") or [])]


def get_doc(coll, key):
    def fetch(**kw):
        return post(f"{MDDB}/v1/get",
                    {"collection": coll, "key": key,
                     "include_content": True, **kw}, timeout=60)
    try:
        d = fetch()
    except Exception:
        d = None
    # prefer a lang variant that actually carries content
    if d is not None and not (d.get("contentMd") or "").strip():
        for lang in ("en", "th"):
            try:
                d2 = fetch(lang=lang)
                if (d2.get("contentMd") or "").strip():
                    return d2
            except Exception:
                continue
    if d is not None:
        return d
    for lang in ("en", "th"):
        try:
            return fetch(lang=lang)
        except Exception:
            continue
    return None


def doc_text(d):
    if not d:
        return ""
    meta = d.get("meta") or {}
    title = ""
    if isinstance(meta, dict):
        for k in ("title", "wiki_title", "topic"):
            v = meta.get(k)
            if v:
                title = str(v[0] if isinstance(v, list) else v)
                break
    body = (d.get("contentMd") or "")[:DOC_CHARS]
    return f"{title}\n\n{body}".strip()


EMBED_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".embed_cache.json")
_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        try:
            _cache = json.load(open(EMBED_CACHE))
        except Exception:
            _cache = {}
    return _cache


def _save_cache():
    tmp = EMBED_CACHE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_cache, f)
    os.replace(tmp, EMBED_CACHE)


def embed(base, model, texts, batch=8):
    import hashlib
    cache = _load_cache()
    out, todo_idx, todo_txt = [], [], []
    for i, t in enumerate(texts):
        h = hashlib.sha1(f"{model}|{t}".encode()).hexdigest()
        if h in cache:
            out.append((i, cache[h]))
        else:
            todo_idx.append(i)
            todo_txt.append(t)
    res = [None] * len(texts)
    for i, v in out:
        res[i] = v
    for i in range(0, len(todo_txt), batch):
        chunk = todo_txt[i:i + batch]
        vecs = None
        for attempt in range(6):
            try:
                d = post(f"{base}/api/embed",
                         {"model": model, "input": chunk}, timeout=180)
                embs = d.get("embeddings") or []
                if len(embs) == len(chunk):
                    vecs = embs
                    break
            except Exception:
                pass
            time.sleep(4 * (attempt + 1))
        if vecs is None:
            raise RuntimeError(f"embed failed at offset {i} on {base}")
        for j, v in enumerate(vecs):
            idx = todo_idx[i + j]
            res[idx] = v
            t = texts[idx]
            h = hashlib.sha1(f"{model}|{t}".encode()).hexdigest()
            cache[h] = v
        _save_cache()
    return res


def cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def metrics(ranked, relevant):
    rel = set(relevant)
    seen = []
    for k in ranked:
        if k not in seen:
            seen.append(k)
    ranked = seen  # dedupe lang-variant double hits on the same key
    hits5 = sum(1 for k in ranked[:5] if k in rel)
    hits10 = sum(1 for k in ranked[:10] if k in rel)
    rr = 0.0
    for i, k in enumerate(ranked, 1):
        if k in rel:
            rr = 1.0 / i
            break
    n = len(rel)
    return {"recall@5": hits5 / n, "recall@10": hits10 / n, "mrr": rr,
            "n_rel": n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=os.path.join(
        os.path.dirname(__file__), "golden_set.json"))
    ap.add_argument("--out", default="golden_eval_results.json")
    ap.add_argument("--skip-doccos", action="store_true",
                    help="prod-index arm only (no embedding calls)")
    args = ap.parse_args()

    golden = json.load(open(args.golden))["queries"]
    rows = []

    # ---- pass 1: prod-index arm + build pools ----
    pools = {}
    for i, q in enumerate(golden):
        coll, query, rel = q["collection"], q["query"], q["relevant"]
        top = [k for k in vsearch(coll, query, POOL_VEC_K) if k]
        pool = list(dict.fromkeys(top + rel))[:POOL_VEC_K + len(rel)]
        pools[i] = pool
        ranked = top[:10]
        rows.append({"i": i, "collection": coll, "query": query,
                     "relevant": rel, "pool": pool,
                     "prod": {"ranked": ranked, **metrics(ranked, rel)}})
        print(f"[{i+1}/{len(golden)}] prod {coll}: "
              f"r@5={rows[-1]['prod']['recall@5']:.2f} "
              f"pool={len(pool)}", flush=True)

    if args.skip_doccos:
        finish(rows, args.out)
        return

    # ---- pass 2: fetch pool doc texts ----
    def fetch(pi):
        i, pool = pi
        q = golden[i]
        texts = {}
        for k in pool:
            d = get_doc(q["collection"], k)
            texts[k] = doc_text(d)
        return i, texts

    doc_texts = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, texts in ex.map(fetch, pools.items()):
            doc_texts[i] = texts
    print("pool docs fetched")

    # ---- pass 3: embed queries + docs per arm ----
    arms = {"gemini": (GEMINI, "gemini-embedding-2"),
            "bge": (BGE, "bge-m3")}
    arm_ranked = {a: {} for a in arms}
    for arm, (base, model) in arms.items():
        # queries
        qtexts = [q["query"] for q in golden]
        qembs = embed(base, model, qtexts)
        # docs (dedup across queries within same collection+key)
        doc_jobs = {}   # (i, key) -> text
        uniq = {}
        for i, texts in doc_texts.items():
            for k, t in texts.items():
                if t:
                    uniq.setdefault((golden[i]["collection"], k), t)
        keys = list(uniq)
        print(f"{arm}: embedding {len(qtexts)} queries + "
              f"{len(keys)} unique docs", flush=True)
        dembs = embed(base, model, [uniq[k] for k in keys])
        dvec = {k: v for k, v in zip(keys, dembs)}
        for i, q in enumerate(golden):
            coll = q["collection"]
            scored = []
            for k in pools[i]:
                dv = dvec.get((coll, k))
                if dv is None:
                    continue
                scored.append((cos(qembs[i], dv), k))
            scored.sort(key=lambda x: -x[0])
            arm_ranked[arm][i] = [k for _, k in scored[:10]]
        print(f"{arm}: done", flush=True)

    for i, q in enumerate(golden):
        rel = q["relevant"]
        rows[i]["gemini"] = {"ranked": arm_ranked["gemini"][i],
                             **metrics(arm_ranked["gemini"][i], rel)}
        rows[i]["bge"] = {"ranked": arm_ranked["bge"][i],
                          **metrics(arm_ranked["bge"][i], rel)}

    finish(rows, args.out)


def finish(rows, out):
    # ---- aggregate ----
    per_coll = {}
    for r in rows:
        c = per_coll.setdefault(r["collection"], {"n": 0})
        c["n"] += 1
        for arm in ("prod", "gemini", "bge"):
            if arm in r:
                for m in ("recall@5", "recall@10", "mrr"):
                    c.setdefault(arm, {}).setdefault(m, []).append(
                        r[arm][m])
    summary = {"per_collection": {}, "overall": {}}
    for coll, c in per_coll.items():
        summary["per_collection"][coll] = {
            "n": c["n"],
            **{arm: {m: round(sum(v) / len(v), 4)
                     for m, v in c.get(arm, {}).items()}
               for arm in ("prod", "gemini", "bge") if arm in c}}
    allrows = {"n": len(rows)}
    for arm in ("prod", "gemini", "bge"):
        vals = {m: [r[arm][m] for r in rows if arm in r]
                for m in ("recall@5", "recall@10", "mrr")}
        allrows[arm] = {m: round(sum(v) / len(v), 4) for m, v in vals.items()}
    summary["overall"] = allrows

    print("\n=== OVERALL ===")
    print(json.dumps(allrows, indent=2))
    print("\n=== PER COLLECTION ===")
    for coll, c in sorted(summary["per_collection"].items()):
        print(f"{coll} (n={c['n']}): {json.dumps(c)}")

    with open(out, "w") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
