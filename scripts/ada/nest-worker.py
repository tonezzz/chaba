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
                      [--scan-only] [--ready-policy auto|required|optional]
"""
import argparse, datetime, glob, json, os, shutil, signal, subprocess
import sys, tempfile, time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:
    import nest_pack_ready as npr
except ImportError:                    # older synced copies ship worker
    npr = None                         # alone — degrade, never crash

REMOTE = 'gdrive:ada-nest'
# /tmp on managed hosts is a small tmpfs (dell: 7.5G) — venvs + synced
# packs belong on the real disk
WORKDIR = os.path.expanduser('~/.cache/nest-worker')
WORKER = None
# fleet hosts keep rclone in ~/.local/bin which non-login shells (ssh,
# systemd units) don't have on PATH — resolve once at start
RCLONE = shutil.which('rclone') or os.path.expanduser('~/.local/bin/rclone')


def rc(*args, check=True, timeout=900):
    r = subprocess.run([RCLONE] + list(args), capture_output=True,
                       text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f'rclone {args[0]}: {r.stderr.strip()[:300]}')
    return r


def lsf(path, recursive=False):
    args = ['lsf', path]
    if recursive:
        args.append('--recursive')
    return [l.rstrip('/') for l in rc(*args, check=False)
            .stdout.splitlines() if l.strip()]


def pack_inventory(remote_root):
    """One remote listing grouped by pack: {pack: {relpath: mtime|None}}.

    Drive/rclone latency dominates small queues when each pack is listed
    separately. A single recursive listing — with modtimes folded into the
    same call — keeps claim/stale-claim semantics unchanged while making
    newly staged packs visible promptly.
    """
    inventory = {}
    for line in rc('lsf', f'{remote_root}/packs', '--recursive',
                   '--format', 'pt', check=False).stdout.splitlines():
        path, _, ts = line.rpartition(';')
        parts = path.rstrip('/').split('/', 1)
        if len(parts) == 1:
            # empty pack dir (half-staged) — keep it visible so the scan
            # still reports 'no pack.yml — skip' like the old per-pack lsf
            if parts[0]:
                inventory.setdefault(parts[0], {})
            continue
        mtime = None
        try:
            mtime = datetime.datetime.strptime(
                ts.strip().split('.')[0], '%Y-%m-%d %H:%M:%S').timestamp()
        except ValueError:
            pass
        inventory.setdefault(parts[0], {})[parts[1]] = mtime
    return inventory


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


def norm_requires(spec):
    reqs = spec.get('requires')
    if isinstance(reqs, str):
        return [reqs]
    if isinstance(reqs, (list, tuple)):
        return [r for r in reqs if isinstance(r, str)]
    return []


def requires_unmet(spec, remote_root, inv=None, meta=None):
    """Claim gate for `requires:` — same contract as the Colab
    queue-runner: every required pack needs a done marker; a *-preflight
    requirement also needs a readable preflight.json verdict pass|warn.
    A failed release preflight therefore blocks dependents on fleet
    workers exactly as on Colab.

    inv/meta let callers pass the batched inventory + metadata fetch
    ({pack: {rel: mtime}}, {rel: text}); without them this falls back to
    one lsf/cat per requirement — the pre-batch behaviour."""
    for req in norm_requires(spec):
        if inv is not None:
            entries = inv.get(req) or {}
        else:
            entries = lsf(f'{remote_root}/packs/{req}')
        if 'done' not in entries:
            return f'requires {req}: not done'
        if 'preflight.json' in entries:
            if meta is not None:
                pj = meta.get(f'{req}/preflight.json', '')
            else:
                pj = cat(f'{remote_root}/packs/{req}/preflight.json')
            try:
                verdict = json.loads(pj).get('verdict')
            except Exception:
                return f'requires {req}: preflight.json unreadable'
            if req.endswith('-preflight'):
                if verdict not in ('pass', 'warn'):
                    return f'requires {req}: preflight verdict {verdict!r}'
            elif verdict == 'fail':
                return f'requires {req}: preflight verdict fail'
        elif req.endswith('-preflight'):
            return f'requires {req}: done but preflight.json missing'
    return ''


READY_REQUIRED_REMOTES = ('/kk-llm', '-kk-llm')


def resolve_ready_policy(remote_root, policy):
    """auto -> 'required' on the dedicated kk-llm queue (producer-managed;
    every pack there is sealed) and 'optional' elsewhere: a present
    marker must validate, an absent marker keeps legacy behaviour so
    older unmarked packs on shared queues are not stranded."""
    if policy != 'auto':
        return policy
    tail = '/' + remote_root.rstrip('/').rsplit('/', 1)[-1] \
        if '/' in remote_root else remote_root
    if any(tail.endswith(sfx) or remote_root.endswith(sfx)
           for sfx in READY_REQUIRED_REMOTES):
        return 'required'
    return 'optional'


def ready_check(remote_root, name, entries, meta, policy):
    """None when the pack may be claimed; a skip reason otherwise.

    required : marker absent -> not claimable (half-staged dirs are
               invisible to the worker); marker must validate.
    optional : absent marker -> claimable (legacy packs); a present
               marker must still validate — a corrupt seal means the
               staging integrity guarantee is broken, never claim.
    One extra lsf --format sp per marked candidate; unmarked packs keep
    the O(1) discovery bound."""
    if 'ready' not in entries:
        if policy == 'required':
            return 'no ready marker — unsealed pack'
        return None
    if npr is None:
        if policy == 'required':
            return 'nest_pack_ready unavailable — cannot validate marker'
        return None
    marker = npr.parse_marker(meta.get(f'{name}/ready', ''))
    if marker is None:
        return 'ready marker unparseable — staging corrupted'
    remote_entries = npr.remote_manifest(
        lambda *a, input_text=None: rc(*a).stdout,
        f'{remote_root}/packs/{name}')
    ok, why = npr.marker_valid(marker, remote_entries)
    return None if ok else f'ready {why}'


def fetch_pack_meta(remote_root, inventory, pending):
    """One batched fetch of every pending pack.yml plus every
    preflight.json on the store — the only metadata discovery needs.
    Returns {relpath: text}; falls back to per-pack cat for pending
    pack.yml if the batch copy fails."""
    want = [f'{d}/pack.yml' for d in pending]
    want += [f'{d}/ready' for d in pending
             if 'ready' in inventory[d]]
    want += [f'{d}/preflight.json' for d, entries in inventory.items()
             if 'preflight.json' in entries and d not in pending]
    texts = {}
    tmp = tempfile.mkdtemp(prefix='nest-scan-')
    try:
        lst = os.path.join(tmp, 'files.txt')
        with open(lst, 'w') as f:
            f.write('\n'.join(sorted(want)) + '\n')
        r = rc('copy', f'{remote_root}/packs', tmp,
               '--files-from', lst, check=False)
        if r.returncode == 0:
            for rel in want:
                fp = os.path.join(tmp, rel)
                if os.path.isfile(fp):
                    with open(fp) as f:
                        texts[rel] = f.read()
        else:
            say(f'  meta fetch failed: {r.stderr.strip()[:200]}'
                ' — per-pack fallback')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for d in pending:
        key = f'{d}/pack.yml'
        if key not in texts:
            texts[key] = cat(f'{remote_root}/packs/{key}')
    return texts


def refresh_requires(spec, remote_root, inventory, meta):
    """Re-list each required pack so a dependency that finished mid-pass
    (our own earlier claim, or another worker's) still unblocks dependents
    in the same pass — drain-in-one-pass, as before batching."""
    for req in norm_requires(spec):
        entries = lsf(f'{remote_root}/packs/{req}')
        inventory[req] = {e: None for e in entries}
        key = f'{req}/preflight.json'
        if 'preflight.json' in entries and key not in meta:
            meta[key] = cat(f'{remote_root}/packs/{key}')


def plan_pass(remote_root, stale_claim_min, ready_policy='auto'):
    """Queue discovery in ~2 rclone calls regardless of pack count: one
    recursive listing (names+mtimes) + one batched metadata fetch.

    Returns (candidates, releases, inventory, meta): candidates are
    [(pack, spec)] in scan order, gated only on static facts (markers,
    claims, pack.yml, needs, ready seal) — `requires` is re-evaluated
    at claim time so mid-pass completions still unblock dependents.
    releases are [(pack, claim, age_s)] stale claims to drop before
    claiming. inventory/meta are the scan-time snapshot main() refreshes
    per requirement at claim time."""
    policy = resolve_ready_policy(remote_root, ready_policy)
    inventory = pack_inventory(remote_root)
    now = time.time()
    releases, pending = [], []
    for d in sorted(inventory):
        entries = inventory[d]
        if 'done' in entries or 'failed' in entries:
            continue
        claims = {rel.split('/', 1)[1]: ts
                  for rel, ts in entries.items()
                  if rel.startswith('claim/')}
        live = False
        for c, ts in claims.items():
            if ts is not None and now - ts > stale_claim_min * 60:
                releases.append((d, c, now - ts))
            else:
                live = True
        if not live:
            pending.append(d)
    # pack.yml presence is already known from the inventory — only packs
    # that have one go into the batched fetch (no per-pack cat at all)
    staged = []
    for d in pending:
        if 'pack.yml' not in inventory[d]:
            say(f'{d}: no pack.yml — skip')
        else:
            staged.append(d)
    meta = fetch_pack_meta(remote_root, inventory, staged)
    import yaml
    candidates = []
    for d in staged:
        py = meta.get(f'{d}/pack.yml', '')
        if not py:
            say(f'{d}: no pack.yml — skip')
            continue
        try:
            spec = yaml.safe_load(py) or {}
        except Exception as e:
            say(f'{d}: bad pack.yml {e} — skip')
            continue
        if not isinstance(spec, dict):
            say(f'{d}: bad pack.yml (not a mapping) — skip')
            continue
        spec.setdefault('name', d)
        # requires is intentionally NOT gated here — it is re-evaluated
        # per pack at claim time so a dependency finished earlier in the
        # pass still unblocks dependents (drain-in-one-pass)
        why = fits(spec.get('needs'))
        if why:
            say(f'{d}: needs unmet ({why}) — skip')
            continue
        why = ready_check(remote_root, d, inventory[d], meta, policy)
        if why:
            say(f'{d}: {why} — skip')
            continue
        candidates.append((d, spec))
    return candidates, releases, inventory, meta


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
    ap.add_argument('--scan-only', action='store_true',
                    help='report discovery plan without claiming — safe '
                         'measurement mode, never touches the queue')
    ap.add_argument('--ready-policy', default='auto',
                    choices=('auto', 'required', 'optional'),
                    help="ready-marker enforcement: 'auto' requires a "
                         "valid marker on the dedicated kk-llm queue and "
                         "validates markers when present elsewhere; "
                         "'required' skips every unsealed pack; "
                         "'optional' only rejects corrupt markers")
    args = ap.parse_args()
    WORKDIR = args.workdir
    host = subprocess.run(['hostname'], capture_output=True,
                          text=True).stdout.strip()
    WORKER = f'{host}-{os.getpid()}'
    CAPS = caps()
    say(f'nest-worker {WORKER} caps={CAPS}')

    t0 = time.time()
    candidates, releases, inventory, meta = plan_pass(
        args.remote, args.stale_claim_min, args.ready_policy)
    say(f'discovery: {len(candidates)} pending, {len(releases)} stale '
        f'claims, {time.time() - t0:.1f}s')
    if args.scan_only:
        for d, c, age in releases:
            say(f'{d}: stale claim {c} ({age:.0f}s) — would release')
        for d, spec in candidates:
            say(f'{d}: pending')
        say('scan complete (no claims made)')
        return

    for d, c, age in releases:
        say(f'{d}: releasing stale claim {c} ({age:.0f}s)')
        rc('deletefile', f'{args.remote}/packs/{d}/claim/{c}', check=False)
    for d, spec in candidates:
        pdir = f'{args.remote}/packs/{d}'
        # requires is re-evaluated at claim time: a dependency finished
        # mid-pass (by this pass or another worker) unblocks dependents —
        # preserves the pre-batch drain-in-one-pass behaviour
        refresh_requires(spec, args.remote, inventory, meta)
        unmet = requires_unmet(spec, args.remote, inventory, meta)
        if unmet:
            say(f'{d}: requires unmet ({unmet}) — skip')
            continue
        # don't contest a claim that landed after the inventory snapshot
        if lsf(f'{pdir}/claim'):
            say(f'{d}: claimed meanwhile — skip')
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
            # Contract failures are terminal for this package. Leaving the
            # pack unmarked causes an invalid model response to retry forever.
            rcat(f'{pdir}/failed', f'{info} worker={WORKER}')
            rc('deletefile', f'{pdir}/claim/{WORKER}', check=False)
    say('pass complete')


if __name__ == '__main__':
    main()
