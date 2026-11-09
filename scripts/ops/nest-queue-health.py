#!/usr/bin/env python3
"""nest-queue-health.py — cheap ada-nest queue snapshot for local consumers.

Writes one small JSON status file (default
~/var/chaba/health/nest-queue-status.json, which is bind-mounted read-only
into the Node-RED container as /var/chaba-health). Read-only against Drive:
a handful of `rclone cat/lsf/lsl` calls — nothing is mutated.

This is the LIGHT sibling of nest-queue-status.py (the full audit: marker
artifact verification, anomaly detection). This probe answers only what a
status surface needs, in a bounded number of Drive calls:

  - queue/heartbeat          (epoch + state; runner liveness signal)
  - queue/runner.id          (present = runner alive; absent = clean exit)
  - queue/lease              (current queue writer)
  - queue/runtime-sessions/  (managed Colab runtimes; freshest = live VM)
  - packs/                   (total pack dirs vs `*/done` marker count)

Extra lane coverage (OPS-1258, added 2026-11-09):

  - kk-llm/            (inbox depth; packs total/done/failed/pending/active
                        claims — the KK-Mac LLM lane)
  - kk-mac-video-pilot/packs (video queue pack counts + active claims)
  - kk worker heartbeat (MDDB ada-nest-heartbeats: age, ollama_ok,
                        load_1m, disk_free_gb — one HTTP call, no ssh)

Usage: nest-queue-health.py [--out PATH] [--quiet]
Exit: 0 always — the snapshot records anomalies; callers stay green.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime, timezone

ROOT = 'gdrive:ada-nest'
Q = f'{ROOT}/queue'
PACKS = f'{ROOT}/packs'
KK_LLM = f'{ROOT}/kk-llm'
KK_VIDEO = f'{ROOT}/kk-mac-video-pilot'
MDDB_URL = 'http://100.102.134.91:11026/v1'
KK_HB_HOST = 'KKs-Mac-Studio'
KK_HB_TAILNET_IP = '100.108.217.17'
KK_HB_STALE_S = 15 * 60
DEFAULT_OUT = os.path.expanduser('~/var/chaba/health/nest-queue-status.json')
# web-served copy — the web quadlet mounts stacks/web/public read-only as
# /srv/public, so this file lands at
# https://tony-dell.taila0626a.ts.net/snapshots/nest-queue-status.json
# for HTTP consumers (Ada nest_status tool). Generated surface file, not
# committed to git.
PUBLISH_OUT = os.path.expanduser(
    '~/CascadeProjects/chaba-tony-dell/stacks/web/public/'
    'snapshots/nest-queue-status.json')
# heartbeat is rewritten every ~15s by a live runner; >20min + no pending
# work just means "done", but >20min with a live runner.id is a stall.
STALE_S = 20 * 60
SESSION_FRESH_S = 5 * 60


def rc(args, timeout=60):
    r = subprocess.run(['rclone'] + args, capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f'rclone {args[0]}: {r.stderr.strip()[:160]}')
    return r.stdout


def cat(path):
    """Content or '' — markers may legitimately be absent (runner.id is
    removed on clean exit)."""
    r = subprocess.run(['rclone', 'cat', path], capture_output=True,
                       text=True, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ''


def lsf(path, extra=None):
    r = subprocess.run(['rclone', 'lsf', path] + (extra or []),
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return []
    return [l.rstrip('/') for l in r.stdout.splitlines() if l.strip()]


def lsl(path):
    """{name: (size, epoch)} — one Drive call for the whole dir."""
    out = {}
    try:
        for line in rc(['lsl', path]).splitlines():
            m = re.match(r'\s*(\d+)\s+(\S+)\s+(\S+)\s+(.+)', line)
            if m:
                size, d, t, name = m.groups()
                try:
                    from datetime import datetime
                    epoch = int(datetime.fromisoformat(
                        f'{d}T{t}+00:00').timestamp())
                except ValueError:
                    epoch = 0
                out[name] = (int(size), epoch)
    except Exception:
        pass
    return out


def parse_hb(text):
    epoch, state = 0, text or '(empty/missing)'
    parts = text.split(None, 1)
    if parts:
        try:
            epoch = int(parts[0])
            state = parts[1] if len(parts) > 1 else ''
        except ValueError:
            pass
    return epoch, state


def mddb_search(collection, url=MDDB_URL):
    req = urllib.request.Request(
        url.rstrip('/') + '/search',
        data=json.dumps({'collection': collection, 'query': '',
                         'limit': 100}).encode(),
        headers={'content-type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=15) as r:
        v = json.load(r)
    return v if isinstance(v, list) else []


def kk_worker_heartbeat(now):
    """KK-Mac lane heartbeat from MDDB ada-nest-heartbeats — the same doc
    the admission gate reads. No ssh: fields come from the heartbeat body."""
    try:
        docs = mddb_search('ada-nest-heartbeats')
    except Exception as e:
        return {'error': f'mddb: {e}'}
    bodies = []
    for doc in docs:
        try:
            b = json.loads(doc.get('contentMd', '{}'))
        except (TypeError, json.JSONDecodeError):
            continue
        if b.get('host') == KK_HB_HOST:
            bodies.append(b)
        elif b.get('tailnet_ip') == KK_HB_TAILNET_IP:
            bodies.append(b)  # LAN-aliased legacy heartbeats
    def _ts(b):
        try:
            raw = b['ts']
            return (float(raw) if isinstance(raw, (int, float)) else
                    datetime.fromisoformat(
                        str(raw).replace('Z', '+00:00')).timestamp())
        except (KeyError, TypeError, ValueError):
            return 0.0
    body = max(bodies, key=_ts) if bodies else None
    if not isinstance(body, dict):
        return {'error': 'heartbeat_missing', 'stale': True}
    try:
        raw_ts = body['ts']
        ts = float(raw_ts) if isinstance(raw_ts, (int, float)) else \
            datetime.fromisoformat(
                str(raw_ts).replace('Z', '+00:00')).timestamp()
        age = max(0, round(now - ts, 1))
    except (KeyError, TypeError, ValueError):
        return {'error': 'heartbeat_invalid', 'stale': True}
    return {
        'host': body.get('host') or KK_HB_HOST,
        'age_s': age,
        'stale': age > KK_HB_STALE_S,
        'ollama_ok': body.get('ollama_ok'),
        'load_1m': body.get('load_1m'),
        'disk_free_gb': body.get('disk_free_gb'),
        'node_busy': body.get('node_busy'),
    }


def pack_stats(remote):
    """One recursive files-only listing -> per-pack marker counts.
    claim/* files on a done/failed pack are normal residue; a claim on a
    live pack is an active claim."""
    stats = {'total': 0, 'done': 0, 'failed': 0,
             'pending': 0, 'active_claims': 0}
    try:
        entries = lsf(f'{remote}/packs', ['--recursive', '--files-only'])
    except Exception as e:
        stats['error'] = str(e)
        return stats
    packs = {}
    for e in entries:
        parts = e.split('/', 1)
        if len(parts) != 2:
            continue
        name, rel = parts
        p = packs.setdefault(
            name, {'done': False, 'failed': False, 'claim': False})
        if rel == 'done':
            p['done'] = True
        elif rel == 'failed':
            p['failed'] = True
        elif rel.startswith('claim/'):
            p['claim'] = True
    stats['total'] = len(packs)
    for p in packs.values():
        if p['done']:
            stats['done'] += 1
        elif p['failed']:
            stats['failed'] += 1
        else:
            stats['pending'] += 1
            if p['claim']:
                stats['active_claims'] += 1
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()
    now = int(time.time())
    snap = {'checked_at': now, 'source': 'nest-queue-health.py',
            'root': ROOT}
    errors = []

    hb_raw = cat(f'{Q}/heartbeat')
    hb_epoch, hb_state = parse_hb(hb_raw)
    hb_age = now - hb_epoch if hb_epoch else None
    snap['heartbeat'] = {'epoch': hb_epoch, 'age_s': hb_age,
                         'state': hb_state}

    rid_raw = cat(f'{Q}/runner.id')
    runner_id = None
    if rid_raw:
        try:
            runner_id = json.loads(rid_raw)
        except json.JSONDecodeError:
            runner_id = {'raw': rid_raw}
    snap['runner_id'] = runner_id
    snap['runner_pid'] = cat(f'{Q}/runner.pid') or None

    lease_raw = cat(f'{Q}/lease')
    lease = None
    if lease_raw:
        try:
            lease = json.loads(lease_raw)
            lease['age_s'] = now - int(lease.get('ts') or 0)
        except (json.JSONDecodeError, TypeError, ValueError):
            lease = {'raw': lease_raw}
    snap['lease'] = lease

    sessions = lsl(f'{Q}/runtime-sessions')
    freshest = None
    for name, (_size, epoch) in sessions.items():
        if freshest is None or epoch > freshest['mtime_epoch']:
            freshest = {'file': name, 'mtime_epoch': epoch}
    if freshest:
        freshest['age_s'] = now - freshest['mtime_epoch']
        try:
            rec = json.loads(cat(
                f"{Q}/runtime-sessions/{freshest['file']}"))
            freshest['boot_id'] = rec.get('boot_id')
            freshest['gpu'] = (rec.get('gpu') if isinstance(
                rec.get('gpu'), str) else (rec.get('gpu') or {}).get(
                'name')) or rec.get('gpu')
            freshest['ts'] = rec.get('ts') or rec.get('last_seen')
            if freshest['ts']:
                freshest['age_s'] = now - int(freshest['ts'])
        except Exception as e:
            errors.append(f'session {freshest["file"]}: {e}')
    snap['sessions'] = {'count': len(sessions), 'freshest': freshest}

    try:
        pack_dirs = lsf(PACKS)
        done_marks = lsf(PACKS, ['--include', '*/done'])
    except Exception as e:
        pack_dirs, done_marks = [], []
        errors.append(f'packs: {e}')
    snap['packs'] = {'total': len(pack_dirs), 'done': len(done_marks),
                     'pending': max(0, len(pack_dirs) - len(done_marks))}

    # --- KK-Mac lanes (kk-llm + video) ---
    kk = pack_stats(KK_LLM)
    try:
        # spec files persist as dedupe keys after their packs are staged —
        # this is total specs received, not unprocessed work
        kk['inbox_specs'] = len(
            [x for x in lsf(f'{KK_LLM}/inbox') if x.endswith('.json')])
    except Exception as e:
        errors.append(f'kk-llm inbox: {e}')
    snap['kk_worker'] = kk_worker_heartbeat(now)
    snap['kk_llm'] = kk

    video = pack_stats(KK_VIDEO)
    vhb_epoch, vhb_state = parse_hb(cat(f'{KK_VIDEO}/queue/heartbeat'))
    video['heartbeat'] = {
        'epoch': vhb_epoch,
        'age_s': (now - vhb_epoch) if vhb_epoch else None,
        'state': vhb_state}
    snap['video'] = video

    # --- verdict ---
    session_live = (freshest is not None
                    and freshest.get('age_s') is not None
                    and freshest['age_s'] < SESSION_FRESH_S)
    if runner_id and hb_age is not None and hb_age <= STALE_S:
        verdict = 'running'
    elif runner_id:
        verdict = 'stale-heartbeat'   # live pid record, dead heartbeat
    elif session_live:
        verdict = 'idle-runtime'      # Colab VM up, queue runner exited
    else:
        verdict = 'drained'           # nothing running anywhere
    if errors and not hb_raw:
        verdict = 'unreadable'
    snap['verdict'] = verdict
    # per-lane verdicts — 'verdict' above stays the general-queue verdict
    # for existing consumers (Node-RED surface)
    kk_hb = snap.get('kk_worker') or {}
    if kk.get('error'):
        kk_verdict = 'unreadable'
    elif kk_hb.get('error') or kk_hb.get('stale'):
        kk_verdict = 'worker-stale'
    elif kk.get('active_claims'):
        kk_verdict = 'claimed'
    elif kk.get('pending'):
        kk_verdict = 'pending'
    else:
        kk_verdict = 'drained'
    if video.get('error'):
        video_verdict = 'unreadable'
    elif video.get('active_claims'):
        video_verdict = 'claimed'
    elif video.get('pending'):
        video_verdict = 'pending'
    else:
        video_verdict = 'drained'
    snap['verdicts'] = {'general': verdict, 'kk_llm': kk_verdict,
                        'video': video_verdict}
    snap['errors'] = errors

    for out in {args.out, PUBLISH_OUT}:
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            tmp = f'{out}.tmp'
            with open(tmp, 'w') as f:
                json.dump(snap, f, indent=2, ensure_ascii=False)
            os.replace(tmp, out)
        except Exception as e:
            errors.append(f'write {out}: {e}')
    if not args.quiet:
        print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
