#!/usr/bin/env python3
"""Dedicated KK-Mac LLM Nest lane worker (card kk-mac-continuous-llm-worker).

Consumes ONLY bounded read-only LLM task packs from the dedicated queue
(default gdrive:ada-nest/kk-llm) — never the generic GPU/video/coding
packs on the parent ada-nest remote, and never a pack whose
inputs/task.json fails the bounded-class check. Runs on KK-Mac under
launchd (net.adanest.kk-llm-worker) with --host local, or on any fleet
host for a supervised soak with --host kk-mac (ssh path).

One pass:

  gate    drain switch (DEVNEST_KK_MAC_ENABLED=false or --drain-file),
          then fitness: on-host -> kk_mac_admission.local_snapshot()
          (ollama + load + disk + temp + tmux/owner-busy, local ground
          truth); off-host -> the MDDB heartbeat snapshot(). A deny
          exits clean — queued packs are left for a later pass, no
          claims are made.
  claim   first-writer-wins claim file over rclone, same protocol as
          scripts/ada/nest-worker.py (imported — do not fork it). At
          most --max-packs per pass (default 1; the capacity procedure
          allows 2 only after a realistic two-request test).
  run     the canonical executor contract: kk_mac_executor.run_contract
          — heartbeat admission + memory guard + bounded model call +
          independent verifier. No shell, no pack run:/run_sh code is
          ever executed in this lane.
  close   verdict pass -> done; contract violation -> failed;
          lane-condition or invalid output -> fallback marker + claim
          release (held, retried after --fallback-retry-min, never a
          hot-loop, never blocks other lanes). Claims are always
          released; stale claims (> --stale-claim-min) are released for
          the queue.

Usage: kk_mac_lane_worker.py [--remote R] [--host kk-mac|local]
       [--workdir DIR] [--max-packs 1|2] [--scan-only]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pack.yml is optional for the LLM lane
    yaml = None

if __package__:
    from . import kk_mac_admission
    from . import kk_mac_executor
    from . import kk_mac_llm
else:  # direct script execution (launchd / manual soak)
    _d = str(Path(__file__).resolve().parent)
    if _d not in sys.path:
        sys.path.insert(0, _d)
    import kk_mac_admission
    import kk_mac_executor
    import kk_mac_llm

DEFAULT_REMOTE = "gdrive:ada-nest/kk-llm"
DEFAULT_WORKDIR = os.path.expanduser("~/.cache/kk-llm-worker")
DEFAULT_DRAIN = os.path.expanduser("~/.cache/kk-llm-worker.drain")
STALE_CLAIM_MIN = 60
FALLBACK_RETRY_MIN = 30
MAX_PACKS_HARD_LIMIT = 2
CLAIM_SETTLE_S = 3


def _load_nest_worker():
    """The claim/inventory protocol is shared with the Colab queue and
    fleet nest-workers — reuse it, don't fork it."""
    path = Path(__file__).resolve().parents[1] / "ada" / "nest-worker.py"
    spec = importlib.util.spec_from_file_location("nest_worker", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NW = _load_nest_worker()


def say(msg: str) -> None:
    print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)


def gate(*, host: str, drain_file: str, environ: dict | None = None
         ) -> dict:
    """Worker-level fitness check taken before any claim. env kill
    switch and drain file deny instantly; then local ground truth when
    the worker IS the node, heartbeat snapshot when it is orchestrating
    the node remotely."""
    env = os.environ if environ is None else environ
    if env.get("DEVNEST_KK_MAC_ENABLED", "true").lower() != "true":
        return {"eligible": False, "lane": "kk_mac_local",
                "reasons": ["kk_disabled"], "source": "drain"}
    if drain_file and os.path.exists(drain_file):
        return {"eligible": False, "lane": "kk_mac_local",
                "reasons": ["drain_file"], "source": "drain"}
    try:
        if kk_mac_llm.is_local_host(host):
            return kk_mac_admission.local_snapshot(host=host)
        return kk_mac_admission.snapshot(host=host)
    except Exception as exc:
        return {"eligible": False, "lane": "kk_mac_local",
                "reasons": [f"gate_failed:{type(exc).__name__}"],
                "source": "probe"}


def plan(remote: str, *, now: float, stale_claim_min: int,
         fallback_retry_min: int, inventory: dict | None = None
         ) -> dict:
    """Queue discovery over one recursive inventory. Returns
    {candidates, stale_claims, stale_fallbacks, skipped}: candidates are
    pack names with pack.yml + inputs/task.json, no terminal marker, no
    live claim, no fresh fallback hold. Packs missing the LLM task
    signature are skipped — this worker never claims video/GPU/coding/
    destructive packs."""
    inv = NW.pack_inventory(remote) if inventory is None else inventory
    out = {"candidates": [], "stale_claims": [], "stale_fallbacks": [],
           "skipped": []}
    for d in sorted(inv):
        entries = inv[d]
        if "done" in entries or "failed" in entries:
            continue
        fb_ts = entries.get("fallback")
        claims = {rel.split("/", 1)[1]: ts
                  for rel, ts in entries.items()
                  if rel.startswith("claim/")}
        live = False
        for c, ts in claims.items():
            if ts is not None and now - ts > stale_claim_min * 60:
                out["stale_claims"].append((d, c, now - ts))
            else:
                live = True
        if live:
            continue
        if fb_ts is not None:
            age = now - fb_ts
            if age < fallback_retry_min * 60:
                out["skipped"].append(f"{d}:fallback_held:{age:.0f}s")
                continue
            out["stale_fallbacks"].append(d)
        if "pack.yml" not in entries:
            out["skipped"].append(f"{d}:no_pack_yml")
            continue
        if "inputs/task.json" not in entries:
            out["skipped"].append(f"{d}:not_llm_pack")
            continue
        out["candidates"].append(d)
    return out


def _load_task(text: str, pack: str) -> dict | None:
    """Pre-claim validation: an unreadable or unadmitted task.json is
    never claimed. Returns the task envelope or None."""
    try:
        task = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        say(f'{pack}: task.json unreadable — never claim')
        return None
    if not isinstance(task, dict):
        say(f'{pack}: task.json not an object — never claim')
        return None
    tc = str(task.get("task_class") or "")
    if tc not in kk_mac_llm.ALLOWED_TASKS:
        say(f'{pack}: task_class {tc!r} not admitted — never claim')
        return None
    prompt = str(task.get("prompt") or "")
    if not prompt.strip() or len(prompt) > kk_mac_llm.MAX_PROMPT_CHARS:
        say(f'{pack}: prompt missing/oversized — never claim')
        return None
    return task


def claim(remote: str, pack: str, worker: str,
          settle_s: float = CLAIM_SETTLE_S) -> bool:
    """First-writer-wins claim, identical semantics to nest-worker."""
    pdir = f'{remote}/packs/{pack}'
    if NW.lsf(f'{pdir}/claim'):
        return False  # claimed meanwhile
    NW.rcat(f'{pdir}/claim/{worker}', str(int(time.time())))
    time.sleep(settle_s)
    if sorted(NW.lsf(f'{pdir}/claim'))[0] != worker:
        NW.rc('deletefile', f'{pdir}/claim/{worker}', check=False)
        return False
    return True


def release(remote: str, pack: str, worker: str) -> None:
    NW.rc('deletefile', f'{remote}/packs/{pack}/claim/{worker}',
          check=False)


def run_pack(remote: str, pack: str, worker: str, *, host: str,
             workdir: str, run_contract=None) -> dict:
    """Claim -> sync down -> executor contract -> push back -> marker.

    The pack's own run/run_sh code is NEVER executed — the lane runs
    only the bounded executor contract on inputs/task.json."""
    run_contract = run_contract or kk_mac_executor.run_contract
    local = os.path.join(workdir, pack)
    if os.path.exists(local):
        shutil.rmtree(local)
    os.makedirs(local)
    r = NW.rc('copy', f'{remote}/packs/{pack}', local,
              '--exclude', 'claim/**', check=False)
    if r.returncode != 0:
        return {"verdict": "fallback",
                "reasons": [f"sync_down:{r.stderr.strip()[:150]}"]}
    try:
        spec = (yaml.safe_load(Path(local, "pack.yml").read_text())
                if yaml else {}) or {}
    except Exception:
        spec = {}
    task = _load_task(Path(local, "inputs/task.json").read_text(), pack)
    if task is None:
        return {"verdict": "failed",
                "reasons": ["task_invalid_post_claim"]}
    envelope = {
        "id": str(task.get("task_id") or pack),
        "card": str(task.get("card") or pack),
        "task_class": task["task_class"],
        "prompt": task["prompt"],
        "expect": task.get("expect") or {},
        "artifact": "",
        "model": str(task.get("model") or "qwen3:8b"),
        "format": task.get("format"),
        "think": task.get("think"),
        "host": host,
    }
    t0 = time.time()
    result = run_contract(envelope, taskdir=Path(local))
    result["wall_seconds"] = round(
        result.get("wall_seconds") or (time.time() - t0), 3)
    result["pack"] = pack
    result["worker"] = worker
    out = Path(local, "out")
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False, default=str)
        + "\n")
    NW.rc('copy', local, f'{remote}/packs/{pack}',
          '--exclude', 'claim/**', check=False)
    if result["verdict"] == "pass":
        ok, missing = NW.verify_artifacts(spec, remote)
        if not ok:
            result["verdict"] = "failed"
            result.setdefault("reasons", []).append(
                f"artifacts_missing:{missing}")
    return result


def pass_once(remote: str, *, host: str, worker: str, workdir: str,
              max_packs: int, stale_claim_min: int,
              fallback_retry_min: int, drain_file: str,
              scan_only: bool = False, now: float | None = None,
              run_contract=None) -> dict:
    now = time.time() if now is None else now
    report = {"remote": remote, "host": host, "worker": worker,
              "gate": None, "claimed": [], "held": [], "results": []}
    g = gate(host=host, drain_file=drain_file)
    report["gate"] = g
    if not g.get("eligible"):
        say(f'gate deny: {",".join(g.get("reasons") or ["?"])} '
            f'— pass skipped, queue untouched')
        return report
    try:
        p = plan(remote, now=now, stale_claim_min=stale_claim_min,
                 fallback_retry_min=fallback_retry_min)
    except Exception as exc:
        say(f'plan failed: {type(exc).__name__}:{exc} — pass skipped')
        report["plan_error"] = f'{type(exc).__name__}:{exc}'[:200]
        return report
    for d, c, age in p["stale_claims"]:
        say(f'{d}: releasing stale claim {c} ({age:.0f}s)')
        if not scan_only:
            NW.rc('deletefile', f'{remote}/packs/{d}/claim/{c}',
                  check=False)
    for d in p["stale_fallbacks"]:
        say(f'{d}: stale fallback hold — releasing for retry')
        if not scan_only:
            NW.rc('deletefile', f'{remote}/packs/{d}/fallback',
                  check=False)
    for s in p["skipped"]:
        say(f'{s} — skip')
    if scan_only:
        for d in p["candidates"]:
            say(f'{d}: pending')
        say('scan complete (no claims made)')
        return report
    for d in p["candidates"]:
        if len(report["claimed"]) >= max_packs:
            report["held"].append(d)
            break
        try:
            text = NW.cat(f'{remote}/packs/{d}/inputs/task.json')
            if _load_task(text, d) is None:
                continue
            if not claim(remote, d, worker):
                say(f'{d}: lost claim race — skip')
                continue
        except Exception as exc:
            # transient store errors must not kill the pass — the pack
            # simply stays queued for the next one
            say(f'{d}: pre-claim error '
                f'{type(exc).__name__}:{exc} — skip')
            continue
        say(f'{d}: CLAIMED — running')
        report["claimed"].append(d)
        try:
            res = run_pack(remote, d, worker, host=host,
                           workdir=workdir, run_contract=run_contract)
        except Exception as exc:
            res = {"verdict": "fallback",
                   "reasons": [f"worker_error:{type(exc).__name__}:"
                               f"{exc}"[:200]]}
        verdict = res.get("verdict")
        reasons = ",".join(res.get("reasons") or [])[:200]
        pdir = f'{remote}/packs/{d}'
        try:
            if verdict == "pass":
                NW.rcat(f'{pdir}/done',
                        f'{res.get("wall_seconds", "?")}s '
                        f'worker={worker} verdict=pass')
                say(f'{d}: DONE {res.get("wall_seconds")}s')
            elif verdict == "failed":
                NW.rcat(f'{pdir}/failed', f'{reasons} worker={worker}')
                say(f'{d}: FAIL {reasons}')
            else:
                NW.rcat(f'{pdir}/fallback',
                        json.dumps({"at": int(time.time()),
                                    "worker": worker,
                                    "reasons":
                                        res.get("reasons") or []}))
                say(f'{d}: FALLBACK {reasons} — held '
                    f'{fallback_retry_min}min')
        except Exception as exc:
            # marker write failed — the claim residue expires via
            # stale-claim recovery, the pack is not lost
            say(f'{d}: marker write failed '
                f'{type(exc).__name__}:{exc}')
        try:
            release(remote, d, worker)
        except Exception:
            pass
        report["results"].append(
            {"pack": d, "verdict": verdict,
             "reasons": res.get("reasons") or [],
             "wall_seconds": res.get("wall_seconds")})
    say('pass complete')
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--remote', default=DEFAULT_REMOTE)
    ap.add_argument('--host', default='local',
                    help='LLM target: local (on KK-Mac) or an ssh alias '
                         'like kk-mac for supervised fleet-side runs')
    ap.add_argument('--workdir', default=DEFAULT_WORKDIR)
    ap.add_argument('--drain-file', default=DEFAULT_DRAIN,
                    help='exists -> admit nothing (drain switch)')
    ap.add_argument('--max-packs', type=int, default=1)
    ap.add_argument('--stale-claim-min', type=int,
                    default=STALE_CLAIM_MIN)
    ap.add_argument('--fallback-retry-min', type=int,
                    default=FALLBACK_RETRY_MIN)
    ap.add_argument('--scan-only', action='store_true')
    args = ap.parse_args()
    max_packs = max(1, min(args.max_packs, MAX_PACKS_HARD_LIMIT))
    host = socket.gethostname()
    worker = f'kkllm-{host}-{os.getpid()}'
    os.makedirs(args.workdir, exist_ok=True)
    rep = pass_once(args.remote, host=args.host, worker=worker,
                    workdir=args.workdir, max_packs=max_packs,
                    stale_claim_min=args.stale_claim_min,
                    fallback_retry_min=args.fallback_retry_min,
                    drain_file=args.drain_file,
                    scan_only=args.scan_only)
    done = sum(1 for r in rep["results"] if r["verdict"] == "pass")
    held = sum(1 for r in rep["results"] if r["verdict"] == "fallback")
    failed = sum(1 for r in rep["results"] if r["verdict"] == "failed")
    say(f'metrics pass: claimed={len(rep["claimed"])} done={done} '
        f'fallback={held} failed={failed} '
        f'gate={rep["gate"].get("eligible")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
