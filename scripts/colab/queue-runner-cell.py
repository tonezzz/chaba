# colab-batch-queue runner — IN-KERNEL blocking variant (debug only).
# Paste into ONE code cell, or push via MCP update_cell.
#
# Runs the CANONICAL queue/runner.py in the foreground so this cell and the
# detached launcher can never drift on semantics (scope/artifacts/markers).
# Prefer queue-launcher-cell.py for real work — it detaches runner.py so the
# kernel stays free and the queue survives kernel restarts.
# See docs/kb/colab-mcp-jobs.md.
import subprocess, sys, os

Q = '/content/drive/MyDrive/ada-nest/queue'

if not os.path.exists(f'{Q}/runner.py'):
    raise SystemExit('runner.py missing — is Drive mounted? (run the mount cell)')

# Foreground so stdout streams into this cell's output; runner.py also writes
# run-<ts>.out.log is NOT used here (that file is the detached launcher's
# redirect) — heartbeat / prep-*.log / done markers are Drive-side either way.
raise SystemExit(
    subprocess.call([sys.executable, '-u', f'{Q}/runner.py'])
)
