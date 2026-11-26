#!/usr/bin/env python3
"""
Scheduler Daemon for Ansible-Centralized Dispatch

Closes the loop: queue -> dispatch playbook -> monitor -> complete/requeue.

Runs as a systemd user service on the control node (idc02). Polls the Redis
priority queue, invokes dispatch_job.yml for each eligible job, monitors the
dispatched container, and marks jobs complete (or requeues on failure).

Features:
- Priority-aware dequeue with fair-share (via QueueManager)
- Configurable poll interval
- Concurrent dispatch limit (max simultaneous jobs)
- Job monitoring via container status (podman/docker ps)
- Automatic retry with backoff via queue_manager.requeue()
- Graceful shutdown (SIGTERM/SIGINT)
- Structured logging to stdout (journald)

Usage:
  python3 scheduler.py --redis 100.123.163.11 --interval 5 --max-concurrent 3
  systemctl --user start dispatch-scheduler.service
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add queue module to path
sys.path.insert(0, str(Path(__file__).parent))
from queue_manager import QueueManager, JobSpec

# ─── Configuration ────────────────────────────────────────────────────────
ANSIBLE_DIR = Path("/home/tony/ansible")
PLAYBOOK = ANSIBLE_DIR / "playbooks" / "dispatch_job.yml"
INVENTORY = ANSIBLE_DIR / "inventory.ini"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("dispatch-scheduler")


class Scheduler:
    def __init__(
        self,
        redis_host: str = "100.123.163.11",
        redis_port: int = 6379,
        redis_db: int = 0,
        poll_interval: int = 5,
        max_concurrent: int = 3,
        monitor_interval: int = 15,
        dry_run: bool = False,
        dispatch_timeout: int = 300,
    ):
        self.qm = QueueManager(redis_host=redis_host, redis_port=redis_port, redis_db=redis_db)
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self.monitor_interval = monitor_interval
        self.dry_run = dry_run
        self.dispatch_timeout = dispatch_timeout
        self.running = False
        self.active_jobs: Dict[str, Dict[str, Any]] = {}  # job_id -> {host, container_id, start_time, process}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)

    def start(self):
        """Start the scheduler loop."""
        self.running = True
        log.info(f"Scheduler started (redis={self.qm.r.connection_pool.connection_kwargs.get('host')}, "
                 f"interval={self.poll_interval}s, max_concurrent={self.max_concurrent}, dry_run={self.dry_run})")

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

        while self.running:
            try:
                self._tick()
            except Exception as e:
                log.error(f"Scheduler tick failed: {e}", exc_info=True)

            # Sleep in small chunks for responsive shutdown
            for _ in range(self.poll_interval):
                if not self.running:
                    break
                time.sleep(1)

        log.info("Scheduler stopped")
        self.executor.shutdown(wait=True)

    def _shutdown(self, signum, frame):
        log.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def _tick(self):
        """One scheduler iteration: dispatch new jobs + monitor active ones."""
        # Monitor existing jobs first
        self._monitor_jobs()

        # Check capacity
        with self.lock:
            active_count = len(self.active_jobs)

        if active_count >= self.max_concurrent:
            log.debug(f"At capacity ({active_count}/{self.max_concurrent}), skipping dequeue")
            return

        # Dequeue next eligible job
        job = self.qm.dequeue(worker_id=f"scheduler-{os.getpid()}")
        if not job:
            log.debug("No eligible jobs in queue")
            return

        log.info(f"Dequeued job {job.job_id} (priority={job.priority}, "
                 f"user={job.user}:{job.project}, gpus={job.job_gpus})")

        # Dispatch in thread pool
        future = self.executor.submit(self._dispatch_job, job)
        future.add_done_callback(lambda f, j=job: self._dispatch_done(f, j))

    def _select_target_host(self, job: JobSpec) -> Optional[str]:
        """Select the best eligible host from sidecar metrics, considering
        tags, GPU count/VRAM, load, and memory. Returns hostname or None.

        This is the placement decision — Ansible only executes the dispatch.
        """
        r = self.qm.r
        candidates = []

        # Target group members from Ansible inventory (simple parse of inventory.ini)
        group_hosts = self._get_group_hosts(job.target_group)
        if not group_hosts:
            log.warning(f"No hosts found in group {job.target_group}")
            return None

        for hostname in group_hosts:
            data = r.hgetall(f"sidecar:{hostname}")
            if not data:
                continue

            # Parse tags
            try:
                tags = json.loads(data.get("tags", "[]"))
            except (json.JSONDecodeError, TypeError):
                tags = []

            # Tag filters
            if job.job_require_tags and not all(t in tags for t in job.job_require_tags):
                continue
            if job.job_exclude_tags and any(t in tags for t in job.job_exclude_tags):
                continue

            # GPU requirements — indices under an active reservation hold are
            # invisible to placement for every GPU job (reservation or not).
            gpu_count = int(data.get("gpu_count", 0))
            free_enough = 0
            if job.job_gpus > 0 and gpu_count < job.job_gpus:
                continue
            if job.job_gpus > 0:
                try:
                    gpus = json.loads(data.get("gpus", "[]"))
                except (json.JSONDecodeError, TypeError):
                    continue
                held = self.qm.held_gpu_indices(hostname)
                if job.job_min_vram_gb > 0:
                    free_enough = sum(
                        1 for g in gpus
                        if g.get("mem_free_mb", 0) > job.job_min_vram_gb * 1024
                        and g.get("index") not in held
                    )
                else:
                    free_enough = sum(1 for g in gpus if g.get("index") not in held)
                if free_enough < job.job_gpus:
                    continue

            # Load/memory checks
            load1 = float(data.get("load1", 999))
            cpu_count = int(data.get("cpu_count", 1))
            if load1 > cpu_count * job.job_max_load_pct / 100:
                continue
            mem_pct = float(data.get("mem_pct", 100))
            if mem_pct > job.job_max_mem_pct:
                continue

            # Score: lower load = better, more free VRAM = better
            score = (100 - load1 / max(cpu_count, 1) * 100) + (free_enough * 5)
            candidates.append((score, hostname))

        if not candidates:
            log.warning(f"No eligible hosts for {job.job_id} (group={job.target_group}, "
                        f"tags={job.job_require_tags}, gpus={job.job_gpus})")
            return None

        candidates.sort(reverse=True)
        best = candidates[0][1]
        log.info(f"Selected host {best} (score={candidates[0][0]:.1f}, "
                 f"{len(candidates)} eligible candidates)")
        return best

    def _get_group_hosts(self, group: str) -> list:
        """Parse inventory.ini to get hosts in a group (or specific hostname)."""
        # If group is a specific hostname, return it directly
        if group in [h.strip().split()[0] for h in INVENTORY.read_text().splitlines()
                     if h.strip() and not h.strip().startswith(("#", "["))]:
            return [group]

        hosts = []
        in_group = False
        for line in INVENTORY.read_text().splitlines():
            line = line.strip()
            if line.startswith("["):
                in_group = (line == f"[{group}]")
                continue
            if in_group and line and not line.startswith("#"):
                hosts.append(line.split()[0])
        if not hosts and group == "all":
            # All non-grouped hosts + grouped hosts
            seen = set()
            for line in INVENTORY.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "[")):
                    h = line.split()[0]
                    if h not in seen:
                        seen.add(h)
                        hosts.append(h)
        return hosts

    def _acquire_job_gpu_window(self, job: JobSpec, host: str) -> Optional[list]:
        """Create the atomic GPU holds for a reservation job on `host`.

        Returns the held GPU indices, or None when the window is already held
        (caller treats this as resource backpressure — requeue, no penalty).
        """
        data = self.qm.r.hgetall(f"sidecar:{host}")
        try:
            gpus = json.loads(data.get("gpus", "[]"))
        except (json.JSONDecodeError, TypeError):
            gpus = []
        need_mb = job.job_min_vram_gb * 1024
        candidates = [
            int(g["index"]) for g in gpus
            if "index" in g and g.get("mem_free_mb", 0) > need_mb
        ]
        reservation_id = job.reservation_id or f"rsv-{job.job_id}"
        acquired = self.qm.acquire_gpu_holds(
            host,
            candidates,
            needed=job.job_gpus,
            reservation_id=reservation_id,
            job_id=job.job_id,
            ttl_sec=job.reserve_gpu_window_sec,
        )
        if not acquired or len(acquired) < job.job_gpus:
            log.info(f"GPU window on {host} not available for {job.job_id} "
                     f"(held by another reservation)")
            return None
        hold_keys = [self.qm._hold_key(host, i) for i in acquired]
        self.qm.r.hset(f"queue:job:{job.job_id}", mapping={
            "reservation_id": reservation_id,
            "gpu_hold_keys": json.dumps(hold_keys),
        })
        job.reservation_id = reservation_id
        log.info(f"Reserved GPU window on {host} indices={acquired} "
                 f"reservation={reservation_id} ttl={job.reserve_gpu_window_sec}s")
        return acquired

    def _dispatch_job(self, job: JobSpec) -> Optional[Dict[str, Any]]:
        """Invoke dispatch_job.yml for a job. Returns dispatch info or None."""
        # Select target host based on placement policy
        target_host = self._select_target_host(job)
        if not target_host:
            return {"no_host": True, "job_id": job.job_id}

        cmd = [
            "ansible-playbook",
            str(PLAYBOOK),
            "-i", str(INVENTORY),
            "-e", f"job_id={job.job_id}",
            "-e", f"job_image={job.job_image}",
            # job_cmd is free text — key=value -e splits on whitespace, so pass
            # it as a JSON extra-var to preserve spaces/quotes end-to-end.
            "-e", json.dumps({"job_cmd": job.job_cmd}),
            "-e", f"job_gpus={job.job_gpus}",
            "-e", f"job_min_vram_gb={job.job_min_vram_gb}",
            "-e", f"job_max_load_pct={job.job_max_load_pct}",
            "-e", f"job_max_mem_pct={job.job_max_mem_pct}",
            "-e", f"target_group={target_host}",
            "-e", f"container_runtime={job.container_runtime}",
            "-e", f"job_timeout_sec={job.job_timeout_sec}",
        ]

        # Tags (still pass for double-check in playbook)
        if job.job_require_tags:
            cmd.extend(["-e", f"job_require_tags={json.dumps(job.job_require_tags)}"])
        if job.job_exclude_tags:
            cmd.extend(["-e", f"job_exclude_tags={json.dumps(job.job_exclude_tags)}"])

        if self.dry_run:
            cmd.append("--check")
            log.info(f"[DRY RUN] Would dispatch {job.job_id}: {' '.join(cmd[:6])}...")
            return {"dry_run": True, "job_id": job.job_id}

        # GPU window reservation: acquire the hold atomically before dispatch.
        # Failure means another reservation holds the window — treat as
        # resource backpressure (requeue without retry penalty).
        if job.job_gpus > 0 and job.reserve_gpu_window_sec > 0:
            acquired = self._acquire_job_gpu_window(job, target_host)
            if acquired is None:
                return {"no_host": True, "reason": "gpu_window_held",
                        "job_id": job.job_id}
            cmd.extend([
                "-e", f"gpu_device_indices={','.join(str(i) for i in acquired)}",
                "-e", f"gpu_reservation_id={job.reservation_id}",
            ])

        log.info(f"Dispatching {job.job_id}: {' '.join(cmd[:8])}...")

        env = os.environ.copy()
        env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
        env["ANSIBLE_PIPELINING"] = "True"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.dispatch_timeout,
                env=env,
                cwd=str(ANSIBLE_DIR),
            )

            if result.returncode != 0:
                log.error(f"Dispatch failed for {job.job_id} (rc={result.returncode}):\n{result.stderr[-2000:]}")
                return None

            # Extract host from playbook output (debug message)
            host = None
            container_id = None
            for line in result.stdout.splitlines():
                if "Dispatched job" in line and "to" in line:
                    parts = line.split("to")
                    if len(parts) > 1:
                        host = parts[1].split()[0].strip()
                if "container=" in line:
                    container_id = line.split("container=")[1].strip().rstrip(")")

            # Fallback: query Redis dispatch record
            if not host:
                record = self.qm.r.hgetall(f"dispatch:{job.job_id}")
                host = record.get("host")
                container_id = record.get("container_id")

            log.info(f"Dispatched {job.job_id} to {host or 'unknown'} (container={container_id})")
            return {
                "job_id": job.job_id,
                "host": host,
                "container_id": container_id,
                "stdout": result.stdout[-1000:],
            }

        except subprocess.TimeoutExpired:
            log.error(f"Dispatch timed out for {job.job_id} after {self.dispatch_timeout}s")
            return None
        except Exception as e:
            log.error(f"Dispatch exception for {job.job_id}: {e}", exc_info=True)
            return None

    def _dispatch_done(self, future, job: JobSpec):
        """Handle dispatch completion."""
        try:
            result = future.result()
        except Exception as e:
            log.error(f"Dispatch future failed for {job.job_id}: {e}")
            self.qm.requeue(job.job_id)
            return

        if result and result.get("no_host"):
            # Resource unavailable (no GPU VRAM, high load, etc.) — wait in queue
            # WITHOUT counting as a failure. This is normal backpressure.
            log.info(f"Job {job.job_id} waiting for resources — returned to queue (no retry penalty)")
            self.qm.requeue(job.job_id, increment_retry=False, reset_status=False)
            return

        if not result:
            log.warning(f"Dispatch failed for {job.job_id}, requeuing (attempt {job.metadata.get('retry_count', 0) + 1}/{job.max_retries})")
            self.qm.requeue(job.job_id)
            return

        if result.get("dry_run"):
            # Dry-run: mark complete immediately
            self.qm.complete_job(job.job_id, success=True, result={"dry_run": True})
            return

        # Track active job for monitoring
        with self.lock:
            self.active_jobs[job.job_id] = {
                "host": result.get("host"),
                "container_id": result.get("container_id"),
                "start_time": time.time(),
                "job": job,
            }

    def _monitor_jobs(self):
        """Check active jobs and mark complete/requeue as needed."""
        with self.lock:
            jobs = list(self.active_jobs.items())

        for job_id, info in jobs:
            job = info["job"]
            host = info["host"]
            container_id = info["container_id"]
            elapsed = time.time() - info["start_time"]

            if not host:
                log.warning(f"No host info for {job_id}, cannot monitor")
                with self.lock:
                    self.active_jobs.pop(job_id, None)
                continue

            # Check if job timed out
            if elapsed > job.job_timeout_sec:
                log.warning(f"Job {job_id} exceeded timeout ({job.job_timeout_sec}s), marking failed")
                self.qm.complete_job(job_id, success=False, result={"reason": "timeout", "elapsed_sec": elapsed})
                with self.lock:
                    self.active_jobs.pop(job_id, None)
                continue

            # Check container status via SSH to host
            status = self._check_container_status(host, job_id, job.container_runtime)
            if status == "running":
                log.debug(f"Job {job_id} still running on {host} ({int(elapsed)}s)")
                continue
            elif status == "exited":
                # Check exit code
                exit_code = self._get_container_exit_code(host, job_id, job.container_runtime)
                success = exit_code == 0
                log.info(f"Job {job_id} finished on {host} (exit_code={exit_code}, success={success}, elapsed={int(elapsed)}s)")
                self.qm.complete_job(job_id, success=success, result={
                    "exit_code": exit_code,
                    "elapsed_sec": elapsed,
                    "host": host,
                })
                if not success:
                    # Optionally requeue failed jobs
                    retry_count = job.metadata.get("retry_count", 0)
                    if retry_count < job.max_retries:
                        log.info(f"Requeueing failed job {job_id} (retry {retry_count + 1}/{job.max_retries})")
                        self.qm.requeue(job_id)
                with self.lock:
                    self.active_jobs.pop(job_id, None)
            elif status == "not_found":
                # Container not found - dispatch may have silently failed
                log.warning(f"Container for {job_id} not found on {host}, requeuing")
                self.qm.requeue(job_id)
                with self.lock:
                    self.active_jobs.pop(job_id, None)
            else:
                # Unknown state (SSH failure, etc.) - retry later
                log.debug(f"Could not check status of {job_id} on {host} (state={status})")

    def _ssh_target(self, host: str) -> str:
        """Map an Ansible inventory hostname to its ansible_host SSH address."""
        for line in INVENTORY.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "[")):
                continue
            parts = line.split()
            if parts[0] == host:
                for part in parts[1:]:
                    if part.startswith("ansible_host="):
                        return part.split("=", 1)[1]
        return host

    def _check_container_status(self, host: str, job_id: str, runtime: str) -> str:
        """Check if job container is running on host. Returns: running/exited/not_found/unknown."""
        ssh_cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            f"tony@{self._ssh_target(host)}",
            f"{runtime} ps -a --filter name=job-{job_id} --format '{{{{.Status}}}}'",
        ]
        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return "unknown"
            out = result.stdout.strip()
            if not out:
                return "not_found"
            if "Up" in out or "running" in out.lower():
                return "running"
            if "Exited" in out or "Created" in out:
                return "exited"
            return "unknown"
        except Exception:
            return "unknown"

    def _get_container_exit_code(self, host: str, job_id: str, runtime: str) -> int:
        """Get container exit code via inspect."""
        ssh_cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            f"tony@{self._ssh_target(host)}",
            f"{runtime} inspect --format '{{{{.State.ExitCode}}}}' job-{job_id}",
        ]
        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return int(result.stdout.strip())
        except (ValueError, Exception):
            pass
        return -1

    def status(self) -> Dict[str, Any]:
        """Get scheduler status for health checks."""
        with self.lock:
            active = list(self.active_jobs.keys())
        return {
            "running": self.running,
            "active_jobs": active,
            "active_count": len(active),
            "max_concurrent": self.max_concurrent,
            "queue_stats": self.qm.get_queue_stats(),
            "reservations": self.qm.list_reservations(),
        }


def main():
    parser = argparse.ArgumentParser(description="Ansible Dispatch Scheduler")
    parser.add_argument("--redis", default="100.123.163.11", help="Redis host")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis port")
    parser.add_argument("--redis-db", type=int, default=0, help="Redis logical DB")
    parser.add_argument("--interval", type=int, default=5, help="Poll interval seconds")
    parser.add_argument("--max-concurrent", type=int, default=3, help="Max concurrent dispatches")
    parser.add_argument("--monitor-interval", type=int, default=15, help="Job monitor interval seconds")
    parser.add_argument("--dispatch-timeout", type=int, default=300, help="Dispatch playbook timeout seconds")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (check mode, no actual dispatch)")
    parser.add_argument("--once", action="store_true", help="Run one tick and exit (for testing)")
    args = parser.parse_args()

    scheduler = Scheduler(
        redis_host=args.redis,
        redis_port=args.redis_port,
        redis_db=args.redis_db,
        poll_interval=args.interval,
        max_concurrent=args.max_concurrent,
        monitor_interval=args.monitor_interval,
        dry_run=args.dry_run,
        dispatch_timeout=args.dispatch_timeout,
    )

    if args.once:
        log.info("Running single scheduler tick...")
        scheduler._tick()
        print(json.dumps(scheduler.status(), indent=2))
        return

    scheduler.start()


if __name__ == "__main__":
    main()