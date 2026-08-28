"""Generate MDDB semantic search results for the vector-search app.

Searches the MDDB knowledge base for one query per vector-search idea and
caches the top results as JSON. The app loads this JSON so the documentation
card is live rather than a static placeholder.

Usage:
    .venv/bin/python mddb_search.py

Requires MDDB API on MDDB_HOST (default http://tony-dell:11023).
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
MDDB_HOST = os.environ.get("MDDB_HOST", "tony-dell:11023")
MDDB_URL = f"http://{MDDB_HOST}/v1/vector-search"

QUERIES = [
    ("Granger causality on financial time series", "kb-system"),
    ("PCA and UMAP for market regimes", "kb-system"),
    ("Similarity weighted forecast kernel neighbors", "kb-system"),
    ("Anomaly change point detection time series", "kb-system"),
    ("Vector search pattern matching in price data", "kb-system"),
]


def search(query, collection, top_k=3):
    payload = {
        "collection": collection,
        "query": query,
        "limit": top_k,
    }
    req = urllib.request.Request(
        MDDB_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"MDDB search failed for '{query}': {e}", file=sys.stderr)
        return []

    results = []
    for r in body.get("results", []):
        doc = r.get("document", {})
        meta = doc.get("meta", {})
        results.append({
            "key": doc.get("key", ""),
            "title": (meta.get("title") or [doc.get("key", "")])[0],
            "rel_path": (meta.get("rel_path") or [""])[0],
            "score": float(r.get("score", 0.0)),
            "rank": int(r.get("rank", 0)),
            "collection": collection,
        })
    return results


def main():
    out = []
    for query, collection in QUERIES:
        results = search(query, collection, top_k=3)
        out.append({
            "idea": query,
            "collection": collection,
            "mddb_host": MDDB_HOST,
            "results": results,
        })
        print(f"'{query}' → {len(results)} results")
        for r in results:
            print(f"  {r['rank']:1d}. {r['title']} ({r['score']:.3f})")

    DATA.mkdir(exist_ok=True)
    (DATA / "mddb_results.json").write_text(json.dumps(out, indent=2))
    print(f"\nSaved: {DATA / 'mddb_results.json'}")


if __name__ == "__main__":
    main()
