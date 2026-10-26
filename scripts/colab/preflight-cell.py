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
import os, sys, time, threading

Q = os.environ.get('NEST_QUEUE', '/content/drive/MyDrive/ada-nest/queue')
ALLOW_SECOND_RUNTIME = False        # deliberate dual-VM escape hatch only
HB_S = 60                            # registry refresh cadence


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
