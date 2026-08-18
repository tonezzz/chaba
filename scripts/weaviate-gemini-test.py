#!/usr/bin/env python3
"""Insert and query a Weaviate test collection for Gemini side-by-side comparison."""
import argparse
import json
import sys
import uuid
import urllib.request

WEAVIATE_URL = "http://localhost:8084"
CLASS_NAME = "GeminiTest"


def _req(method, path, body=None):
    url = f"{WEAVIATE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode(), "status": e.code}


def ensure_class():
    _req("DELETE", f"/v1/schema/{CLASS_NAME}")
    body = {
        "class": CLASS_NAME,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "properties": [
            {"name": "content", "dataType": ["text"], "tokenization": "word"},
            {"name": "source", "dataType": ["text"], "tokenization": "field"},
        ],
    }
    return _req("POST", "/v1/schema", body)


def insert_batch(items):
    """items: list of dicts with 'content', 'source', and 'vector' (list of floats).
    Optional 'id' as a UUID string."""
    objects = []
    for it in items:
        obj = {
            "class": CLASS_NAME,
            "id": it.get("id") or str(uuid.uuid4()),
            "vector": it["vector"],
            "properties": {"content": it["content"], "source": it["source"]},
        }
        objects.append(obj)
    return _req("POST", "/v1/batch/objects", {"objects": objects})


def near_vector(vector, limit=5):
    body = {
        "query": "{ Get { GeminiTest (nearVector: {vector: %s}, limit: %d) { content source _additional { distance id } } } }" % (json.dumps(vector), limit)
    }
    return _req("POST", "/v1/graphql", body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["ensure-class", "insert", "query"])
    parser.add_argument("--file", help="JSON file with documents and vectors for insert")
    parser.add_argument("--vector", help="JSON file with a single query vector for query")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    if args.action == "ensure-class":
        print(json.dumps(ensure_class(), indent=2))
    elif args.action == "insert":
        if not args.file:
            print("--file required", file=sys.stderr)
            sys.exit(1)
        items = json.load(open(args.file))
        print(json.dumps(insert_batch(items), indent=2))
    elif args.action == "query":
        if not args.vector:
            print("--vector required", file=sys.stderr)
            sys.exit(1)
        vector = json.load(open(args.vector))
        print(json.dumps(near_vector(vector, args.limit), indent=2))


if __name__ == "__main__":
    main()
