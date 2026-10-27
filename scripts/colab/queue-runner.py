#!/usr/bin/env python3
# colab-batch-queue runner — DAEMON version.
# Lives on Drive at ada-nest/queue/runner.py; launched detached by
# queue-launcher-cell.py so the notebook kernel stays free for diagnostics
# (nvidia-smi, df, py-spy) while the queue runs.
#
# Manifest: ada-nest/queue/JOBS.py — JOBS=[{name, scope, prep, run, artifacts}].
# prep = shell (CPU-bound fetch/install/extract); run = python source exec'd
# in a shared namespace. Resumable: queue/done/<name>.done markers mean
# restart this runner after any crash/recycle.
#
# scope (default 'work'):
#   'work' — real output; done marker is GLOBAL (queue/done/), survives
#            runtime recycling. This is what resumability is for.
#   'env'  — prepares THIS runtime only (pip install, asset extract, cache
#            restore). Marker lives under queue/env-done/<boot_id>/ so a
#            fresh VM always re-runs it — a pip install can't outlive its VM.
# artifacts: glob patterns relative to ada-nest/ root. Before a job is marked
#   done, every pattern must match ≥1 non-empty file on Drive. Catches
#   "run returned but wrote nothing" — marker content records matched sizes
#   so the fleet watchdog can spot-check server-side.
#
# PACKS (nest-pack v2): ada-nest/packs/<name>/ is a self-contained job
# bundle — pack.yml {name, needs:{gpu_gb,disk_gb,egress_only_ok}, prep, run,
# artifacts, scope, timeout_s} plus optional inputs/. Packs run AFTER the
# JOBS manifest, are claimed optimistically (packs/<name>/claim/<worker>),
# and mark done at packs/<name>/done — so ANY worker on ANY store can pick
# them up. needs is a capability floor: this worker advertises gpu via
# nvidia-smi, disk via statvfs, egress_only_ok=True always.
#
# Observability (all on Drive, readable via rclone from fleet hosts):
#   queue/run-<ts>.out.log   — every byte this process prints incl. job runs
#   queue/prep-<name>.log    — per-job prep stdout/stderr
#   queue/heartbeat          — rewritten every 15s: <epoch> <job> <phase>
#   queue/runner.pid         — running pid, removed on clean exit (legacy)
#   queue/runner.id          — JSON {pid,boot_id,worker,epoch,ts} — the
#                            — boot-scoped identity; a pid on shared Drive is
#                            — NOT a process handle on any other VM
#   queue/done/<name>.done   — per-job completion markers (work scope)
#   queue/env-done/<boot>/   — env markers, scoped to this VM's boot_id
import os, sys, time, subprocess, traceback, threading, signal, glob

ROOT = os.environ.get('NEST_ROOT', '/content/drive/MyDrive/ada-nest')
Q = os.environ.get('NEST_QUEUE', f'{ROOT}/queue')
DONE = f'{Q}/done'
try:
    BOOT_ID = open('/proc/sys/kernel/random/boot_id').read().strip()
except OSError:
    BOOT_ID = time.strftime('%Y%m%d-%H%M')   # non-linux fallback: per-launch
ENV_DONE = f'{Q}/env-done/{BOOT_ID}'
os.makedirs(DONE, exist_ok=True)
os.makedirs(ENV_DONE, exist_ok=True)
sys.path.insert(0, Q)

import importlib
import JOBS as jobs_mod
importlib.reload(jobs_mod)          # pick up manifest edits without restart
JOBS = jobs_mod.JOBS

PACKS = f'{ROOT}/packs'
def load_packs():
    """Discover ada-nest/packs/<name>/pack.yml → normalized job dicts."""
    out = []
    if not os.path.isdir(PACKS):
        return out
    try:
        import yaml
    except ImportError:
        print('packs/ present but pyyaml missing — run a deps job first')
        return out
    for d in sorted(os.listdir(PACKS)):
        py = f'{PACKS}/{d}/pack.yml'
        if not os.path.isfile(py):
            continue
        try:
            spec = yaml.safe_load(open(py)) or {}
        except Exception as e:
            print(f'pack {d}: bad pack.yml ({e}) — skipped')
            continue
        spec.setdefault('name', d)
        spec['_pack'] = True
        out.append(spec)
    return out

log = open(f'{Q}/log-{time.strftime("%Y%m%d-%H%M")}.txt', 'a', buffering=1)
def say(msg):
    line = f'{time.strftime("%H:%M:%S")} {msg}'
    print(line, flush=True)          # stdout -> run-<ts>.out.log on Drive
    log.write(line + '\n')

# --- nest-fence (v4): lease + epoch. Only the newest generation may write;
# a zombie that resurfaces discovers it lost the lease and self-exits
# before it can mutate the store. Two-VM race: newer epoch wins. ---
import json
LEASE = f'{Q}/lease'

def read_lease():
    try:
        d = json.loads(open(LEASE).read())
        return int(d.get('epoch', 0)), str(d.get('worker', ''))
    except Exception:
        return 0, ''

def take_lease(worker):
    # FUSE write->read visibility can lag arbitrarily — a read-back
    # check would self-exit on a healthy store. Write-and-remember:
    # fence_watch arbitrates (last-writer wins; a beaten writer sees a
    # different (epoch,worker) within its 15s poll and exits).
    e, _w = read_lease()
    with open(LEASE, 'w') as f:
        f.write(json.dumps(
            {'worker': worker, 'epoch': e + 1, 'ts': int(time.time())}))
    return e + 1

def fenced_out(my_epoch, worker):
    e, w = read_lease()
    # FUSE read-lag: an empty/absent lease is NOT proof of loss — only
    # yield when the lease is readable and names a different worker.
    if not w:
        return False
    return (e, w) != (my_epoch, worker)

# heartbeat: lets fleet-side checks flag a stall without any notebook access
state = {'job': 'boot', 'phase': 'boot'}

def _registry_refresh():
    """Keep this VM's managed-runtime record fresh while the queue runs —
    the console's duplicate-session gate reads queue/runtime-sessions/. Best-effort:
    runtime_registry.py may be absent on older Drive trees."""
    try:
        import runtime_registry as rr
        rr.register()
    except Exception:
        pass

def heartbeat():
    while True:
        try:
            with open(f'{Q}/heartbeat', 'w') as h:
                h.write(f'{time.time():.0f} {state["job"]} {state["phase"]}\n')
            # refresh lease ts while I still hold it — liveness for watchers
            e, w = read_lease()
            if w == WORKER:
                with open(LEASE, 'w') as f:
                    f.write(json.dumps(
                        {'worker': WORKER, 'epoch': EPOCH,
                         'ts': int(time.time())}))
            _registry_refresh()
        except OSError:
            pass
        time.sleep(15)

def fence_watch():
    # self-fencing: if my lease was overwritten, my writes are no longer
    # legitimate — die before corrupting the store
    while True:
        time.sleep(15)
        try:
            if fenced_out(EPOCH, WORKER):
                os._exit(1)
        except OSError:
            pass                    # unreadable lease ≠ lost lease; retry

WORKER = f'colab-{BOOT_ID[:8]}-{os.getpid()}'
EPOCH = take_lease(WORKER)
say(f'lease acquired: {WORKER} epoch {EPOCH}')
# heartbeat thread starts only after WORKER/EPOCH exist — starting it
# earlier raced the take_lease settle window and died on NameError
# (observed 2026-10-23: heartbeat NameError: EPOCH -> no heartbeat ever)
threading.Thread(target=heartbeat, daemon=True).start()
threading.Thread(target=fence_watch, daemon=True).start()

# runner.id — boot-scoped identity. runner.pid is kept for fleet tooling but
# is attribution-free; anything that wants to SIGNAL a runner must match
# runner.id's boot_id to its own /proc boot_id first (PID-collision lesson).
def write_runner_id():
    try:
        with open(f'{Q}/runner.id', 'w') as f:
            f.write(json.dumps({'pid': os.getpid(), 'boot_id': BOOT_ID,
                                'worker': WORKER, 'epoch': EPOCH,
                                'ts': int(time.time())}) + '\n')
    except OSError:
        pass

write_runner_id()
open(f'{Q}/runner.pid', 'w').write(str(os.getpid()))

def remove_own_runner_marks():
    """Delete our identity files only when they still name US — a fenced-out
    zombie must not strip the identity of the runner that beat it."""
    try:
        if open(f'{Q}/runner.pid').read().strip() == str(os.getpid()):
            os.unlink(f'{Q}/runner.pid')
    except OSError:
        pass
    try:
        d = json.loads(open(f'{Q}/runner.id').read())
        if d.get('pid') == os.getpid() and d.get('boot_id') == BOOT_ID:
            os.unlink(f'{Q}/runner.id')
    except Exception:
        pass

def bye(*a):
    remove_own_runner_marks()
    sys.exit(1)
signal.signal(signal.SIGTERM, bye)
signal.signal(signal.SIGINT, bye)

def gpu_note():
    # utilization is instantaneous — the memory figure is the useful half
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used',
                            '--format=csv,noheader'], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return 'n/a'

def disk_note():
    try:
        r = subprocess.run(['df', '--output=pcent', '/'], capture_output=True,
                           text=True, timeout=10)
        return r.stdout.split()[-1]
    except Exception:
        return '?'

def start_prep(job):
    # own process group so an interrupt/SIGTERM can reach the whole tree;
    # output -> Drive-side prep-<name>.log (rclone-visible progress).
    pl = open(f'{Q}/prep-{job["name"]}.log', 'ab')
    pl.write(f'\n===== {time.strftime("%H:%M:%S")} prep start =====\n'.encode())
    pl.flush()
    pack_dir = f'{PACKS}/{job["name"]}' if job.get('_pack') else ''
    return (job['name'], pl,
            subprocess.Popen(job['prep'], shell=True,
                             stdout=pl, stderr=subprocess.STDOUT,
                             env=dict(os.environ, NEST_ROOT=ROOT,
                                      PACK_DIR=pack_dir),
                             start_new_session=True))

def wait_prep(prep):
    name, pl, proc = prep
    rc = proc.wait()
    pl.write(f'===== {time.strftime("%H:%M:%S")} rc={rc} =====\n'.encode())
    pl.close()
    return rc

def caps():
    c = {'gpu_gb': 0.0, 'disk_gb': 0.0, 'egress_only_ok': True, 'ram_gb': 0.0}
    try:
        c['ram_gb'] = round(os.sysconf('SC_PHYS_PAGES')
                            * os.sysconf('SC_PAGE_SIZE') / 1e9, 1)
    except Exception:
        pass
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=memory.total',
                            '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=10)
        c['gpu_gb'] = float(r.stdout.strip().split()[0]) / 1024
    except Exception:
        pass
    try:
        st = os.statvfs('/')
        c['disk_gb'] = st.f_bavail * st.f_frsize / 1e9
    except Exception:
        pass
    return c
CAPS = caps()

def fits(job):
    for k, v in (job.get('needs') or {}).items():
        if k == 'egress_only_ok':
            if v and not CAPS['egress_only_ok']:
                return 'egress_only'
        elif CAPS.get(k, 0) < v:
            return f'{k} {CAPS.get(k,0):.1f} < {v}'
    return ''

def markpath(job):
    if job.get('_pack'):
        return f"{PACKS}/{job['name']}/done"
    d = ENV_DONE if job.get('scope') == 'env' else DONE
    return f"{d}/{job['name']}.done"

def release_claim(name):
    """Delete our own claim file — a failed/dead worker must not leave a
    claim that poisons the pack for the stale-claim window (2026-10-23)."""
    try:
        os.unlink(f'{PACKS}/{name}/claim/{WORKER}')
    except OSError:
        pass

def touch_index(name, state, info=''):
    """packs-index.json — one tiny line per state change so fleet scans
    can go O(1) instead of O(packs x rclone lsf). Best-effort."""
    try:
        with open(f'{Q}/packs-index.json', 'a') as f:
            f.write(f'{time.time():.0f} {name} {state} {WORKER} {info}\n')
    except OSError:
        pass

def claim(job):
    """Optimistic first-writer-wins on packs/<name>/claim/. Drive dir-listing
    lag means this is best-effort for >1 simultaneous worker — fine at our
    scale; the watchdog arbitrates real conflicts."""
    if fenced_out(EPOCH, WORKER):
        sys.exit('fenced — lost lease before claim')
    cdir = f"{PACKS}/{job['name']}/claim"
    os.makedirs(cdir, exist_ok=True)
    if os.listdir(cdir):
        return False
    open(f'{cdir}/{WORKER}', 'w').write(f'{time.time():.0f} ep={EPOCH}\n')
    time.sleep(2)                       # let a racing claim surface
    return sorted(os.listdir(cdir))[0] == WORKER

def verify_artifacts(job, timeout=180):
    """Every declared glob must match ≥1 non-empty file. Local stat is the
    best in-VM signal (server-side truth is the fleet watchdog's job), but it
    still catches run-returned-but-wrote-nothing — the failure that made a
    false save-hf-cache.done while the tar never landed (2026-10-23)."""
    # {boot_id} expands so env-scope jobs can declare boot-scoped artifacts
    pats = [p.replace('{boot_id}', BOOT_ID)
            for p in (job.get('artifacts') or [])]
    if not pats:
        return True, ''
    deadline = time.time() + timeout
    while True:
        hits = {}
        for p in pats:
            m = [f for f in glob.glob(f'{ROOT}/{p}')
                 if os.path.isfile(f) and os.path.getsize(f) > 0]
            hits[p] = m
        missing = [p for p, m in hits.items() if not m]
        if not missing:
            return True, ' '.join(f'{p}={len(hits[p])}x'
                                  f'{sum(os.path.getsize(f) for f in hits[p])}B'
                                  for p in pats)
        if time.time() > deadline:
            return False, ' '.join(missing)
        time.sleep(5)

class PackTimeout(Exception): pass
def _alrm(sig, frm): raise PackTimeout('pack exceeded timeout_s')
signal.signal(signal.SIGALRM, _alrm)

try:
    ns = {}
    current = ""                   # pack name whose claim we hold
    pending = None                  # (job_name, logfile, Popen) — bg prep for a
                                    # specific job, started under an earlier job's
                                    # GPU time. Only the owning job consumes it.
    packs = load_packs()
    if packs:
        say(f'packs discovered: {[p["name"] for p in packs]} (caps gpu={CAPS["gpu_gb"]:.0f}GB disk={CAPS["disk_gb"]:.0f}GB)')
    queue = JOBS + packs
    for i, job in enumerate(queue):
        name = job['name']
        state.update(job=name, phase='check')
        if os.path.exists(markpath(job)):
            say(f'== {name}: SKIP (done marker)')
            continue
        if job.get('_pack'):
            why = fits(job)
            if why:
                say(f'== {name}: SKIP needs unmet ({why})'); continue
            if not claim(job):
                say(f'== {name}: SKIP (claimed by another worker)'); continue
            current = name
            touch_index(name, 'claim')
        if pending is not None and pending[0] == name:
            state['phase'] = 'prep-wait'
            rc = wait_prep(pending); pending = None
            say(f'== {name}: prep rc={rc}')
            if rc != 0:
                say(f'== {name}: PREP FAILED — skipping')
                if job.get('_pack'): release_claim(name)
                continue
        elif job.get('prep') and (pending is None or pending[0] != name):
            state['phase'] = 'prep'
            say(f'== {name}: prep (foreground, see prep-{name}.log)')
            if wait_prep(start_prep(job)) != 0:
                say(f'== {name}: PREP FAILED — skipping')
                if job.get('_pack'): release_claim(name)
                continue
        if pending is None:         # one bg slot — hide next prep under this run
            nxt = next((j for j in queue[i+1:]
                        if j.get('prep')
                        and not os.path.exists(markpath(j))),
                       None)
            if nxt:
                say(f'   (bg) prepping {nxt["name"]} (see prep-{nxt["name"]}.log)')
                pending = start_prep(nxt)
        try:
            state['phase'] = 'run'
            say(f'== {name}: run (gpu {gpu_note()} disk {disk_note()})')
            t0 = time.time()
            signal.alarm(int(job.get('timeout_s') or 0))
            try:
                pack_dir = f"{PACKS}/{name}" if job.get('_pack') else ''
                if job.get('run_sh'):
                    env = dict(os.environ, NEST_ROOT=ROOT, PACK_DIR=pack_dir)
                    r = subprocess.run(job['run_sh'], shell=True, env=env)
                    if r.returncode:
                        raise RuntimeError(f'run_sh rc={r.returncode}')
                else:
                    ns['PACK_DIR'] = pack_dir
                    ns['NEST_ROOT'] = ROOT
                    ns['BOOT_ID'] = BOOT_ID
                    # (name, logfile, Popen) of the next job's bg prep — lets
                    # a run (e.g. t4-session-warmup) keep the GPU busy exactly
                    # until that prep exits. None when nothing is pending.
                    ns['QUEUE_PENDING'] = pending
                    ns['QUEUE_STATE'] = state
                    exec(compile(job['run'], f'<{name}>', 'exec'), ns)
            finally:
                signal.alarm(0)
            dt = time.time() - t0
            ok, info = verify_artifacts(job)
            if not ok:
                say(f'== {name}: FAIL artifacts missing after run: {info}')
                if job.get('_pack'): release_claim(name)
                continue
            if fenced_out(EPOCH, WORKER):
                sys.exit('fenced — lost lease before done-mark')
            open(markpath(job), 'w').write(f'{dt:.0f}s boot={BOOT_ID} ep={EPOCH} {info}\n')
            if job.get('_pack'): touch_index(name, 'done', info)
            say(f'== {name}: DONE {dt:.0f}s {info} (gpu {gpu_note()})')
        except Exception:
            say(f'== {name}: FAIL')
            traceback.print_exc()
            log.write(traceback.format_exc() + '\n')
            if job.get('_pack'): release_claim(name)
    if pending is not None:
        state['phase'] = 'drain-prep'
        wait_prep(pending)
    # DriveFS flushes async — give big artifacts a window to land server-side
    # before the VM idles/recycles. Marker content already recorded sizes so
    # a fleet-side rclone check can confirm.
    state['phase'] = 'flush-settle'
    settle = float(os.environ.get('NEST_QUEUE_SETTLE_S', '120'))
    say(f'QUEUE-DRAINED — settling {settle:.0f}s for DriveFS flush')
    time.sleep(settle)
finally:
    state['job'] = 'exit'; state['phase'] = 'exit'
    if current:
        release_claim(current)      # died mid-pack — don't poison the pack
    remove_own_runner_marks()
