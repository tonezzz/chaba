#!/usr/bin/env python3
"""nest-job-reconcile.py — read-only consistency check across the four
surfaces that claim to know a nest job's state (OPS-0923).

Surfaces:
  - WP `nest_job` CPT        — the member-facing mirror, written only
                               through board-api `/job` (and `/publish`
                               job sink). Read via `GET /nest-jobs`.
  - `packs/<name>/` markers  — `done` FILE marker + `claim/` dir on the
                               Drive store (authoritative queue truth).
  - `queue/packs-index/`     — advisory per-event JSON fold
                               {ts,pack,state,worker} (stage|claim|done|
                               fail|release); never authoritative alone.
  - `queue/lease`            — unified liveness {worker,epoch,ts,job,
                               phase}; queue/heartbeat is the fallback.

The contract being reconciled (docs/kb/job-package-status-sop.md +
board-api JOB_TRANSITIONS): terminal `done` requires a durable
`result_ref` AND verified artifact evidence; a pack `done` marker is
the queue-side proof. This script NEVER mutates — no status writes, no
claim clears, no cancels. Findings are report-only; acting on them is a
separate gated decision.

Usage:
  nest-job-reconcile.py [--api URL] [--jobs-file PATH] [--no-drive]
                        [--stale-min N] [--json] [--strict]

Exit: 0 clean (or warnings only), 1 on error-severity findings
(--strict: any finding), 2 on collector failure.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = 'gdrive:ada-nest'
Q = f'{ROOT}/queue'
PACKS = f'{ROOT}/packs'
PINDEX = f'{Q}/packs-index'
DEFAULT_API = os.environ.get(
    'BOARD_API', 'https://idc03.taila0626a.ts.net:10000')

ACTIVE_JOB_STATES = {'claimed', 'running'}
TERMINAL_JOB_STATES = {'done', 'failed', 'stalled', 'cancelled'}
INDEX_TERMINAL = {'done', 'fail'}
LEASE_RUN_PHASES = {'run', 'prep', 'prep-wait'}


# ---------------------------------------------------------------------------
# collectors (thin — all Drive/WP access lives here; reconcile() is pure)


def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def collect_jobs(api, limit=500):
    """GET /nest-jobs — the WP mirror side (server caps at 500).
    Returns list of {id,slug,title,modified,status,meta}."""
    url = f'{api}/nest-jobs?limit={min(limit, 500)}'
    res = http_json(url)
    return (res.get('jobs') or [])[:limit]


def _rc(args, timeout=90):
    r = subprocess.run(['rclone'] + args, capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(
            f'rclone {args[0]}: {r.stderr.strip()[:160]}')
    return r.stdout


def collect_packs():
    """One recursive files-only listing -> {pack: {done, failed,
    claims[]}}. claim/* files on a terminal pack are residue, not live
    claims — reconcile() applies that rule."""
    packs = {}
    try:
        entries = _rc(['lsf', PACKS, '--recursive', '--files-only'],
                      timeout=120).splitlines()
    except Exception:
        return packs, 'packs listing failed'
    for e in entries:
        e = e.strip().rstrip('/')
        if not e:
            continue
        name, _, rel = e.partition('/')
        if not name or not rel:
            continue
        p = packs.setdefault(name, {'done': False, 'failed': False,
                                    'claims': []})
        if rel == 'done':
            p['done'] = True
        elif rel == 'failed':
            p['failed'] = True
        elif rel.startswith('claim/'):
            p['claims'].append(rel.split('/', 1)[1])
    return packs, None


def collect_index():
    """Fold queue/packs-index event files -> {pack: {state,ts,worker}}
    (latest event wins). Advisory only."""
    idx = {}
    tmp = tempfile.mkdtemp(prefix='nest-job-recon-')
    try:
        r = subprocess.run(
            ['rclone', 'copy', PINDEX, tmp, '--include', '*.json'],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return idx, 'packs-index copy failed'
        for fn in os.listdir(tmp):
            try:
                with open(os.path.join(tmp, fn)) as f:
                    ev = json.load(f)
            except Exception:
                continue
            p, st = ev.get('pack'), ev.get('state')
            try:
                ts = float(ev.get('ts') or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if not p or not st:
                continue
            cur = idx.get(p)
            if cur is None or ts >= cur['ts']:
                idx[p] = {'state': st, 'ts': ts,
                          'worker': ev.get('worker')}
        return idx, None
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def collect_lease():
    """queue/lease JSON {worker,epoch,ts,job,phase}; heartbeat text
    fallback for pre-unification writers."""
    try:
        out = _rc(['cat', f'{Q}/lease'], timeout=30).strip()
    except Exception:
        out = ''
    lease = None
    if out:
        try:
            lease = json.loads(out)
        except Exception:
            lease = {'raw': out[:200]}
    return lease


# ---------------------------------------------------------------------------
# pure reconciliation


def _truthy(v):
    return v is True or str(v or '').strip().lower() in (
        '1', 'true', 'yes', 'verified')


def _job_evidence(meta):
    """Verified-artifact signal on stored meta: evidence refs,
    artifact_verified flag, or a verified marker the writer persisted."""
    if _truthy(meta.get('artifact_verified')):
        return True
    ev = meta.get('evidence')
    if isinstance(ev, str) and ev.strip():
        return True
    if isinstance(ev, (list, tuple)) and any(str(x).strip() for x in ev):
        return True
    return False


def _pack_terminal(pack, index_ev):
    """Queue-side terminal state: done FILE marker is authoritative;
    index done/fail counts too (advisory but corroborating)."""
    if pack and pack.get('done'):
        return 'done'
    if pack and pack.get('failed'):
        return 'failed'
    st = (index_ev or {}).get('state')
    if st == 'done':
        return 'done'
    if st == 'fail':
        return 'failed'
    return None


def reconcile(jobs, packs, index, lease, now=None,
              stale_min=20):
    """Compare the four surfaces. Returns
    {'findings': [...], 'summary': {...}} — never mutates inputs."""
    now = now if now is not None else time.time()
    findings = []

    def flag(code, severity, subject, detail):
        findings.append({'code': code, 'severity': severity,
                         'subject': subject, 'detail': detail})

    packs = packs or {}
    index = index or {}
    pack_names = set(packs) | set(index)

    # --- per-job checks -------------------------------------------------
    active_jobs = []
    for job in jobs or []:
        slug = str(job.get('slug') or '')
        meta = job.get('meta') or {}
        status = str(meta.get('status') or '').strip()
        if not slug or not status:
            continue
        # join key: declared pack meta first, then slug-as-pack-name
        pack_name = str(meta.get('pack') or '').strip() or (
            slug if slug in pack_names else '')
        pack = packs.get(pack_name) if pack_name else None
        idx_ev = index.get(pack_name) if pack_name else None
        terminal = _pack_terminal(pack, idx_ev)

        if status == 'done':
            if not str(meta.get('result_ref') or '').strip():
                flag('DONE-NO-RESULT-REF', 'error', slug,
                     'status=done with no result_ref — the durable '
                     'pointer is missing (pre-gate legacy write or '
                     'contract violation)')
            elif not _job_evidence(meta):
                flag('DONE-UNVERIFIED', 'warn', slug,
                     'status=done has result_ref but no evidence[]/'
                     'artifact_verified — verification not recorded')
            if pack_name and terminal != 'done':
                flag('DONE-NO-PACK-MARKER', 'warn', slug,
                     f'job done but pack {pack_name} has no done '
                     f'marker (queue terminal={terminal or "none"})')
        elif status in ACTIVE_JOB_STATES and pack_name:
            active_jobs.append(slug)
            claims = (pack or {}).get('claims') or []
            idx_state = (idx_ev or {}).get('state')
            if terminal:
                flag('ACTIVE-JOB-PACK-TERMINAL', 'warn', slug,
                     f'job {status} but pack {pack_name} is '
                     f'{terminal} — mirror is behind the queue')
            elif idx_state in ('done', 'fail'):
                flag('ACTIVE-JOB-INDEX-TERMINAL', 'warn', slug,
                     f'job {status} but packs-index says '
                     f'{idx_state} for {pack_name}')
            elif not claims and idx_state != 'claim':
                flag('ACTIVE-NO-CLAIM', 'info', slug,
                     f'job {status} but pack {pack_name} shows no '
                     'claim marker — possible stale mirror or '
                     'non-Drive job')
        elif status == 'cancelled' and pack_name:
            claims = (pack or {}).get('claims') or []
            if claims:
                flag('CANCELLED-LINGER-CLAIM', 'warn', slug,
                     f'job cancelled but pack {pack_name} still has '
                     f'{len(claims)} claim file(s) — claim was not '
                     'released (report-only; clearing is a gated op)')

    # --- pack -> job direction ------------------------------------------
    job_by_pack = {}
    for job in jobs or []:
        meta = job.get('meta') or {}
        slug = str(job.get('slug') or '')
        pname = str(meta.get('pack') or '').strip() or (
            slug if slug in pack_names else '')
        if pname:
            job_by_pack[pname] = (slug, str(meta.get('status') or ''))
    for pname, pack in sorted(packs.items()):
        if not (pack.get('done') or pack.get('failed')):
            continue
        term = 'done' if pack.get('done') else 'failed'
        hit = job_by_pack.get(pname)
        if not hit:
            flag('PACK-TERMINAL-NO-JOB', 'info', pname,
                 f'pack {term} but no nest_job mirrors it')
        else:
            slug, jstatus = hit
            if term == 'done' and jstatus != 'done':
                flag('PACK-DONE-JOB-NOT-DONE', 'warn', slug,
                     f'pack {pname} has done marker but nest_job '
                     f'status={jstatus or "none"} — mirror lag or '
                     'missing /job write')
            elif term == 'failed' and jstatus in (
                    'claimed', 'running', 'done'):
                flag('PACK-FAILED-JOB-INCONSISTENT', 'warn', slug,
                     f'pack {pname} failed but nest_job status='
                     f'{jstatus}')

    # --- lease liveness --------------------------------------------------
    lease_info = {'present': bool(lease)}
    if isinstance(lease, dict) and not lease.get('raw'):
        try:
            lts = float(lease.get('ts') or 0)
        except (TypeError, ValueError):
            lts = 0.0
        age = now - lts if lts else None
        lease_info.update({'age_s': age,
                           'job': lease.get('job'),
                           'phase': lease.get('phase'),
                           'worker': lease.get('worker')})
        fresh = age is not None and age <= stale_min * 60
        lease_info['fresh'] = fresh
        lname = str(lease.get('job') or '').strip()
        if lname and fresh and lease.get('phase') in LEASE_RUN_PHASES:
            # does the lease's job name resolve to a nest_job?
            cand = [j for j in (jobs or [])
                    if str(j.get('slug') or '') == lname
                    or str((j.get('meta') or {}).get('pack') or '')
                    == lname]
            if cand:
                jstatus = str(
                    (cand[0].get('meta') or {}).get('status') or '')
                if jstatus in TERMINAL_JOB_STATES:
                    flag('LEASE-ACTIVE-TERMINAL-JOB', 'warn', lname,
                         f'queue lease says {lname} is '
                         f'{lease.get("phase")} but nest_job '
                         f'status={jstatus} — one surface is stale')
        if active_jobs and age is not None \
                and age > stale_min * 60:
            flag('LEASE-STALE-WITH-ACTIVE-JOBS', 'warn',
                 'queue/lease',
                 f'lease {int(age)}s old (> {stale_min}m) while '
                 f'{len(active_jobs)} nest_job(s) claim '
                 'claimed/running — runner may be dead')

    sev_rank = {'error': 0, 'warn': 1, 'info': 2}
    findings.sort(key=lambda f: (sev_rank.get(f['severity'], 3),
                                 f['code'], f['subject']))
    counts = {'error': 0, 'warn': 0, 'info': 0}
    for f in findings:
        counts[f['severity']] += 1
    return {'findings': findings, 'lease': lease_info,
            'summary': {'jobs': len(jobs or []),
                        'packs': len(packs),
                        'index_events': len(index),
                        **counts}}


# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--api', default=DEFAULT_API,
                    help='board-api base URL (GET /nest-jobs)')
    ap.add_argument('--jobs-file',
                    help='JSON file with nest_job list — skip the '
                         'board-api read (offline/tests)')
    ap.add_argument('--no-drive', action='store_true',
                    help='skip rclone collectors (jobs-only checks)')
    ap.add_argument('--stale-min', type=int, default=20)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--strict', action='store_true',
                    help='exit 1 on ANY finding (default: error only)')
    args = ap.parse_args()

    errors = []
    if args.jobs_file:
        try:
            with open(args.jobs_file) as f:
                jobs = json.load(f)
            if isinstance(jobs, dict):
                jobs = jobs.get('jobs') or []
        except Exception as e:
            print(f'error: cannot read --jobs-file: {e}', file=sys.stderr)
            return 2
    else:
        try:
            jobs = collect_jobs(args.api)
        except Exception as e:
            print(f'error: /nest-jobs unreachable: {e}', file=sys.stderr)
            return 2

    packs, index, lease = {}, {}, None
    if not args.no_drive:
        packs, e1 = collect_packs()
        if e1:
            errors.append(e1)
        index, e2 = collect_index()
        if e2:
            errors.append(e2)
        lease = collect_lease()

    rep = reconcile(jobs, packs, index, lease,
                    stale_min=args.stale_min)
    rep['errors'] = errors
    rep['generated_at'] = int(time.time())

    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        s = rep['summary']
        print(f"nest-job reconcile: {s['jobs']} jobs, "
              f"{s['packs']} packs, {s['index_events']} index events, "
              f"{s['error']} error / {s['warn']} warn / "
              f"{s['info']} info")
        li = rep['lease']
        if li.get('present'):
            print(f"  lease: job={li.get('job')!r} "
                  f"phase={li.get('phase')!r} worker={li.get('worker')!r}"
                  f" age={li.get('age_s')}s fresh={li.get('fresh')}")
        for f in rep['findings']:
            print(f"  [{f['severity']:5}] {f['code']:28} "
                  f"{f['subject']}: {f['detail']}")
        for e in errors:
            print(f'  [collector] {e}')
        if not rep['findings'] and not errors:
            print('OK — surfaces agree')

    if rep['summary']['error']:
        return 1
    if args.strict and rep['findings']:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
