#!/usr/bin/env python3
"""KK-Mac JevNest lane metrics rollup (card kk-mac-continuous-llm-worker).

Scans gdrive:ada-nest/kk-llm/packs and reports the metrics the capacity
procedure feeds back into JevTeam review:

  queue wait    staged -> claim (pack file mtimes via one rclone lsl)
  wall time     done-marker duration or result.json wall_seconds
  eval tokens   out/result.json eval_count / eval_duration (--tokens)
  verifier      result.json verified flag (--tokens)
  fallback      packs with failed marker, reason from marker text

Read-only. One recursive `rclone lsl` covers statuses/timing; --tokens
adds one `rclone cat` per finished pack (bounded by --budget-s).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REMOTE = "gdrive:ada-nest/kk-llm"
DONE_RE = re.compile(r"^(\d+(?:\.\d+)?)s\s")


def rclone(*args: str) -> str:
    r = subprocess.run(["rclone", *args], capture_output=True,
                       text=True, timeout=90)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300] or "rclone failed")
    return r.stdout


def _lsl_epoch(date_s: str, time_s: str) -> float | None:
    """`rclone lsl` timestamp: '2026-10-30 10:41:45.749000000' (UTC)."""
    try:
        base = datetime.strptime(f"{date_s} {time_s.split('.')[0]}",
                                 "%Y-%m-%d %H:%M:%S")
        frac = time_s.split(".", 1)
        micro = int(frac[1][:6].ljust(6, "0")) if len(frac) > 1 else 0
        return base.replace(tzinfo=timezone.utc).timestamp() + micro / 1e6
    except (ValueError, IndexError):
        return None


def parse_lsl(text: str) -> dict[str, dict]:
    """`rclone lsl <remote>/packs --recursive` lines look like
    `92 2026-10-30 10:41:45.749000000 pack-x/done`; paths are relative to
    packs/, so {pack_name: {relpath: (mtime_epoch, size)}}."""
    packs: dict[str, dict] = {}
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            size = int(parts[0])
        except ValueError:
            continue
        epoch = _lsl_epoch(parts[1], parts[2])
        if epoch is None:
            continue
        seg = parts[3].strip().split("/", 1)
        if len(seg) < 2:
            continue  # top-level stray file, not a pack
        packs.setdefault(seg[0], {})[seg[1]] = (epoch, size)
    return packs


def pack_metrics(files: dict) -> dict:
    """One pack's files {relpath: (mtime,size)} -> status + timings.
    Status precedence: done/failed terminal > fallback hold > live."""
    m = {"status": "live", "staged_at": None, "claimed_at": None,
         "finished_at": None, "queue_wait_s": None, "wall_s": None,
         "latency_s": None, "worker": None}
    ts = [v[0] for v in files.values()]
    if ts:
        m["staged_at"] = min(ts)
    for rel, (epoch, _size) in files.items():
        top = rel.split("/", 1)[0]
        if top == "claim" and "/" in rel:
            m["claimed_at"] = epoch if m["claimed_at"] is None \
                else min(m["claimed_at"], epoch)
            m["worker"] = rel.split("/", 1)[1]
        elif rel == "done":
            m["status"] = "done"
            m["finished_at"] = epoch
        elif rel == "failed":
            if m["status"] != "done":
                m["status"] = "failed"
                m["finished_at"] = epoch
        elif rel == "fallback":
            if m["status"] == "live":
                m["status"] = "fallback"
                m["finished_at"] = epoch
    if m["staged_at"] and m["claimed_at"]:
        m["queue_wait_s"] = round(m["claimed_at"] - m["staged_at"], 1)
    if m["staged_at"] and m["finished_at"]:
        m["latency_s"] = round(m["finished_at"] - m["staged_at"], 1)
    return m


def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return round(s[i], 1)


def _stats(vals: list[float]) -> dict:
    return {"n": len(vals), "total": round(sum(vals), 1),
            "mean": round(sum(vals) / len(vals), 1) if vals else None,
            "p50": _pct(vals, 50), "p95": _pct(vals, 95),
            "max": round(max(vals), 1) if vals else None}


def collect(*, remote: str = REMOTE, with_tokens: bool = False,
            budget_s: float = 120.0,
            cat=None) -> dict:
    cat = cat or (lambda p: rclone("cat", p))
    started = time.monotonic()
    packs = parse_lsl(rclone("lsl", f"{remote}/packs"))
    per_pack = {name: pack_metrics(f) for name, f in packs.items()}
    counts = {"done": 0, "failed": 0, "fallback": 0, "live": 0}
    for m in per_pack.values():
        counts[m["status"]] += 1
    waits = [m["queue_wait_s"] for m in per_pack.values()
             if m["queue_wait_s"] is not None]
    latencies = [m["latency_s"] for m in per_pack.values()
                 if m["latency_s"] is not None]
    walls = []
    tokens = {"eval_count_total": 0, "eval_duration_s_total": 0.0,
              "load_duration_s_total": 0.0, "verified": 0,
              "unverified": 0, "result_files": 0, "budget_skipped": 0}
    for name, m in per_pack.items():
        if m["status"] == "live" or not with_tokens:
            continue
        if time.monotonic() - started >= budget_s:
            tokens["budget_skipped"] += 1
            continue
        # result.json carries wall_seconds + token usage + verdict
        try:
            res = json.loads(cat(f"{remote}/packs/{name}/out/result.json"))
        except Exception:
            continue
        if not isinstance(res, dict):
            continue
        tokens["result_files"] += 1
        # pack-era results carry verified:true; executor-contract
        # results carry verdict:pass — both mean the independent
        # verifier passed
        if res.get("verified") or res.get("verdict") == "pass":
            tokens["verified"] += 1
        else:
            tokens["unverified"] += 1
        usage = res.get("usage") if isinstance(res.get("usage"), dict) \
            else res
        tokens["eval_count_total"] += int(usage.get("eval_count") or 0)
        tokens["eval_duration_s_total"] += (
            usage.get("eval_duration") or 0) / 1e9
        tokens["load_duration_s_total"] += (
            usage.get("load_duration") or 0) / 1e9
        if res.get("wall_seconds") is not None:
            walls.append(float(res["wall_seconds"]))
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "remote": remote,
        "packs": {"total": len(per_pack), **counts},
        # intervention = packs that need a human: terminal contract
        # failures plus packs currently held on a fallback marker
        "interventions": counts["failed"] + counts["fallback"],
        "queue_wait_seconds": _stats(waits),
        # staged->terminal latency: claim files are released on close,
        # so queue_wait only sees still-claimed packs — latency_s is
        # the durable end-to-end measure
        "staged_to_done_seconds": _stats(latencies),
        "wall_seconds": _stats(walls),
    }
    if with_tokens:
        tokens["eval_duration_s_total"] = round(
            tokens["eval_duration_s_total"], 1)
        tokens["load_duration_s_total"] = round(
            tokens["load_duration_s_total"], 1)
        out["tokens"] = tokens
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--remote", default=REMOTE)
    p.add_argument("--tokens", action="store_true",
                   help="fetch each finished pack's result.json for "
                        "token/verifier stats (one rclone cat per pack)")
    p.add_argument("--budget-s", type=float, default=120.0)
    args = p.parse_args()
    print(json.dumps(collect(remote=args.remote,
                             with_tokens=args.tokens,
                             budget_s=args.budget_s),
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
