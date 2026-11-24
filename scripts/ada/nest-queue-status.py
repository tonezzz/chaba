#!/usr/bin/env python3
"""nest-queue status — fleet-side truth check for the ada-nest Drive queue.

Run on any host with rclone access to gdrive: (tony-dell is canonical).
Read-only: scans markers/claims/artifacts and reports; it never mutates.

Checks (the things that have actually bitten us):
  - heartbeat age — >STALE_MIN while work is pending = stalled runner
  - false markers — a done marker declares artifacts "Nx<bytes>B" recorded
    at mark time; remote listing must match (the 2026-10-23 save-hf-cache
    incident: marker landed, 13GB tar never did)
  - env markers — env-done/<boot_id>/ listing (per-runtime state)
  - packs — claim/done per pack dir; done marker vs artifacts verify
  - unclaimed packs — published work no worker has taken

Usage: nest-queue-status.py [--json] [--stale-min N]
Exit: 0 ok/drained, 1 anomalies found (stalled runner, false marker).
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time

ROOT = 'gdrive:ada-nest'
Q = f'{ROOT}/queue'
PACKS = f'{ROOT}/packs'
MARKER_RE = re.compile(r'^(?P<dt>\d+)s.*?(?P<arts>(?:\S+=\d+x\d+B ?)+)?$')


def rc(args, timeout=60):
    r = subprocess.run(['rclone'] + args, capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f'rclone {args[0]} failed: {r.stderr.strip()[:200]}')
    return r.stdout


def lsf(path):
    out = rc(['lsf', path])
    return [l.rstrip('/') for l in out.splitlines() if l.strip()]


def lsl(path):
    out = rc(['lsl', path])
    files = {}
    for line in out.splitlines():
        m = re.match(r'\s*(\d+)\s+\S+\s+\S+\s+(.+)', line)
        if m:
            files[m.group(2)] = int(m.group(1))
    return files


def cat(path):
    """Content or '' for absent/empty files — markers may legitimately
    not exist (runner.pid removed on clean exit)."""
    r = subprocess.run(['rclone', 'cat', path], capture_output=True,
                       text=True, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ''


def packs_index():
    """Fold queue/packs-index event files -> {pack: {state, ts, worker}}.

    One rclone copy of the whole dir (ADA-0806): event files are written
    by the Colab runner, nest-worker and nest-pack-submit on every
    claim/done/fail/stage/release. {} when the index is absent — callers
    fall back to live per-pack checks."""
    tmp = tempfile.mkdtemp(prefix='nest-packs-index-')
    try:
        r = subprocess.run(
            ['rclone', 'copy', f'{Q}/packs-index', tmp,
             '--include', '*.json'],
            capture_output=True, text=True, timeout=90)
        if r.returncode != 0:
            return {}
        state = {}
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
            cur = state.get(p)
            if cur is None or ts >= cur['ts']:
                state[p] = {'state': st, 'ts': ts,
                            'worker': ev.get('worker')}
        return state
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def batch_done_markers(dirs):
    """{pack: done-marker text} for every pack dir in ONE rclone copy —
    files-from 'd/done' entries; absent markers simply don't come back.
    Replaces a per-pack `rclone cat` for the common all-done case."""
    if not dirs:
        return {}
    tmp = tempfile.mkdtemp(prefix='nest-done-')
    try:
        lst = os.path.join(tmp, 'files.txt')
        with open(lst, 'w') as f:
            f.write('\n'.join(f'{d}/done' for d in dirs) + '\n')
        dst = os.path.join(tmp, 'out')
        r = subprocess.run(
            ['rclone', 'copy', PACKS, dst, '--files-from', lst],
            capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            return {}
        markers = {}
        for d in dirs:
            fp = os.path.join(dst, d, 'done')
            if os.path.isfile(fp):
                with open(fp) as f:
                    markers[d] = f.read().strip()
        return markers
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def glob_remote(pattern):
    """rclone lsf-style glob vs ada-nest root → {relpath: size}."""
    parent, _, pat = pattern.rpartition('/')
    d = f'{ROOT}/{parent}' if parent else ROOT
    out = rc(['lsf', d, '--format', 'sp', '--include', pat])
    files = {}
    for line in out.splitlines():
        sz, _, name = line.rstrip().rpartition(';')
        name = name.strip()
        if not name or name.endswith('/'):   # dirs always list; skip them
            continue
        try:
            files[f'{parent}/{name}' if parent else name] = int(sz)
        except ValueError:
            pass
    return files


def check_marker_artifacts(text):
    """Parse marker content '<dt>s boot=<id> <glob>=<n>x<size>B ...' →
    [(glob, declared_bytes)] + remote verify verdicts."""
    declared = re.findall(r'(\S+)=(\d+)x(\d+)B', text)
    verdicts = []
    for glob_pat, _n, size in declared:
        remote = glob_remote(glob_pat)
        total = sum(remote.values())
        ok = bool(remote) and total == int(size)
        verdicts.append({
            'glob': glob_pat, 'declared_bytes': int(size),
            'remote_files': len(remote), 'remote_bytes': total,
            'ok': ok,
        })
    return verdicts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--stale-min', type=int, default=20)
    args = ap.parse_args()
    anomalies, report = [], {'checked_at': int(time.time())}

    # --- liveness: queue/lease is the unified file (ADA-0806); the
    # legacy queue/heartbeat text is the pre-unification fallback ---
    hb_epoch, hb_state = 0, ''
    d = {}
    try:
        d = json.loads(cat(f'{Q}/lease'))
        hb_epoch = int(float(d.get('ts') or 0))
        hb_state = ' '.join(x for x in (
            str(d.get('job') or ''), str(d.get('phase') or '')) if x)
    except Exception:
        d = {}
    if not hb_epoch or not hb_state:
        parts = cat(f'{Q}/heartbeat').split()
        if not hb_epoch:
            try:
                hb_epoch = int(parts[0])
            except (ValueError, IndexError):
                pass
        if not hb_state and len(parts) >= 2:
            hb_state = ' '.join(parts[1:])
    if not hb_state:
        hb_state = (str(d.get('worker')) if isinstance(d, dict) else '') \
            or '(empty/missing)'
    hb_age = int(time.time()) - hb_epoch if hb_epoch else None
    report['heartbeat'] = {'epoch': hb_epoch, 'age_s': hb_age,
                           'state': hb_state}
    pid = cat(f'{Q}/runner.pid')
    report['runner_pid'] = pid or None

    # --- work markers ---
    done = {f: cat(f'{Q}/done/{f}') for f in lsf(f'{Q}/done') if f.endswith('.done')}
    report['done'] = {}
    for f, text in done.items():
        verdicts = check_marker_artifacts(text)
        bad = [v for v in verdicts if not v['ok']]
        report['done'][f] = {'text': text, 'artifacts': verdicts}
        if bad:
            anomalies.append(f'FALSE-MARKER {f}: ' +
                             '; '.join(f"{v['glob']} remote={v['remote_bytes']}B "
                                       f"declared={v['declared_bytes']}B" for v in bad))

    # --- env markers (per-runtime) ---
    env = {}
    for boot in lsf(f'{Q}/env-done'):
        env[boot] = lsf(f'{Q}/env-done/{boot}')
    report['env_done'] = env

    # --- packs ---
    # packs-index (ADA-0806) + one batched done-marker fetch keep the
    # enumeration near O(1); live per-pack lsf/cat survives only for packs
    # the index doesn't call terminal — claim state must be read remotely
    # anyway, and the index is advisory, never authoritative.
    idx = packs_index()
    dirs = lsf(PACKS)
    markers = batch_done_markers(dirs)
    packs = {}
    for d in dirs:
        ev = idx.get(d) or {}
        st = ev.get('state')
        done_text = markers.get(d)
        if done_text is None and st not in ('done', 'fail'):
            done_text = cat(f'{PACKS}/{d}/done') or None
        entry = {'claimed_by': [], 'done': done_text or None}
        if entry['done'] is None and st != 'fail':
            entry['claimed_by'] = lsf(f'{PACKS}/{d}/claim')
        elif st in ('done', 'fail') and ev.get('worker'):
            # terminal state — attribution comes from the index event
            # instead of a per-pack claim listing
            entry['claimed_by'] = [ev['worker']]
        if entry['done']:
            entry['artifacts'] = check_marker_artifacts(entry['done'])
            bad = [v for v in entry['artifacts'] if not v['ok']]
            if bad:
                anomalies.append(f'FALSE-MARKER pack {d}')
        elif not entry['claimed_by']:
            anomalies.append(f'UNCLAIMED pack {d}')
        packs[d] = entry
    report['packs'] = packs
    report['packs_index_events'] = len(idx)

    # --- stall detection: live work but dead heartbeat ---
    pending = bool(packs and any(not p['done'] for p in packs.values()))
    if hb_age is not None and hb_age > args.stale_min * 60 and (pending or pid):
        anomalies.append(f'STALE-HEARTBEAT {hb_age}s old, state="{hb_state}"')

    report['anomalies'] = anomalies
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        h = report['heartbeat']
        print(f"heartbeat: {h['state']!r} age={h['age_s']}s pid={report['runner_pid']}")
        for f, e in report['done'].items():
            flag = ' ⚠' if any(not v['ok'] for v in e['artifacts']) else ''
            print(f"  done/{f}: {e['text'][:100]}{flag}")
        for b, jobs in report['env_done'].items():
            print(f"  env-done/{b[:8]}: {len(jobs)} jobs")
        for d, e in packs.items():
            print(f"  pack {d}: claimed_by={e['claimed_by']} done={'yes' if e['done'] else 'no'}")
        for a in anomalies:
            print(f'ANOMALY: {a}')
        if not anomalies:
            print('OK — no anomalies')
    return 1 if anomalies else 0


if __name__ == '__main__':
    sys.exit(main())
