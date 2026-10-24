#!/usr/bin/env python3
"""nest-worker — fleet-side pack worker. Same protocol as colab's
runner.py, over rclone instead of a Drive FUSE mount. Runs on dell,
omen, idc — any host with rclone gdrive: access.

Loop: scan gdrive:ada-nest/packs/ -> for each undone, unclaimed pack
whose `needs` fit this host's caps: claim (first-writer-wins claim
file) -> sync pack dir to local workdir -> run prep (shell) then
run|run_sh (python exec / shell) -> verify artifacts REMOTE-side ->
write done marker.

Packs address the store via $NEST_ROOT (local sync root here, the
/content/drive mount on Colab) and $PACK_DIR for their own dir —
pack code must use those, never hardcode /content/drive.

Usage: nest-worker.py [--once] [--remote gdrive:ada-nest]
                      [--workdir /tmp/nest-worker] [--stale-claim-min 60]
"""
import argparse, glob, json, os, re, shutil, signal, subprocess, sys, time

REMOTE = 'gdrive:ada-nest'
# /tmp on managed hosts is a small tmpfs (dell: 7.5G) — venvs + synced
# packs belong on the real disk
WORKDIR = os.path.expanduser('~/.cache/nest-worker')
WORKER = None
# fleet hosts keep rclone in ~/.local/bin which non-login shells (ssh,
# systemd units) don't have on PATH — resolve once at start
RCLONE = shutil.which('rclone') or os.path.expanduser('~/.local/bin/rclone')


def rc(*args, check=True):
    r = subprocess.run([RCLONE] + list(args), capture_output=True,
                       text=True, timeout=300)
    if check and r.returncode != 0:
        raise RuntimeError(f'rclone {args[0]}: {r.stderr.strip()[:300]}')
    return r


def lsf(path):
    return [l.rstrip('/') for l in rc('lsf', path, check=False)
            .stdout.splitlines() if l.strip()]


def rcat(path, text):
    r = subprocess.run([RCLONE, 'rcat', path], input=text,
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f'rcat {path}: {r.stderr.strip()[:200]}')


def cat(path):
    r = rc('cat', path, check=False)
    return r.stdout.strip() if r.returncode == 0 else ''


def caps():
    c = {'gpu_gb': 0.0, 'disk_gb': 0.0, 'egress_only_ok': False, 'ram_gb': 0.0}
    try:
        m = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1e9
        c['ram_gb'] = round(m, 1)
    except Exception:
        pass
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=memory.total',
                            '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=10)
        c['gpu_gb'] = float(r.stdout.strip().split()[0]) / 1024
    except Exception:
        pass
    st = os.statvfs('/')
    c['disk_gb'] = st.f_bavail * st.f_frsize / 1e9
    return c


def fits(needs):
    c = CAPS
    for k, v in (needs or {}).items():
        if k == 'egress_only_ok':
            continue                       # fleet can always egress
        if c.get(k, 0) < v:
            return f'{k} {c.get(k,0):.1f} < {v}'
    return ''


def say(msg):
    print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)


def glob_remote(remote_root, pattern):
    """{relpath: size} for glob vs ada-nest root — remote truth."""
    parent, _, pat = pattern.rpartition('/')
    d = f'{remote_root}/{parent}' if parent else remote_root
    out = rc('lsf', d, '--format', 'sp', '--include', pat,
             check=False).stdout
    files = {}
    for line in out.splitlines():
        sz, _, name = line.rstrip().rpartition(';')
        name = name.strip()
        if not name or name.endswith('/'):
            continue
        try:
            files[name] = int(sz)
        except ValueError:
            pass
    return files


def verify_artifacts(spec, remote_root):
    for p in (spec.get('artifacts') or []):
        hits = glob_remote(remote_root, p)
        if not hits:
            return False, p
    return True, ''


def run_pack(name, spec, remote_root):
    """Local execution of one claimed pack. Returns (ok, info)."""
    local = f'{WORKDIR}/{name}'
    if os.path.exists(local):
        shutil.rmtree(local)
    os.makedirs(local)
    # sync the pack down (inputs/ etc.) — artifacts write back after run
    r = rc('copy', f'{remote_root}/packs/{name}', local,
           '--exclude', 'claim/**', '--exclude', 'done', check=False)
    if r.returncode != 0:
        say(f'  sync-down failed: {r.stderr.strip()[:200]}')

    # fetch: extra store paths the pack reads via $NEST_ROOT (on Colab the
    # mount covers them; fleet workers must materialize them locally).
    # Trailing slash = directory; otherwise a single file.
    fetched = []
    for rel in (spec.get('fetch') or []):
        if rel.endswith('/'):
            r = rc('copy', f'{remote_root}/{rel}', f'{local}/{rel}',
                   check=False)
        else:
            os.makedirs(os.path.dirname(f'{local}/{rel}'), exist_ok=True)
            r = rc('copyto', f'{remote_root}/{rel}', f'{local}/{rel}',
                   check=False)
        if r.returncode != 0:
            say(f'  fetch {rel}: {r.stderr.strip()[:200]}')
            return False, f'fetch failed: {rel}'
        fetched.append(rel.rstrip('/') + ('/**' if rel.endswith('/') else ''))

    env = dict(os.environ, NEST_ROOT=local, PACK_DIR=local)
    pyexe = sys.executable
    if spec.get('venv'):
        # PEP-668 hosts (dell/omen) block system pip — per-pack venv keeps
        # pack preps working identically to Colab's permissive env.
        venv = f'{local}/.venv'
        if not os.path.exists(venv):
            r = subprocess.run([sys.executable, '-m', 'venv', venv],
                               env=env, timeout=300)
            if r.returncode != 0:
                return False, 'venv create failed'
        pyexe = f'{venv}/bin/python'
        env['PATH'] = f'{venv}/bin:{env["PATH"]}'

    if spec.get('prep'):
        say(f'  prep: {spec["prep"][:80]}')
        r = subprocess.run(spec['prep'], shell=True, env=env,
                           cwd=local, timeout=int(spec.get('timeout_s') or 3600))
        if r.returncode != 0:
            return False, f'prep rc={r.returncode}'

    t0 = time.time()
    if spec.get('run_sh'):
        r = subprocess.run(spec['run_sh'], shell=True, env=env, cwd=local,
                           timeout=int(spec.get('timeout_s') or 3600))
        if r.returncode != 0:
            return False, f'run_sh rc={r.returncode}'
    elif spec.get('venv'):
        # run in venv: wrap source with the same injected globals so pack
        # code is byte-identical to the Colab exec path
        hdr = (f"PACK_DIR={local!r}\nNEST_ROOT={local!r}\n"
               f"import os\n")
        open(f'{local}/_run.py', 'w').write(hdr + spec['run'])
        r = subprocess.run([pyexe, '_run.py'], env=env, cwd=local,
                           timeout=int(spec.get('timeout_s') or 3600))
        if r.returncode != 0:
            return False, f'run rc={r.returncode}'
    else:
        ns = {'PACK_DIR': local, 'NEST_ROOT': local}
        try:
            exec(compile(spec['run'], f'<{name}>', 'exec'), ns)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f'run: {e}'
    dt = time.time() - t0

    # push everything back (out/, report.md, refs stay local — pack
    # decides what it publishes by writing under its own dir). Never push
    # the execution env or fetched inputs — already on the store.
    excl = (['--exclude', 'claim/**', '--exclude', 'done',
             '--exclude', '.venv/**', '--exclude', '_run.py'] +
            [x for rel in fetched for x in ('--exclude', rel)])
    rc('copy', local, f'{remote_root}/packs/{name}', *excl, check=False)
    # publish: {pack-rel src prefix: store-rel dest prefix} — packs that
    # produce store-side assets (keyframes, caches) outside their own dir.
    # On Colab the same writes go straight to the mount; this is the
    # fleet-side equivalent.
    for src, dest in (spec.get('publish') or {}).items():
        r = rc('copy', f'{local}/{src.rstrip("/")}',
               f'{remote_root}/{dest.rstrip("/")}', check=False)
        if r.returncode != 0:
            say(f'  publish {src} -> {dest}: {r.stderr.strip()[:200]}')
            return False, f'publish failed: {src}'
    ok, missing = verify_artifacts(spec, remote_root)
    if not ok:
        return False, f'artifacts missing remote: {missing}'
    arts = ' '.join(f'{p}={len(glob_remote(remote_root,p))}x'
                    f'{sum(glob_remote(remote_root,p).values())}B'
                    for p in (spec.get('artifacts') or []))
    return True, f'{dt:.0f}s {arts}'


def main():
    global WORKER, CAPS, WORKDIR
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true',
                    help='process currently-claimable packs then exit')
    ap.add_argument('--remote', default=REMOTE)
    ap.add_argument('--workdir', default=WORKDIR)
    ap.add_argument('--stale-claim-min', type=int, default=60)
    args = ap.parse_args()
    WORKDIR = args.workdir
    host = subprocess.run(['hostname'], capture_output=True,
                          text=True).stdout.strip()
    WORKER = f'{host}-{os.getpid()}'
    CAPS = caps()
    say(f'nest-worker {WORKER} caps={CAPS}')

    for d in sorted(lsf(f'{args.remote}/packs')):
        pdir = f'{args.remote}/packs/{d}'
        entries = lsf(pdir)
        if 'done' in entries:
            continue
        claims = lsf(f'{pdir}/claim')
        if claims:
            # stale-claim release: claim file older than N min + no done
            # → previous worker died. lsl gives us mtime.
            stale = False
            for c in claims:
                r = rc('lsl', f'{pdir}/claim/{c}', check=False).stdout
                m = re.match(r'\s*\d+\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})', r)
                if m:
                    import datetime
                    ts = datetime.datetime.strptime(
                        f'{m.group(1)} {m.group(2)}', '%Y-%m-%d %H:%M:%S')
                    age = time.time() - ts.timestamp()
                    if age > args.stale_claim_min * 60:
                        say(f'{d}: releasing stale claim {c} ({age:.0f}s)')
                        rc('deletefile', f'{pdir}/claim/{c}', check=False)
                        stale = True
            if not stale and claims:
                continue
            if lsf(f'{pdir}/claim'):
                continue
        py = cat(f'{pdir}/pack.yml')
        if not py:
            say(f'{d}: no pack.yml — skip')
            continue
        try:
            import yaml
            spec = yaml.safe_load(py) or {}
        except Exception as e:
            say(f'{d}: bad pack.yml {e} — skip')
            continue
        spec.setdefault('name', d)
        why = fits(spec.get('needs'))
        if why:
            say(f'{d}: needs unmet ({why}) — skip')
            continue
        # claim: write worker file, settle, verify first-claimer wins
        rcat(f'{pdir}/claim/{WORKER}', str(int(time.time())))
        time.sleep(3)
        if sorted(lsf(f'{pdir}/claim'))[0] != WORKER:
            say(f'{d}: lost claim race — skip')
            # remove our own losing claim file — otherwise it lingers
            # and can poison the pack for the 60min stale-claim window
            rc('deletefile', f'{pdir}/claim/{WORKER}', check=False)
            continue
        say(f'{d}: CLAIMED — running')
        ok, info = run_pack(d, spec, args.remote)
        if ok:
            rcat(f'{pdir}/done', f'{info} worker={WORKER}')
            say(f'{d}: DONE {info}')
        else:
            say(f'{d}: FAIL {info}')
            rc('deletefile', f'{pdir}/claim/{WORKER}', check=False)
    say('pass complete')


if __name__ == '__main__':
    main()
