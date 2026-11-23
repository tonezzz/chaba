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
          hot-loop, never blocks other lanes). Each fallback also lands
          a retries/<n>-<fault|cond> marker: pack faults quarantine to
          `failed` after FAULT_QUARANTINE_AT, any pack after
          RETRY_QUARANTINE_AT, and holds escalate to RETRY_HOLD_CAP_MIN.
          Claims are always released; stale claims (> --stale-claim-min)
          are released for the queue.
  idle    between ticks the worker keeps <workdir>/idle.json: when no
          timer is due it does one dirs-only probe instead of the full
          recursive plan. --no-idle-schedule restores plan-per-pass.

Usage: kk_mac_lane_worker.py [--remote R] [--host kk-mac|local]
       [--workdir DIR] [--max-packs 1|2] [--scan-only]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
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
    from . import kk_mac_memory
else:  # direct script execution (launchd / manual soak)
    _d = str(Path(__file__).resolve().parent)
    if _d not in sys.path:
        sys.path.insert(0, _d)
    import kk_mac_admission
    import kk_mac_executor
    import kk_mac_llm
    import kk_mac_memory

DEFAULT_REMOTE = "gdrive:ada-nest/kk-llm"
DEFAULT_WORKDIR = os.path.expanduser("~/.cache/kk-llm-worker")
DEFAULT_DRAIN = os.path.expanduser("~/.cache/kk-llm-worker.drain")
STALE_CLAIM_MIN = 60
FALLBACK_RETRY_MIN = 30
MAX_PACKS_HARD_LIMIT = 2
CLAIM_SETTLE_S = 3

# Retry accounting: every fallback hold also lands a `retries/<n>-<kind>`
# marker so the attempt count is visible in the plain inventory listing —
# no extra reads to enforce the quarantine policy.
RETRY_MARKER_RE = re.compile(r"^retries/(\d+)-(fault|cond)$")
# Reasons caused by the pack/task itself (deterministic re-failure) vs
# lane conditions (node busy, memory pressure, store errors) that clear
# on their own. Pack faults quarantine fast; conditions retry longer.
PACK_FAULT_PREFIXES = ("invalid_output", "task_invalid",
                       "artifacts_missing")
FAULT_QUARANTINE_AT = 2     # pack-fault fallbacks before terminal quarantine
RETRY_QUARANTINE_AT = 6     # any fallbacks before terminal quarantine
RETRY_HOLD_CAP_MIN = 240    # escalating hold ceiling per pack

# Idle scheduling: the launchd tick stays cheap. Each pass either runs a
# full recursive plan or a ~5-request dirs-only probe; state lives in
# <workdir>/idle.json. next_scan is computed from real timers (fallback
# hold expiries, claim staleness, a forced-rescan bound), so held work
# is retried the pass after its hold expires — never earlier, never
# forgotten.
IDLE_STATE_FILE = "idle.json"
PROBE_BASE_S = 60.0
PROBE_MAX_S = 300.0         # cheap-probe stretch cap between full scans
RESCAN_MAX_S = 900.0        # bound: full plan at least this often
PROBE_ERR_MAX_S = 900.0     # error backoff cap for the cheap probe


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
            snap = kk_mac_admission.local_snapshot(host=host)
            # Owner-capacity floor: when the host is already memory-
            # pressured there is no point claiming a pack only to have
            # the executor's own memory guard abort it — that is the
            # claim->sync->abort->hold churn observed 2026-11-23. A
            # failed sample stays silent here; the contract still fails
            # closed at run time. DEVNEST_KK_MAC_MEM_GATE=false opts out.
            if snap.get("eligible") and str(env.get(
                    "DEVNEST_KK_MAC_MEM_GATE", "true")).lower() == "true":
                try:
                    mem = kk_mac_memory.sample("local")
                except Exception:
                    mem = {"ok": False}
                snap["mem_free_pct"] = mem.get("free_pct")
                if mem.get("ok"):
                    reasons = snap.setdefault("reasons", [])
                    reasons += [
                        r for r in kk_mac_memory.evaluate(
                            mem, phase="pre")
                        if r not in reasons]
                    snap["eligible"] = not reasons
            return snap
        return kk_mac_admission.snapshot(host=host)
    except Exception as exc:
        return {"eligible": False, "lane": "kk_mac_local",
                "reasons": [f"gate_failed:{type(exc).__name__}"],
                "source": "probe"}


def _retry_counts(entries: dict) -> tuple[int, int]:
    """(total fallbacks, pack-fault fallbacks) from `retries/<n>-<kind>`
    markers already present in the inventory — no extra reads."""
    n = faults = 0
    for rel in entries:
        m = RETRY_MARKER_RE.match(rel)
        if m:
            n += 1
            faults += m.group(2) == "fault"
    return n, faults


def effective_hold_min(fallback_retry_min: int, retries_done: int) -> int:
    """Escalating hold for a pack that has already burned `retries_done`
    fallbacks: base, base, 2x, 4x, 8x … capped — a persistently failing
    pack backs off instead of hammering every retry window."""
    return int(min(fallback_retry_min * (2 ** max(retries_done - 1, 0)),
                   RETRY_HOLD_CAP_MIN))


def quarantined(retries_done: int, faults: int) -> str:
    """Non-empty reason string when a pack has exhausted its retries."""
    if faults >= FAULT_QUARANTINE_AT:
        return f"fault_retries={faults}"
    if retries_done >= RETRY_QUARANTINE_AT:
        return f"retries={retries_done}"
    return ""


def plan(remote: str, *, now: float, stale_claim_min: int,
         fallback_retry_min: int, inventory: dict | None = None
         ) -> dict:
    """Queue discovery over one recursive inventory. Returns
    {candidates, stale_claims, stale_fallbacks, quarantine, held,
    live_claim_stale_at, retry, dirs, skipped}: candidates are
    pack names with pack.yml + inputs/task.json, no terminal marker, no
    live claim, no fresh fallback hold. Packs missing the LLM task
    signature are skipped — this worker never claims video/GPU/coding/
    destructive packs. Packs whose retries/ markers already exceed the
    quarantine policy are routed to `quarantine` instead of retrying."""
    inv = NW.pack_inventory(remote) if inventory is None else inventory
    out = {"candidates": [], "stale_claims": [], "stale_fallbacks": [],
           "quarantine": [], "held": [], "live_claim_stale_at": [],
           "retry": {}, "dirs": set(inv), "skipped": []}
    for d in sorted(inv):
        entries = inv[d]
        if "done" in entries or "failed" in entries:
            continue
        retries_done, faults = _retry_counts(entries)
        if retries_done:
            out["retry"][d] = {"n": retries_done, "faults": faults}
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
                if ts is not None:
                    out["live_claim_stale_at"].append(
                        ts + stale_claim_min * 60)
        if live:
            continue
        why = quarantined(retries_done, faults)
        if why:
            out["quarantine"].append((d, why))
            continue
        if fb_ts is not None:
            hold_min = effective_hold_min(fallback_retry_min,
                                          retries_done)
            hold_until = fb_ts + hold_min * 60
            age = now - fb_ts
            if now < hold_until:
                out["held"].append((d, hold_until))
                out["skipped"].append(
                    f"{d}:fallback_held:{age:.0f}s<{hold_min}min")
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


def pack_dirs(remote: str) -> set:
    """Cheap queue index: one dirs-only listing (~5 Drive requests vs
    ~27 for the recursive inventory). Detects staged/removed pack dirs;
    marker-level changes are covered by the scheduled rescans."""
    r = NW.rc('lsf', f'{remote}/packs', '--dirs-only', check=False)
    if r.returncode != 0:
        raise RuntimeError(f'dirs probe: '
                           f'{(r.stderr or "").strip()[:150]}')
    return {l.strip().rstrip("/") for l in r.stdout.splitlines()
            if l.strip()}


def _idle_path(workdir: str) -> str:
    return os.path.join(workdir, IDLE_STATE_FILE)


def _idle_load(workdir: str) -> dict:
    try:
        with open(_idle_path(workdir)) as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def _idle_save(workdir: str, st: dict) -> None:
    try:
        os.makedirs(workdir, exist_ok=True)
        tmp = _idle_path(workdir) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.replace(tmp, _idle_path(workdir))
    except OSError:
        pass


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
              '--exclude', 'claim/**', '--exclude', 'retries/**',
              check=False)
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


def _record_fallback(remote: str, d: str, worker: str, reasons: list,
                     retry: dict, fallback_retry_min: int) -> dict:
    """Write the retry marker + fallback hold for one pack. Returns
    {action, kind, n, hold_min, quarantine_reason} — quarantine_reason
    set means the pack exhausted its policy and the caller writes
    `failed` instead of `fallback`."""
    prev = (retry or {}).get(d) or {"n": 0, "faults": 0}
    kind = ("fault" if any(str(r).startswith(PACK_FAULT_PREFIXES)
                           for r in reasons or []) else "cond")
    n = prev["n"] + 1
    faults = prev["faults"] + (kind == "fault")
    why = quarantined(n, faults)
    pdir = f'{remote}/packs/{d}'
    NW.rcat(f'{pdir}/retries/{n}-{kind}', '')
    if why:
        return {"action": "quarantine", "kind": kind, "n": n,
                "faults": faults, "hold_min": 0,
                "quarantine_reason": why}
    hold_min = effective_hold_min(fallback_retry_min, n)
    NW.rcat(f'{pdir}/fallback',
            json.dumps({"at": int(time.time()), "worker": worker,
                        "reasons": reasons or [], "attempts": n,
                        "kind": kind, "hold_min": hold_min}))
    return {"action": "hold", "kind": kind, "n": n, "faults": faults,
            "hold_min": hold_min, "quarantine_reason": ""}


def pass_once(remote: str, *, host: str, worker: str, workdir: str,
              max_packs: int, stale_claim_min: int,
              fallback_retry_min: int, drain_file: str,
              scan_only: bool = False, now: float | None = None,
              run_contract=None, idle_schedule: bool = True,
              probe_max_s: float = PROBE_MAX_S,
              rescan_max_s: float = RESCAN_MAX_S) -> dict:
    now = time.time() if now is None else now
    report = {"remote": remote, "host": host, "worker": worker,
              "gate": None, "claimed": [], "held": [], "results": [],
              "idle": False}
    g = gate(host=host, drain_file=drain_file)
    report["gate"] = g
    if not g.get("eligible"):
        say(f'gate deny: {",".join(g.get("reasons") or ["?"])} '
            f'— pass skipped, queue untouched')
        return report

    # Idle schedule: skip the recursive plan when nothing scheduled it.
    # A due full scan (hold expiry, claim staleness, forced rescan) runs
    # directly; otherwise one cheap dirs-only probe decides.
    st = _idle_load(workdir) if idle_schedule else {}
    if idle_schedule and not scan_only:
        due = now >= float(st.get("next_scan") or 0)
        if not due:
            if now < float(st.get("next_probe") or 0):
                report["idle"] = True
                say(f'idle: probe deferred '
                    f'{float(st["next_probe"]) - now:.0f}s')
                return report
            try:
                dirs = pack_dirs(remote)
            except Exception as exc:
                st["probe_err"] = int(st.get("probe_err") or 0) + 1
                st["next_probe"] = now + min(
                    PROBE_ERR_MAX_S,
                    PROBE_BASE_S * 2 ** min(st["probe_err"], 4))
                _idle_save(workdir, st)
                report["probe_error"] = \
                    f'{type(exc).__name__}:{exc}'[:200]
                say(f'dirs probe failed: {exc} — backing off')
                return report
            st["probe_err"] = 0
            if dirs == set(st.get("dirs") or []):
                st["unchanged"] = int(st.get("unchanged") or 0) + 1
                stretch = min(probe_max_s, PROBE_BASE_S *
                              2 ** min(st["unchanged"], 3))
                st["next_probe"] = now + stretch
                _idle_save(workdir, st)
                report["idle"] = True
                say(f'idle: {len(dirs)} pack dirs unchanged; '
                    f'next probe in {stretch:.0f}s')
                return report
            say('queue dir set changed — full scan')
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
    for d, why in p["quarantine"]:
        say(f'{d}: retry budget exhausted ({why}) — quarantining')
        if not scan_only:
            pdir = f'{remote}/packs/{d}'
            NW.rcat(f'{pdir}/failed',
                    f'quarantined:{why} worker={worker}')
            NW.rc('deletefile', f'{pdir}/fallback', check=False)
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
        reasons = res.get("reasons") or []
        reasons_str = ",".join(str(r) for r in reasons)[:200]
        pdir = f'{remote}/packs/{d}'
        try:
            if verdict == "pass":
                NW.rcat(f'{pdir}/done',
                        f'{res.get("wall_seconds", "?")}s '
                        f'worker={worker} verdict=pass')
                # done is terminal — retry history is just noise now
                NW.rc('delete', f'{pdir}/retries', check=False)
                say(f'{d}: DONE {res.get("wall_seconds")}s')
            elif verdict == "failed":
                NW.rcat(f'{pdir}/failed',
                        f'{reasons_str} worker={worker}')
                say(f'{d}: FAIL {reasons_str}')
            else:
                rec = _record_fallback(remote, d, worker, reasons,
                                       p.get("retry") or {},
                                       fallback_retry_min)
                if rec["action"] == "quarantine":
                    verdict = "failed"
                    NW.rcat(f'{pdir}/failed',
                            f'quarantined:{rec["quarantine_reason"]} '
                            f'last={reasons_str} worker={worker}')
                    NW.rc('deletefile', f'{pdir}/fallback', check=False)
                    say(f'{d}: FAIL quarantined:'
                        f'{rec["quarantine_reason"]} ({reasons_str})')
                else:
                    say(f'{d}: FALLBACK {reasons_str} '
                        f'— attempt {rec["n"]}, held {rec["hold_min"]}min')
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
    if idle_schedule and not scan_only:
        wakeups = [now + rescan_max_s]
        wakeups += [t for _, t in p["held"]]
        wakeups += p["live_claim_stale_at"]
        if report["claimed"] or report["held"]:
            # work is flowing or queued behind max_packs — the next tick
            # plans again immediately (serial drain is unchanged)
            st["next_scan"] = 0
        else:
            st["next_scan"] = min(wakeups)
        st["dirs"] = sorted(p["dirs"])
        st["unchanged"] = 0
        st["next_probe"] = now + PROBE_BASE_S
        _idle_save(workdir, st)
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
    ap.add_argument('--no-idle-schedule', action='store_true',
                    help='rollback: full recursive plan every pass '
                         '(pre-idle-schedule behaviour)')
    ap.add_argument('--probe-max-s', type=float, default=PROBE_MAX_S,
                    help='cap for the cheap dirs-probe stretch')
    ap.add_argument('--rescan-max-s', type=float, default=RESCAN_MAX_S,
                    help='bound: full queue plan at least this often')
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
                    scan_only=args.scan_only,
                    idle_schedule=not args.no_idle_schedule,
                    probe_max_s=args.probe_max_s,
                    rescan_max_s=args.rescan_max_s)
    done = sum(1 for r in rep["results"] if r["verdict"] == "pass")
    held = sum(1 for r in rep["results"] if r["verdict"] == "fallback")
    failed = sum(1 for r in rep["results"] if r["verdict"] == "failed")
    say(f'metrics pass: claimed={len(rep["claimed"])} done={done} '
        f'fallback={held} failed={failed} '
        f'gate={rep["gate"].get("eligible")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
