#!/usr/bin/env python3
"""Phase-0 for card nest-query-cache: near-repeat analysis of real
ada_memory_search queries.

Input: tests/bench/bankq-corpus-20261008.jsonl (1366 prod rows mined from
the nest-bank-router 'memory_search timing' instrumentation, 2026-10-06
.. 2026-10-08).

Method: replay the stream chronologically. For each row, embed the
normalized query with the Weaviate embed service (all-MiniLM-L6-v2,
384d, localhost:5000 -> mn01) and take max cosine vs every EARLIER row,
both unrestricted and within the same (scope, bank_arg) partition —
the partition being the cache-key's bank+speaker scope proxy (speaker
not in the corpus; all corpus rows are Tony-owned traffic).

Output: experiments/query-cache-phase0/results.json + stdout report.

Embedding-space caveat: production memory search embeds via MDDB ->
gemini-ollama-proxy -> google/gemini-embedding-2 (OpenRouter Vertex or
direct Gemini, bit-identical). That path was quota-dead on 2026-10-08
(OR total-limit 403 + Gemini 429s), so this analysis runs in the
MiniLM space — which is also the space a Weaviate-resident cache would
actually use. Threshold fractions are reported across a band so the
decision does not hinge on one space's calibration.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "bankq-corpus-20261008.jsonl"
OUT = HERE / "results.json"
EMBED_URL = "http://127.0.0.1:5000/embed"
BATCH = 64

# time-sensitive markers — per the cache policy these are never-cache;
# report the repeat rate on the cacheable subset too.
TIME_RE = re.compile(
    r"\b(today|latest|now|yesterday|recent|recently|current|currently|"
    r"this morning|tonight|this week|last night|just now)\b", re.I)
THAI_RE = re.compile(r"[฀-๿]")
PUNCT_RE = re.compile(r"[^\w\sก-๙]", re.UNICODE)
WS_RE = re.compile(r"\s+")


def normalize(q: str) -> str:
    q = PUNCT_RE.sub(" ", q.lower())
    return WS_RE.sub(" ", q).strip()


def embed(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps({"texts": texts}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["embeddings"]


def main() -> None:
    rows = [json.loads(l) for l in open(CORPUS) if l.strip()]
    rows.sort(key=lambda r: r["ts"])
    for r in rows:
        r["nq"] = normalize(r.get("query") or "")
        r["time_sensitive"] = bool(TIME_RE.search(r["nq"]))
        r["thai"] = bool(THAI_RE.search(r["nq"]))
        r["partition"] = f"{r.get('scope')}|{r.get('bank_arg')}"

    # embed unique normalized queries once
    uniq = sorted({r["nq"] for r in rows})
    vecs: dict[str, list[float]] = {}
    t0 = time.time()
    for i in range(0, len(uniq), BATCH):
        for q, v in zip(uniq[i:i + BATCH],
                        embed(uniq[i:i + BATCH])):
            vecs[q] = v
    embed_s = time.time() - t0

    # vector matrix, row order; L2-normalize for cosine
    V = np.array([vecs[r["nq"]] for r in rows], dtype=np.float32)
    V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-12
    S = V @ V.T  # full pairwise cosine, use lower triangle vs earlier
    np.fill_diagonal(S, -1.0)

    parts = np.array([r["partition"] for r in rows])
    for i, r in enumerate(rows):
        r["sim_any"] = float(S[i, :i].max()) if i else -1.0
        same = parts[:i] == r["partition"]
        r["sim_part"] = float(S[i, :i][same].max()) if same.any() else -1.0

    thresholds = [0.80, 0.85, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98]

    def frac(rows_sub, key, t):
        el = [r[key] for r in rows_sub if r[key] >= 0]
        if not rows_sub:
            return 0.0
        return sum(1 for r in rows_sub if r[key] >= t) / len(rows_sub)

    n = len(rows)
    seen: set[str] = set()
    n_exact_rep = 0
    seen_part: set[tuple[str, str]] = set()
    n_exact_rep_part = 0
    for r in rows:
        if r["nq"] in seen:
            n_exact_rep += 1
        seen.add(r["nq"])
        k = (r["partition"], r["nq"])
        if k in seen_part:
            n_exact_rep_part += 1
        seen_part.add(k)

    cacheable = [r for r in rows if not r["time_sensitive"]]
    sessions_scope = [r for r in rows if r.get("scope") == "sessions"]
    curated = [r for r in cacheable if r.get("scope") != "sessions"]

    def dist(rows_sub, key):
        el = sorted(r[key] for r in rows_sub if r[key] >= 0)
        if not el:
            return {}
        return {
            "n": len(rows_sub),
            "p50": el[len(el) // 2],
            "p90": el[int(len(el) * 0.9)],
            "p99": el[int(len(el) * 0.99)],
            "frac_ge": {str(t): round(frac(rows_sub, key, t), 4)
                        for t in thresholds},
        }

    # near-repeats at 0.92: argmax partner in same session vs cross-session
    within = cross = 0
    for i, r in enumerate(rows):
        if r["sim_any"] >= 0.92:
            j = int(S[i, :i].argmax())
            if rows[j]["session"] == r["session"]:
                within += 1
            else:
                cross += 1

    # borderline pairs for the doc (0.88-1.0, argmax vs earlier row)
    pairs = []
    for i, r in enumerate(rows):
        if i and 0.88 <= r["sim_any"] < 1.0:
            j = int(S[i, :i].argmax())
            pairs.append({"sim": round(r["sim_any"], 4), "q": r["nq"],
                          "earlier": rows[j]["nq"],
                          "partition": r["partition"]})
    pairs.sort(key=lambda p: -p["sim"])

    lat = [r["latency_s"] for r in rows if r.get("latency_s")]
    p50_lat = statistics.median(lat)

    results = {
        "meta": {
            "corpus": str(CORPUS), "rows": n,
            "unique_normalized_queries": len(uniq),
            "sessions": len({r["session"] for r in rows}),
            "ts_range": [rows[0]["ts"], rows[-1]["ts"]],
            "embed_model": "all-MiniLM-L6-v2 (weaviate-embed, mn01, 384d)",
            "embed_seconds": round(embed_s, 1),
            "prod_embed_space": "google/gemini-embedding-2 (unavailable: "
                                "OR quota 403 + Gemini 429 on 2026-10-08)",
            "real_path_latency_s": {"p50": round(p50_lat, 3),
                                    "mean": round(statistics.mean(lat), 3)},
        },
        "exact_normalized_repeats": {
            "any_partition": n_exact_rep,
            "same_partition": n_exact_rep_part,
            "frac_any": round(n_exact_rep / n, 4),
            "frac_same_partition": round(n_exact_rep_part / n, 4),
        },
        "near_repeat_distribution": {
            "all_rows_same_partition": dist(rows, "sim_part"),
            "all_rows_any_partition": dist(rows, "sim_any"),
            "cacheable_subset_same_partition": dist(curated, "sim_part"),
            "time_sensitive_same_partition": dist(
                [r for r in rows if r["time_sensitive"]], "sim_part"),
            "sessions_scope_same_partition": dist(sessions_scope, "sim_part"),
            "thai_queries_same_partition": dist(
                [r for r in rows if r["thai"]], "sim_part"),
        },
        "repeats_at_0.92_within_vs_cross_session": {
            "within_session": within, "cross_session": cross,
        },
        "top_borderline_pairs_0.88_1.0": pairs[:40],
    }
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    m = results["meta"]
    print(f"rows={m['rows']} unique_norm={m['unique_normalized_queries']} "
          f"sessions={m['sessions']} embed={m['embed_seconds']}s")
    print(f"exact normalized repeats: {n_exact_rep} ({n_exact_rep/n:.1%}) any, "
          f"{n_exact_rep_part} ({n_exact_rep_part/n:.1%}) same-partition")
    for name, d in results["near_repeat_distribution"].items():
        if not d:
            continue
        print(f"\n{name}: n={d['n']} p50={d['p50']:.3f} p90={d['p90']:.3f}")
        print("  frac>=", {k: v for k, v in d["frac_ge"].items()})
    print(f"\n@0.92 any-partition: within-session={within} cross={cross}")
    print("\ntop borderline pairs:")
    for p in pairs[:12]:
        print(f"  {p['sim']:.3f} {p['q']!r} ~~ {p['earlier']!r}")


if __name__ == "__main__":
    sys.exit(main())
