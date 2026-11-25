#!/usr/bin/env python3
"""
GPU Dispatch Web UI — single-pane read-mostly view over the Ansible
dispatch queue (queue/queue_manager.py) and fleet sidecar metrics.

Runs on the control node (idc02) next to Redis and dispatch-scheduler.
Binds the tailnet IP only — no credentials in code; the tailnet is the
trust boundary (same posture as gpu-queue :3001, secrets-console :8005).

Endpoints:
  GET  /                     -> static UI
  GET  /static/*             -> UI assets
  GET  /api/state            -> queue stats + jobs + fleet GPUs + scheduler + audit tail
  GET  /api/jobs/<id>        -> one job (hash + dispatch record)
  GET  /api/audit            -> recent audit entries
  POST /api/jobs             -> enqueue   {job:{...}, confirm:true, actor}
  POST /api/jobs/<id>/cancel -> cancel    {confirm:true, actor}
  POST /api/jobs/<id>/requeue-> requeue   {confirm:true, actor}

Mutating endpoints require {"confirm": true} and are appended to
audit.jsonl (plus the Redis list queue:audit). The service never writes
job state to Redis directly — it only calls QueueManager methods, so
the CLI remains the authoritative fallback.

Env:
  GPU_WEBUI_HOST    bind address      (default 100.123.163.11 — tailnet IP)
  GPU_WEBUI_PORT    bind port         (default 8795)
  ANSIBLE_DIR       repo root         (default /home/tony/ansible)
  REDIS_HOST        redis host        (default 127.0.0.1)
"""

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

ANSIBLE_DIR = Path(os.getenv("ANSIBLE_DIR", "/home/tony/ansible"))
sys.path.insert(0, str(ANSIBLE_DIR / "queue"))
from queue_manager import JobSpec, Priority, QueueManager  # noqa: E402

BIND_HOST = os.getenv("GPU_WEBUI_HOST", "100.123.163.11")
BIND_PORT = int(os.getenv("GPU_WEBUI_PORT", "8795"))
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
STATIC_DIR = Path(__file__).resolve().parent / "static"
AUDIT_FILE = Path(__file__).resolve().parent / "audit.jsonl"
AUDIT_REDIS_KEY = "queue:audit"
AUDIT_REDIS_MAX = 1000
MAX_BODY = 1024 * 1024
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{0,63}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
SIDECAR_STALE_SEC = 45  # collectors push every 15s; TTL is 3x interval

qm = QueueManager(redis_host=REDIS_HOST)
_audit_lock = threading.Lock()


# ─── Helpers ─────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()


def _parse_redis_value(v: Any) -> Any:
    """queue_manager stores lists/dicts as JSON strings, scalars as str."""
    if not isinstance(v, str):
        return v
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return v


def _job_from_hash(job_id: str, data: Dict[str, str]) -> Dict[str, Any]:
    job = {k: _parse_redis_value(v) for k, v in data.items()}
    job["_key"] = f"queue:job:{job_id}"
    return job


def _all_jobs(limit: int = 300) -> List[Dict[str, Any]]:
    jobs = []
    for key in qm.r.scan_iter("queue:job:*", count=200):
        job_id = key.rsplit(":", 1)[-1]
        data = qm.r.hgetall(key)
        if data:
            jobs.append(_job_from_hash(job_id, data))
    jobs.sort(key=lambda j: str(j.get("created_at", "")), reverse=True)
    return jobs[:limit]


def _dispatch_records() -> Dict[str, Dict[str, Any]]:
    out = {}
    for key in qm.r.scan_iter("dispatch:*", count=200):
        job_id = key.rsplit(":", 1)[-1]
        out[job_id] = {k: _parse_redis_value(v) for k, v in qm.r.hgetall(key).items()}
    return out


def _sidecar_hosts() -> List[Dict[str, Any]]:
    hosts = []
    now_ts = datetime.now().timestamp()
    for key in qm.r.scan_iter("sidecar:*", count=100):
        data = qm.r.hgetall(key)
        if not data:
            continue
        host = _parse_redis_value(data)
        host["_key"] = key
        try:
            age = now_ts - float(host.get("timestamp", 0))
        except (TypeError, ValueError):
            age = None
        host["metric_age_sec"] = round(age, 1) if age is not None else None
        host["stale"] = age is None or age > SIDECAR_STALE_SEC
        hosts.append(host)
    hosts.sort(key=lambda h: h.get("hostname", h.get("_key", "")))
    return hosts


def _scheduler_health() -> Dict[str, Any]:
    health = {"dispatch-scheduler": {}, "sidecar-collector": {}}
    for unit in health:
        try:
            active = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            show = subprocess.run(
                ["systemctl", "--user", "show", unit,
                 "-p", "MainPID,ActiveEnterTimestamp,NRestarts,ExecMainStatus"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            props = dict(
                line.split("=", 1) for line in show.splitlines() if "=" in line
            )
            health[unit] = {
                "active": active,
                "pid": props.get("MainPID", ""),
                "since": props.get("ActiveEnterTimestamp", ""),
                "restarts": props.get("NRestarts", ""),
            }
        except Exception as e:  # noqa: BLE001 — health endpoint must not 500
            health[unit] = {"active": "unknown", "error": str(e)}
    return health


def _audit_tail(n: int = 25) -> List[Dict[str, Any]]:
    if not AUDIT_FILE.exists():
        return []
    try:
        size = AUDIT_FILE.stat().st_size
        with open(AUDIT_FILE, "rb") as f:
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8", "replace").splitlines()
        entries = []
        for line in tail[-n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
    except OSError:
        return []


def build_state() -> Dict[str, Any]:
    stats = qm.get_queue_stats()
    dispatches = _dispatch_records()
    jobs = _all_jobs()
    for job in jobs:
        job["dispatch"] = dispatches.get(job.get("job_id", ""))
    dlq_ids = [str(x) for x in qm.r.lrange("queue:dlq", 0, -1)]
    return {
        "now": _now(),
        "queue": {
            "stats": stats,
            "fairshare": qm.get_fairshare_status(),
            "dlq": dlq_ids,
        },
        "jobs": jobs,
        "gpu": {"hosts": _sidecar_hosts()},
        "scheduler": _scheduler_health(),
        "audit": _audit_tail(15),
    }


# ─── Audit ───────────────────────────────────────────────────────────────

def audit(action: str, actor: str, job_id: str,
          params: Dict[str, Any], result: Dict[str, Any]) -> None:
    entry = {
        "ts": _now(), "actor": actor, "action": action,
        "job_id": job_id, "params": params, "result": result,
    }
    line = json.dumps(entry, default=str)
    with _audit_lock:
        try:
            with open(AUDIT_FILE, "a") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass
        try:
            qm.r.lpush(AUDIT_REDIS_KEY, line)
            qm.r.ltrim(AUDIT_REDIS_KEY, 0, AUDIT_REDIS_MAX - 1)
        except Exception:  # noqa: BLE001 — audit mirror is best-effort
            pass


# ─── Validation ──────────────────────────────────────────────────────────

JOB_FIELDS = {
    "job_id": str, "job_image": str, "job_cmd": str,
    "job_gpus": int, "job_min_vram_gb": int,
    "job_max_load_pct": int, "job_max_mem_pct": int,
    "job_require_tags": list, "job_exclude_tags": list,
    "target_group": str, "container_runtime": str,
    "job_timeout_sec": int, "reserve_gpu_window_sec": int,
    "reservation_id": str, "priority": int,
    "user": str, "project": str, "max_retries": int,
    "metadata": dict,
}
INT_BOUNDS = {
    "job_gpus": (0, 8), "job_min_vram_gb": (0, 64),
    "job_max_load_pct": (1, 10000), "job_max_mem_pct": (1, 100),
    "job_timeout_sec": (10, 604800), "reserve_gpu_window_sec": (0, 86400),
    "max_retries": (0, 10), "priority": (0, 9),
}
STR_BOUNDS = {
    "job_image": 500, "job_cmd": 4000, "target_group": 64,
    "container_runtime": 16, "reservation_id": 64,
    "user": 64, "project": 64,
}


def validate_job(raw: Any) -> tuple[Optional[JobSpec], Optional[str]]:
    if not isinstance(raw, dict):
        return None, "job must be an object"
    kwargs: Dict[str, Any] = {}
    for key, want in JOB_FIELDS.items():
        if key not in raw or raw[key] is None:
            continue
        val = raw[key]
        if want is int:
            try:
                val = int(val)
            except (TypeError, ValueError):
                return None, f"{key} must be an integer"
            lo, hi = INT_BOUNDS[key]
            if not lo <= val <= hi:
                return None, f"{key} must be {lo}..{hi}"
        elif want is list:
            if not isinstance(val, list) or len(val) > 16:
                return None, f"{key} must be a list of <=16 tags"
            if not all(isinstance(t, str) and TAG_RE.match(t) for t in val):
                return None, f"{key} entries must match {TAG_RE.pattern}"
        elif want is dict:
            if not isinstance(val, dict):
                return None, f"{key} must be an object"
            try:
                if len(json.dumps(val)) > 4096:
                    return None, f"{key} too large"
            except (TypeError, ValueError):
                return None, f"{key} must be JSON-serializable"
        else:
            if not isinstance(val, str):
                return None, f"{key} must be a string"
            val = val.strip()
            limit = STR_BOUNDS.get(key, 128)
            if len(val) > limit:
                return None, f"{key} too long (max {limit})"
        kwargs[key] = val

    if not kwargs.get("job_image"):
        return None, "job_image is required"
    if not kwargs.get("job_cmd"):
        return None, "job_cmd is required"
    if kwargs.get("job_id") and not JOB_ID_RE.match(kwargs["job_id"]):
        return None, "job_id must match [A-Za-z0-9._-] (max 64 chars)"
    if kwargs.get("container_runtime", "podman") not in ("podman", "docker"):
        return None, "container_runtime must be podman or docker"
    return JobSpec(**kwargs), None


def clean_actor(raw: Any) -> str:
    if isinstance(raw, str) and ACTOR_RE.match(raw.strip()):
        return raw.strip()
    return "webui"


# ─── HTTP handler ────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "gpu-dispatch-webui/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep journald clean; access via audit
        pass

    # -- plumbing ---------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200):
        self._send(code, json.dumps(obj, default=str).encode())

    def _error(self, code: int, msg: str, **extra):
        self._json({"ok": False, "error": msg, **extra}, code)

    def _read_json(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    # -- GET --------------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            if "/" in name or ".." in name:
                return self._error(404, "not found")
            ctype = {
                ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".map": "application/json",
            }.get(Path(name).suffix, "application/octet-stream")
            return self._static(name, ctype)
        if path == "/api/state":
            try:
                return self._json({"ok": True, "state": build_state()})
            except Exception as e:  # noqa: BLE001
                return self._error(500, f"state build failed: {e}")
        if path == "/api/audit":
            return self._json({"ok": True, "audit": _audit_tail(100)})
        if path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):]
            if not JOB_ID_RE.match(job_id):
                return self._error(404, "not found")
            data = qm.r.hgetall(f"queue:job:{job_id}")
            if not data:
                return self._error(404, "job not found")
            job = _job_from_hash(job_id, data)
            disp = qm.r.hgetall(f"dispatch:{job_id}")
            job["dispatch"] = {k: _parse_redis_value(v) for k, v in disp.items()} if disp else None
            holds = [h for h in qm.list_reservations() if h.get("job_id") == job_id]
            job["holds"] = holds
            return self._json({"ok": True, "job": job})
        return self._error(404, "not found")

    def _static(self, name: str, ctype: str):
        f = STATIC_DIR / name
        if not f.is_file():
            return self._error(404, "not found")
        self._send(200, f.read_bytes(), ctype)

    # -- POST -------------------------------------------------------------

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()
        if body is None:
            return self._error(400, "invalid JSON body")

        if path == "/api/jobs":
            return self._op_enqueue(body)
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9._-]{1,64})/(cancel|requeue)", path)
        if m:
            job_id, op = m.group(1), m.group(2)
            return self._op_job_action(op, job_id, body)
        return self._error(404, "not found")

    def _require_confirm(self, body: Dict[str, Any]):
        if body.get("confirm") is not True:
            self._error(400, "confirmation required",
                        hint='resend with {"confirm": true} after operator approval')
            return False
        return True

    def _op_enqueue(self, body: Dict[str, Any]):
        if not self._require_confirm(body):
            return
        actor = clean_actor(body.get("actor"))
        job, err = validate_job(body.get("job"))
        if err:
            return self._error(400, err)
        try:
            job_id = qm.enqueue(job)
        except Exception as e:  # noqa: BLE001
            return self._error(500, f"enqueue failed: {e}")
        result = {"job_id": job_id, "priority": job.priority}
        audit("enqueue", actor, job_id, {"job": body.get("job")}, result)
        return self._json({"ok": True, **result})

    def _op_job_action(self, op: str, job_id: str, body: Dict[str, Any]):
        if not self._require_confirm(body):
            return
        actor = clean_actor(body.get("actor"))
        if op == "cancel":
            res = qm.cancel_job(job_id, actor=actor)
            audit("cancel", actor, job_id, {}, res)
            if res.get("ok"):
                return self._json({"ok": True, **res})
            code = {"not_found": 404}.get(res.get("reason"), 409)
            return self._json({"ok": False, **res}, code)
        # requeue — only terminal-ish states; never duplicate a live queue entry
        data = qm.r.hgetall(f"queue:job:{job_id}")
        if not data:
            audit("requeue", actor, job_id, {}, {"ok": False, "reason": "not_found"})
            return self._error(404, "job not found")
        status = data.get("status", "unknown")
        if status in ("queued", "waiting", "processing"):
            res = {"ok": False, "reason": "already_active", "status": status,
                   "detail": "job is still in the queue; cancel it first if needed"}
            audit("requeue", actor, job_id, {}, res)
            return self._json(res, 409)
        ok = qm.requeue(job_id, increment_retry=False, reset_status=True)
        res = {"ok": bool(ok), "job_id": job_id, "previous_status": status}
        audit("requeue", actor, job_id, {}, res)
        if ok:
            return self._json(res)
        return self._json({"ok": False, "error": "requeue failed"}, 409)

    def do_OPTIONS(self):
        self._error(405, "method not allowed")


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    if not (ANSIBLE_DIR / "queue" / "queue_manager.py").is_file():
        print(f"queue_manager.py not found under {ANSIBLE_DIR}/queue", file=sys.stderr)
        sys.exit(1)
    httpd = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    httpd.daemon_threads = True
    print(f"gpu-dispatch-webui listening on http://{BIND_HOST}:{BIND_PORT} "
          f"(ansible_dir={ANSIBLE_DIR}, redis={REDIS_HOST})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
