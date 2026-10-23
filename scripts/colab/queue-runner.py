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
#   queue/runner.pid         — running pid, removed on clean exit
#   queue/done/<name>.done   — per-job completion markers (work scope)
#   queue/env-done/<boot>/   — env markers, scoped to this VM's boot_id
import os, sys, time, subprocess, traceback, threading, signal, glob

Q = '/content/drive/MyDrive/ada-nest/queue'
ROOT = '/content/drive/MyDrive/ada-nest'
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

# heartbeat: lets fleet-side checks flag a stall without any notebook access
state = {'job': 'boot', 'phase': 'boot'}
def heartbeat():
    while True:
        try:
            with open(f'{Q}/heartbeat', 'w') as h:
                h.write(f'{time.time():.0f} {state["job"]} {state["phase"]}\n')
        except OSError:
            pass
        time.sleep(15)
threading.Thread(target=heartbeat, daemon=True).start()

open(f'{Q}/runner.pid', 'w').write(str(os.getpid()))
def bye(*a):
    try: os.unlink(f'{Q}/runner.pid')
    except OSError: pass
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

WORKER = f'colab-{BOOT_ID[:8]}-{os.getpid()}'

def caps():
    c = {'gpu_gb': 0.0, 'disk_gb': 0.0, 'egress_only_ok': True}
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

def claim(job):
    """Optimistic first-writer-wins on packs/<name>/claim/. Drive dir-listing
    lag means this is best-effort for >1 simultaneous worker — fine at our
    scale; the watchdog arbitrates real conflicts."""
    cdir = f"{PACKS}/{job['name']}/claim"
    os.makedirs(cdir, exist_ok=True)
    if os.listdir(cdir):
        return False
    open(f'{cdir}/{WORKER}', 'w').write(f'{time.time():.0f}\n')
    time.sleep(2)                       # let a racing claim surface
    return sorted(os.listdir(cdir))[0] == WORKER

def verify_artifacts(job, timeout=180):
    """Every declared glob must match ≥1 non-empty file. Local stat is the
    best in-VM signal (server-side truth is the fleet watchdog's job), but it
    still catches run-returned-but-wrote-nothing — the failure that made a
    false save-hf-cache.done while the tar never landed (2026-10-23)."""
    pats = job.get('artifacts') or []
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
        if pending is not None and pending[0] == name:
            state['phase'] = 'prep-wait'
            rc = wait_prep(pending); pending = None
            say(f'== {name}: prep rc={rc}')
            if rc != 0:
                say(f'== {name}: PREP FAILED — skipping'); continue
        elif job.get('prep') and (pending is None or pending[0] != name):
            state['phase'] = 'prep'
            say(f'== {name}: prep (foreground, see prep-{name}.log)')
            if wait_prep(start_prep(job)) != 0:
                say(f'== {name}: PREP FAILED — skipping'); continue
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
                    exec(compile(job['run'], f'<{name}>', 'exec'), ns)
            finally:
                signal.alarm(0)
            dt = time.time() - t0
            ok, info = verify_artifacts(job)
            if not ok:
                say(f'== {name}: FAIL artifacts missing after run: {info}')
                continue
            open(markpath(job), 'w').write(f'{dt:.0f}s boot={BOOT_ID} {info}\n')
            say(f'== {name}: DONE {dt:.0f}s {info} (gpu {gpu_note()})')
        except Exception:
            say(f'== {name}: FAIL')
            traceback.print_exc()
            log.write(traceback.format_exc() + '\n')
    if pending is not None:
        state['phase'] = 'drain-prep'
        wait_prep(pending)
    # DriveFS flushes async — give big artifacts a window to land server-side
    # before the VM idles/recycles. Marker content already recorded sizes so
    # a fleet-side rclone check can confirm.
    state['phase'] = 'flush-settle'
    say('QUEUE-DRAINED — settling 120s for DriveFS flush')
    time.sleep(120)
finally:
    state['job'] = 'exit'; state['phase'] = 'exit'
    try: os.unlink(f'{Q}/runner.pid')
    except OSError: pass
