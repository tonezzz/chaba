#!/usr/bin/env python3
"""Live memory-pressure guard for the KK-Mac bounded executor
(card kk-mac-live-memory-guard, MEM-1043).

The bounded lane shares KK-Mac with the owner, so every admitted task
must prove headroom BEFORE the model loads and keep proving it while
generation runs. Floors (approved):

  pre-load   free memory >= 60%  — below that the task defers
  abort      free memory <  50% or critical pressure — stop/fail closed

Sampling runs on the dispatch host over the same ssh path the executor
already uses (`memory_pressure -Q`, vm_stat fallback). A sample that
cannot be taken fails closed at pre-load; during-run samples are
best-effort evidence — a breach still fails the verdict.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from typing import Callable

PRELOAD_MIN_FREE_PCT = 60.0
ABORT_FREE_PCT = 50.0
DEFAULT_HOST = "kk-mac"
POLL_S = 15.0
LOCAL_HOSTS = frozenset({"local", "localhost", "127.0.0.1", "::1"})


def is_local_host(host: str) -> bool:
    return str(host or "").strip().lower() in LOCAL_HOSTS


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_ssh(cmd: list[str], timeout: int = 25
                 ) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _meminfo_free_pct() -> float | None:
    """Linux-local fallback: MemAvailable / MemTotal from procfs."""
    try:
        vals = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                vals[k.strip()] = int(v.strip().split()[0])
        total = vals.get("MemTotal")
        avail = vals.get("MemAvailable", vals.get("MemFree"))
        if total and avail is not None:
            return round(100.0 * avail / total, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _host_cmd(host: str, shell_cmd: str) -> list[str]:
    if is_local_host(host):
        return ["sh", "-c", shell_cmd]
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            host, shell_cmd]


def sample(host: str = DEFAULT_HOST, *,
           ssh_run: Callable = _default_ssh) -> dict:
    """One memory sample from the KK-Mac host ->
    {ok, free_pct, level, raw, at, error}. ok=False means the sample
    could not be taken — callers treat that as fail-closed at pre-load.
    When host is local (the on-host lane worker) the same probes run
    directly instead of over ssh."""
    out = {"ok": False, "free_pct": None, "level": None, "raw": "",
           "at": now_iso(), "error": None}
    if is_local_host(host) and os.uname().sysname == "Linux":
        pct = _meminfo_free_pct()
        if pct is not None:
            out.update(ok=True, free_pct=pct, raw="procfs_meminfo")
        else:
            out["error"] = "meminfo_unreadable"
        return out
    cmd = _host_cmd(host, "memory_pressure -Q 2>/dev/null || true")
    try:
        r = ssh_run(cmd, timeout=25)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{exc}"[:200]
        return out
    text = (getattr(r, "stdout", b"") or b"").decode(errors="replace")
    if getattr(r, "returncode", 1) != 0 and not text.strip():
        out["error"] = "ssh_failed"
        return out
    out["raw"] = text.strip()[:2000]
    m = re.search(r"free percentage:\s*(\d+(?:\.\d+)?)\s*%", text)
    if m:
        out["free_pct"] = float(m.group(1))
        out["ok"] = True
        return out
    # memory_pressure -Q may be unavailable; fall back to vm_stat pages.
    cmd2 = _host_cmd(host, "vm_stat | head -12")
    try:
        r2 = ssh_run(cmd2, timeout=25)
    except Exception as exc:
        out["error"] = f"vm_stat:{type(exc).__name__}"[:200]
        return out
    text2 = (getattr(r2, "stdout", b"") or b"").decode(errors="replace")
    out["raw"] += "\n" + text2.strip()[:2000]
    pages = {}
    for line in text2.splitlines():
        m2 = re.match(r"([^:]+):\s+(\d+)\.", line)
        if m2:
            pages[m2.group(1).strip()] = int(m2.group(2))
    free = pages.get("Pages free", 0) + pages.get("Pages inactive", 0)
    total = sum(pages.values())
    if total > 0:
        out["free_pct"] = round(100.0 * free / total, 1)
        out["ok"] = True
    else:
        out["error"] = "unparseable_memory_output"
    return out


def evaluate(snap: dict, *, phase: str) -> list[str]:
    """-> reasons this sample blocks the run. phase: 'pre'|'during'|'post'."""
    reasons = []
    if not snap.get("ok"):
        if phase == "pre":
            reasons.append("memory_sample_failed")
        return reasons
    pct = snap.get("free_pct")
    if pct is None:
        if phase == "pre":
            reasons.append("memory_sample_failed")
        return reasons
    if phase == "pre" and pct < PRELOAD_MIN_FREE_PCT:
        reasons.append(f"memory_preload_floor:{pct}%<{PRELOAD_MIN_FREE_PCT}%")
    if pct < ABORT_FREE_PCT:
        reasons.append(f"memory_pressure_abort:{pct}%<{ABORT_FREE_PCT}%")
    lvl = str(snap.get("level") or "").lower()
    if phase != "pre" and "critical" in lvl:
        reasons.append("memory_pressure_critical")
    return reasons


class MemoryMonitor(threading.Thread):
    """Polls memory while the blocking executor call runs; records every
    sample so pre/during/post evidence is persisted. Detection only —
    the bounded ssh call is not killed mid-flight; a breach still fails
    the contract verdict (fail closed)."""

    def __init__(self, host: str = DEFAULT_HOST, *,
                 ssh_run: Callable = _default_ssh,
                 interval: float = POLL_S):
        super().__init__(daemon=True)
        self.host = host
        self.ssh_run = ssh_run
        self.interval = interval
        self.samples: list[dict] = []
        # must not shadow Thread._stop() — join() calls it internally
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.samples.append(sample(self.host, ssh_run=self.ssh_run))
            except Exception:
                pass
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5)

    def worst_reasons(self) -> list[str]:
        out: list[str] = []
        for s in self.samples:
            for r in evaluate(s, phase="during"):
                if r not in out:
                    out.append(r)
        return out
