# ada-nest JOB CONSOLE — CELL 2: start the detached shared queue ONCE.
# Canonical source: scripts/colab/queue-launcher-cell.py (chaba repo);
# deployed copy lives at ada-nest/queue/queue-launcher-cell.py.
#
# Starts queue/runner.py DETACHED (own session, output to Drive) so the
# kernel stays free for diagnostics and the queue survives kernel restart.
#
# Gates, in order — any failure prints why and refuses:
#   1. Drive mounted + runner.py present
#   2. GPU detected (CPU runtimes must not start the GPU queue)
#   3. no OTHER managed runtime fresh in queue/runtime-sessions/ (ambiguous duplicate
#      — see Runtime > Manage Sessions; ALLOW_SECOND_RUNTIME to override)
#   4. runner liveness is boot-scoped: queue/runner.id carries
#      {pid,boot_id,worker,epoch}. A pid is only ever signaled when its
#      recorded boot_id equals THIS VM's — a stale Drive record can name a
#      PID that happens to be alive locally on a different VM, and killing
#      it would be a PID-collision kill (OPS-0872 lesson). Foreign/stale
#      records are left alone; a fresh heartbeat from another boot means the
#      queue is already running elsewhere and we refuse.
# Rerun-safe: a live same-VM runner is reported, a stale-heartbeat same-VM
# zombie is reaped, anything else spawns a fresh detached runner.
import subprocess, os, sys, time, json

ALLOW_SECOND_RUNTIME = False        # deliberate dual-VM escape hatch only
REAP_S = 90                          # heartbeat age that makes a live pid a zombie


def _q():
    return os.environ.get('NEST_QUEUE', '/content/drive/MyDrive/ada-nest/queue')


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
    """Preflight + duplicate check. Returns problems list (empty = go)."""
    q = q or _q()
    sys.path.insert(0, q)
    try:
        import runtime_registry as rr
        return rr.launch_gate(allow_second=ALLOW_SECOND_RUNTIME)
    except ImportError:
        problems = []
        if not os.path.exists(f'{q}/runner.py'):
            problems.append(f'{q}/runner.py missing — is Drive mounted?')
        return problems


def reap(pid):
    try:
        os.kill(int(pid), 15)
        time.sleep(3)
        os.kill(int(pid), 9)
    except ProcessLookupError:
        pass


def spawn(q):
    ts = time.strftime('%Y%m%d-%H%M')
    out = open(f'{q}/run-{ts}.out.log', 'ab')
    p = subprocess.Popen([sys.executable, '-u', f'{q}/runner.py'],
                         stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    print(f'queue pid {p.pid} -> run-{ts}.out.log')
    return p


def main():
    q = _q()
    problems = launch_gate(q)
    if problems:
        raise SystemExit('QUEUE-START REFUSED:\n - ' + '\n - '.join(problems))

    state, detail = runner_state(q)
    print(f'runner state: {state} ({detail})')
    if state == 'alive-local':
        rid = _read_runner_id(q) or {}
        print(f"queue already running, pid {rid.get('pid')}")
    elif state == 'zombie-local':
        rid = _read_runner_id(q) or {}
        print(f"reaping same-VM zombie pid {rid.get('pid')}")
        reap(rid.get('pid'))
        spawn(q)
    elif state == 'alive-elsewhere':
        raise SystemExit(
            'QUEUE-START REFUSED: ' + detail +
            ' — another runtime is mid-queue. Check Runtime > Manage '
            'Sessions; wait for its heartbeat to go stale or finish there.')
    else:
        spawn(q)

    print('watch from fleet: rclone cat gdrive:ada-nest/queue/run-<ts>.out.log')
    print('  heartbeat: queue/heartbeat | done: queue/done/ | preps: queue/prep-*.log')
    print('  identity:  queue/runner.id | runtime-sessions: queue/runtime-sessions/')
    print('  stop it:   Runtime > interrupt execution (kills this VM only)')


if __name__ == '__main__':
    main()
