# ada-nest GAP-RUNNER launcher — paste into ONE code cell, or push via MCP.
# Starts a detached supervisor loop that re-invokes the PINNED
# releases/<id>/queue/gap-runner.py every ~20s (each invocation is a
# single scan pass over the release's gap-packs/).
# Output -> queue/gap-runner.log; loop pid -> queue/gap-runner.pid.
# Rerun-safe: refuses to start a second loop while one's alive.
# The gap runner self-gates on the main heartbeat (fresh prep/prep-wait),
# the VRAM gate, and queue/gap-lease — it is safe to leave this loop up
# for the whole runtime session; it does nothing outside prep gaps.
import subprocess, os, time, json

ROOT = os.environ.get('NEST_ROOT', '/content/drive/MyDrive/ada-nest')
Q = os.environ.get('NEST_QUEUE', f'{ROOT}/queue')
pid_f = f'{Q}/gap-runner.pid'

try:
    ptr = json.loads(open(f'{Q}/ACTIVE_RELEASE.json').read())
    rel_id = str(ptr.get('release_id'))
    gap_runner = f'{ROOT}/releases/{rel_id}/queue/gap-runner.py'
except Exception:
    rel_id = 'unpinned'
    gap_runner = f'{Q}/gap-runner.py'

if not os.path.exists(gap_runner):
    raise SystemExit('gap-runner.py missing — is Drive mounted / a '
                     'release published?')

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
         f'while true; do python3 -u {gap_runner}; sleep 20; done'],
        stdout=out, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True)
    open(pid_f, 'w').write(str(p.pid))
    print(f'gap loop pid {p.pid} release {rel_id} -> gap-runner.log')

print('watch: rclone cat gdrive:ada-nest/queue/gap-runner.log')
print('  heartbeat: queue/gap-heartbeat | lease: queue/gap-lease')
print('  kill it:   kill -- -$(cat queue/gap-runner.pid)')
