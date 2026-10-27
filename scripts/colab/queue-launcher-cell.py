# ada-nest JOB CONSOLE — CELL 2: start the detached shared queue ONCE.
# Canonical source: scripts/colab/queue-launcher-cell.py (chaba repo);
# the pinned copy lives at ada-nest/releases/<id>/queue/
# queue-launcher-cell.py (the control watcher invokes THAT copy).
#
# Starts releases/<id>/queue/runner.py DETACHED (own session, output to
# Drive) so the kernel stays free for diagnostics and the queue survives
# kernel restart.
#
# Gates, in order — any failure prints why and refuses:
#   1. Drive mounted + runner present
#   2. RELEASE PINNED + VERIFIED — queue/ACTIVE_RELEASE.json resolves to
#      releases/<id>/ whose release.json sha256 matches the pointer, and
#      every declared file (runner, JOBS.py, cells, pack manifests and
#      inputs) matches its recorded sha256, with nothing undeclared in the
#      dir. The deployed queue/ada-nest-job-console.ipynb must also be
#      byte-identical to the released notebook.
#   3. GPU detected (CPU runtimes must not start the GPU queue)
#   4. no OTHER managed runtime fresh in queue/runtime-sessions/ (ambiguous
#      duplicate — see Runtime > Manage Sessions; ALLOW_SECOND_RUNTIME to
#      override)
#   5. runner liveness is boot-scoped: queue/runner.id carries
#      {pid,boot_id,worker,epoch,release}. A pid is only ever signaled when
#      its recorded boot_id equals THIS VM's — a stale Drive record can
#      name a PID that happens to be alive locally on a different VM, and
#      killing it would be a PID-collision kill (OPS-0872 lesson).
#      Foreign/stale records are left alone; a fresh heartbeat from
#      another boot means the queue is already running elsewhere and we
#      refuse.
# Rerun-safe: a live same-VM runner is reported, a stale-heartbeat same-VM
# zombie is reaped, anything else spawns a fresh detached runner.
import subprocess, os, sys, time, json

ALLOW_SECOND_RUNTIME = False        # deliberate dual-VM escape hatch only
REAP_S = 90                          # heartbeat age that makes a live pid a zombie

_ROOT = os.environ.get('NEST_ROOT', '/content/drive/MyDrive/ada-nest')


def _q():
    return os.environ.get('NEST_QUEUE', f'{_ROOT}/queue')


def _sha256(p):
    import hashlib
    h = hashlib.sha256()
    try:
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def _load_module(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def release_state(q=None):
    """Resolve + verify the pinned release.
    -> (status, info, rel_id, rel_dir, manifest, rl)
    status: 'pinned' (problems=[] means verified), 'unpinned' (no pointer —
            launch REFUSES in the pinned era), 'bad'.
    rl is the hash-checked release_lib module — imported only after its own
    sha is proven, then it verifies every remaining file."""
    q = q or _q()
    try:
        ptr = json.loads(open(f'{q}/ACTIVE_RELEASE.json').read())
    except Exception as e:
        if os.path.exists(f'{q}/ACTIVE_RELEASE.json'):
            return ('bad', f'ACTIVE_RELEASE.json unreadable ({e})',
                    None, None, None, None)
        return ('unpinned', 'no queue/ACTIVE_RELEASE.json — no pinned '
                'release has been published yet', None, None, None, None)
    rel_id = str(ptr.get('release_id'))
    rel_dir = f'{_ROOT}/releases/{rel_id}'
    rel_q = f'{rel_dir}/queue'
    manifest_path = f'{rel_dir}/release.json'
    try:
        manifest = json.loads(open(manifest_path).read())
    except Exception as e:
        return ('bad', f'{rel_id}: release.json unreadable ({e})',
                rel_id, rel_dir, None, None)
    want_sha = str(ptr.get('release_sha256') or '')
    got_sha = _sha256(manifest_path)
    if want_sha and got_sha != want_sha:
        return ('bad', f'{rel_id}: release.json sha {str(got_sha)[:12]} '
                f'!= pointer {want_sha[:12]}', rel_id, rel_dir, None, None)
    files = manifest.get('files') or {}
    want_lib = files.get('queue/release_lib.py')
    lib = f'{rel_q}/release_lib.py'
    if not want_lib or _sha256(lib) != want_lib:
        return ('bad', f'{rel_id}: release_lib.py missing/tampered',
                rel_id, rel_dir, None, None)
    try:
        rl = _load_module(lib, 'nest_release_lib')
    except Exception as e:
        return ('bad', f'{rel_id}: release_lib import failed ({e})',
                rel_id, rel_dir, None, None)
    problems = rl.verify_release(_ROOT, rel_id, manifest)
    # the operator surface itself must be the released notebook — a
    # replaced/edited deployed copy is a launch-refusing mismatch.
    want_nb = files.get('queue/ada-nest-job-console.ipynb')
    deployed_nb = f'{q}/ada-nest-job-console.ipynb'
    if want_nb:
        got_nb = _sha256(deployed_nb)
        if got_nb != want_nb:
            problems.append(
                'deployed queue/ada-nest-job-console.ipynb does not match '
                'the pinned release — this notebook is not the released '
                'operator surface (re-run the publisher or open the '
                'release notebook)')
    else:
        problems.append('manifest lacks queue/ada-nest-job-console.ipynb')
    if problems:
        return ('bad', problems, rel_id, rel_dir, manifest, rl)
    return ('pinned', 'verified', rel_id, rel_dir, manifest, rl)


def _boot_id():
    try:
        return open('/proc/sys/kernel/random/boot_id').read().strip()
    except OSError:
        return 'noboot-' + time.strftime('%Y%m%d-%H%M')


def _heartbeat_age(q):
    try:
        return time.time() - float(open(f'{q}/heartbeat').read().split()[0])
    except Exception:
        return float('inf')


def _read_runner_id(q):
    try:
        return json.loads(open(f'{q}/runner.id').read())
    except Exception:
        return None


def _pid_alive(pid):
    """Signal-0 liveness — ONLY ever called on pids whose runner.id boot_id
    already matched THIS VM. Never call on a Drive-recorded foreign pid."""
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, PermissionError):
        return False


def runner_state(q=None):
    """(state, detail) —
    'alive-local'      our VM's runner is up and heartbeating
    'zombie-local'     our VM's runner pid lives but heartbeat is stale (reap)
    'alive-elsewhere'  fresh queue heartbeat owned by another boot — refuse
    'free'             no live runner anywhere we can prove
    """
    q = q or _q()
    rid = _read_runner_id(q)
    hb = _heartbeat_age(q)
    me = _boot_id()
    if rid and str(rid.get('boot_id')) == me:
        pid = rid.get('pid')
        if pid and _pid_alive(pid):
            if hb <= REAP_S:
                return 'alive-local', f"pid {pid} heartbeat {hb:.0f}s"
            return 'zombie-local', f"pid {pid} heartbeat {hb:.0f}s stale"
        return 'free', f'same-boot runner.id pid {pid} not alive'
    if rid:
        if hb <= REAP_S:
            return ('alive-elsewhere',
                    f"runner.id names other boot {str(rid.get('boot_id'))[:8]} "
                    f"worker {rid.get('worker')} — queue heartbeat {hb:.0f}s fresh")
        return 'free', (f"foreign runner.id (boot {str(rid.get('boot_id'))[:8]}) "
                        f"stale — never signaling pid {rid.get('pid')}")
    # legacy runner.pid (bare number, no boot attribution): it is NOT a process
    # handle on this VM — never os.kill it. Queue heartbeat is the only signal.
    legacy = os.path.exists(f'{q}/runner.pid')
    if hb <= REAP_S:
        return 'alive-elsewhere', (f'fresh queue heartbeat ({hb:.0f}s) with '
                                   + ('legacy runner.pid' if legacy else 'no runner.id')
                                   + ' — queue active on another runtime')
    return 'free', ('legacy runner.pid' if legacy else 'no runner record') + \
                   f', heartbeat {hb if hb != float("inf") else "absent"}'


def launch_gate(q=None):
    """Preflight + release verify + duplicate check -> problems list
    (empty = go)."""
    q = q or _q()
    problems = []
    status, info, rel_id, rel_dir, manifest, rl = release_state(q)
    if status != 'pinned':
        if isinstance(info, list):
            problems += info
        else:
            problems.append(info)
        if status == 'unpinned':
            problems.append('publish a release first '
                            '(scripts/colab/publish-release.py on idc02) — '
                            'the queue refuses to run unversioned code')
        return problems, None
    try:
        rr = _load_module(f'{rel_dir}/queue/runtime_registry.py',
                          'nest_runtime_registry')
        problems += rr.launch_gate(
            allow_second=ALLOW_SECOND_RUNTIME,
            runner_path=f'{rel_dir}/queue/runner.py')
    except FileNotFoundError:
        problems.append(f'{rel_dir}/queue/runtime_registry.py missing')
    return problems, (rel_id, rel_dir, manifest)


def reap(pid):
    try:
        os.kill(int(pid), 15)
        time.sleep(3)
        os.kill(int(pid), 9)
    except ProcessLookupError:
        pass


def spawn(q, rel_id, rel_dir, manifest_sha=''):
    ts = time.strftime('%Y%m%d-%H%M')
    out = open(f'{q}/run-{ts}.out.log', 'ab')
    env = dict(os.environ,
               NEST_RELEASE_ID=rel_id,
               NEST_RELEASE_DIR=rel_dir,
               NEST_RELEASE_SHA=manifest_sha)
    p = subprocess.Popen([sys.executable, '-u', f'{rel_dir}/queue/runner.py'],
                         stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True,
                         env=env)
    print(f'queue pid {p.pid} release {rel_id} -> run-{ts}.out.log')
    return p


def main():
    q = _q()
    problems, rel = launch_gate(q)
    if problems:
        raise SystemExit('QUEUE-START REFUSED:\n - ' + '\n - '.join(problems))
    rel_id, rel_dir, manifest = rel
    print(f'release: {rel_id} verified '
          f'(commit {str(manifest.get("commit"))[:12]}, '
          f'{len(manifest.get("files") or {})} files)')

    state, detail = runner_state(q)
    print(f'runner state: {state} ({detail})')
    if state == 'alive-local':
        rid = _read_runner_id(q) or {}
        print(f"queue already running, pid {rid.get('pid')} "
              f"release {rid.get('release')}")
    elif state == 'zombie-local':
        rid = _read_runner_id(q) or {}
        print(f"reaping same-VM zombie pid {rid.get('pid')}")
        reap(rid.get('pid'))
        spawn(q, rel_id, rel_dir, _sha256(f'{rel_dir}/release.json'))
    elif state == 'alive-elsewhere':
        raise SystemExit(
            'QUEUE-START REFUSED: ' + detail +
            ' — another runtime is mid-queue. Check Runtime > Manage '
            'Sessions; wait for its heartbeat to go stale or finish there.')
    else:
        spawn(q, rel_id, rel_dir, _sha256(f'{rel_dir}/release.json'))

    print('watch from fleet: rclone cat gdrive:ada-nest/queue/run-<ts>.out.log')
    print('  heartbeat: queue/heartbeat | done: queue/done/ | preps: queue/prep-*.log')
    print('  identity:  queue/runner.id | runtime-sessions: queue/runtime-sessions/')
    print('  release:   queue/ACTIVE_RELEASE.json | rollback: repoint to an older release')
    print('  stop it:   Runtime > interrupt execution (kills this VM only)')


if __name__ == '__main__':
    main()
