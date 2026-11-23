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
          release (held, retried after an exponential hold starting at
          --fallback-retry-min capped by --fallback-retry-max-min,
          never a hot-loop, never blocks other lanes). The fallback
          marker doubles as the retry ledger — packs that exhaust
          --max-fallback-attempts are quarantined: a `quarantine`
          audit file + terminal `failed` marker are written so old
          failed work cannot cause repeated retry bursts. Claims are
          always released; stale claims (> --stale-claim-min) are
          released for the queue.

  idle    launchd ticks every StartInterval (60s). Between full passes
          the worker keeps idle-state.json in the workdir: while a
          pass is not yet due it makes ONE cheap non-recursive lsf tip
          check (pack-dir name signature) — unchanged signature means
          the tick exits without gate probes or the recursive
          inventory. Idle gaps double 60->120->... up to
          --idle-backoff-max-s (default 600s, 0 disables); any claim,
          held pack, or changed queue tip resets the backoff.

Usage: kk_mac_lane_worker.py [--remote R] [--host kk-mac|local]
       [--workdir DIR] [--max-packs 1|2] [--scan-only]
       [--idle-backoff-max-s 600] [--fallback-retry-max-min 240]
       [--max-fallback-attempts 5]
"""
from __future__ import annotations

import argparse
import hashlib
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
FALLBACK_RETRY_MAX_MIN = 240
MAX_FALLBACK_ATTEMPTS = 5
IDLE_BACKOFF_BASE_S = 60
IDLE_BACKOFF_MAX_S = 600
IDLE_STATE_NAME = "idle-state.json"
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


def _sig(names) -> str:
    """Stable signature of the pack-dir names — the cheap queue tip."""
    return hashlib.sha1(
        "\n".join(sorted(names)).encode()).hexdigest()[:16]


def packs_tip_signature(remote: str) -> str:
    """One non-recursive rclone call: names directly under packs/ — the
    idle governor's queue-notification index. Name changes (pack staged
    or removed) wake the worker early; content arriving inside an
    existing dir is caught at the next due pass (bounded staleness)."""
    return _sig(NW.lsf(f'{remote}/packs'))


def _idle_state_path(workdir: str) -> str:
    return os.path.join(workdir, IDLE_STATE_NAME)


def load_idle_state(workdir: str) -> dict:
    try:
        d = json.loads(Path(_idle_state_path(workdir)).read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_idle_state(workdir: str, state: dict) -> None:
    try:
        os.makedirs(workdir, exist_ok=True)
        tmp = _idle_state_path(workdir) + ".tmp"
        Path(tmp).write_text(json.dumps(state) + "\n")
        os.replace(tmp, _idle_state_path(workdir))
    except Exception as exc:
        say(f'idle state write failed: {type(exc).__name__}:{exc}')


def idle_delay_s(consecutive_idle: int, *, max_s: int) -> int:
    """Bounded exponential gap between full passes while the queue is
    idle: base 60s doubling to max_s. n<=0 means 'due now'."""
    if consecutive_idle <= 0:
        return 0
    return min(max_s, IDLE_BACKOFF_BASE_S
               * (1 << min(consecutive_idle - 1, 10)))


def _fallback_attempt(text: str) -> int:
    """attempt count from a fallback marker body; unreadable or legacy
    plain-text markers count as attempt 1 (pre-ledger holds)."""
    try:
        d = json.loads(text or "")
        return max(1, int(d.get("attempt") or 1))
    except (TypeError, ValueError, AttributeError):
        return 1


def fallback_hold_min(attempt: int, *, retry_min: int,
                      retry_max_min: int | None = None) -> float:
    """Hold before a pack with `attempt` recorded fallbacks may retry:
    retry_min * 2^(attempt-1), capped at retry_max_min."""
    hold = retry_min * (1 << min(max(attempt - 1, 0), 10))
    if retry_max_min:
        hold = min(hold, retry_max_min)
    return float(hold)


def governor_check(remote: str, workdir: str, idle_max_s: int,
                   now: float | None = None) -> bool:
    """True when this launchd tick may exit without a full pass: a
    pass is not yet due AND the cheap queue-tip signature is
    unchanged. Every failure path falls back to running a full pass —
    the governor can only ever cost latency, never lose work."""
    if idle_max_s <= 0:
        return False
    now = time.time() if now is None else now
    state = load_idle_state(workdir)
    due = float(state.get("next_due") or 0)
    if now >= due:
        return False
    try:
        tip = packs_tip_signature(remote)
    except Exception as exc:
        say(f'tip check failed {type(exc).__name__}:{exc} — running '
            f'full pass')
        return False
    if tip == state.get("queue_sig"):
        say(f'idle backoff: queue tip unchanged — next full pass in '
            f'{due - now:.0f}s')
        return True
    say('idle backoff: queue tip changed — running full pass now')
    return False


def governor_record(remote: str, workdir: str, idle_max_s: int,
                    rep: dict) -> None:
    """Update idle-state.json after a pass: any claimed or still-held
    (pending-beyond-max_packs) pack resets the backoff so drain
    cadence under load is unchanged; an idle pass doubles the gap to
    the next full pass up to idle_max_s."""
    if idle_max_s <= 0:
        return
    if rep["claimed"] or rep["held"]:
        state = {"consecutive_idle": 0, "next_due": 0}
    else:
        state = load_idle_state(workdir)
        n = int(state.get("consecutive_idle") or 0) + 1
        state["consecutive_idle"] = n
        state["next_due"] = (time.time()
                             + idle_delay_s(n, max_s=idle_max_s))
    try:
        state["queue_sig"] = (rep.get("queue_sig")
                              or packs_tip_signature(remote))
    except Exception:
        pass  # a stale signature only wakes the next pass early
    state["last_pass_at"] = int(time.time())
    save_idle_state(workdir, state)


def gate(*, host: str, drain_file: str, environ: dict | None = None,
         quiet_hours: str | None = None, now: float | None = None
         ) -> dict:
    """Worker-level fitness check taken before any claim. env kill
    switch, drain file, and the configured quiet-hours window
    (DEVNEST_KK_MAC_QUIET_HOURS="HH:MM-HH:MM", kk-mac local time) deny
    instantly; then local ground truth when the worker IS the node,
    heartbeat snapshot when it is orchestrating the node remotely."""
    env = os.environ if environ is None else environ
    if env.get("DEVNEST_KK_MAC_ENABLED", "true").lower() != "true":
        return {"eligible": False, "lane": "kk_mac_local",
                "reasons": ["kk_disabled"], "source": "drain"}
    if drain_file and os.path.exists(drain_file):
        return {"eligible": False, "lane": "kk_mac_local",
                "reasons": ["drain_file"], "source": "drain"}
    win = env.get("DEVNEST_KK_MAC_QUIET_HOURS", "") \
        if quiet_hours is None else quiet_hours
    if str(win or "").strip():
        qh = kk_mac_admission.quiet_hours_active(str(win), now=now)
        if qh is not False:
            return {"eligible": False, "lane": "kk_mac_local",
                    "reasons": ["quiet_hours" if qh else
                                "quiet_hours_malformed"],
                    "source": "quiet_hours"}
    try:
        if kk_mac_llm.is_local_host(host):
            return kk_mac_admission.local_snapshot(host=host)
        return kk_mac_admission.snapshot(host=host)
    except Exception as exc:
        return {"eligible": False, "lane": "kk_mac_local",
                "reasons": [f"gate_failed:{type(exc).__name__}"],
                "source": "probe"}


def plan(remote: str, *, now: float, stale_claim_min: int,
         fallback_retry_min: int, inventory: dict | None = None,
         marker_reader=None, fallback_retry_max_min: int | None = None,
         max_fallback_attempts: int = 0) -> dict:
    """Queue discovery over one recursive inventory. Returns
    {candidates, stale_claims, stale_fallbacks, quarantined,
    fallback_attempts, skipped, signature}: candidates are pack names
    with pack.yml + inputs/task.json, no terminal marker, no live
    claim, no active fallback hold. Packs missing the LLM task
    signature are skipped — this worker never claims video/GPU/coding/
    destructive packs.

    A `quarantine` marker is terminal like done/failed. A fallback
    marker holds the pack for fallback_hold_min(attempt) — exponential
    per recorded attempt (marker_reader supplies marker bodies; without
    it every hold counts as attempt 1, the pre-ledger behaviour). At
    max_fallback_attempts the pack is listed in `quarantined` for the
    caller to park terminally; 0 disables quarantine (retry forever,
    the old behaviour)."""
    inv = NW.pack_inventory(remote) if inventory is None else inventory
    out = {"candidates": [], "stale_claims": [], "stale_fallbacks": [],
           "quarantined": [], "fallback_attempts": {}, "skipped": [],
           "signature": _sig(inv)}
    for d in sorted(inv):
        entries = inv[d]
        if ("done" in entries or "failed" in entries
                or "quarantine" in entries):
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
            attempt = (_fallback_attempt(marker_reader(d))
                       if marker_reader else 1)
            out["fallback_attempts"][d] = attempt
            if max_fallback_attempts and attempt >= max_fallback_attempts:
                out["quarantined"].append(d)
                continue
            age = now - fb_ts
            hold = fallback_hold_min(
                attempt, retry_min=fallback_retry_min,
                retry_max_min=fallback_retry_max_min) * 60
            if age < hold:
                out["skipped"].append(
                    f"{d}:fallback_held:{age:.0f}s:a{attempt}")
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
        "model": str(task.get("model") or "qwen2.5:32b"),
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
              run_contract=None, fallback_retry_max_min: int | None = None,
              max_fallback_attempts: int = 0) -> dict:
    now = time.time() if now is None else now
    report = {"remote": remote, "host": host, "worker": worker,
              "gate": None, "claimed": [], "held": [], "results": [],
              "quarantined": [], "queue_sig": None}
    g = gate(host=host, drain_file=drain_file)
    report["gate"] = g
    if not g.get("eligible"):
        say(f'gate deny: {",".join(g.get("reasons") or ["?"])} '
            f'— pass skipped, queue untouched')
        return report
    try:
        p = plan(remote, now=now, stale_claim_min=stale_claim_min,
                 fallback_retry_min=fallback_retry_min,
                 marker_reader=(
                     None if scan_only else
                     lambda d: NW.cat(f'{remote}/packs/{d}/fallback')),
                 fallback_retry_max_min=fallback_retry_max_min,
                 max_fallback_attempts=max_fallback_attempts)
        report["queue_sig"] = p.get("signature")
    except Exception as exc:
        say(f'plan failed: {type(exc).__name__}:{exc} — pass skipped')
        report["plan_error"] = f'{type(exc).__name__}:{exc}'[:200]
        return report
    for d, c, age in p["stale_claims"]:
        say(f'{d}: releasing stale claim {c} ({age:.0f}s)')
        if not scan_only:
            NW.rc('deletefile', f'{remote}/packs/{d}/claim/{c}',
                  check=False)
    for d in p["quarantined"]:
        n = p["fallback_attempts"].get(d, "?")
        say(f'{d}: fallback attempts exhausted ({n}) — quarantining')
        report["quarantined"].append(d)
        if scan_only:
            continue
        pdir = f'{remote}/packs/{d}'
        try:
            last = {}
            try:
                last = json.loads(NW.cat(f'{pdir}/fallback') or "{}")
            except (TypeError, ValueError):
                last = {}
            NW.rcat(f'{pdir}/quarantine', json.dumps(
                {"at": int(time.time()), "worker": worker,
                 "attempts": n,
                 "last_reasons": last.get("reasons") or []}))
            NW.rcat(f'{pdir}/failed',
                    f'quarantine:max_fallback_attempts={n} '
                    f'worker={worker}')
            NW.rc('deletefile', f'{pdir}/fallback', check=False)
        except Exception as exc:
            # marker failure is not fatal — the stale-claim/stale-
            # fallback recovery paths still bound this pack
            say(f'{d}: quarantine write failed '
                f'{type(exc).__name__}:{exc}')
    for d in p["stale_fallbacks"]:
        # the fallback marker is the retry ledger — it is NOT deleted
        # for retry, so the attempt count survives into the next run
        say(f'{d}: fallback retry due (attempt '
            f'{p["fallback_attempts"].get(d, "?")}) — eligible again')
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
                NW.rc('deletefile', f'{pdir}/fallback', check=False)
                say(f'{d}: DONE {res.get("wall_seconds")}s')
            elif verdict == "failed":
                NW.rcat(f'{pdir}/failed', f'{reasons} worker={worker}')
                NW.rc('deletefile', f'{pdir}/fallback', check=False)
                say(f'{d}: FAIL {reasons}')
            else:
                prior = 0
                try:
                    prior = _fallback_attempt(
                        NW.cat(f'{pdir}/fallback'))
                except Exception:
                    prior = 0
                attempt = prior + 1
                NW.rcat(f'{pdir}/fallback',
                        json.dumps({"at": int(time.time()),
                                    "worker": worker,
                                    "attempt": attempt,
                                    "reasons":
                                        res.get("reasons") or []}))
                hold = fallback_hold_min(
                    attempt, retry_min=fallback_retry_min,
                    retry_max_min=fallback_retry_max_min)
                say(f'{d}: FALLBACK {reasons} — attempt {attempt}, '
                    f'held {hold:.0f}min')
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
    ap.add_argument('--fallback-retry-max-min', type=int,
                    default=FALLBACK_RETRY_MAX_MIN,
                    help='cap on the exponential fallback hold (min)')
    ap.add_argument('--max-fallback-attempts', type=int,
                    default=MAX_FALLBACK_ATTEMPTS,
                    help='fallbacks past this quarantine the pack; '
                         '0 retries forever (legacy behaviour)')
    ap.add_argument('--idle-backoff-max-s', type=int,
                    default=IDLE_BACKOFF_MAX_S,
                    help='cap on worker-side idle backoff between full '
                         'passes (seconds); 0 disables the governor')
    ap.add_argument('--scan-only', action='store_true')
    args = ap.parse_args()
    max_packs = max(1, min(args.max_packs, MAX_PACKS_HARD_LIMIT))
    host = socket.gethostname()
    worker = f'kkllm-{host}-{os.getpid()}'
    os.makedirs(args.workdir, exist_ok=True)

    # idle governor: launchd still ticks at StartInterval; between due
    # passes a non-due tick costs ONE non-recursive lsf tip check —
    # no gate probes (ollama/sysctl/statvfs/tmux), no recursive
    # inventory. A changed pack-name signature wakes the pass early.
    # scan-only is a measurement mode: it never touches idle state.
    idle_max = 0 if args.scan_only else max(0, args.idle_backoff_max_s)
    if governor_check(args.remote, args.workdir, idle_max):
        return 0

    rep = pass_once(args.remote, host=args.host, worker=worker,
                    workdir=args.workdir, max_packs=max_packs,
                    stale_claim_min=args.stale_claim_min,
                    fallback_retry_min=args.fallback_retry_min,
                    drain_file=args.drain_file,
                    scan_only=args.scan_only,
                    fallback_retry_max_min=args.fallback_retry_max_min,
                    max_fallback_attempts=args.max_fallback_attempts)

    governor_record(args.remote, args.workdir, idle_max, rep)
    done = sum(1 for r in rep["results"] if r["verdict"] == "pass")
    held = sum(1 for r in rep["results"] if r["verdict"] == "fallback")
    failed = sum(1 for r in rep["results"] if r["verdict"] == "failed")
    say(f'metrics pass: claimed={len(rep["claimed"])} done={done} '
        f'fallback={held} failed={failed} '
        f'gate={rep["gate"].get("eligible")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
