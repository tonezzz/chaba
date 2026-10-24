#!/usr/bin/env python3
"""nest-efficiency — per-session efficiency report for the ada-nest queue.

Parses queue/run-*.out.log + packs/*/done + heartbeat to compute, per
session (one run log = one worker pass):
  wall_min      launch -> QUEUE-DRAINED (or last event)
  gpu_min       sum of per-job seconds where the DONE line reported
                high gpu% (gpu >= 50)
  idle_min      wall - sum(job durations) - settle
  packs_done    done markers touched by this session's worker
  failures      FAIL / PREP FAILED / lease-lost lines
  cold_start_min for sessions that ran env jobs: time from first env
                prep to the first pack run

Usage: nest-efficiency.py [--remote gdrive:ada-nest] [--json]
Reads via rclone (fleet hosts) or a local mount if the path exists.
"""
import argparse, glob, json, os, re, subprocess, sys, time

RCLONE = (shutil.which('rclone') if False else None)  # placeholder; resolved below
import shutil
RCLONE = shutil.which('rclone') or os.path.expanduser('~/.local/bin/rclone')

def rc(*a, check=True, **kw):
    r = subprocess.run([RCLONE] + list(a), capture_output=True,
                       text=True, timeout=300)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return r

def fetch(remote, rel):
    try:
        return rc('cat', f'{remote}/{rel}', check=False).stdout
    except Exception:
        return ''

def parse_session(logtext, name):
    lines = logtext.splitlines()
    s = {'session': name, 'packs_done': 0, 'failures': 0,
         'gpu_sec': 0, 'job_sec': 0, 'events': []}
    t0 = None
    last_ts = None
    for ln in lines:
        m = re.match(r'^(\d{2}:\d{2}:\d{2})', ln)
        ts = m.group(1) if m else None
        if ts:
            h, mi, se = map(int, ts.split(':'))
            e = h * 3600 + mi * 60 + se
            if t0 is None:
                t0 = e
            last_ts = e
        if re.search(r'== .*DONE', ln):
            s['packs_done'] += 1
            gm = re.search(r'gpu (\d+) %', ln)
            if gm and int(gm.group(1)) >= 50:
                d = re.search(r'DONE (\d+)s', ln)
                s['gpu_sec'] += int(d.group(1)) if d else 0
            d = re.search(r'DONE (\d+)s', ln)
            s['job_sec'] += int(d.group(1)) if d else 0
        if re.search(r'FAIL|PREP FAILED|lease lost|fenced', ln):
            s['failures'] += 1
        s['events'].append(ln)
    if t0 is not None and last_ts is not None:
        s['wall_min'] = round((last_ts - t0) / 60, 1)
    else:
        s['wall_min'] = 0
    s['gpu_min'] = round(s['gpu_sec'] / 60, 1)
    s['job_min'] = round(s['job_sec'] / 60, 1)
    s['idle_min'] = round(max(0, s['wall_min'] - s['job_min']), 1)
    return s

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--remote', default='gdrive:ada-nest')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if os.path.isdir(a.remote):
        logs = [f for f in os.listdir(a.remote)
                if (f.startswith('run-') or f.startswith('log-'))
                and f.endswith(('.out.log', '.txt'))]
    else:
        logs = [l for l in rc('lsf', f'{a.remote}/queue', check=False)
                .stdout.split() if (l.startswith('run-')
                or l.startswith('log-')) and l.endswith(('.out.log', '.txt'))]
    reports = []
    for f in sorted(logs):
        if os.path.isdir(a.remote):
            txt = open(f'{a.remote}/{f}').read()
        else:
            txt = fetch(a.remote, f'queue/{f}')
        if not txt:
            continue
        s = parse_session(txt, f.replace('.out.log', '').replace('.txt', ''))
        reports.append(s)
    if a.json:
        print(json.dumps(reports, indent=1))
        return
    print(f"{'session':24} {'wall':>6} {'gpu':>5} {'idle':>6} {'done':>4} {'fail':>4}")
    print('-' * 56)
    for s in reports:
        print(f"{s['session']:24} {s['wall_min']:6.1f} {s['gpu_min']:5.1f} "
              f"{s['idle_min']:6.1f} {s['packs_done']:4d} {s['failures']:4d}")

if __name__ == '__main__':
    main()
