#!/usr/bin/env python3
"""bge-rerank-server.py — warm cross-encoder rerank endpoint (MEM-1129).

Holds bge-reranker-v2-m3 resident on GPU (or CPU) and answers:
  POST /rerank {"query": str, "docs": [{"id":..., "text":...}]}
    -> {"scores": [float, ...]}   (same order as docs)
  GET  /health -> {"ok", "model", "device", "served"}

Measured on Omen GPU (fp32, max_length 320): ~57ms/pair —
rerank top-10 ≈ 565ms, the MEM-1129 production arm. fp16 is *slower*
on this card; don't add it.

Run inside ~/.local/share/chaba-ml-gpu-venv (torch+transformers, cuda).
  RERANK_ADDR=100.75.102.88:11555 python3 bge-rerank-server.py
"""
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
ADDR = os.environ.get("RERANK_ADDR", "127.0.0.1:11555")
MAX_LEN = int(os.environ.get("RERANK_MAX_LEN", "320"))
MAX_DOCS = int(os.environ.get("RERANK_MAX_DOCS", "100"))

_tok = None
_model = None
_device = "cpu"
_served = 0
_lock = threading.Lock()


def _load():
    global _tok, _model, _device
    import torch
    from transformers import (AutoModelForSequenceClassification,
                              AutoTokenizer)
    _tok = AutoTokenizer.from_pretrained(MODEL)
    _model = AutoModelForSequenceClassification.from_pretrained(MODEL)
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _model.to(_device).eval()
    return torch


def _score(query, texts):
    import torch
    pairs = [[query, t[:1200]] for t in texts]
    out = []
    with torch.no_grad():
        for i in range(0, len(pairs), 32):
            batch = _tok(pairs[i:i + 32], padding=True, truncation=True,
                         max_length=MAX_LEN, return_tensors="pt")
            batch = {k: v.to(_device) for k, v in batch.items()}
            out += _model(**batch).logits.view(-1).tolist()
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global _served
        if self.path == "/health":
            self._json(200, {"ok": _model is not None, "model": MODEL,
                             "device": _device, "served": _served})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        global _served
        if self.path != "/rerank":
            self._json(404, {"error": "not found"})
            return
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", "0"))))
            query = (body.get("query") or "").strip()
            docs = (body.get("docs") or [])[:MAX_DOCS]
            if not query or not docs:
                self._json(400, {"error": "need query + docs"})
                return
            texts = [d.get("text") or "" for d in docs]
            with _lock:  # serialize GPU inference — batching is the win
                scores = _score(query, texts)
                _served += 1
            self._json(200, {"scores": scores})
        except Exception as e:
            self._json(500, {"error": str(e)[:200]})


if __name__ == "__main__":
    torch = _load()
    host, port = ADDR.rsplit(":", 1)
    print(f"bge-rerank-server {MODEL} on {_device} at {ADDR}")
    ThreadingHTTPServer((host, int(port)), H).serve_forever()
