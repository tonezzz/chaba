#!/usr/bin/env python3
"""Regenerate scripts/colab/ada-nest-job-console.ipynb from the canonical
cell sources so the checked-in notebook can never drift from them.

Usage:
  build-job-console.py           # write the .ipynb in place
  build-job-console.py --check   # exit 1 if the file is stale (tests)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'ada-nest-job-console.ipynb'

CELL1 = HERE / 'preflight-cell.py'
CELL2 = HERE / 'queue-launcher-cell.py'

MD_INTRO = """\
# ada-nest job console — the ONE Colab notebook for queue work

All GPU workloads run as **queue jobs + packs** pinned to a published
release (`ada-nest/releases/<id>/` — JOBS.py + packs/<name>/pack.yml,
hash-verified end to end) — never as hand-run per-job cells and never as
unversioned Drive files. This notebook is only the operator surface:
run cell 1 once, then start the shared queue through `mcp-colab` or use
cell 2 as a manual fallback.

## How to run a session

1. **Runtime → Change runtime type → T4.** Consumer Colab runtime
   provisioning remains a manual UI action; this controller does not create
   or stop account runtimes.
2. **Run cell 1** — mounts Drive, prints this VM's identity, **reports and
   validates the pinned release** (`RELEASE-OK <id>` = every file in the
   bundle hash-matched; `RELEASE-BAD` refuses), checks for a managed peer
   before registering, and starts a small Drive-command watcher.
   After `PREFLIGHT-OK`, `mcp-colab` can start the shared queue for this exact
   boot ID without requiring cell 2.
3. **Optional fallback — run cell 2** to start the shared queue manually if
   the MCP command path is unavailable. Cell 2 refuses when the release
   pointer, any release hash, the deployed notebook, JOBS.py, the runner,
   or a pack manifest mismatches — and on a CPU runtime.

The queue then drains the pinned `JOBS.py` (per-runtime warmup → HF-cache
restore → deps → assets → cache save) and every un-done `packs/<name>` —
voice, video, DevNest, eval packs all ride the same runner in the same VM.
Done/failed markers record the release + code hash, so a stale marker can
never skip new code; rollback = repoint `queue/ACTIVE_RELEASE.json`.

## Watching / stopping

- Fleet-side: `rclone cat gdrive:ada-nest/queue/run-<ts>.out.log`,
  `queue/heartbeat`, `queue/done/`, `packs/<name>/done`,
  `queue/runtime-sessions/*.json`, `queue/runner.id`,
  `queue/ACTIVE_RELEASE.json` (which release is pinned).
- In-notebook diagnostics are safe any time (the runner is detached):
  `!nvidia-smi`, `!df -h`, etc.
- **Stopping:** the queue stops with the VM (Runtime → disconnect) or
  Runtime → interrupt execution. Nothing here ever stops *another*
  session — **Google Runtime > Manage Sessions is the authoritative
  inventory** for notebooks that didn't run cell 1.
"""

MD_CELL1 = """\
### Cell 1 — mount Drive + register this managed runtime

Reports and validates `queue/ACTIVE_RELEASE.json` → the pinned
`releases/<id>/` bundle (release.json sha must match the pointer; every
declared file must hash-match; nothing undeclared may sit in the dir).
`RELEASE-OK` prints the release id + commit; `RELEASE-BAD` lists the
mismatches and refuses. Then it checks for a fresh peer before
registering — a present peer refuses without leaving a heartbeat record.
Otherwise it writes `queue/runtime-sessions/<boot_id>.json` and refreshes
it on a background heartbeat, then starts a watcher for MCP queue-start
requests targeted at this boot ID. Resolve peers in Runtime > Manage
Sessions.
"""

MD_CELL2 = """\
### Cell 2 — manual fallback to start the shared queue

Prefer `mcp-colab` `colab_queue_start(boot_id)` after cell 1. Use this cell
only when the MCP control path is unavailable.

Runs the full gate before spawning: Drive mounted, **release pointer +
every release hash + deployed notebook + JOBS.py + runner + pack
manifests all verified**, GPU present, no fresh peer runtime, and runner
liveness is **boot-scoped** (`queue/runner.id` carries `boot_id` — a bare
PID on shared Drive is never a process handle, so a PID from another VM's
stale record is never signaled). It then spawns
`releases/<id>/queue/runner.py` — the code snapshot that was just verified.
"""


def md(src):
    return {'cell_type': 'markdown', 'metadata': {}, 'source': src}


def code(path):
    src = path.read_text()
    if not src.endswith('\n'):
        src += '\n'
    return {'cell_type': 'code', 'metadata': {},
            'source': src, 'execution_count': None, 'outputs': []}


def build():
    return {
        'cells': [md(MD_INTRO), md(MD_CELL1), code(CELL1),
                  md(MD_CELL2), code(CELL2)],
        'metadata': {
            'colab': {'provenance': []},
            'kernelspec': {'name': 'python3', 'display_name': 'Python 3'},
            'language_info': {'name': 'python'},
        },
        'nbformat': 4,
        'nbformat_minor': 0,
    }


def main():
    nb = build()
    text = json.dumps(nb, indent=1, ensure_ascii=False) + '\n'
    if '--check' in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f'{OUT.name} is stale — run build-job-console.py')
            return 1
        return 0
    OUT.write_text(text)
    print(f'wrote {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
