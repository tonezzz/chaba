#!/usr/bin/env python3
# colab-batch-queue runner — DAEMON version.
# Lives on Drive at ada-nest/queue/runner.py; launched detached by
# queue-launcher-cell.py so the notebook kernel stays free for diagnostics
# (nvidia-smi, df, py-spy) while the queue runs.
#
# Manifest: ada-nest/queue/JOBS.py — JOBS=[{name, prep, run}].
# prep = shell (CPU-bound fetch/install/extract); run = python source exec'd
# in a shared namespace. Resumable: queue/done/<name>.done markers mean
# restart this runner after any crash/recycle.
#
# Observability (all on Drive, readable via rclone from fleet hosts):
#   queue/run-<ts>.out.log   — every byte this process prints incl. job runs
#   queue/prep-<name>.log    — per-job prep stdout/stderr
#   queue/heartbeat          — rewritten every 15s: <epoch> <job> <phase>
#   queue/runner.pid         — running pid, removed on clean exit
#   queue/done/<name>.done   — per-job completion markers
import os, sys, time, subprocess, traceback, threading, signal

Q = '/content/drive/MyDrive/ada-nest/queue'
DONE = f'{Q}/done'
os.makedirs(DONE, exist_ok=True)
sys.path.insert(0, Q)

import importlib
import JOBS as jobs_mod
importlib.reload(jobs_mod)          # pick up manifest edits without restart
JOBS = jobs_mod.JOBS

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
    return (job['name'], pl,
            subprocess.Popen(job['prep'], shell=True,
                             stdout=pl, stderr=subprocess.STDOUT,
                             start_new_session=True))

def wait_prep(prep):
    name, pl, proc = prep
    rc = proc.wait()
    pl.write(f'===== {time.strftime("%H:%M:%S")} rc={rc} =====\n'.encode())
    pl.close()
    return rc

try:
    ns = {}
    pending = None                  # (job_name, logfile, Popen) — bg prep for a
                                    # specific job, started under an earlier job's
                                    # GPU time. Only the owning job consumes it.
    for i, job in enumerate(JOBS):
        name = job['name']
        state.update(job=name, phase='check')
        if os.path.exists(f'{DONE}/{name}.done'):
            say(f'== {name}: SKIP (done marker)')
            continue
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
            nxt = next((j for j in JOBS[i+1:]
                        if j.get('prep')
                        and not os.path.exists(f"{DONE}/{j['name']}.done")),
                       None)
            if nxt:
                say(f'   (bg) prepping {nxt["name"]} (see prep-{nxt["name"]}.log)')
                pending = start_prep(nxt)
        try:
            state['phase'] = 'run'
            say(f'== {name}: run (gpu {gpu_note()} disk {disk_note()})')
            t0 = time.time()
            exec(compile(job['run'], f'<{name}>', 'exec'), ns)
            open(f'{DONE}/{name}.done', 'w').write(f'{time.time()-t0:.0f}s\n')
            say(f'== {name}: DONE {time.time()-t0:.0f}s (gpu {gpu_note()})')
        except Exception:
            say(f'== {name}: FAIL')
            traceback.print_exc()
            log.write(traceback.format_exc() + '\n')
    if pending is not None:
        state['phase'] = 'drain-prep'
        wait_prep(pending)
    say('QUEUE-DRAINED')
finally:
    state['job'] = 'exit'; state['phase'] = 'exit'
    try: os.unlink(f'{Q}/runner.pid')
    except OSError: pass
