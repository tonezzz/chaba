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

All GPU workloads run as **queue jobs + packs** on Drive
(`ada-nest/queue/JOBS.py` + `ada-nest/packs/<name>/pack.yml`) — never as
hand-run per-job cells. This notebook is only the operator surface:
two cells, run once each, top to bottom.

## How to run a session

1. **Runtime → Change runtime type → T4.** The queue exists to fill a GPU;
   cell 2 refuses to start on a CPU runtime.
2. **Run cell 1** — mounts Drive, prints this VM's identity (boot id, GPU,
   RAM), registers it in `queue/runtime-sessions/`, and refuses if *another* managed
   runtime is still fresh (ambiguous duplicate). If you genuinely want two
   VMs, set `ALLOW_SECOND_RUNTIME = True` in the cell and re-run — the
   queue lease then arbitrates writers.
3. **Run cell 2** — starts the detached shared queue **once**. Safe to
   re-run: a live runner is reported, a stale same-VM zombie is reaped, a
   fresh heartbeat from another VM refuses.

The queue then drains `JOBS.py` (per-runtime warmup → HF-cache restore →
deps → assets → cache save) and every un-done `packs/<name>` — voice,
video, DevNest, eval packs all ride the same runner in the same VM.

## Watching / stopping

- Fleet-side: `rclone cat gdrive:ada-nest/queue/run-<ts>.out.log`,
  `queue/heartbeat`, `queue/done/`, `packs/<name>/done`,
  `queue/runtime-sessions/*.json`, `queue/runner.id`.
- In-notebook diagnostics are safe any time (the runner is detached):
  `!nvidia-smi`, `!df -h`, etc.
- **Stopping:** the queue stops with the VM (Runtime → disconnect) or
  Runtime → interrupt execution. Nothing here ever stops *another*
  session — **Google Runtime > Manage Sessions is the authoritative
  inventory** for notebooks that didn't run cell 1.
"""

MD_CELL1 = """\
### Cell 1 — mount Drive + preflight this managed runtime

Checks for a fresh peer before registering this VM. If a peer is present,
the cell refuses without leaving a heartbeat record. Otherwise it writes
`queue/runtime-sessions/<boot_id>.json` and refreshes it on a background
heartbeat. Resolve peers in Runtime > Manage Sessions.
"""

MD_CELL2 = """\
### Cell 2 — start the shared queue once

Runs the full gate before spawning: Drive mounted, GPU present, no fresh
peer runtime, and runner liveness is **boot-scoped** (`queue/runner.id`
carries `boot_id` — a bare PID on shared Drive is never a process handle,
so a PID from another VM's stale record is never signaled).
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
