#!/usr/bin/env python3
"""A/B fixture bench for the kk-llm lane worker idle schedule.

Runs kk_mac_lane_worker.pass_once ticks against an IDENTICAL local-dir
queue fixture (rclone's local backend — no Drive, no kk-mac, no model)
in two modes:

  before  the worker as it stood before this change — materialized from
          `git merge-base HEAD origin/master` (plan-every-pass, flat
          30min retry, no quarantine)
  after   the working-tree worker (dirs-probe idle schedule, retries/
          accounting, escalating holds, quarantine, memory gate)

Every "remote op" is a real rclone subprocess against the fixture dir —
the counts are directly comparable. Drive-side request counts (measured
live: 27 HTTP requests for the recursive listing vs 5 for dirs-only)
are reported alongside in the summary doc.

Simulated time: pass_once(now=t0 + tick*60) — marker mtimes are real
file mtimes, so t0 is the fixture build time and one tick = one
simulated minute. claim() sleeps are patched out.

Usage: python3 evals/kk-mac-lane/idle_schedule_bench.py [--json OUT]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
TICK_S = 60

sys.path.insert(0, str(REPO))
import scripts.devnest.kk_mac_lane_worker as lw_new  # noqa: E402


def _legacy_module():
    """The pre-change worker from the merge base, loaded as a sibling
    module so its `import kk_mac_*` fallbacks resolve the real files."""
    base = subprocess.run(
        ["git", "merge-base", "HEAD", "origin/master"], cwd=REPO,
        capture_output=True, text=True, check=True).stdout.strip()
    src = subprocess.run(
        ["git", "show", f"{base}:scripts/devnest/kk_mac_lane_worker.py"],
        cwd=REPO, capture_output=True, text=True, check=True).stdout
    dst = REPO / "scripts" / "devnest" / "_bench_legacy_worker.py"
    dst.write_text(src)
    try:
        spec = importlib.util.spec_from_file_location(
            "kk_bench_legacy", dst)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        dst.unlink()
    return mod


GOOD_TASK = {"task_id": "fx-1", "task_class": "summary",
             "prompt": "summarize the staged evidence",
             "expect": {"facts": ["evidence"]}, "model": "qwen3:8b"}


def build_fixture(root: Path, spec: list) -> None:
    """spec entries: {name, state} where state in pending|done|failed|
    fallback — deterministic identical content across runs."""
    packs = root / "packs"
    for item in spec:
        p = packs / item["name"]
        (p / "inputs").mkdir(parents=True, exist_ok=True)
        (p / "pack.yml").write_text(f"name: {item['name']}\n")
        if item["state"] != "empty":
            (p / "inputs" / "task.json").write_text(json.dumps(GOOD_TASK))
        if item["state"] in ("done", "failed", "fallback"):
            (p / item["state"]).write_text(item.get("marker", "x"))
    (root).mkdir(parents=True, exist_ok=True)


def _count_remote(mod):
    """Wrap a worker module's NW ops with call counters (call-through —
    the real rclone still runs against the local fixture)."""
    ops = {"rc": 0, "rcat": 0}
    real_rc, real_rcat = mod.NW.rc, mod.NW.rcat

    def rc(*a, **k):
        ops["rc"] += 1
        return real_rc(*a, **k)

    def rcat(*a, **k):
        ops["rcat"] += 1
        return real_rcat(*a, **k)

    return ops, {"rc": rc, "rcat": rcat}


def run_scenario(mod, remote: Path, spec: list, ticks: int,
                 verdict_fn, extra_kwargs: dict, label: str):
    workdir = Path(tempfile.mkdtemp(prefix=f"kkbench-{label}-"))
    fixture = Path(tempfile.mkdtemp(prefix=f"kkbench-fix-{label}-"))
    build_fixture(fixture, spec)
    remote_root = str(fixture)  # contains packs/
    ops, wrap = _count_remote(mod)
    per_tick = []
    contract_calls = [0]

    def contract(env, taskdir=None):
        contract_calls[0] += 1
        return verdict_fn(env)

    t0 = time.time()
    with patch.object(mod.NW, "rc", side_effect=wrap["rc"]), \
         patch.object(mod.NW, "rcat", side_effect=wrap["rcat"]), \
         patch.object(mod.time, "sleep"), \
         patch.object(mod, "gate",
                      return_value={"eligible": True, "reasons": []}):
        for i in range(ticks):
            now = t0 + i * TICK_S
            real_start = time.time()
            t = time.process_time()
            rep = mod.pass_once(
                remote_root, host="local", worker=f"bench-{label}",
                workdir=str(workdir), max_packs=1, stale_claim_min=60,
                fallback_retry_min=30,
                drain_file=str(fixture / "drain-missing"),
                now=now, run_contract=contract, **extra_kwargs)
            # markers written this tick get the SIMULATED write time —
            # real file mtimes only age in real seconds, which would
            # make every new hold look instantly stale to the next tick.
            # Bounded both sides: files already stamped to a sim time
            # outside this real pass window must not be touched again.
            real_end = time.time() + 0.5
            for fp in Path(fixture).rglob("*"):
                try:
                    if fp.is_file() and real_start - 0.5 <= \
                            fp.stat().st_mtime <= real_end:
                        os.utime(fp, (now, now))
                except OSError:
                    pass
            per_tick.append({
                "tick": i, "cpu_ms": round(
                    (time.process_time() - t) * 1000, 1),
                "ops_rc": ops["rc"], "ops_rcat": ops["rcat"],
                "idle": rep.get("idle", False),
                "claimed": len(rep["claimed"]),
                "results": [(r["pack"], r["verdict"])
                            for r in rep["results"]]})
    shutil.rmtree(workdir, ignore_errors=True)
    shutil.rmtree(fixture, ignore_errors=True)
    return {"label": label, "ticks": ticks,
            "remote_rc": ops["rc"], "remote_rcat": ops["rcat"],
            "contract_runs": contract_calls[0],
            "total_cpu_ms": round(sum(t["cpu_ms"] for t in per_tick), 1),
            "per_tick": per_tick}


def summarize(res: dict) -> dict:
    idle_ticks = sum(1 for t in res["per_tick"] if t["idle"])
    return {"label": res["label"], "ticks": res["ticks"],
            "remote_ops": res["remote_rc"] + res["remote_rcat"],
            "contract_runs": res["contract_runs"],
            "idle_ticks": idle_ticks,
            "total_cpu_ms": res["total_cpu_ms"],
            "avg_cpu_ms_per_tick":
                round(res["total_cpu_ms"] / res["ticks"], 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    legacy = _legacy_module()
    report = {"scenarios": {}, "note": (
        "remote_ops = real rclone invocations vs a local fixture; on "
        "gdrive the recursive inventory is 27 HTTPS requests vs 5 for "
        "the dirs-only probe (measured live 2026-11-23).")}

    # S1: quiet queue — 20 terminal packs + 5 fresh fallback holds,
    # 12 ticks (~12min inside one rescan window)
    spec_quiet = (
        [{"name": f"done-{i:02d}", "state": "done"}
         for i in range(20)] +
        [{"name": f"held-{i}", "state": "fallback",
          "marker": json.dumps({"at": int(time.time()), "worker": "w",
                                "reasons": ["memory_pressure_abort"]})}
         for i in range(5)])
    report["scenarios"]["quiet_queue"] = {
        "spec": "20 done + 5 fresh fallback holds, 12 ticks",
        "before": summarize(run_scenario(
            legacy, None, spec_quiet, 12,
            lambda e: {"verdict": "pass", "reasons": []}, {},
            "before")),
        "after": summarize(run_scenario(
            lw_new, None, spec_quiet, 12,
            lambda e: {"verdict": "pass", "reasons": []}, {},
            "after")),
    }

    # S2: deterministic pack fault — invalid_output forever.
    # 130 ticks (~2.2h): legacy retries every flat 30min hold; the new
    # policy quarantines on the 2nd fault.
    spec_fault = [{"name": "faulty-1", "state": "pending"}]
    fault = lambda e: {"verdict": "fallback",   # noqa: E731
                       "reasons": ["invalid_output:fact:x"],
                       "wall_seconds": 0.2}
    report["scenarios"]["fault_loop"] = {
        "spec": "1 pack, invalid_output every run, 130 ticks (~2.2h)",
        "before": summarize(run_scenario(
            legacy, None, spec_fault, 130, fault, {}, "before")),
        "after": summarize(run_scenario(
            lw_new, None, spec_fault, 130, fault, {}, "after")),
    }

    # S3: lane-condition abort — memory_pressure forever.
    # 400 ticks (~6.7h): legacy retries every 30min (~13 runs); the new
    # policy escalates holds (30/60/120/240...) and quarantines at 6.
    spec_cond = [{"name": "cond-1", "state": "pending"}]
    cond = lambda e: {"verdict": "fallback",   # noqa: E731
                      "reasons": ["memory_pressure_abort:13%<50%"],
                      "wall_seconds": 0.2}
    report["scenarios"]["cond_loop"] = {
        "spec": "1 pack, memory abort every run, 400 ticks (~6.7h)",
        "before": summarize(run_scenario(
            legacy, None, spec_cond, 400, cond, {}, "before")),
        "after": summarize(run_scenario(
            lw_new, None, spec_cond, 400, cond, {}, "after")),
    }

    text = json.dumps(report, indent=1)
    print(text)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
