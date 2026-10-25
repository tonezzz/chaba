#!/usr/bin/env python3
# ada-nest GAP RUNNER — opportunistic GPU work inside main-queue prep gaps.
# Lives on Drive at ada-nest/queue/gap-runner.py; canonical source is
# scripts/colab/gap-runner.py in the chaba repo.
#
# The main queue (queue/runner.py) spends real wall time in CPU-bound prep
# phases (downloads, tar extracts, pip installs) while the GPU sits idle.
# This runner fills those gaps with small "gap packs" — it never starts a
# second main runner, never touches the main lease/claims/done space, and
# aborts the moment the main queue wants the GPU back.
#
# Eligibility — ALL must hold before a pack is claimed, re-checked mid-run:
#   1. queue/heartbeat is fresh (age <= GAP_STALE_S, default 60s)
#   2. heartbeat phase is 'prep' or 'prep-wait'
#   3. nvidia-smi reports >= pack.min_free_gpu_gb free VRAM
#   4. queue/gap-lease is free, stale, or already ours (one gap runner)
#   5. pack is unclaimed, has no done/failed marker, is not disabled
#
# Pack contract — gap-packs/<name>/pack.json (stdlib json; no yaml dep):
#   {"name": "...", "run": "<shell string>", "timeout_s": 120,
#    "min_free_gpu_gb": 1, "artifacts": ["gap-packs/<name>/out/*.json"],
#    "disabled": false}
#   run       — exec'd via `bash -lc` with GAP_PACK / GAP_OUT / NEST_ROOT in
#               env, cwd=/tmp, own process group.
#   timeout_s — hard kill of the whole process group (SIGTERM, SIGKILL +5s).
#   artifacts — globs vs ada-nest/ root; each must match >=1 non-empty file
#               before done-marking (same verify-before-mark rule as packs/).
#
# State (all inside gap-packs/ + queue/, never the main pack space):
#   gap-packs/<name>/claim/<worker>  first-writer-wins; claims older than
#                                    GAP_CLAIM_TTL (1h) are reapable
#   gap-packs/<name>/done            FILE marker (same shape as packs/)
#   gap-packs/<name>/failed          pack exited nonzero / artifacts missing;
#                                    skipped until an operator deletes it
#   gap-packs/<name>/out/gap.log     pack stdout+stderr
#   gap-packs/<name>/out/aborted.txt last window-abort reason (retries allowed)
#   queue/gap-lease                  {worker, pid, ts} — mutual exclusion
#   queue/gap-heartbeat              '<epoch> <worker> <pack|-> <state>'
#
# Forbidden in gap packs — enforced by a static scan of run/prep text AND
# documented in gap-packs/PROCEDURE.md: model pulls, HF/Drive cache writes,
# production index mutations, long agent loops, a second runner.py/lease.
# The scan is a seatbelt; pack authors are still responsible for the policy.
#
# Usage: one pass per invocation — wrap in the launcher cell
# (scripts/colab/gap-launcher-cell.py) which re-runs it every ~20s.
# A missed gap is always safe; contending with the main queue is not.
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get('NEST_ROOT', '/content/drive/MyDrive/ada-nest'))
Q = ROOT / 'queue'
PACKS = ROOT / 'gap-packs'
GAP_LEASE = Q / 'gap-lease'
GAP_HB = Q / 'gap-heartbeat'

STALE_S = float(os.environ.get('GAP_STALE_S', '60'))
LEASE_TTL = float(os.environ.get('GAP_LEASE_TTL', '180'))
CLAIM_TTL = float(os.environ.get('GAP_CLAIM_TTL', '3600'))
SETTLE_S = float(os.environ.get('GAP_SETTLE_S', '2'))
POLL_S = float(os.environ.get('GAP_POLL_S', '10'))
KILL_GRACE_S = 5
ALLOWED = {'prep', 'prep-wait'}

FORBIDDEN_RE = re.compile(
    r'ollama\s+pull|snapshot_download|hf_hub_download|huggingface-cli\s+download'
    r'|pip3?\s+install|apt(?:-get)?\s+install|git\s+clone'
    r'|ada-nest/cache|\.cache/huggingface|/queue/lease\b|runner\.py',
    re.IGNORECASE)

try:
    BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
except OSError:
    BOOT_ID = time.strftime('%Y%m%d-%H%M')
WORKER = f'gap-{BOOT_ID[:8]}-{os.getpid()}'


def say(msg):
    print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)


def heartbeat():
    """queue/heartbeat -> (age_s, job, phase). Missing/corrupt = stale."""
    try:
        p = (Q / 'heartbeat').read_text().split()
        return time.time() - float(p[0]), ' '.join(p[1:-1]), p[-1]
    except Exception:
        return float('inf'), '', ''


def window_open():
    """'' when the main queue is in a fresh prep/prep-wait gap."""
    age, _job, phase = heartbeat()
    if age > STALE_S:
        return f'main heartbeat stale ({age:.0f}s)'
    if phase not in ALLOWED:
        return f'main phase {phase or "?"}'
    return ''


def free_gpu_gb():
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=10)
        vals = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        return max(vals) / 1024 if vals else 0.0
    except Exception:
        return 0.0


# --- gap lease: separate from queue/lease, same write-and-remember lesson.
# Read-back is CONSERVATIVE here (opposite of the main runner): a missed gap
# is safe, so if we cannot confirm our own lease write we simply pass. ---

def read_gap_lease():
    try:
        d = json.loads(GAP_LEASE.read_text())
        return str(d.get('worker', '')), float(d.get('ts', 0))
    except Exception:
        return '', 0.0


def write_gap_lease():
    try:
        GAP_LEASE.write_text(json.dumps(
            {'worker': WORKER, 'pid': os.getpid(), 'ts': time.time()}))
    except OSError:
        pass


def acquire_lease():
    w, ts = read_gap_lease()
    if w == WORKER:
        write_gap_lease()                        # refresh, still ours
        return True
    if w and time.time() - ts < LEASE_TTL:
        say(f'gap-lease held by {w} ({time.time() - ts:.0f}s) — pass')
        return False
    write_gap_lease()                            # free/stale/corrupt -> take
    time.sleep(SETTLE_S)
    w, _ = read_gap_lease()
    if w == WORKER:
        return True
    say(f'gap-lease unconfirmed (read back {w or "nothing"}) — pass')
    return False


def lease_lost():
    w, _ = read_gap_lease()
    return bool(w) and w != WORKER


def release_lease():
    try:
        w, _ = read_gap_lease()
        if w in ('', WORKER):
            GAP_LEASE.unlink(missing_ok=True)
    except OSError:
        pass


def beat_gap(state, pack='-'):
    try:
        GAP_HB.write_text(f'{time.time():.0f} {WORKER} {pack} {state}\n')
    except OSError:
        pass


def load_spec(d):
    for cand in (d / 'pack.json', d / 'pack.yml'):
        if not cand.exists():
            continue
        try:
            if cand.suffix == '.json':
                spec = json.loads(cand.read_text())
            else:
                import yaml
                spec = yaml.safe_load(cand.read_text())
        except Exception as e:
            say(f'== {d.name}: SKIP bad {cand.name} ({e})')
            return None
        if isinstance(spec, dict) and spec.get('run'):
            spec.setdefault('name', d.name)
            return spec
        say(f'== {d.name}: SKIP {cand.name} missing run')
        return None
    return None


def claim(d):
    cdir = d / 'claim'
    cdir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for f in list(cdir.iterdir()):
        try:
            if now - f.stat().st_mtime > CLAIM_TTL:
                f.unlink()                       # reap stale claims
        except OSError:
            pass
    if any(cdir.iterdir()):
        return False
    (cdir / WORKER).write_text(f'{now:.0f}\n')
    time.sleep(SETTLE_S)
    try:
        return sorted(f.name for f in cdir.iterdir())[0] == WORKER
    except Exception:
        return False


def release_claim(d):
    try:
        (d / 'claim' / WORKER).unlink()
    except OSError:
        pass


def killpg(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=KILL_GRACE_S)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_pack(d, spec):
    """Run one pack under the live window; returns (state, rc).
    state: 'run' | 'aborted: <why>' | 'timeout'."""
    name = d.name
    outdir = d / 'out'
    outdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GAP_PACK=str(d), GAP_OUT=str(outdir),
               NEST_ROOT=str(ROOT))
    log = open(outdir / 'gap.log', 'ab')
    log.write(f'\n===== {time.strftime("%H:%M:%S")} gap run {WORKER} =====\n'
              .encode())
    log.flush()
    proc = subprocess.Popen(['bash', '-lc', spec['run']], env=env, cwd='/tmp',
                            stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    deadline = time.time() + int(spec.get('timeout_s') or 120)
    state = 'run'
    while proc.poll() is None:
        time.sleep(POLL_S)
        if lease_lost():
            state = 'aborted: gap-lease lost'
            break
        write_gap_lease()                        # hold liveness while we run
        why = window_open()
        if why:
            state = f'aborted: {why}'
            break
        if time.time() > deadline:
            state = 'timeout'
            break
        beat_gap('run', name)
    if state != 'run':
        killpg(proc)
    rc = proc.wait()
    log.close()
    return state, rc


def verify_artifacts(spec, timeout=60):
    """Every declared glob must match >=1 non-empty file (verify-before-mark)."""
    pats = spec.get('artifacts') or []
    if not pats:
        return True, 'no-artifacts-declared'
    deadline = time.time() + timeout
    while True:
        hits = {p: [f for f in glob.glob(str(ROOT / p))
                    if os.path.isfile(f) and os.path.getsize(f) > 0]
                for p in pats}
        missing = [p for p, m in hits.items() if not m]
        if not missing:
            return True, ' '.join(
                f'{p}={len(hits[p])}x'
                f'{sum(os.path.getsize(f) for f in hits[p])}B' for p in pats)
        if time.time() > deadline:
            return False, ' '.join(missing)
        time.sleep(5)


def main():
    if not PACKS.is_dir():
        say(f'no {PACKS} — nothing to do')
        return
    why = window_open()
    if why:
        say(f'gap closed: {why}')
        return
    if not acquire_lease():
        return
    beat_gap('scan')
    try:
        for d in sorted(PACKS.glob('*/')):
            why = window_open() or ('gap-lease lost' if lease_lost() else '')
            if why:
                say(f'window closed ({why}) — stopping')
                break
            spec = load_spec(d)
            if spec is None:
                continue
            name = spec['name']
            if (d / 'done').exists() or (d / 'failed').exists():
                continue
            if spec.get('disabled'):
                say(f'== {name}: SKIP disabled')
                continue
            bad = FORBIDDEN_RE.search(
                f"{spec.get('run', '')}\n{spec.get('prep', '')}")
            if bad:
                say(f'== {name}: SKIP forbidden pattern {bad.group(0)!r}')
                continue
            need = float(spec.get('min_free_gpu_gb') or 0)
            free = free_gpu_gb()
            if free < need:
                say(f'== {name}: SKIP vram {free:.1f}GB < {need}GB')
                continue
            if not claim(d):
                say(f'== {name}: SKIP claimed')
                continue
            say(f'== {name}: run (free vram {free:.1f}GB)')
            t0 = time.time()
            state, rc = run_pack(d, spec)
            dt = time.time() - t0
            release_claim(d)
            if state != 'run':
                say(f'== {name}: {state.upper()} after {dt:.0f}s — released for retry')
                try:
                    (d / 'out' / 'aborted.txt').write_text(
                        f'{state} at {time.time():.0f}\n')
                except OSError:
                    pass
                if 'lease' not in state:
                    break                          # window closing -> stop
                return                           # lease lost -> nothing is ours
            if rc != 0:
                say(f'== {name}: FAIL rc={rc} after {dt:.0f}s')
                (d / 'failed').write_text(json.dumps(
                    {'rc': rc, 'at': time.time(), 'worker': WORKER}))
                continue
            ok, info = verify_artifacts(spec)
            if not ok:
                say(f'== {name}: FAIL artifacts missing: {info}')
                (d / 'failed').write_text(json.dumps(
                    {'err': f'artifacts missing: {info}',
                     'at': time.time(), 'worker': WORKER}))
                continue
            (d / 'done').write_text(json.dumps(
                {'at': time.time(), 'worker': WORKER,
                 'seconds': round(dt, 1), 'artifacts': info}))
            say(f'== {name}: DONE {dt:.0f}s {info}')
    finally:
        beat_gap('exit')
        release_lease()


if __name__ == '__main__':
    sys.exit(main())
