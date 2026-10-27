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
#   N-1. devnest-heldout-assessment — cache-independent held-out worker
#      assessment (fixed GPU battery + queue-history audit; no model
#      pulls). Runs while the LAST job's repack prep is backgrounded,
#      closing the second un-hideable GPU-idle window. This is a worker/
#      queue assessment — NOT a DevNest replay-benchmark pass (those
#      fixtures/verifiers are not frozen).
#   last. save-hf-cache — repack the hub cache so the NEXT runtime skips
#      weight downloads. Its CPU-bound tar prep hides under the
#      assessment's GPU time. Real workloads live in packs/, never here.
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


# devnest-heldout-assessment — the cache-independent held-out assessment
# slot of the standard sequence (OPS-0880). Fixed battery + fixed audit:
# nothing here is fitted to what it measures, and no model weights or
# packs are downloaded, so it stays valid while the hub-cache repack
# mutates /root/.cache in the background. Writes one JSON + one MD report
# per boot under queue/assessments/ (durable artifacts gate the job).
_HELDOUT_RUN = r'''
import os, re, time, json, glob

_root = globals().get('NEST_ROOT', '/content/drive/MyDrive/ada-nest')
_boot = globals().get('BOOT_ID', 'noboot')
_q = f'{_root}/queue'
_outdir = f'{_q}/assessments'
os.makedirs(_outdir, exist_ok=True)
_t0 = time.time()
rep = {'kind': 'devnest-heldout-assessment', 'boot_id': _boot, 'ts': _t0,
       'scope': 'worker+queue assessment — NOT a replay-benchmark pass '
                '(fixtures/verifiers unfrozen per OPS-0880)',
       'battery': {}, 'audit': {}, 'verdicts': {}}

# ---- 1. fixed GPU battery — held-out params, zero downloads -----------
_b = {}
try:
    import torch
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        _b['gpu'] = torch.cuda.get_device_name(0)
        _b['torch'] = torch.__version__
        for _dtn in ('float16', 'bfloat16'):
            _dt = getattr(torch, _dtn)
            _x = torch.randn(4096, 4096, device='cuda', dtype=_dt)
            _y = torch.randn(4096, 4096, device='cuda', dtype=_dt)
            for _i in range(3):
                _z = _x @ _y                     # warm
            torch.cuda.synchronize()
            _s = time.time()
            for _i in range(20):
                _z = _x @ _y
            torch.cuda.synchronize()
            _b[f'tflops_{_dtn}'] = round(
                20 * 2 * 4096.0**3 / (time.time() - _s) / 1e12, 2)
            del _x, _y, _z
            torch.cuda.empty_cache()
        _buf = torch.empty(64 * 1024 * 1024, dtype=torch.float32)
        _buf = _buf.pin_memory()
        _d = torch.empty(64 * 1024 * 1024, dtype=torch.float32,
                         device='cuda')
        for _i in range(2):
            _d.copy_(_buf, non_blocking=True)
        torch.cuda.synchronize()
        _s = time.time()
        for _i in range(8):
            _d.copy_(_buf, non_blocking=True)
        torch.cuda.synchronize()
        _b['h2d_gbps'] = round(8 * _buf.numel() * 4
                               / (time.time() - _s) / 1e9, 2)
        _s = time.time()
        for _i in range(8):
            _buf.copy_(_d, non_blocking=True)
        torch.cuda.synchronize()
        _b['d2h_gbps'] = round(8 * _buf.numel() * 4
                               / (time.time() - _s) / 1e9, 2)
        _b['peak_alloc_gb'] = round(
            torch.cuda.max_memory_allocated() / 1e9, 3)
        _b['mode'] = 'cuda'
    else:
        _b['mode'] = 'cpu-only'
except Exception as _e:
    _b['mode'] = 'error'
    _b['error'] = repr(_e)[:200]
rep['battery'] = _b

# ---- 2. queue-history audit — production logs are the held-out set ----
def _lts(ln):
    m = re.match(r'^(\d\d):(\d\d):(\d\d)', ln)
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60
            + int(m.group(3))) if m else None

# Per-file pass: a prep is "hidden" when its '(bg) prepping' line lands
# inside a run window (run .. DONE/FAIL). The runner logs prep rc only
# when the NEXT job is reached, so exact prep-exit time is unknowable
# from the main log — hidden_s is the run-window overlap UPPER BOUND
# (window_end - prep_start), reported as such.
_a = {'files': 0, 'jobs_run': 0, 'jobs_done': 0, 'jobs_fail': 0,
      'bg_preps': 0, 'bg_preps_in_run_window': 0, 'fg_preps': 0,
      'hidden_prep_upper_s': 0.0,
      'artifact_fails': 0, 'prep_fails': 0, 'fence_exits': 0}
for _lf in sorted(glob.glob(f'{_q}/log-*.txt')
                  + glob.glob(f'{_q}/run-*.out.log')):
    try:
        _lines = open(_lf, errors='replace').read().splitlines()
    except OSError:
        continue
    _a['files'] += 1
    _in_run = False
    _win_bg = []                                    # prep start ts in window
    for _ln in _lines:
        _ts = _lts(_ln)
        if _ts is None:
            continue
        if '== ' in _ln and ': run' in _ln:
            _a['jobs_run'] += 1
            _in_run = True
            _win_bg = []
        elif '(bg) prepping' in _ln:
            _a['bg_preps'] += 1
            if _in_run:
                _a['bg_preps_in_run_window'] += 1
                _win_bg.append(_ts)
        elif 'prep (foreground' in _ln:
            _a['fg_preps'] += 1
        elif ': DONE' in _ln or ': FAIL' in _ln:
            if ': DONE' in _ln:
                _a['jobs_done'] += 1
            else:
                _a['jobs_fail'] += 1
                if 'artifacts missing' in _ln:
                    _a['artifact_fails'] += 1
            for _st in _win_bg:
                _a['hidden_prep_upper_s'] += max(0, _ts - _st)
            _win_bg = []
            _in_run = False
        elif 'PREP FAILED' in _ln:
            _a['prep_fails'] += 1
        elif 'fenced' in _ln:
            _a['fence_exits'] += 1
_a['done_markers'] = len(glob.glob(f'{_q}/done/*.done'))
_a['env_markers'] = len(glob.glob(f'{_q}/env-done/*/*.done'))
_a['hidden_prep_upper_s'] = round(_a['hidden_prep_upper_s'], 1)
rep['audit'] = _a

# ---- 3. verdicts -------------------------------------------------------
_v = rep['verdicts']
_v['gpu_battery'] = ('pass' if _b.get('tflops_float16', 0) >= 5
                     else 'warn' if _b.get('mode') == 'cuda' else 'fail')
_v['prep_overlap'] = ('pass' if _a['bg_preps_in_run_window'] > 0
                      else 'info' if _a['bg_preps'] == 0 else 'warn')
_v['artifact_gate'] = ('pass' if _a['artifact_fails'] > 0 else 'info')
_v['history'] = 'pass' if _a['files'] > 0 else 'warn'
rep['seconds'] = round(time.time() - _t0, 1)

_j = f'{_outdir}/devnest-heldout-{_boot}.json'
_mdf = f'{_outdir}/devnest-heldout-{_boot}.md'
with open(_j, 'w') as f:
    json.dump(rep, f, indent=1)
_md = ['# devnest-heldout-assessment', '',
       f"- boot_id: `{_boot}`  seconds: {rep['seconds']}",
       f"- scope: {rep['scope']}", '',
       '## battery', '']
_md += [f'- {k}: {v}' for k, v in _b.items()]
_md += ['', '## queue-history audit', '']
_md += [f'- {k}: {v}' for k, v in _a.items()]
_md += ['', '## verdicts', '']
_md += [f'- {k}: **{v}**' for k, v in _v.items()]
open(_mdf, 'w').write('\n'.join(_md) + '\n')
print('heldout-assessment:', json.dumps(rep['verdicts']),
      json.dumps(_b.get('mode')), f"{_a['files']} log files")
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

    # ---- 5. held-out worker assessment — cache-independent GPU work that
    #         hides the save-hf-cache repack prep (the second un-hideable
    #         window). env scope: re-runs every boot like the warmup. -----
    {"name": "devnest-heldout-assessment", "scope": "env",
     "artifacts": ["queue/assessments/devnest-heldout-{boot_id}.json",
                   "queue/assessments/devnest-heldout-{boot_id}.md"],
     "timeout_s": 1200,
     "run": _HELDOUT_RUN},

    # ---- 6. repack hub cache for the next runtime (verify-before-mark) --
    {"name": "save-hf-cache", "scope": "env",
     "artifacts": ["cache/hf-hub.tar.zst"],
     "prep": "test -d /root/.cache/huggingface/hub"
             " && mkdir -p /content/drive/MyDrive/ada-nest/cache"
             " && tar -I zstd -cf /content/drive/MyDrive/ada-nest/cache/hf-hub.tar.zst"
             "    -C /root/.cache/huggingface hub || true",
     "run": "print('hf cache packed')"},
]
