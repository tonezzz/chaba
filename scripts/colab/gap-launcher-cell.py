# ada-nest GAP-RUNNER launcher — paste into ONE code cell, or push via MCP.
# Starts a detached supervisor loop that re-invokes queue/gap-runner.py
# every ~20s (each invocation is a single scan pass over gap-packs/).
# Output -> queue/gap-runner.log; loop pid -> queue/gap-runner.pid.
# Rerun-safe: refuses to start a second loop while one's alive.
# The gap runner self-gates on the main heartbeat (fresh prep/prep-wait),
# the VRAM gate, and queue/gap-lease — it is safe to leave this loop up
# for the whole runtime session; it does nothing outside prep gaps.
import subprocess, os, time

Q = '/content/drive/MyDrive/ada-nest/queue'
pid_f = f'{Q}/gap-runner.pid'

if not os.path.exists(f'{Q}/gap-runner.py'):
    raise SystemExit('gap-runner.py missing — is Drive mounted?')

alive = False
if os.path.exists(pid_f):
    try:
        os.kill(int(open(pid_f).read().strip()), 0)
        alive = True
    except (ProcessLookupError, ValueError):
        pass

if alive:
    print('gap loop already running, pid', open(pid_f).read().strip())
else:
    out = open(f'{Q}/gap-runner.log', 'ab')
    p = subprocess.Popen(
        ['bash', '-lc',
         f'while true; do python3 -u {Q}/gap-runner.py; sleep 20; done'],
        stdout=out, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True)
    open(pid_f, 'w').write(str(p.pid))
    print(f'gap loop pid {p.pid} -> gap-runner.log')

print('watch: rclone cat gdrive:ada-nest/queue/gap-runner.log')
print('  heartbeat: queue/gap-heartbeat | lease: queue/gap-lease')
print('  kill it:   kill -- -$(cat queue/gap-runner.pid)')
