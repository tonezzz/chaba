# ada-nest QUEUE MANIFEST — canonical baseline, deployed to
# ada-nest/queue/JOBS.py (rclone copy from a fleet host; the runner imports
# it once at launch). Canonical source: scripts/colab/JOBS.py (chaba repo).
#
# Contract (see docs/kb/colab-mcp-jobs.md):
#   JOBS = [{name, scope, prep, run|run_sh, artifacts, timeout_s}]
#   scope 'env'  — marks under queue/env-done/<boot_id>/ : re-runs every VM
#   scope 'work' — marks under queue/done/               : survives recycle
#   artifacts    — globs vs ada-nest/ root; every glob must match >=1
#                  non-empty file before the job may mark done
#                  ('{boot_id}' in a pattern expands to this VM's boot id)
#
# ORDER IS THE POINT:
#   1. t4-session-warmup — small GPU smoke that runs until the NEXT job's
#      background prep exits (30s min / 300s cap). It hides the expensive
#      restore-hf-cache extract under useful GPU work — previously the
#      first job's un-hideable prep window left the T4 idle for ~4 min.
#   2..N. env setup — cache restore, shared deps, asset staging.
#   last. save-hf-cache — repack the hub cache so the NEXT runtime skips
#      weight downloads. Real workloads live in packs/, never here.
#
# The runner execs `run` with these globals: NEST_ROOT, PACK_DIR, BOOT_ID,
# QUEUE_PENDING ((name, log, Popen) of the next job's bg prep or None),
# QUEUE_STATE.

import os

_WARMUP_RUN = r'''
import os, time, json
_t0 = time.time()
MIN_S = float(os.environ.get('WARMUP_MIN_S', '30'))
MAX_S = float(os.environ.get('WARMUP_MAX_S', '300'))
_pend = globals().get('QUEUE_PENDING')

def _pending_alive():
    try:
        return bool(_pend) and _pend[2].poll() is None
    except Exception:
        return False

# GPU smoke when torch+cuda exist (the normal T4 case); a CPU burn fallback
# keeps the same timing contract everywhere else so the overlap still works.
_torch = None
def _tick():
    pass
try:
    import torch as _t
    if _t.cuda.is_available():
        _a = _t.randn(512, 512, device='cuda', dtype=_t.float16)
        _b = _t.randn(512, 512, device='cuda', dtype=_t.float16)
        _torch = _t
        def _tick():
            global _mm
            _mm = _a @ _b
        mode = 'cuda-matmul'
    else:
        mode = 'cpu-spin'
except Exception:
    mode = 'cpu-spin'
if mode == 'cpu-spin':
    _x = 1.0000001
    def _tick():
        global _x
        for _i in range(20000):
            _x = (_x * 1.0000001) % 97.0

_n = 0
while True:
    _tick()
    _n += 1
    _el = time.time() - _t0
    if _el >= MIN_S and (not _pending_alive() or _el >= MAX_S):
        break
if _torch is not None:
    _torch.cuda.synchronize()

stats = {
    'mode': mode, 'ticks': _n, 'seconds': round(time.time() - _t0, 1),
    'waited_for_prep': _pend[0] if _pend else None,
    'peak_gpu_gb': round(_torch.cuda.max_memory_allocated() / 1e9, 3)
                   if _torch is not None else 0,
    'boot_id': globals().get('BOOT_ID'), 'ts': time.time(),
}
_root = globals().get('NEST_ROOT', '/content/drive/MyDrive/ada-nest')
os.makedirs(f'{_root}/queue/warmup', exist_ok=True)
open(f"{_root}/queue/warmup/{globals().get('BOOT_ID')}.json",
     'w').write(json.dumps(stats) + '\n')
print('warmup:', stats)
'''


JOBS = [
    # ---- 1. per-runtime T4 warmup — overlaps the next job's prep ----------
    {"name": "t4-session-warmup", "scope": "env",
     "artifacts": ["queue/warmup/{boot_id}.json"],
     "timeout_s": 330,
     "run": _WARMUP_RUN},

    # ---- 2. restore HF hub cache from Drive (big CPU-bound extract) -------
    {"name": "restore-hf-cache", "scope": "env",
     "prep": "test -f /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
             " && mkdir -p /root/.cache/huggingface"
             " && tar -I zstd -xf /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
             "    -C /root/.cache/huggingface || true",
     "run": "import os;p='/root/.cache/huggingface/hub';"
            "print('hub entries:',len(os.listdir(p))if os.path.isdir(p)else 0)"},

    # ---- 3. shared deps — packs may still declare their own prep ----------
    {"name": "deps", "scope": "env",
     "prep": "apt-get install -y -qq zstd >/dev/null 2>&1 || true;"
             " pip install -q pyyaml huggingface-hub",
     "run": "import yaml,huggingface_hub;"
            "print('deps ok: pyyaml',yaml.__version__)"},

    # ---- 4. stage any operator-uploaded asset bundles into /tmp -----------
    {"name": "assets-stage", "scope": "env",
     "prep": "mkdir -p /tmp/stage;"
             " for t in /content/drive/MyDrive/ada-nest/assets/incoming/*.tar.zst;"
             " do [ -e \"$t\" ] && tar -I zstd -xf \"$t\" -C /tmp/stage || true; done",
     "run": "import os;p='/tmp/stage';"
            "print('staged:',os.listdir(p)if os.path.isdir(p)else [])"},

    # ---- 5. repack hub cache for the next runtime (verify-before-mark) ----
    {"name": "save-hf-cache", "scope": "env",
     "artifacts": ["cache/hf-hub.tar.zst"],
     "prep": "test -d /root/.cache/huggingface/hub"
             " && mkdir -p /content/drive/MyDrive/ada-nest/cache"
             " && tar -I zstd -cf /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
             "    -C /root/.cache/huggingface hub || true",
     "run": "print('hf cache packed')"},
]
