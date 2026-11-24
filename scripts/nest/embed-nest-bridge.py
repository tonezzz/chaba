#!/usr/bin/env python3
"""embed-nest-bridge — pull->push bridge putting browser/nest workers
behind the embed pool's one ollama-shaped endpoint (MEM-0805 lane B;
rebuilt 2026-11-24 — the original worktree was lost before commit).

Two doors on one port:

  Pool side (ollama-shaped, called by embed-pool-shim upstreams):
    POST /api/embed  {"model": "bge-m3", "input": "text"|[...]} —
                     enqueue a job and BLOCK for a worker result,
                     answering {"embeddings": [[...]]} like ollama.

  Worker side (long-poll, called by browser/PWA workers e.g. the
  iPhone WebGPU page at /apps/webgpu-bench):
    GET  /v1/job?model=bge-m3&cap=bge-m3,minilm&w=<worker-id>
                     long-poll claim — 200 {job_id, model, texts}
                     or 204 when nothing claimable within wait_s.
    POST /v1/result  {"job_id", "embeddings": [[...]]} or {"error": ...}
                     resolves the blocked /api/embed caller.

  GET /health — queue depth, worker registry, counters.

Semantics (original lane-B spec, card embed-pool-fleet-nest-workers):
  - instant 503 on /api/embed when no worker seen in WORKER_STALE_S
    (45s) — the pool fails fast to its next racer instead of queueing
    into a void.
  - job TTL JOB_TTL_S (~7s) stays under the pool shim's 8s upstream
    timeout; a claimed job's LEASE_S expiry requeues it once, then
    fails the waiter.
  - workers are opportunistic: claim->embed->result, lease requeue
    covers a phone that backgrounds mid-job.

Config (env):
  NEST_BRIDGE_ADDR       listen addr     (default 127.0.0.1:11440 —
                        prod binds the tailnet IP, e.g.
                        100.102.134.91:11440, NEVER 0.0.0.0 on a VPS)
  NEST_BRIDGE_WAIT_S     block budget for /api/embed (default 6.5 —
                        under the pool's 8s upstream timeout)
  NEST_BRIDGE_JOB_TTL_S  unclaimed job ttl (default 7)
  NEST_BRIDGE_LEASE_S    claim lease before requeue (default 20)
  NEST_BRIDGE_WORKER_STALE_S  no-worker fast-503 window (default 45)
  NEST_BRIDGE_MAX_TEXTS  reject oversized batches (default 64)
  NEST_BRIDGE_MAX_CHARS  per-text cap (default 8000)
"""
import json
import os
import threading
import time
import urllib.parse
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADDR = os.environ.get("NEST_BRIDGE_ADDR", "127.0.0.1:11440")
WAIT_S = float(os.environ.get("NEST_BRIDGE_WAIT_S", "6.5"))
JOB_TTL_S = float(os.environ.get("NEST_BRIDGE_JOB_TTL_S", "7"))
LEASE_S = float(os.environ.get("NEST_BRIDGE_LEASE_S", "20"))
WORKER_STALE_S = float(os.environ.get("NEST_BRIDGE_WORKER_STALE_S", "45"))
MAX_TEXTS = int(os.environ.get("NEST_BRIDGE_MAX_TEXTS", "64"))
MAX_CHARS = int(os.environ.get("NEST_BRIDGE_MAX_CHARS", "8000"))
POLL_S = float(os.environ.get("NEST_BRIDGE_POLL_S", "0.05"))

T0 = time.time()


class Job:
    __slots__ = ("id", "model", "texts", "created", "event", "result",
                 "error", "claimed_by", "lease_until", "requeues")

    def __init__(self, model, texts):
        self.id = "job-" + uuid.uuid4().hex[:12]
        self.model = model
        self.texts = texts
        self.created = time.time()
        self.event = threading.Event()
        self.result = None
        self.error = None
        self.claimed_by = None
        self.lease_until = 0.0
        self.requeues = 0

    def payload(self):
        return {"job_id": self.id, "model": self.model,
                "texts": self.texts}


class JobStore:
    """Pending-job queue + worker registry. All mutations under _lock;
    waiters sleep on per-job Events so claim/resolve never block the
    accept loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = deque()          # unclaimed Jobs, FIFO
        self._claimed = {}               # job_id -> Job (awaiting result)
        self._done = 0
        self._failed = 0
        self._workers = {}               # worker_id -> {last_seen, model}
        self._last_worker_seen = 0.0

    # ---------------------------------------------------------- pool side
    def worker_alive(self):
        return (time.time() - self._last_worker_seen) <= WORKER_STALE_S

    def submit(self, model, texts):
        """Enqueue and block up to WAIT_S for the worker result.
        Returns (status, body_dict)."""
        if not self.worker_alive():
            return 503, {"error": "no nest worker seen in "
                                 f"{int(WORKER_STALE_S)}s"}
        job = Job(model, texts)
        with self._lock:
            self._pending.append(job)
        job.event.wait(WAIT_S)
        if job.result is not None:
            return 200, {"embeddings": job.result}
        # Timed out — cancel so a late claim doesn't burn worker cycles;
        # a result landing concurrently still wins.
        with self._lock:
            if job.result is not None:
                return 200, {"embeddings": job.result}
            if job in self._pending:
                self._pending.remove(job)
            self._claimed.pop(job.id, None)
        return 503, {"error": job.error or "nest worker timeout"}

    # -------------------------------------------------------- worker side
    def claim(self, worker_id, caps, wait_s):
        """Long-poll for a claimable job. caps = set of models the
        worker can serve (empty set = any). Returns job payload or
        None on timeout."""
        deadline = time.time() + wait_s
        while True:
            self._touch_worker(worker_id)
            with self._lock:
                job = self._match_locked(caps)
                if job is not None:
                    job.claimed_by = worker_id
                    job.lease_until = time.time() + LEASE_S
                    self._pending.remove(job)
                    self._claimed[job.id] = job
                    return job.payload()
            if time.time() >= deadline:
                return None
            time.sleep(POLL_S)

    def _match_locked(self, caps):
        for job in self._pending:
            if time.time() - job.created > JOB_TTL_S:
                continue
            if not caps or job.model in caps:
                return job
        return None

    def resolve(self, worker_id, job_id, embeddings=None, error=None):
        """Worker posts a result. Returns True if it resolved a live
        waiter, False if the job is unknown/expired."""
        self._touch_worker(worker_id)
        with self._lock:
            job = self._claimed.pop(job_id, None)
        if job is None:
            return False
        if error:
            job.error = str(error)[:500]
            self._bump("_failed")
        else:
            job.result = embeddings
            self._bump("_done")
        job.event.set()
        return True

    # ------------------------------------------------------------ hygiene
    def _touch_worker(self, worker_id):
        with self._lock:
            self._last_worker_seen = time.time()
            w = self._workers.setdefault(worker_id, {})
            w["last_seen"] = time.time()

    def worker_model(self, worker_id, model):
        with self._lock:
            self._workers.setdefault(worker_id, {})["model"] = model

    def _bump(self, attr):
        with self._lock:
            setattr(self, attr, getattr(self, attr) + 1)

    def reap(self):
        """Expire claimed leases (requeue once) and stale pending jobs.
        Called from a daemon thread."""
        now = time.time()
        with self._lock:
            for job in list(self._claimed.values()):
                if job.lease_until and now > job.lease_until:
                    del self._claimed[job.id]
                    if job.requeues < 1:
                        job.requeues += 1
                        job.claimed_by = None
                        job.lease_until = 0.0
                        self._pending.append(job)
                    else:
                        job.error = "claim lease expired twice"
                        self._failed += 1
                        job.event.set()
            for job in list(self._pending):
                if now - job.created > JOB_TTL_S:
                    self._pending.remove(job)
                    job.error = "job ttl expired"
                    self._failed += 1
                    job.event.set()

    def stats(self):
        with self._lock:
            return {
                "uptime_s": int(time.time() - T0),
                "pending": len(self._pending),
                "claimed": len(self._claimed),
                "done": self._done,
                "failed": self._failed,
                "workers": {w: dict(v) for w, v in self._workers.items()},
                "worker_alive": self.worker_alive(),
                "config": {"wait_s": WAIT_S, "job_ttl_s": JOB_TTL_S,
                           "lease_s": LEASE_S,
                           "worker_stale_s": WORKER_STALE_S},
            }


STORE = JobStore()


def _reaper():
    while True:
        time.sleep(1.0)
        STORE.reap()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, obj):
        data = json.dumps(obj).encode() if not isinstance(obj, bytes) \
            else obj
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        # tailnet-only service, but the /apps proxy is same-origin —
        # CORS * keeps direct tailnet debugging painless.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    # ------------------------------------------------------------- GET
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if path == "/health":
            return self._send(200, {"ok": True, **STORE.stats()})
        if path == "/v1/job":
            w = (q.get("w") or ["anon"])[0][:64]
            model = (q.get("model") or [""])[0]
            cap = (q.get("cap") or q.get("model") or [""])[0]
            caps = {c.strip() for c in cap.split(",") if c.strip()}
            if model:
                STORE.worker_model(w, model)
            try:
                wait_s = min(float((q.get("wait") or [str(WAIT_S)])[0]), 60)
            except ValueError:
                wait_s = WAIT_S
            job = STORE.claim(w, caps, wait_s)
            if job is None:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._send(200, job)
        return self._send(404, {"error": "not found"})

    # ------------------------------------------------------------ POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._body()
        if path == "/api/embed":
            model = str(body.get("model") or "bge-m3")[:64]
            inp = body.get("input")
            texts = inp if isinstance(inp, list) else [inp]
            texts = [str(t)[:MAX_CHARS] for t in texts if t is not None]
            if not texts:
                return self._send(400, {"error": "empty input"})
            if len(texts) > MAX_TEXTS:
                return self._send(413, {"error": f"batch > {MAX_TEXTS}"})
            status, obj = STORE.submit(model, texts)
            if status == 200:
                obj["model"] = model
            return self._send(status, obj)
        if path == "/v1/result":
            job_id = str(body.get("job_id") or "")[:80]
            w = str(body.get("worker") or "anon")[:64]
            ok = STORE.resolve(w, job_id,
                               embeddings=body.get("embeddings"),
                               error=body.get("error"))
            return self._send(200 if ok else 404,
                              {"ok": ok} if ok else
                              {"error": "unknown or expired job"})
        return self._send(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    host, port = ADDR.rsplit(":", 1)
    threading.Thread(target=_reaper, daemon=True).start()
    srv = ThreadingHTTPServer((host, int(port)), H)
    print(f"embed-nest-bridge on {ADDR} — wait {WAIT_S}s, "
          f"job ttl {JOB_TTL_S}s, lease {LEASE_S}s, "
          f"worker-stale {WORKER_STALE_S}s")
    srv.serve_forever()


if __name__ == "__main__":
    main()
