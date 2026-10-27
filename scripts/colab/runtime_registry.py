#!/usr/bin/env python3
# ada-nest MANAGED-RUNTIME REGISTRY — session guard for the Colab job console.
# Lives on Drive at ada-nest/queue/runtime_registry.py; canonical source is
# scripts/colab/runtime_registry.py in the chaba repo. Pure stdlib.
#
# A "managed runtime" is a Colab VM whose operator ran the console notebook's
# preflight cell — it registers itself at queue/runtime-sessions/<boot_id>.json and
# refreshes ts on a heartbeat. The registry answers ONE question: "is another
# instrumented VM fresh right now?" It cannot see uninstrumented sessions —
# Google Runtime > Manage Sessions remains the authoritative inventory for
# those, and NOTHING here ever stops another session (OPS-0872 lesson:
# numeric runner.pid on shared Drive is not a process handle — a local PID
# that collides with a stale record must never be signaled).
#
# Record shape (queue/runtime-sessions/<boot_id>.json):
#   {boot_id, kind:'managed-notebook', gpu, gpu_gb, ram_gb, drive_mounted,
#    registered_at, ts, runner:{pid,worker,epoch}|null}
#
# Env overrides (sandbox tests / non-Drive stores):
#   NEST_ROOT           ada-nest root   (default /content/drive/MyDrive/ada-nest)
#   NEST_RUNTIME_TTL_S  peer freshness window (default 300)
import json
import os
import subprocess
import time
from pathlib import Path

DEFAULT_ROOT = '/content/drive/MyDrive/ada-nest'
KIND = 'managed-notebook'


def nest_root():
    return Path(os.environ.get('NEST_ROOT', DEFAULT_ROOT))


def queue_dir(root=None):
    return Path(root) / 'queue' if root else nest_root() / 'queue'


def ttl_s():
    return float(os.environ.get('NEST_RUNTIME_TTL_S', '300'))


def boot_id():
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return 'noboot-' + time.strftime('%Y%m%d-%H%M')


def gpu_info():
    """(name, vram_gb). ('', 0.0) when nvidia-smi is absent/fails — CPU runtime."""
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or not r.stdout.strip():
            return '', 0.0
        name, mib = r.stdout.strip().splitlines()[0].rsplit(',', 1)
        return name.strip(), round(float(mib.strip()) / 1024, 2)
    except Exception:
        return '', 0.0


def ram_gb():
    try:
        return round(os.sysconf('SC_PHYS_PAGES')
                     * os.sysconf('SC_PAGE_SIZE') / 1e9, 1)
    except Exception:
        return 0.0


def drive_mounted(root=None):
    """True when the nest root sits on a real mount — or NEST_ROOT points at a
    sandbox dir (tests). Default root requires a FUSE mount at the usual
    Colab mountpoints so a VM with Drive unmounted can't fake 'mounted'
    just because /content/drive exists as an empty dir."""
    root = Path(root or nest_root())
    if os.environ.get('NEST_ROOT'):
        return root.is_dir()
    if not root.is_dir():
        return False
    return any(os.path.ismount(m)
               for m in ('/content/drive', '/content/gdrive'))


def read_runner_id(qdir=None):
    """queue/runner.id — per-boot identity of the live queue runner, or None."""
    try:
        return json.loads((Path(qdir or queue_dir()) / 'runner.id').read_text())
    except Exception:
        return None


def record(root=None):
    """This VM's registry record (fresh ts)."""
    name, gb = gpu_info()
    rid = read_runner_id()
    mine = rid if rid and rid.get('boot_id') == boot_id() else None
    return {
        'boot_id': boot_id(),
        'kind': KIND,
        'gpu': name,
        'gpu_gb': gb,
        'ram_gb': ram_gb(),
        'drive_mounted': drive_mounted(root),
        'registered_at': time.time(),
        'ts': time.time(),
        'runner': ({'pid': mine.get('pid'), 'worker': mine.get('worker'),
                    'epoch': mine.get('epoch')} if mine else None),
    }


def _record_path(root=None):
    return queue_dir(root) / 'runtime-sessions' / f'{boot_id()}.json'


def register(root=None):
    """Write/refresh queue/runtime-sessions/<boot_id>.json; preserves registered_at."""
    qd = queue_dir(root)
    rdir = qd / 'runtime-sessions'
    rdir.mkdir(parents=True, exist_ok=True)
    rec = record(root)
    try:
        old = json.loads(_record_path(root).read_text())
        rec['registered_at'] = float(old.get('registered_at') or rec['ts'])
    except Exception:
        pass
    _record_path(root).write_text(json.dumps(rec) + '\n')
    return rec


def _all_records(root=None):
    rdir = queue_dir(root) / 'runtime-sessions'
    out = []
    if not rdir.is_dir():
        return out
    for f in sorted(rdir.glob('*.json')):
        try:
            d = json.loads(f.read_text())
            d['_path'] = f.name
            out.append(d)
        except Exception:
            continue
    return out


def peers(root=None, ttl=None):
    """OTHER managed runtimes whose ts is still inside the TTL window."""
    ttl = ttl_s() if ttl is None else ttl
    me = boot_id()
    now = time.time()
    return [r for r in _all_records(root)
            if r.get('boot_id') != me and now - float(r.get('ts') or 0) <= ttl]


def stale(root=None, ttl=None):
    """Registry records past the TTL — reported for visibility, never acted on."""
    ttl = ttl_s() if ttl is None else ttl
    me = boot_id()
    now = time.time()
    return [r for r in _all_records(root)
            if r.get('boot_id') != me and now - float(r.get('ts') or 0) > ttl]


def fmt_runtime(r):
    age = time.time() - float(r.get('ts') or 0)
    gpu = f"{r.get('gpu') or 'cpu'} {r.get('gpu_gb') or 0:.0f}GB"
    runner = r.get('runner') or {}
    rbit = f" runner={runner.get('worker')}" if runner.get('worker') else ''
    return (f"{str(r.get('boot_id'))[:8]} ({gpu}, ram {r.get('ram_gb')}GB,"
            f" ts {age:.0f}s ago{rbit})")


def launch_gate(root=None, ttl=None, allow_second=False, runner_path=None):
    """Problems list for starting the shared queue on THIS VM.
    Empty list = go. Non-empty = refuse (print each to the operator).
      - Drive not mounted / runner.py absent
      - no GPU (CPU runtime — the queue exists to fill a T4)
      - another managed runtime fresh in the registry (ambiguous duplicate)
    allow_second bypasses ONLY the duplicate leg — the deliberate two-VM
    case the queue lease then arbitrates.
    runner_path: under release pinning the runner is
      releases/<id>/queue/runner.py — the launcher passes that path; the
      legacy queue/runner.py check remains for unpinned trees."""
    root = root or nest_root()
    problems = []
    qd = queue_dir(root)
    if not drive_mounted(root):
        problems.append('Drive is not mounted — run cell 1 first')
    rp = Path(runner_path) if runner_path else qd / 'runner.py'
    if not rp.exists():
        problems.append(f'{rp} missing — deploy the queue files')
    name, gb = gpu_info()
    if gb <= 0:
        problems.append('no GPU detected — Runtime > Change runtime type > T4')
    if not allow_second:
        for p in peers(root, ttl):
            problems.append(
                f'another managed runtime is fresh: {fmt_runtime(p)} — '
                'refusing ambiguous duplicate launch (see Runtime > '
                'Manage Sessions; set ALLOW_SECOND_RUNTIME to override)')
    return problems
