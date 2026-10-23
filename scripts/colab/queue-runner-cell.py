# colab-batch-queue runner — paste into ONE code cell, or push via MCP update_cell.
# Manifest lives at gdrive:ada-nest/queue/JOBS.py (JOBS = [{name, prep, run}]).
# prep = shell string (CPU-bound fetch/install/extract); run = python source
# exec'd in a shared namespace. Resumable: queue/done/<name>.done markers mean
# rerun the same cell after any crash/recycle. See docs/kb/colab-mcp-jobs.md.
import os, sys, time, subprocess, traceback

Q = '/content/drive/MyDrive/ada-nest/queue'
DONE = f'{Q}/done'
os.makedirs(DONE, exist_ok=True)
sys.path.insert(0, Q)

import importlib
import JOBS as jobs_mod
importlib.reload(jobs_mod)          # pick up manifest edits without kernel restart
JOBS = jobs_mod.JOBS

log = open(f'{Q}/log-{time.strftime("%Y%m%d-%H%M")}.txt', 'a', buffering=1)
def say(msg):
    line = f'{time.strftime("%H:%M:%S")} {msg}'
    print(line, flush=True)
    log.write(line + '\n')

def gpu_note():
    # utilization is instantaneous — the memory figure is the useful half
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used',
                            '--format=csv,noheader'], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return 'n/a'

def start_prep(job):
    # prep output -> Drive-side prep-<name>.log so fleet hosts can watch
    # progress via `rclone cat` (subprocess stdout never reaches MCP cell
    # outputs — 2026-10-23 lesson). rc line is appended when it exits.
    pl = open(f'{Q}/prep-{job["name"]}.log', 'ab')
    pl.write(f'\n===== {time.strftime("%H:%M:%S")} prep start =====\n'.encode())
    pl.flush()
    return (job['name'], pl,
            subprocess.Popen(job['prep'], shell=True,
                             stdout=pl, stderr=subprocess.STDOUT))

def wait_prep(prep):
    name, pl, proc = prep
    rc = proc.wait()
    pl.write(f'===== {time.strftime("%H:%M:%S")} rc={rc} =====\n'.encode())
    pl.close()
    return rc

ns = {}
pending = None                      # (job_name, logfile, Popen) — bg prep for a
                                  # specific job, started under an earlier job's
                                  # GPU time. Only the owning job consumes it
                                  # (2026-10-23 bug: unattributed prep skipped
                                  # the wrong job).
for i, job in enumerate(JOBS):
    name = job['name']
    if os.path.exists(f'{DONE}/{name}.done'):
        say(f'== {name}: SKIP (done marker)')
        continue
    if pending is not None and pending[0] == name:
        rc = wait_prep(pending); pending = None
        say(f'== {name}: prep rc={rc}')
        if rc != 0:
            say(f'== {name}: PREP FAILED — skipping'); continue
    elif job.get('prep') and (pending is None or pending[0] != name):
        say(f'== {name}: prep (foreground, see prep-{name}.log)')
        if wait_prep(start_prep(job)) != 0:
            say(f'== {name}: PREP FAILED — skipping'); continue
    if pending is None:             # one bg slot — hide next prep under this run
        nxt = next((j for j in JOBS[i+1:]
                    if j.get('prep')
                    and not os.path.exists(f"{DONE}/{j['name']}.done")),
                   None)
        if nxt:
            say(f'   (bg) prepping {nxt["name"]} (see prep-{nxt["name"]}.log)')
            pending = start_prep(nxt)
    try:
        say(f'== {name}: run (gpu {gpu_note()})')
        t0 = time.time()
        exec(compile(job['run'], f'<{name}>', 'exec'), ns)
        open(f'{DONE}/{name}.done', 'w').write(f'{time.time()-t0:.0f}s\n')
        say(f'== {name}: DONE {time.time()-t0:.0f}s (gpu {gpu_note()})')
    except Exception:
        say(f'== {name}: FAIL')
        traceback.print_exc()
        log.write(traceback.format_exc() + '\n')
if pending is not None:
    wait_prep(pending)
say('QUEUE-DRAINED')
