#!/usr/bin/env python3
"""embed-space-eval.py — recall@k benchmark across embedding spaces.

Card embed-space-eval: can the mddb memory banks migrate off
gemini-embedding-2 onto local nomic-embed-text, and does translating
Thai text to English first close the gap?

Arms (rankings computed by cosine over doc-level embeddings):
  gemini    — gemini-embedding-2 (768d) — the production space
  nomic     — nomic-embed-text via Ollama on the raw text
  nomic_en  — nomic-embed-text, but Thai-containing docs/queries are
              translated to English first (flash free tier)
  mddb      — production reference: per-collection /v1/vector-search
              with a gemini query vector (mddb's own chunking +
              int8-quantized index)

Eval set: ~30-50 real ada_memory_search queries from the bankq corpus
(mined by scripts/ada/bank-router-mine.py from ada-ha-tony journals).
Labels: LLM-judged relevance on the pooled top-10 of every arm.

Runs on idc03 (needs ~/.config/secrets/gemini-keys.env for
GEMINI_API_KEY_FREE, local Ollama nomic-embed-text, and local mddb):

    cd ~/CascadeProjects/chaba && set -a && \
      source ~/.config/secrets/gemini-keys.env && set +a && \
      python3 scripts/ada/embed-space-eval.py --work /tmp/embedeval --all

Stages (each resumable — existing artifacts are reused):
  --fetch --select --translate --embed --prod --label --score | --all
"""
import argparse
import base64
import json
import math
import os
import re
import statistics
import struct
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

MDDB_VEC = os.environ.get("MDDB_BASE_URL", "http://127.0.0.1:11023")
MDDB_CMS = os.environ.get("MDDB_CMS_URL", "http://100.102.134.91:11027")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or \
    os.environ.get("GEMINI_API_KEY_FREE", "")
EMBED_MODELS = ["gemini-embedding-2", "gemini-embedding-001"]
CHAT_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
DIMS = 768
DOC_CHARS = 1500          # mddb chunk size — embed the same window
NOMIC_DOC = "search_document: "
NOMIC_QRY = "search_query: "
THAI_RE = re.compile(r"[ก-๙]")

# Vector-searched tony collections — ops-routed collections
# (ada-ha-recall-summary-*, ada-ha-scenario-reports) are keyword-ranked in
# production, NOT embedded, so they are out of scope for a space
# migration.  personal-kk/testo stay: they appear in mined hit_banks.
BANK_COLLS = {
    "chaba-archive": "chaba-archive",
    "chaba-docs": "chaba-docs",
    "cms": "ada-cms-pages",
    "developer": "ada-ha-bank-developer-tony",
    "devin": "ada-ha-bank-devin-tony",
    "devin-handoff": "ada-ha-bank-devin-handoff",
    "devin-kb": "devin-kb",
    "documents": "documents",
    "general": "ada-ha-bank-general",
    "github": "ada-ha-bank-github",
    "home": "ada-ha-bank-home",
    "ideas": "ada-ha-bank-ideas-tony",
    "infrastructure-ssot": "infrastructure-ssot",
    "kb-development": "kb-development",
    "kb-features": "kb-features",
    "kb-operations": "kb-operations",
    "kb-system": "kb-system",
    "note": "ada-ha-bank-note-tony",
    "people": "ada-ha-bank-people",
    "personal": "ada-ha-bank-personal-tony",
    "personal-kk": "ada-ha-bank-personal-kk",
    "personal-testo": "ada-ha-bank-personal-testo",
    "purchase": "ada-ha-bank-purchase",
    "tony-projects": "ada-ha-bank-projects-tony",
}
CMS_PREFIX = ("ada-cms-", "chaba-", "kb-")
CMS_EXACT = {"documents", "infrastructure-ssot", "devin-kb", "ada-tools",
             "ada-scenario", "ada-session-audit", "ada-tool-profile",
             "ssot"}


def mddb_base(coll: str) -> str:
    return (MDDB_CMS if coll.startswith(CMS_PREFIX) or coll in CMS_EXACT
            else MDDB_VEC)


def post(url: str, payload: dict, timeout: float = 60.0,
         headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def jload(path: str, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def jlines(path: str):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def jdump(path: str, obj) -> None:
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def wlines(path: str, rows, mode="w") -> None:
    with open(path, mode) as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def is_thai(s: str) -> bool:
    return bool(THAI_RE.search(s or ""))


def doc_status(meta: dict) -> str:
    v = (meta or {}).get("status") or ["active"]
    return str(v[0]) if isinstance(v, list) and v else str(v)


# ---------------------------------------------------------------- fetch
def stage_fetch(work: str) -> None:
    out = os.path.join(work, "docs.jsonl")
    if os.path.exists(out):
        print(f"fetch: {len(jlines(out))} docs (cached)")
        return
    rows = []
    for bank, coll in sorted(BANK_COLLS.items()):
        try:
            docs = post(mddb_base(coll) + "/v1/search",
                        {"collection": coll, "limit": 5000})
        except Exception as e:
            print(f"fetch {coll}: ERR {e}", file=sys.stderr)
            continue
        n = 0
        for d in (docs if isinstance(docs, list)
                  else docs.get("results") or []):
            text = (d.get("contentMd") or d.get("content") or "")[:DOC_CHARS]
            if len(text) < 20:
                continue
            rows.append({
                "id": d.get("id") or f"{coll}|{d.get('key')}|{d.get('lang')}",
                "collection": coll, "bank": bank,
                "key": d.get("key"), "lang": d.get("lang"),
                "status": doc_status(d.get("meta")),
                "text": text,
                "thai": is_thai(text),
            })
            n += 1
        print(f"fetch {bank:20s} {coll:38s} {n}")
        time.sleep(0.2)
    wlines(out, rows)
    print(f"fetch: {len(rows)} docs -> {out}")


# --------------------------------------------------------------- select
def stage_select(work: str, corpus: str, n_en: int, n_th: int,
                 n_ctrl: int) -> None:
    out = os.path.join(work, "queries.jsonl")
    if os.path.exists(out):
        print(f"select: {len(jlines(out))} queries (cached)")
        return
    rows = jlines(corpus)
    seen, uniq = set(), []
    for r in rows:
        q = (r.get("query") or "").strip()
        if len(q) < 3:
            continue
        k = re.sub(r"\s+", " ", q.lower())
        if k in seen:
            continue
        seen.add(k)
        r = dict(r)
        r["lang"] = "th" if is_thai(q) else "en"
        uniq.append(r)

    vec_banks = set(BANK_COLLS)
    en_pool = [r for r in uniq if r["lang"] == "en"
               and r.get("hit_count", 0) > 0
               and r.get("top_bank") in vec_banks]
    th_pool = [r for r in uniq if r["lang"] == "th"
               and r.get("hit_count", 0) > 0]
    ctrl_pool = [r for r in uniq if r["lang"] == "en"
                 and r.get("top_bank") in ("sessions", "ops-scenarios")
                 and r.get("hit_count", 0) > 0]

    def spread(pool, n, per_bank=4):
        """Round-robin across top_bank for diversity; also dedupe
        queries sharing the same first 4 normalized tokens."""
        by_bank: dict[str, list] = {}
        seen_pref = set()
        for r in pool:
            pref = " ".join(r["query"].lower().split()[:4])
            if pref in seen_pref:
                continue
            seen_pref.add(pref)
            by_bank.setdefault(r.get("top_bank") or "?", []).append(r)
        pick, order = [], sorted(by_bank, key=lambda b: -len(by_bank[b]))
        while len(pick) < n and order:
            nxt = []
            for b in order:
                if len(pick) >= n:
                    break
                lst = by_bank[b]
                cap = per_bank if b != "devin" else per_bank + 2
                taken = sum(1 for p in pick if
                            (p.get("top_bank") or "?") == b)
                if lst and taken < cap:
                    pick.append(lst.pop(0))
                if lst and taken + 1 < cap:
                    nxt.append(b)
            order = nxt
        return pick

    # prefer rows that carry the user's utterance (judge context)
    for pool in (en_pool, th_pool, ctrl_pool):
        pool.sort(key=lambda r: 0 if r.get("utterance") else 1)

    sel = (spread(en_pool, n_en) + spread(th_pool, n_th, per_bank=3)
           + spread(ctrl_pool, n_ctrl))
    for i, r in enumerate(sel):
        r["qid"] = f"q{i:02d}"
    wlines(out, sel)
    c = Counter((r["lang"], r.get("top_bank")) for r in sel)
    print(f"select: {len(sel)} queries -> {out}")
    for k, v in sorted(c.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        print("   ", k, v)


# ------------------------------------------------------------ translate
CHAT_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent?key={key}")


def gemini_chat(prompt: str, tries: int = 4) -> str:
    err = None
    for model in CHAT_MODELS:
        for attempt in range(tries):
            try:
                d = post(CHAT_URL.format(model=model, key=GEMINI_KEY),
                         {"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {
                              "responseMimeType": "application/json"}},
                         timeout=90)
                parts = (d.get("candidates") or [{}])[0] \
                    .get("content", {}).get("parts") or []
                txt = "".join(p.get("text", "") for p in parts)
                if txt.strip():
                    return txt
                err = f"{model}: empty"
            except Exception as e:
                err = f"{model}: {e}"
                if "429" in str(e) or "503" in str(e):
                    time.sleep(5 * (attempt + 1))
                    continue
                break
        else:
            continue
    raise RuntimeError(f"gemini_chat failed: {err}")


def extract_json(txt: str):
    txt = txt.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        txt = m.group(1)
    s, e = min((txt.find(c) for c in "[{" if txt.find(c) >= 0),
               default=0), max(txt.rfind("]"), txt.rfind("}"))
    return json.loads(txt[s:e + 1])


def stage_translate(work: str) -> None:
    out = os.path.join(work, "translations.json")
    done = jload(out, {})
    docs = jlines(os.path.join(work, "docs.jsonl"))
    queries = jlines(os.path.join(work, "queries.jsonl"))
    todo = [{"tid": f"doc:{d['id']}", "text": d["text"][:1200]}
            for d in docs if d["thai"] and f"doc:{d['id']}" not in done]
    todo += [{"tid": f"q:{q['qid']}", "text": q["query"]}
             for q in queries if q["lang"] == "th"
             and f"q:{q['qid']}" not in done]
    print(f"translate: {len(todo)} texts to translate "
          f"({len(done)} cached)")
    B = 8
    for i in range(0, len(todo), B):
        chunk = todo[i:i + B]
        prompt = (
            "Translate each text below to natural English for "
            "embedding-based memory retrieval. Texts are Thai or "
            "mixed Thai/English memory notes and search queries about "
            "a household (people: Tony, KK/คุณกุ้ง/Kaewta/แก้วตา, Testo, "
            "Nhong; places: Noble Park, Bangkok). Preserve names, "
            "numbers, plates, dates. Output ONLY a JSON array of "
            "English strings, same order, same length.\n\n"
            + "\n".join(f"[{j}] {t['text']!r}"
                        for j, t in enumerate(chunk)))
        try:
            arr = extract_json(gemini_chat(prompt))
            if not isinstance(arr, list) or len(arr) != len(chunk):
                raise ValueError(f"len {len(arr)} != {len(chunk)}")
            for t, en in zip(chunk, arr):
                done[t["tid"]] = str(en)
        except Exception as e:
            print(f"translate batch {i}: ERR {e} — items skipped",
                  file=sys.stderr)
        jdump(out, done)
        print(f"translate: {min(i + B, len(todo))}/{len(todo)}")
        time.sleep(3)
    print(f"translate: {len(done)} total -> {out}")


# ---------------------------------------------------------------- embed
def embed_gemini(texts: list[str]) -> list[list[float]]:
    last = None
    for model in EMBED_MODELS:
        payload = {"requests": [{
            "model": f"models/{model}",
            "content": {"parts": [{"text": t}]},
            "outputDimensionality": DIMS,
        } for t in texts]}
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:batchEmbedContents?key={GEMINI_KEY}")
        try:
            d = post(url, payload, timeout=120)
            embs = [e["values"] for e in d.get("embeddings", [])]
            if len(embs) == len(texts):
                return embs
            last = f"{len(embs)}/{len(texts)}"
        except Exception as e:
            last = str(e)
    raise RuntimeError(f"gemini embed failed: {last}")


def embed_nomic(texts: list[str]) -> list[list[float]]:
    d = post(f"{OLLAMA}/api/embed",
             {"model": "nomic-embed-text", "input": texts}, timeout=300)
    return d["embeddings"]


def b64e(v: list[float]) -> str:
    return base64.b64encode(
        struct.pack(f"<{len(v)}f", *v)).decode()


def b64d(s: str) -> list[float]:
    raw = base64.b64decode(s)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def _save_vecs(path: str, vecs: dict, mode="a") -> None:
    with open(path, mode) as f:
        for k, v in vecs.items():
            f.write(json.dumps({"id": k, "v": b64e(v)}) + "\n")


def stage_embed(work: str) -> None:
    docs = jlines(os.path.join(work, "docs.jsonl"))
    queries = jlines(os.path.join(work, "queries.jsonl"))
    trans = jload(os.path.join(work, "translations.json"), {})
    lat_path = os.path.join(work, "latency.json")
    lat = jload(lat_path, {})

    def have(path):
        return {r["id"] for r in jlines(path)}

    def embed_docs(arm: str, text_of, skip_done=True):
        path = os.path.join(work, f"vec-{arm}.jsonl")
        done = have(path) if skip_done else set()
        todo = [d for d in docs if d["id"] not in done]
        print(f"embed {arm}: {len(todo)} docs "
              f"({len(done)} cached)")
        B = 25 if arm == "gemini" else 32
        for i in range(0, len(todo), B):
            chunk = todo[i:i + B]
            texts = [text_of(d) for d in chunk]
            for attempt in range(6):
                try:
                    vs = (embed_gemini(texts) if arm == "gemini"
                          else embed_nomic(texts))
                    break
                except Exception as e:
                    print(f"  {arm} batch {i} try{attempt}: {e}",
                          file=sys.stderr)
                    time.sleep((30 * (attempt + 1)) if arm == "gemini"
                               else 4 * (attempt + 1))
            else:
                raise SystemExit(f"embed {arm} failed at {i}")
            _save_vecs(path, {d["id"]: v for d, v in zip(chunk, vs)})
            if i % 500 == 0:
                print(f"  {arm}: {i}/{len(todo)}")
            time.sleep(5 if arm == "gemini" else 0.05)

    # --- doc vectors ---------------------------------------------------
    embed_docs("nomic", lambda d: NOMIC_DOC + d["text"])
    if os.environ.get("SKIP_GEMINI_DOCS") != "1":
        embed_docs("gemini", lambda d: d["text"])
    # nomic_en: non-thai docs reuse the nomic vectors; only the ~500
    # translated texts need a fresh embed.
    ne_path = os.path.join(work, "vec-nomic_en.jsonl")
    nvecs = load_vec(os.path.join(work, "vec-nomic.jsonl"))
    have_ne = {r["id"] for r in jlines(ne_path)}
    with open(ne_path, "a") as f:
        for d in docs:
            if d["id"] in have_ne:
                continue
            if not d["thai"] and d["id"] in nvecs:
                f.write(json.dumps({"id": d["id"],
                                    "v": b64e(nvecs[d["id"]])}) + "\n")
    embed_docs("nomic_en", lambda d: NOMIC_DOC + (
        trans.get(f"doc:{d['id']}", d["text"]) if d["thai"] else d["text"]))

    # --- query vectors + per-query latency -----------------------------
    qpath = os.path.join(work, "vec-queries.jsonl")
    qdone = {r["id"] for r in jlines(qpath)}
    lat.setdefault("gemini", {})
    lat.setdefault("nomic", {})
    lat.setdefault("nomic_en", {})
    for q in queries:
        qid = q["qid"]
        if qid in qdone:
            continue
        row = {"id": qid}
        t0 = time.time()
        row["gemini"] = b64e(embed_gemini([q["query"]])[0])
        lat["gemini"][qid] = round(time.time() - t0, 3)
        t0 = time.time()
        row["nomic"] = b64e(embed_nomic([NOMIC_QRY + q["query"]])[0])
        lat["nomic"][qid] = round(time.time() - t0, 3)
        t0 = time.time()
        qtext = (trans.get(f"q:{qid}", q["query"])
                 if q["lang"] == "th" else q["query"])
        row["nomic_en"] = b64e(embed_nomic([NOMIC_QRY + qtext])[0])
        lat["nomic_en"][qid] = round(time.time() - t0, 3)
        with open(qpath, "a") as f:
            f.write(json.dumps(row) + "\n")
        jdump(lat_path, lat)
        print(f"  q {qid}: g={lat['gemini'][qid]:.2f}s "
              f"n={lat['nomic'][qid]:.2f}s "
              f"ne={lat['nomic_en'][qid]:.2f}s")
        time.sleep(0.3)
    print("embed: done")


# ----------------------------------------------------------------- prod
def stage_prod(work: str) -> None:
    out = os.path.join(work, "prod-hits.jsonl")
    done = {r["qid"] for r in jlines(out)}
    queries = jlines(os.path.join(work, "queries.jsonl"))
    qvecs = {r["id"]: r for r in jlines(
        os.path.join(work, "vec-queries.jsonl"))}
    todo = [q for q in queries if q["qid"] not in done]
    print(f"prod: {len(todo)} queries x {len(BANK_COLLS)} colls")

    def one(q):
        qv = b64d(qvecs[q["qid"]]["gemini"])
        hits = []
        def search(bank_coll):
            bank, coll = bank_coll
            try:
                d = post(mddb_base(coll) + "/v1/vector-search",
                         {"collection": coll, "queryVector": qv,
                          "topK": 10, "includeContent": False},
                         timeout=30)
                for h in d.get("results") or []:
                    doc = h.get("document") or {}
                    hits.append({"id": doc.get("id"),
                                 "bank": bank, "score": h.get("score")})
            except Exception as e:
                hits.append({"id": None, "bank": bank,
                             "err": str(e)[:80]})
        with ThreadPoolExecutor(12) as ex:
            list(ex.map(search, sorted(BANK_COLLS.items())))
        hits = [h for h in hits if h.get("id")]
        hits.sort(key=lambda h: -(h.get("score") or 0))
        return {"qid": q["qid"], "hits": hits[:10]}

    with open(out, "a") as f:
        for q in todo:
            r = one(q)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  prod {r['qid']}: top={r['hits'][0]['bank'] if r['hits'] else '-'}")
    print("prod: done")


# ----------------------------------------------------------------- label
def cos(a, b):
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


def load_vec(path: str) -> dict[str, list[float]]:
    return {r["id"]: b64d(r["v"]) for r in jlines(path)}


def active_docs(work: str) -> dict[str, dict]:
    """Ranking pool — status=retracted docs are dropped (production
    hides them by default); drafts stay (they surface framed)."""
    return {d["id"]: d for d in jlines(os.path.join(work, "docs.jsonl"))
            if d["status"] != "retracted"}


def rank_arm(arm: str, qvec, dvecs, doc_ids):
    scored = [(cos(qvec, dvecs[i]), i) for i in doc_ids]
    scored.sort(key=lambda t: -t[0])
    return scored


def stage_label(work: str, topn: int) -> None:
    out = os.path.join(work, "qrels.json")
    rel = jload(out, {})
    cand_path = os.path.join(work, "candidates.jsonl")
    queries = jlines(os.path.join(work, "queries.jsonl"))
    docs = active_docs(work)
    doc_ids = list(docs)
    dvecs = {a: load_vec(os.path.join(work, f"vec-{a}.jsonl"))
             for a in ("gemini", "nomic", "nomic_en")}
    qvecs = {r["id"]: {a: b64d(r[a]) for a in ("gemini", "nomic", "nomic_en")}
             for r in jlines(os.path.join(work, "vec-queries.jsonl"))}
    prod = {r["qid"]: [h["id"] for h in r["hits"]]
            for r in jlines(os.path.join(work, "prod-hits.jsonl"))}

    # build/rebuild candidate pools for unlabeled queries
    cand = {r["qid"]: r["candidates"] for r in jlines(cand_path)}
    for q in queries:
        qid = q["qid"]
        if qid in rel:
            continue
        if qid not in cand:
            pool: list[str] = []
            for a in ("gemini", "nomic", "nomic_en"):
                for _, i in rank_arm(a, qvecs[qid][a], dvecs[a],
                                     doc_ids)[:topn]:
                    if i not in pool:
                        pool.append(i)
            for i in prod.get(qid, []):
                if i in docs and i not in pool:
                    pool.append(i)
            cand[qid] = pool[: topn * 4]
        items = cand[qid]
        listing = "\n\n".join(
            f"[{j}] bank={docs[i]['bank']} key={docs[i]['key']}\n"
            f"{docs[i]['text'][:700]}"
            for j, i in enumerate(items))
        prompt = (
            "You are labeling retrieval candidates for a recall "
            "benchmark. A household voice assistant ran a memory "
            "search. Decide which candidate memory docs would actually "
            "help answer the user's need — topically relevant, not "
            "just sharing a word. When in doubt about a stale or "
            "trivially related doc, leave it out.\n\n"
            f"Search query: {q['query']!r}\n"
            + (f"User said: {q['utterance']!r}\n"
               if q.get("utterance") else "")
            + f"\nCandidates:\n{listing}\n\n"
            'Output ONLY JSON: {"relevant": [<indices>]}')
        try:
            arr = extract_json(gemini_chat(prompt))
            rel[qid] = sorted({items[j] for j in
                               (arr.get("relevant") or [])
                               if isinstance(j, int) and 0 <= j < len(items)})
        except Exception as e:
            print(f"label {qid}: ERR {e}", file=sys.stderr)
        jdump(out, rel)
        wlines(cand_path, [{"qid": k, "candidates": v}
                           for k, v in cand.items()])
        print(f"label {qid}: {len(rel.get(qid, []))} relevant "
              f"of {len(items)}")
        time.sleep(3)
    print(f"label: {len(rel)} queries -> {out}")


# ----------------------------------------------------------------- score
def stage_score(work: str, topn: int) -> None:
    queries = jlines(os.path.join(work, "queries.jsonl"))
    docs = active_docs(work)
    doc_ids = list(docs)
    rel = jload(os.path.join(work, "qrels.json"), {})
    lat = jload(os.path.join(work, "latency.json"), {})
    dvecs = {a: load_vec(os.path.join(work, f"vec-{a}.jsonl"))
             for a in ("gemini", "nomic", "nomic_en")}
    qvec_rows = {r["id"]: r for r in jlines(
        os.path.join(work, "vec-queries.jsonl"))}
    prod = {r["qid"]: [h["id"] for h in r["hits"]]
            for r in jlines(os.path.join(work, "prod-hits.jsonl"))}
    bank_of = {i: d["bank"] for i, d in docs.items()}
    coll_of = {i: d["collection"] for i, d in docs.items()}

    arms = ["gemini", "nomic", "nomic_en", "mddb"]
    # per-query ranked lists
    ranks: dict[str, dict[str, list[str]]] = {}
    for q in queries:
        qid = q["qid"]
        if qid not in qvec_rows:
            continue
        ranks[qid] = {}
        qr = qvec_rows[qid]
        for a in ("gemini", "nomic", "nomic_en"):
            ranks[qid][a] = [i for _, i in rank_arm(
                a, b64d(qr[a]), dvecs[a], doc_ids)]
        ranks[qid]["mddb"] = [i for i in prod.get(qid, []) if i in docs]

    def pct(v, p):
        if not v:
            return float("nan")
        s = sorted(v)
        k = (len(s) - 1) * p / 100
        f = math.floor(k)
        return round(s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (k - f), 3)

    def metrics(qsub):
        out = {}
        for a in arms:
            rec = {k: [] for k in (1, 3, 5)}
            rr, topbank_hit5 = [], []
            n_eval = 0
            for q in qsub:
                qid = q["qid"]
                relset = set(rel.get(qid) or [])
                if not relset or qid not in ranks:
                    continue
                n_eval += 1
                got = ranks[qid][a]
                for k in rec:
                    rec[k].append(
                        len(set(got[:k]) & relset) / len(relset))
                first = next((i + 1 for i, d in enumerate(got)
                              if d in relset), None)
                rr.append(1.0 / first if first else 0.0)
                top5_banks = {bank_of.get(d) for d in got[:5]}
                topbank_hit5.append(q.get("top_bank") in top5_banks)
            out[a] = {
                "n": n_eval,
                "recall@1": round(statistics.fmean(rec[1]), 3),
                "recall@3": round(statistics.fmean(rec[3]), 3),
                "recall@5": round(statistics.fmean(rec[5]), 3),
                "mrr": round(statistics.fmean(rr), 3),
                "top_bank_in_top5": round(
                    statistics.fmean(topbank_hit5), 3),
            }
        return out

    en_q = [q for q in queries if q["lang"] == "en"]
    th_q = [q for q in queries if q["lang"] == "th"]
    rep = {
        "run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "docs_pool": len(doc_ids),
        "queries": len(queries),
        "labeled": len(rel),
        "no_relevant": sum(1 for q in queries
                           if not rel.get(q["qid"])),
        "arms": arms,
        "overall": metrics(queries),
        "en": metrics(en_q),
        "th": metrics(th_q),
        "query_latency_s": {
            a: {"p50": pct(list(lat.get(a, {}).values()), 50),
                "p95": pct(list(lat.get(a, {}).values()), 95)}
            for a in ("gemini", "nomic", "nomic_en")},
    }
    # cross-arm agreement: gemini top5 vs others
    agree = {}
    for a in ("nomic", "nomic_en"):
        ov = []
        for q in queries:
            qid = q["qid"]
            if qid in ranks and ranks[qid].get(a):
                ov.append(len(set(ranks[qid]["gemini"][:5])
                              & set(ranks[qid][a][:5])) / 5)
        agree[a] = round(statistics.fmean(ov), 3) if ov else None
    rep["top5_overlap_vs_gemini"] = agree
    jdump(os.path.join(work, "report.json"), rep)
    print(json.dumps(rep, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------ cli
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/embedeval")
    ap.add_argument("--corpus",
                    default="experiments/query-cache-phase0/"
                            "bankq-corpus-20261008.jsonl")
    ap.add_argument("--n-en", type=int, default=30)
    ap.add_argument("--n-th", type=int, default=14)
    ap.add_argument("--n-ctrl", type=int, default=4)
    ap.add_argument("--topn", type=int, default=10)
    for s in ("fetch", "select", "translate", "embed", "prod",
              "label", "score", "all"):
        ap.add_argument(f"--{s}", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.work, exist_ok=True)
    if not GEMINI_KEY:
        sys.exit("need GEMINI_API_KEY[_FREE] (gemini-keys.env)")
    do = lambda s: getattr(args, s) or args.all
    if do("fetch"):
        stage_fetch(args.work)
    if do("select"):
        stage_select(args.work, args.corpus,
                     args.n_en, args.n_th, args.n_ctrl)
    if do("translate"):
        stage_translate(args.work)
    if do("embed"):
        stage_embed(args.work)
    if do("prod"):
        stage_prod(args.work)
    if do("label"):
        stage_label(args.work, args.topn)
    if do("score"):
        stage_score(args.work, args.topn)


if __name__ == "__main__":
    main()
