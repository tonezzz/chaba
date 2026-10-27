# colab-batch-queue runner — IN-KERNEL blocking variant (debug only).
# Paste into ONE code cell, or push via MCP update_cell.
#
# Runs the PINNED releases/<id>/queue/runner.py in the foreground so this
# cell and the detached launcher can never drift on semantics
# (scope/artifacts/markers/release). Prefer queue-launcher-cell.py for
# real work — it verifies + detaches runner.py so the kernel stays free
# and the queue survives kernel restarts. See docs/kb/colab-mcp-jobs.md.
import subprocess, sys, os, json

ROOT = os.environ.get('NEST_ROOT', '/content/drive/MyDrive/ada-nest')
Q = os.environ.get('NEST_QUEUE', f'{ROOT}/queue')

try:
    ptr = json.loads(open(f'{Q}/ACTIVE_RELEASE.json').read())
    rel_id = str(ptr.get('release_id'))
    runner = f'{ROOT}/releases/{rel_id}/queue/runner.py'
except Exception:
    runner = f'{Q}/runner.py'           # unpinned fallback (debug only)

if not os.path.exists(runner):
    raise SystemExit('runner.py missing — is Drive mounted / a release '
                     'published? (run the mount cell)')

# Foreground so stdout streams into this cell's output; the detached
# launcher's run-<ts>.out.log redirect is not used here — heartbeat /
# prep-*.log / done markers are Drive-side either way.
raise SystemExit(
    subprocess.call([sys.executable, '-u', runner])
)
