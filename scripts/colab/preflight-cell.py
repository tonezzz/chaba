# ada-nest JOB CONSOLE — CELL 1: mount Drive, identify + register this
# managed runtime, refuse ambiguous duplicate launches. Run ONCE per session,
# before CELL 2. Canonical source: scripts/colab/preflight-cell.py (chaba
# repo); deployed copy lives at ada-nest/queue/preflight-cell.py.
#
# What it does:
#   1. mounts Google Drive at /content/drive
#   2. prints this VM's identity: boot_id, GPU model/VRAM, RAM, Drive state
#   3. registers the VM at queue/runtime-sessions/<boot_id>.json and refreshes it
#      on a background heartbeat while this notebook stays open
#   4. if ANOTHER managed runtime's record is still fresh (<TTL), refuses —
#      a second console session is ambiguous: it may be about to launch its
#      own queue. Resolve via Google Runtime > Manage Sessions (authoritative
#      for ALL sessions incl. uninstrumented notebooks) or re-run after the
#      peer goes stale (~5 min). Deliberate two-VM ops: set
#      ALLOW_SECOND_RUNTIME = True below and re-run — the queue lease then
#      arbitrates writers.
#
# Nothing here stops or kills another session — ever. Unknown/uninstrumented
# sessions are Google's UI problem, not ours.
import contextlib
import glob
import io
import json
import os
import runpy
import sys
import threading
import time
import uuid

Q = os.environ.get('NEST_QUEUE', '/content/drive/MyDrive/ada-nest/queue')
ALLOW_SECOND_RUNTIME = False        # deliberate dual-VM escape hatch only
HB_S = 60                            # registry refresh cadence
CONTROL_POLL_S = 5
CONTROL_TTL_S = 300


def mount_drive():
    if os.environ.get('NEST_ROOT'):
        return 'sandbox NEST_ROOT — skipping drive.mount'
    from google.colab import drive
    drive.mount('/content/drive')
    return 'drive mounted at /content/drive'


def heartbeat_loop(rr):
    while True:
        time.sleep(HB_S)
        try:
            rr.register()
        except Exception:
            pass


def _write_control_ack(q, request_id, target_boot_id, status, message):
    ack_dir = os.path.join(q, 'control', 'acks')
    os.makedirs(ack_dir, exist_ok=True)
    ack_path = os.path.join(ack_dir, f'{request_id}.json')
    tmp = f'{ack_path}.{uuid.uuid4().hex}.tmp'
    with open(tmp, 'w') as f:
        json.dump({
            'request_id': request_id,
            'target_boot_id': target_boot_id,
            'status': status,
            'message': str(message)[-2000:],
            'handled_at': time.time(),
        }, f)
        f.write('\n')
    os.replace(tmp, ack_path)
    return ack_path


def process_control_request(request_path, boot_id, queue_dir=None,
                            launcher_main=None):
    """Handle one managed-runtime command; foreign requests are left alone."""
    q = queue_dir or Q
    request_id = os.path.basename(request_path).removesuffix('.json')
    ack_path = os.path.join(q, 'control', 'acks', f'{request_id}.json')
    if os.path.exists(ack_path):
        return {'status': 'already-acked', 'request_id': request_id}

    try:
        with open(request_path) as f:
            request = json.load(f)
    except Exception as exc:
        return {'status': 'unreadable', 'request_id': request_id,
                'message': str(exc)}
    target = str(request.get('target_boot_id') or '')
    if target != boot_id:
        return {'status': 'not-targeted', 'request_id': request_id}
    if request.get('request_id') != request_id:
        return {'status': 'invalid', 'request_id': request_id,
                'message': 'request id does not match filename'}
    if request.get('confirmed') is not True:
        _write_control_ack(q, request_id, target, 'rejected',
                           'explicit MCP confirmation is required')
        return {'status': 'rejected', 'request_id': request_id}
    try:
        age = time.time() - float(request.get('created_at') or 0)
    except (TypeError, ValueError):
        _write_control_ack(q, request_id, target, 'rejected',
                           'request created_at is invalid')
        return {'status': 'rejected', 'request_id': request_id}
    if age > CONTROL_TTL_S:
        _write_control_ack(q, request_id, target, 'expired',
                           f'request expired ({age:.0f}s old)')
        return {'status': 'expired', 'request_id': request_id}
    if request.get('command') != 'start_queue':
        _write_control_ack(q, request_id, target, 'rejected',
                           f"unsupported command: {request.get('command')!r}")
        return {'status': 'rejected', 'request_id': request_id}

    output = io.StringIO()
    try:
        if launcher_main is None:
            launcher = runpy.run_path(
                os.path.join(q, 'queue-launcher-cell.py'),
                run_name='mcp_queue_launcher')
            launcher_main = launcher['main']
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            launcher_main()
        message = output.getvalue()
        status = ('already-running' if 'queue already running' in message
                  else 'started')
    except SystemExit as exc:
        message = output.getvalue() + str(exc)
        status = 'refused'
    except Exception as exc:
        message = output.getvalue() + repr(exc)
        status = 'error'

    _write_control_ack(q, request_id, target, status, message)
    return {'status': status, 'request_id': request_id, 'message': message}


def control_watcher_loop(queue_dir, boot_id):
    """Listen for MCP requests directed at this already-running runtime."""
    requests = os.path.join(queue_dir, 'control', 'requests')
    while True:
        for path in sorted(glob.glob(os.path.join(requests, '*.json'))):
            try:
                process_control_request(path, boot_id, queue_dir=queue_dir)
            except Exception:
                continue
        time.sleep(CONTROL_POLL_S)


def main():
    print(mount_drive())
    sys.path.insert(0, Q)
    import runtime_registry as rr
    fresh = rr.peers()
    if fresh and not ALLOW_SECOND_RUNTIME:
        names = '; '.join(rr.fmt_runtime(p) for p in fresh)
        raise SystemExit(
            'REFUSED: another managed runtime is fresh: ' + names +
            ' — ambiguous duplicate launch. Check Runtime > Manage Sessions; '
            'to run a second VM deliberately set ALLOW_SECOND_RUNTIME = True '
            'in this cell and re-run.')

    rec = rr.register()
    print(f"runtime: boot {rec['boot_id'][:8]}  gpu "
          f"{rec['gpu'] or 'NONE'} {rec['gpu_gb']:.1f}GB  ram {rec['ram_gb']}GB"
          f"  drive_mounted={rec['drive_mounted']}")
    print(f"registered -> {Q}/runtime-sessions/{rec['boot_id']}.json"
          f"  (heartbeat every {HB_S}s, ttl {rr.ttl_s():.0f}s)")
    threading.Thread(target=heartbeat_loop, args=(rr,), daemon=True).start()
    if not os.environ.get('NEST_ROOT'):
        control_boot = rec['boot_id']
        started = globals().setdefault('_NEST_CONTROL_WATCHERS', set())
        if control_boot not in started:
            started.add(control_boot)
            threading.Thread(
                target=control_watcher_loop, args=(Q, control_boot),
                daemon=True).start()
            print('MCP queue-start control ready for this runtime.')

    if fresh:
        print('NOTE: proceeding alongside fresh peer(s) '
              '(ALLOW_SECOND_RUNTIME): ' +
              '; '.join(rr.fmt_runtime(p) for p in fresh))
    old = rr.stale()
    if old:
        print('stale registry records (idle info only): '
              + '; '.join(rr.fmt_runtime(p) for p in old))
    if not rec['gpu']:
        print('NOTE: no GPU on this runtime — cell 2 will refuse to start '
              'the queue (Runtime > Change runtime type > T4).')
    print('PREFLIGHT-OK — run cell 2 to start the shared queue once.')


if __name__ == '__main__':
    main()
