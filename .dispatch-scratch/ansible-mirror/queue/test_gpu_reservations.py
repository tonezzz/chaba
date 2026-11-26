#!/usr/bin/env python3
"""
GPU reservation exclusivity test.

Queues two overlapping GPU jobs against an isolated Redis logical DB and
verifies that only one can hold the GPU window: the second job's host
placement returns no host while the first job's reservation is active, and
placement succeeds again after release.

Uses a dedicated Redis DB (default 15) seeded with fake sidecar metrics for
"omen" — no real hosts, containers, or the production queue (db 0) are
touched. Requires a reachable Redis; run on the control node (idc02):

    python3 queue/test_gpu_reservations.py [--redis 100.123.163.11] [--db 15]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import redis  # noqa: E402
from queue_manager import JobSpec, Priority, QueueManager  # noqa: E402
from scheduler import Scheduler  # noqa: E402


def seed_sidecar(r, host="omen"):
    r.hset(f"sidecar:{host}", mapping={
        "hostname": host,
        "tags": json.dumps(["gpu"]),
        "gpu_count": "1",
        "gpus": json.dumps([{
            "index": 0, "name": "NVIDIA GeForce GTX 1650",
            "mem_used_mb": 1000, "mem_free_mb": 3000,
            "util_pct": 0, "temp_c": 40,
        }]),
        "load1": "1.0", "cpu_count": "12", "mem_pct": "40",
    })


def make_job(job_id, reserve_window=600, priority=Priority.HIGH):
    return JobSpec(
        job_id=job_id,
        job_image="docker.io/nvidia/cuda:12.2.0-base-ubuntu22.04",
        job_cmd="nvidia-smi -L",
        job_gpus=1,
        job_min_vram_gb=1,
        job_require_tags=["gpu"],
        target_group="all",
        container_runtime="podman",
        reserve_gpu_window_sec=reserve_window,
        priority=priority,
        user="test",
        project="reservation-test",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--redis", default="100.123.163.11")
    ap.add_argument("--db", type=int, default=15)
    args = ap.parse_args()

    r = redis.Redis(host=args.redis, db=args.db, decode_responses=True)
    if not r.ping():
        print("FAIL: redis not reachable")
        return 1
    if r.dbsize() != 0:
        print(f"FAIL: redis db {args.db} is not empty ({r.dbsize()} keys) — "
              f"pick a clean --db")
        return 1

    failures = []

    def check(name, cond, detail=""):
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {name} {detail}")
        if not cond:
            failures.append(name)

    try:
        seed_sidecar(r)
        qm = QueueManager(redis_host=args.redis, redis_db=args.db)
        sched = Scheduler(redis_host=args.redis, redis_db=args.db)

        # Queue two overlapping reservation jobs (same priority -> FIFO).
        # int() keeps priority a plain int — IntEnum str() varies by Python
        # version and would land in the wrong queue:jobs:<p> list key.
        job_a = make_job("test-rsv-a", priority=int(Priority.HIGH))
        job_b = make_job("test-rsv-b", priority=int(Priority.HIGH))
        qm.enqueue(job_a)
        qm.enqueue(job_b)

        # First dequeue gets job A (FIFO within priority)
        ja = qm.dequeue(worker_id="test")
        check("dequeue returns job A first", ja is not None and ja.job_id == "test-rsv-a",
              f"got={ja.job_id if ja else None}")

        host_a = sched._select_target_host(ja)
        check("job A selects omen", host_a == "omen", f"host={host_a}")
        idx_a = sched._acquire_job_gpu_window(ja, host_a)
        check("job A acquires GPU 0 hold", idx_a == [0], f"indices={idx_a}")
        check("hold visible in ledger",
              qm.held_gpu_indices("omen") == {0},
              f"held={qm.held_gpu_indices('omen')}")

        # Second dequeue gets job B — but omen's only GPU is held
        jb = qm.dequeue(worker_id="test")
        check("dequeue returns job B second", jb is not None and jb.job_id == "test-rsv-b",
              f"got={jb.job_id if jb else None}")

        host_b = sched._select_target_host(jb)
        check("job B placement refused while held", host_b is None, f"host={host_b}")

        # Even if forced to the same host, the atomic acquire must refuse
        idx_b = sched._acquire_job_gpu_window(jb, "omen")
        check("job B atomic acquire refused", idx_b is None, f"indices={idx_b}")

        # A non-reservation GPU job is also kept off the held index
        job_c = make_job("test-plain-c", reserve_window=0, priority=int(Priority.LOW))
        host_c = sched._select_target_host(job_c)
        check("plain GPU job also blocked by hold", host_c is None, f"host={host_c}")

        # Completing A releases the window; B can now be placed
        qm.complete_job("test-rsv-a", success=True, result={"test": True})
        check("release on complete clears hold",
              qm.held_gpu_indices("omen") == set(),
              f"held={qm.held_gpu_indices('omen')}")

        host_b2 = sched._select_target_host(jb)
        check("job B placement succeeds after release", host_b2 == "omen",
              f"host={host_b2}")
        idx_b2 = sched._acquire_job_gpu_window(jb, host_b2)
        check("job B acquires hold after release", idx_b2 == [0], f"indices={idx_b2}")

        # holds CLI shape used by dispatch_job.yml
        holds_json = qm.host_holds("omen")
        check("host_holds returns reservation_id",
              len(holds_json) == 1 and holds_json[0]["reservation_id"] == "rsv-test-rsv-b",
              f"holds={holds_json}")

        # stats exposes reservations
        stats = qm.get_queue_stats()
        check("stats includes reservations", len(stats.get("reservations", [])) == 1,
              f"reservations={stats.get('reservations')}")

        # TTL expiry path: shrink window and let it lapse
        r.set("gpu:hold:omen:0", qm._hold_payload("rsv-x", "test-rsv-b", "omen", 1), px=1)
        time.sleep(0.05)
        check("expired hold not counted", qm.held_gpu_indices("omen") == set())

    finally:
        r.flushdb()

    if failures:
        print(f"\nFAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
