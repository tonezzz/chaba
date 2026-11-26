#!/usr/bin/env python3
"""
Queue Manager for Ansible-Centralized Dispatch

Redis-backed priority queue with:
- Priority levels (0=highest, 9=lowest)
- Job metadata (requirements, retries, timeouts)
- Fair-share per user/project
- TTL/expiration
- Dead letter queue
- Queue inspection CLI

Data Model:
- queue:jobs:{priority} -> Redis LIST (LPUSH/RPOP for FIFO within priority)
- queue:job:{job_id} -> Redis HASH (full job spec)
- queue:dispatch:{job_id} -> Redis HASH (dispatch record from playbook)
- queue:fairshare:{user} -> Redis SORTED SET (score = jobs_dispatched_recently)
- queue:dlq -> Redis LIST (failed jobs after max retries)
"""

import json
import os
import redis
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from enum import IntEnum


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 5
    LOW = 8
    BACKGROUND = 9


@dataclass
class JobSpec:
    job_id: str
    job_image: str
    job_cmd: str
    job_gpus: int = 1
    job_min_vram_gb: int = 8
    job_max_load_pct: int = 70
    job_max_mem_pct: int = 80
    job_require_tags: List[str] = field(default_factory=list)
    job_exclude_tags: List[str] = field(default_factory=list)
    target_group: str = "all"
    container_runtime: str = "podman"
    job_timeout_sec: int = 86400
    reserve_gpu_window_sec: int = 0
    reservation_id: str = ""
    priority: int = Priority.NORMAL
    user: str = "default"
    project: str = "default"
    max_retries: int = 2
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobSpec":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class QueueManager:
    def __init__(
        self,
        redis_host: str = "100.123.163.11",
        redis_port: int = 6379,
        redis_db: int = 0,
        fairshare_window_sec: int = 3600,  # 1 hour window
        max_jobs_per_user_per_window: int = 10,
    ):
        self.r = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
        self.fairshare_window = fairshare_window_sec
        self.max_jobs_per_user = max_jobs_per_user_per_window

    # ─── Core Queue Operations ────────────────────────────────────────────

    def enqueue(self, job: JobSpec) -> str:
        """Add job to priority queue. Returns job_id."""
        # Ensure job_id
        if not job.job_id:
            job.job_id = f"job-{uuid.uuid4().hex[:8]}"

        # Store job spec
        job_key = f"queue:job:{job.job_id}"
        self.r.hset(job_key, mapping={k: json.dumps(v) if isinstance(v, (list, dict)) else str(v) for k, v in job.to_dict().items()})
        self.r.expire(job_key, 86400 * 7)  # 7 day TTL

        # Add to priority queue (LPUSH = higher priority items at head)
        queue_key = f"queue:jobs:{job.priority}"
        self.r.lpush(queue_key, job.job_id)

        # Track in fair-share
        self._fairshare_record(job.user, job.project)

        # Publish event for real-time consumers
        self.r.publish("queue:events", json.dumps({
            "event": "enqueued",
            "job_id": job.job_id,
            "priority": job.priority,
            "user": job.user,
            "timestamp": datetime.now().isoformat()
        }))

        return job.job_id

    def dequeue(self, worker_id: str = "ansible-dispatcher") -> Optional[JobSpec]:
        """Get next eligible job considering fair-share. Returns JobSpec or None."""
        now = time.time()

        # Scan priorities from highest (0) to lowest (9)
        for priority in range(10):
            queue_key = f"queue:jobs:{priority}"
            # Peek at candidates (up to 50)
            candidates = self.r.lrange(queue_key, 0, 49)
            for job_id in candidates:
                job = self.get_job(job_id)
                if not job:
                    # Orphaned queue entry, remove
                    self.r.lrem(queue_key, 1, job_id)
                    continue

                # Check fair-share
                if not self._fairshare_check(job.user, job.project):
                    continue  # Skip this user's jobs for now

                # Try to claim atomically (move to processing)
                claimed = self._claim_job(job_id, worker_id, priority)
                if claimed:
                    return job

        return None

    def _claim_job(self, job_id: str, worker_id: str, priority: int) -> bool:
        """Atomically claim job: remove from queue, mark processing."""
        queue_key = f"queue:jobs:{priority}"
        job_key = f"queue:job:{job_id}"

        # Lua script for atomic claim
        lua = """
        local queue_key = KEYS[1]
        local job_key = KEYS[2]
        local job_id = ARGV[1]
        local worker_id = ARGV[2]
        local now = ARGV[3]

        -- Verify job is at head of queue (FIFO within priority)
        local head = redis.call('LINDEX', queue_key, -1)
        if head ~= job_id then
            return 0  -- Not our turn
        end

        -- Remove from queue
        redis.call('RPOP', queue_key)

        -- Mark as processing
        redis.call('HSET', job_key, 'status', 'processing', 'worker', worker_id, 'claimed_at', now)

        return 1
        """
        script = self.r.register_script(lua)
        result = script(keys=[queue_key, job_key], args=[job_id, worker_id, str(time.time())])
        return bool(result)

    def requeue(self, job_id: str, increment_retry: bool = True, reset_status: bool = True) -> bool:
        """Return job to queue (e.g., after dispatch failure).

        Args:
            increment_retry: Count this as a failed attempt (default True).
                             Set False for resource-unavailable requeues.
            reset_status: Set status back to 'queued' (default True).
        """
        job = self.get_job(job_id)
        if not job:
            return False

        if increment_retry:
            job.metadata["retry_count"] = job.metadata.get("retry_count", 0) + 1
            if job.metadata["retry_count"] > job.max_retries:
                return self.move_to_dlq(job_id, "max_retries_exceeded")
            # Persist the incremented counter — without this every dequeue
            # re-reads retry_count=0 and failed jobs retry forever.
            self.r.hset(f"queue:job:{job_id}", "metadata", json.dumps(job.metadata))

        # Re-add to same priority queue
        queue_key = f"queue:jobs:{job.priority}"
        self.r.lpush(queue_key, job_id)
        if reset_status:
            self.r.hset(f"queue:job:{job_id}", "status", "queued")
        else:
            self.r.hset(f"queue:job:{job_id}", "status", "waiting")
        # A waiting job must not keep its GPU window — it will re-acquire on dispatch
        self.release_reservation(job_id)
        self.r.publish("queue:events", json.dumps({
            "event": "requeued",
            "job_id": job_id,
            "retry_count": job.metadata.get("retry_count", 0),
            "timestamp": datetime.now().isoformat()
        }))
        return True

    def move_to_dlq(self, job_id: str, reason: str) -> bool:
        """Move job to dead letter queue."""
        job = self.get_job(job_id)
        if not job:
            return False

        self.r.lpush("queue:dlq", job_id)
        self.r.hset(f"queue:job:{job_id}", mapping={
            "status": "dead_letter",
            "dlq_reason": reason,
            "dlq_at": datetime.now().isoformat()
        })
        self.release_reservation(job_id)
        self.r.publish("queue:events", json.dumps({
            "event": "dlq",
            "job_id": job_id,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }))
        return True

    def complete_job(self, job_id: str, success: bool = True, result: Dict = None) -> bool:
        """Mark job complete (called by dispatch playbook or monitor)."""
        status = "completed" if success else "failed"
        self.r.hset(f"queue:job:{job_id}", mapping={
            "status": status,
            "completed_at": datetime.now().isoformat(),
            "result": json.dumps(result or {})
        })
        self.release_reservation(job_id)
        self.r.publish("queue:events", json.dumps({
            "event": status,
            "job_id": job_id,
            "timestamp": datetime.now().isoformat()
        }))
        return True

    def cancel_job(self, job_id: str, actor: str = "cli") -> Dict[str, Any]:
        """Cancel a job that has not been dispatched yet.

        Only 'queued'/'waiting' jobs can be cancelled: once the scheduler
        claims a job (status=processing) the container lifecycle belongs to
        the dispatch playbook and host runtime — stop it there instead.

        Returns a result dict; never raises for expected states.
        """
        job_key = f"queue:job:{job_id}"
        data = self.r.hgetall(job_key)
        if not data:
            return {"ok": False, "reason": "not_found", "job_id": job_id}
        status = data.get("status", "unknown")
        if status == "processing":
            return {"ok": False, "reason": "running", "job_id": job_id, "status": status,
                    "detail": "job is dispatched; stop the container on its host or let it finish"}
        if status not in ("queued", "waiting"):
            return {"ok": False, "reason": "terminal", "job_id": job_id, "status": status,
                    "detail": f"job already {status}; use requeue to run it again"}

        try:
            priority = int(data.get("priority", Priority.NORMAL))
        except (TypeError, ValueError):
            priority = int(Priority.NORMAL)
        queue_key = f"queue:jobs:{priority}"
        now = datetime.now().isoformat()

        # Atomic check-and-cancel: bail if the scheduler claimed the job
        # between our hgetall and now.
        lua = """
        local status = redis.call('HGET', KEYS[1], 'status')
        if status ~= 'queued' and status ~= 'waiting' then
            return {0, status or 'unknown', 0}
        end
        local removed = redis.call('LREM', KEYS[2], 0, ARGV[1])
        redis.call('HSET', KEYS[1],
            'status', 'cancelled',
            'cancelled_at', ARGV[2],
            'cancelled_by', ARGV[3])
        return {1, status, removed}
        """
        script = self.r.register_script(lua)
        res = script(keys=[job_key, queue_key], args=[job_id, now, actor]) or ["0", "unknown", "0"]
        res = [str(x) for x in res]
        if res[0] != "1":
            return {"ok": False, "reason": "state_changed", "job_id": job_id,
                    "status": res[1] if len(res) > 1 else "unknown",
                    "detail": "job changed state before cancel landed; refresh and retry"}
        removed = int(res[2]) if len(res) > 2 and res[2].lstrip("-").isdigit() else 0

        self.release_reservation(job_id)
        self.r.publish("queue:events", json.dumps({
            "event": "cancelled",
            "job_id": job_id,
            "actor": actor,
            "previous_status": res[1],
            "timestamp": now,
        }))
        return {"ok": True, "job_id": job_id, "previous_status": res[1],
                "queue_entries_removed": removed}

    # ─── GPU Reservations ────────────────────────────────────────────────
    #
    # Ledger: one key per held GPU — gpu:hold:{host}:{gpu_index} -> JSON payload
    # with PX ttl = reserve_gpu_window_sec. Holds make the index invisible to
    # scheduler placement for ALL GPU jobs (reservation or not) until release
    # or expiry. Acquire is a single Lua script so concurrent dispatches cannot
    # double-book the same index.

    GPU_HOLD_PREFIX = "gpu:hold:"

    def _hold_key(self, host: str, gpu_index: int) -> str:
        return f"{self.GPU_HOLD_PREFIX}{host}:{gpu_index}"

    @staticmethod
    def _hold_payload(reservation_id: str, job_id: str, host: str, ttl_sec: int) -> str:
        return json.dumps({
            "reservation_id": reservation_id,
            "job_id": job_id,
            "host": host,
            "created_at": datetime.now().isoformat(),
            "expires_at": time.time() + ttl_sec,
        })

    def acquire_gpu_holds(
        self,
        host: str,
        candidate_indices: List[int],
        needed: int,
        reservation_id: str,
        job_id: str,
        ttl_sec: int,
    ) -> Optional[List[int]]:
        """Atomically claim `needed` GPU holds on `host`.

        `candidate_indices` is the ordered list of GPU indices that pass the
        VRAM check; the script picks the first `needed` that are not already
        held. Returns the held indices, or None when fewer than `needed`
        candidates are free (any partial holds are rolled back).
        """
        if needed <= 0:
            return []
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be > 0")
        indices = [str(i) for i in candidate_indices]
        if len(indices) < needed:
            return None
        payload = self._hold_payload(reservation_id, job_id, host, ttl_sec)
        lua = """
        local host = ARGV[1]
        local indices = cjson.decode(ARGV[2])
        local needed = tonumber(ARGV[3])
        local ttl_ms = tonumber(ARGV[4])
        local payload = ARGV[5]
        local chosen = {}
        for _, idx in ipairs(indices) do
            local key = 'gpu:hold:' .. host .. ':' .. idx
            if redis.call('EXISTS', key) == 0 then
                redis.call('SET', key, payload, 'PX', ttl_ms)
                table.insert(chosen, idx)
                if #chosen == needed then break end
            end
        end
        if #chosen == needed then
            return chosen
        end
        for _, idx in ipairs(chosen) do
            redis.call('DEL', 'gpu:hold:' .. host .. ':' .. idx)
        end
        return {}
        """
        script = self.r.register_script(lua)
        result = script(
            args=[host, json.dumps(indices), str(needed), str(int(ttl_sec * 1000)), payload]
        )
        if not result or len(result) < needed:
            return None
        return [int(i) for i in result]

    def release_reservation(self, job_id: str, reservation_id: str = None) -> int:
        """Delete GPU holds recorded on a job hash. Returns holds released.

        A hold is only deleted when its payload reservation_id (or job_id)
        matches, so a stale release cannot evict a newer owner's hold.
        """
        job_key = f"queue:job:{job_id}"
        data = self.r.hgetall(job_key)
        if not data:
            return 0
        try:
            hold_keys = json.loads(data.get("gpu_hold_keys", "[]"))
        except (json.JSONDecodeError, TypeError):
            hold_keys = []
        if not hold_keys:
            return 0
        rid = reservation_id or data.get("reservation_id") or ""
        lua = """
        local rid = ARGV[1]
        local job_id = ARGV[2]
        local n = 0
        for _, key in ipairs(KEYS) do
            local v = redis.call('GET', key)
            if v then
                local ok, obj = pcall(cjson.decode, v)
                if ok and ((rid ~= '' and obj['reservation_id'] == rid) or obj['job_id'] == job_id) then
                    redis.call('DEL', key)
                    n = n + 1
                end
            end
        end
        return n
        """
        script = self.r.register_script(lua)
        released = script(keys=hold_keys, args=[rid, job_id])
        if released:
            self.r.hset(job_key, mapping={
                "gpu_hold_keys": "[]",
                "reservation_state": "released",
                "reservation_released_at": datetime.now().isoformat(),
            })
        return int(released or 0)

    def held_gpu_indices(self, host: str) -> set:
        """GPU indices on `host` with an active (unexpired) hold."""
        held = set()
        for key in self.r.scan_iter(f"{self.GPU_HOLD_PREFIX}{host}:*", count=100):
            # SCAN can return keys whose TTL already lapsed but that active
            # expiry has not collected yet — EXISTS forces the lazy check.
            if not self.r.exists(key):
                continue
            try:
                held.add(int(key.rsplit(":", 1)[-1]))
            except ValueError:
                continue
        return held

    def _parse_hold_key(self, key: str):
        # gpu:hold:{host}:{index} — hostnames contain no ':'
        parts = key.split(":")
        if len(parts) != 4:
            return None, None
        try:
            return parts[2], int(parts[3])
        except ValueError:
            return None, None

    def host_holds(self, host: str) -> List[Dict[str, Any]]:
        """Active holds on one host: [{host, gpu_index, reservation_id, job_id, ttl_ms, expires_at}]."""
        holds = []
        for key in self.r.scan_iter(f"{self.GPU_HOLD_PREFIX}{host}:*", count=100):
            _, idx = self._parse_hold_key(key)
            if idx is None:
                continue
            raw = self.r.get(key)
            info = {}
            if raw:
                try:
                    info = json.loads(raw)
                except json.JSONDecodeError:
                    info = {}
            pttl = self.r.pttl(key)
            holds.append({
                "host": host,
                "gpu_index": idx,
                "reservation_id": info.get("reservation_id", ""),
                "job_id": info.get("job_id", ""),
                "expires_at": info.get("expires_at"),
                "ttl_ms": pttl if pttl and pttl > 0 else 0,
            })
        return sorted(holds, key=lambda h: h["gpu_index"])

    def list_reservations(self) -> List[Dict[str, Any]]:
        "All active GPU holds across the fleet."
        holds = []
        for key in self.r.scan_iter(f"{self.GPU_HOLD_PREFIX}*", count=100):
            host, idx = self._parse_hold_key(key)
            if host is None:
                continue
            raw = self.r.get(key)
            info = {}
            if raw:
                try:
                    info = json.loads(raw)
                except json.JSONDecodeError:
                    info = {}
            pttl = self.r.pttl(key)
            holds.append({
                "host": host,
                "gpu_index": idx,
                "reservation_id": info.get("reservation_id", ""),
                "job_id": info.get("job_id", ""),
                "expires_at": info.get("expires_at"),
                "ttl_ms": pttl if pttl and pttl > 0 else 0,
            })
        return sorted(holds, key=lambda h: (h["host"], h["gpu_index"]))

    # ─── Inspection ────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> Optional[JobSpec]:
        data = self.r.hgetall(f"queue:job:{job_id}")
        if not data:
            return None
        parsed = {}
        for k, v in data.items():
            try:
                parsed[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                parsed[k] = v
        return JobSpec.from_dict(parsed)

    def get_queue_stats(self) -> Dict[str, Any]:
        stats = {"by_priority": {}, "total_queued": 0, "processing": 0, "completed": 0, "failed": 0, "dlq": 0}
        for p in range(10):
            count = self.r.llen(f"queue:jobs:{p}")
            if count:
                stats["by_priority"][p] = count
                stats["total_queued"] += count

        # Scan job statuses (sample for performance)
        for key in self.r.scan_iter("queue:job:*", count=100):
            status = self.r.hget(key, "status")
            if status in stats:
                stats[status] += 1

        stats["dlq"] = self.r.llen("queue:dlq")
        stats["reservations"] = self.list_reservations()
        return stats

    def list_jobs(self, status: str = None, user: str = None, limit: int = 50) -> List[JobSpec]:
        jobs = []
        for key in self.r.scan_iter("queue:job:*", count=limit * 2):
            job = self.get_job(key.split(":")[-1])
            if job and (status is None or job.metadata.get("status") == status) and (user is None or job.user == user):
                jobs.append(job)
                if len(jobs) >= limit:
                    break
        return jobs

    # ─── Fair-Share ────────────────────────────────────────────────────────

    def _fairshare_key(self, user: str, project: str) -> str:
        return f"queue:fairshare:{user}:{project}"

    def _fairshare_record(self, user: str, project: str):
        key = self._fairshare_key(user, project)
        now = time.time()
        self.r.zadd(key, {f"{now}": now})
        # Trim old entries
        self.r.zremrangebyscore(key, 0, now - self.fairshare_window)

    def _fairshare_check(self, user: str, project: str) -> bool:
        key = self._fairshare_key(user, project)
        now = time.time()
        count = self.r.zcount(key, now - self.fairshare_window, now)
        return count < self.max_jobs_per_user

    def get_fairshare_status(self) -> Dict[str, int]:
        status = {}
        for key in self.r.scan_iter("queue:fairshare:*", count=100):
            parts = key.split(":")
            if len(parts) >= 4:
                user, project = parts[2], parts[3]
                now = time.time()
                count = self.r.zcount(key, now - self.fairshare_window, now)
                status[f"{user}:{project}"] = count
        return status


# ─── CLI ──────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Queue Manager CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # Enqueue
    enq = sub.add_parser("enqueue", help="Add job to queue")
    enq.add_argument("--image", required=True)
    enq.add_argument("--cmd", required=True)
    enq.add_argument("--job-id", default="")
    enq.add_argument("--gpus", type=int, default=1)
    enq.add_argument("--min-vram", type=int, default=8)
    enq.add_argument("--priority", type=int, default=Priority.NORMAL, choices=range(10))
    enq.add_argument("--user", default="default")
    enq.add_argument("--project", default="default")
    enq.add_argument("--require-tags", action="append", default=[])
    enq.add_argument("--exclude-tags", action="append", default=[])
    enq.add_argument("--group", default="all")
    enq.add_argument("--runtime", choices=["podman", "docker"], default="podman")
    enq.add_argument("--timeout", type=int, default=86400)
    enq.add_argument("--max-retries", type=int, default=2)
    enq.add_argument("--max-load", type=int, default=70,
                     help="Max CPU load as %% of cpu_count for placement (default 70; use 95 for busy desktop GPUs)")
    enq.add_argument("--max-mem", type=int, default=80,
                     help="Max memory usage %% for placement (default 80)")
    enq.add_argument("--reserve-window", type=int, default=0, dest="reserve_window",
                     help="Seconds to exclusively hold assigned GPUs (0 = no reservation; "
                          "set >= expected runtime)")
    enq.add_argument("--reservation-id", default="",
                     help="Optional reservation ID (default: rsv-<job_id>)")
    enq.add_argument("--redis", default="100.123.163.11")

    # Dequeue
    deq = sub.add_parser("dequeue", help="Get next job (for worker)")
    deq.add_argument("--worker", default="ansible-dispatcher")
    deq.add_argument("--redis", default="100.123.163.11")

    # Stats
    st = sub.add_parser("stats", help="Queue statistics")
    st.add_argument("--redis", default="100.123.163.11")

    # List
    lst = sub.add_parser("list", help="List jobs")
    lst.add_argument("--status", help="Filter by status")
    lst.add_argument("--user", help="Filter by user")
    lst.add_argument("--limit", type=int, default=20)
    lst.add_argument("--redis", default="100.123.163.11")

    # Complete
    comp = sub.add_parser("complete", help="Mark job complete")
    comp.add_argument("job_id")
    comp.add_argument("--success", action="store_true", default=True)
    comp.add_argument("--fail", dest="success", action="store_false")
    comp.add_argument("--redis", default="100.123.163.11")

    # Requeue
    req = sub.add_parser("requeue", help="Requeue job")
    req.add_argument("job_id")
    req.add_argument("--redis", default="100.123.163.11")

    # DLQ
    dlq = sub.add_parser("dlq", help="List dead letter queue")
    dlq.add_argument("--redis", default="100.123.163.11")

    # GPU reservations
    rsv = sub.add_parser("reservations", help="List active GPU reservations")
    rsv.add_argument("--redis", default="100.123.163.11")

    rel = sub.add_parser("release", help="Release GPU holds for a job")
    rel.add_argument("job_id")
    rel.add_argument("--redis", default="100.123.163.11")

    holds = sub.add_parser("holds", help="List GPU holds on a host (JSON, for playbooks)")
    holds.add_argument("--host", required=True)
    holds.add_argument("--redis", default="100.123.163.11")

    # Cancel
    can = sub.add_parser("cancel", help="Cancel a queued/waiting job")
    can.add_argument("job_id")
    can.add_argument("--actor", default="cli", help="Recorded in the audit trail")
    can.add_argument("--redis", default="100.123.163.11")

    args = parser.parse_args()

    qm = QueueManager(redis_host=args.redis)

    if args.command == "enqueue":
        job = JobSpec(
            job_id=args.job_id,
            job_image=args.image,
            job_cmd=args.cmd,
            job_gpus=args.gpus,
            job_min_vram_gb=args.min_vram,
            priority=args.priority,
            user=args.user,
            project=args.project,
            job_require_tags=args.require_tags,
            job_exclude_tags=args.exclude_tags,
            target_group=args.group,
            container_runtime=args.runtime,
            job_timeout_sec=args.timeout,
            max_retries=args.max_retries,
            job_max_load_pct=args.max_load,
            job_max_mem_pct=args.max_mem,
            reserve_gpu_window_sec=args.reserve_window,
            reservation_id=args.reservation_id,
        )
        job_id = qm.enqueue(job)
        print(f"Enqueued: {job_id} (priority={args.priority})")

    elif args.command == "dequeue":
        job = qm.dequeue(args.worker)
        if job:
            print(json.dumps(job.to_dict(), indent=2))
        else:
            print("No eligible jobs")

    elif args.command == "stats":
        stats = qm.get_queue_stats()
        fs = qm.get_fairshare_status()
        print(json.dumps({"queue": stats, "fairshare": fs}, indent=2))

    elif args.command == "list":
        jobs = qm.list_jobs(status=args.status, user=args.user, limit=args.limit)
        for job in jobs:
            print(f"{job.job_id} | {job.metadata.get('status', 'unknown'):12} | p={job.priority} | {job.user}:{job.project} | {job.job_image}")

    elif args.command == "complete":
        qm.complete_job(args.job_id, args.success)
        print(f"Job {args.job_id} marked {'completed' if args.success else 'failed'}")

    elif args.command == "requeue":
        if qm.requeue(args.job_id):
            print(f"Requeued: {args.job_id}")
        else:
            print(f"Failed to requeue: {args.job_id}")

    elif args.command == "dlq":
        dlq_jobs = qm.r.lrange("queue:dlq", 0, -1)
        for job_id in dlq_jobs:
            job = qm.get_job(job_id)
            reason = job.metadata.get("dlq_reason", "unknown") if job else "orphaned"
            print(f"{job_id} | {reason}")

    elif args.command == "reservations":
        holds = qm.list_reservations()
        if not holds:
            print("No active GPU reservations")
        for h in holds:
            ttl_s = h["ttl_ms"] // 1000 if h["ttl_ms"] > 0 else 0
            print(f"{h['host']} gpu{h['gpu_index']} | job={h['job_id']} | "
                  f"reservation={h['reservation_id']} | ttl={ttl_s}s")

    elif args.command == "release":
        n = qm.release_reservation(args.job_id)
        print(f"Released {n} GPU hold(s) for {args.job_id}")

    elif args.command == "holds":
        print(json.dumps(qm.host_holds(args.host)))

    elif args.command == "cancel":
        print(json.dumps(qm.cancel_job(args.job_id, actor=args.actor)))


if __name__ == "__main__":
    main()