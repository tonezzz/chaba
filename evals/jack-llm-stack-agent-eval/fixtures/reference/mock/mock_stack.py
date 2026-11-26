#!/usr/bin/env python3
"""Mock Jack LLM stack — stub Ollama + LiteLLM endpoints on 127.0.0.1.

Used by verify.sh / healthcheck.sh / rollback.sh so the full deploy ->
health -> failure-injection -> rollback loop runs without a container
runtime. State is a small JSON file so sibling scripts can find the
port and pid.

Endpoints:
  GET  /api/tags                  ollama model list
  POST /api/chat                  ollama chat (minimal)
  GET  /health/liveliness         litellm liveliness
  POST /v1/chat/completions       openai-compatible chat
  GET  /mock/status               request counters + fail flag
  POST /mock/fail                 start returning 500s (failure inject)
  POST /mock/ok                   clear failure flag
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = os.environ.get("JACK_OLLAMA_MODEL", "qwen2.5:3b")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
ENVF = os.path.join(HERE, ".env.mock")

state = {"requests": 0, "fail": False, "started": time.time()}
lock = threading.Lock()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        with lock:
            state["requests"] += 1
            fail = state["fail"]
        if fail:
            return self._send(500, {"error": "mock failure injected"})
        if self.path == "/api/tags":
            return self._send(200, {"models": [
                {"name": MODEL, "model": MODEL, "size": 1,
                 "details": {"family": "qwen2"}}]})
        if self.path == "/health/liveliness":
            return self._send(200, {"status": "ok"})
        if self.path == "/mock/status":
            return self._send(200, dict(state))
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self._read()
        with lock:
            state["requests"] += 1
            fail = state["fail"]
        if self.path == "/mock/fail":
            with lock:
                state["fail"] = True
            return self._send(200, {"fail": True})
        if self.path == "/mock/ok":
            with lock:
                state["fail"] = False
            return self._send(200, {"fail": False})
        if fail:
            return self._send(500, {"error": "mock failure injected"})
        if self.path in ("/v1/chat/completions", "/api/chat"):
            try:
                req = json.loads(body or b"{}")
            except json.JSONDecodeError:
                req = {}
            model = req.get("model", "unknown")
            content = f"mock reply via {model}"
            if self.path == "/api/chat":
                return self._send(200, {
                    "model": model, "created_at": "2026-11-24T00:00:00Z",
                    "message": {"role": "assistant", "content": content},
                    "done": True})
            return self._send(200, {
                "id": "mock-1", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {
                    "role": "assistant", "content": content},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 4,
                          "total_tokens": 5}})
        return self._send(404, {"error": "not found"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    port = srv.server_address[1]
    with open(STATE, "w") as f:
        json.dump({"pid": os.getpid(), "port": port,
                   "started": state["started"]}, f)
    with open(ENVF, "w") as f:
        f.write(f"JACK_OLLAMA_URL=http://127.0.0.1:{port}\n")
        f.write(f"JACK_LITELLM_URL=http://127.0.0.1:{port}\n")
        f.write(f"JACK_MOCK_PORT={port}\n")
    print(f"mock stack on http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
