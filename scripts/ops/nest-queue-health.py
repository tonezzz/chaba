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

Usage: nest-queue-health.py [--out PATH] [--quiet]
Exit: 0 always — the snapshot records anomalies; callers stay green.
"""
import argparse, json, os, re, subprocess, sys, time

ROOT = 'gdrive:ada-nest'
Q = f'{ROOT}/queue'
PACKS = f'{ROOT}/packs'
DEFAULT_OUT = os.path.expanduser('~/var/chaba/health/nest-queue-status.json')
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
    snap['errors'] = errors

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp = f'{args.out}.tmp'
    with open(tmp, 'w') as f:
        json.dump(snap, f, indent=2, ensure_ascii=False)
    os.replace(tmp, args.out)
    if not args.quiet:
        print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
