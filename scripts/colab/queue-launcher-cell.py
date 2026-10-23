# colab-batch-queue LAUNCHER — paste into ONE code cell, or push via MCP.
# Starts queue/runner.py DETACHED (own session, output to Drive) so the
# kernel stays free: run diagnostics/df/nvidia-smi cells while it works.
# Survives kernel restart (Drive mount is VM-level); dies only with the VM.
# Rerun-safe: refuses to start a second copy via queue/runner.pid.
import subprocess, os, sys, time

Q = '/content/drive/MyDrive/ada-nest/queue'
pid_f = f'{Q}/runner.pid'

if not os.path.exists(f'{Q}/runner.py'):
    raise SystemExit('runner.py missing — is Drive mounted? (run the mount cell)')

alive = False
if os.path.exists(pid_f):
    try:
        os.kill(int(open(pid_f).read().strip()), 0)
        alive = True
    except (ProcessLookupError, ValueError):
        pass  # stale pid file

if alive:
    print('queue already running, pid', open(pid_f).read().strip())
else:
    ts = time.strftime('%Y%m%d-%H%M')
    out = open(f'{Q}/run-{ts}.out.log', 'ab')
    p = subprocess.Popen([sys.executable, '-u', f'{Q}/runner.py'],
                         stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    print(f'queue pid {p.pid} -> run-{ts}.out.log')

print('watch from fleet: rclone cat gdrive:ada-nest/queue/run-<ts>.out.log')
print('  heartbeat: queue/heartbeat | done: queue/done/ | preps: queue/prep-*.log')
print('  kill it:   kill $(cat queue/runner.pid)   (a cell, or Runtime->restart)')
