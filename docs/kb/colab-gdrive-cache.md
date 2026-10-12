# Colab ↔ Google Drive dataset/artifact cache

Default pattern for any Colab job that downloads > ~20 MB of inputs (datasets, model
weights, wheels). Pay the download cost **once**; every later runtime — even on a fresh
VM — rehydrates from Drive in seconds.

Registered procedure: `colab-gdrive-cache` in `docs/ssot/ssot.procedures.yml`.

## Why

Colab runtimes are ephemeral — `/content`, `/tmp` die with the VM. Slow origins
(e.g. `cs.toronto.edu` for CIFAR) re-cost minutes every session. Drive persists and
has good peering with Colab, **but** it is slow on many-small-file trees — so cache
**packed artifacts** (tar.gz / parquet / zip), never raw directory trees.

## Layout

```
/content/drive/MyDrive/colab-cache/<name>/   # packed artifacts + .sha256 markers
/tmp|/content/...                            # extracted working set (ephemeral, fast)
```

## Pattern (copy-paste cell)

```python
# --- gdrive cache: mount once per session ---
from google.colab import drive
drive.mount('/content/drive')          # one OAuth click (same browser acct)

# --- rehydrate-or-fetch ---
import os, subprocess, time
NAME  = 'cifar10'
CACHE = f'/content/drive/MyDrive/colab-cache/{NAME}'
LOCAL = '/tmp/data'                     # local disk: fast, ephemeral
URL   = 'https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz'
TGZ   = f'{CACHE}/cifar-10-python.tar.gz'

os.makedirs(CACHE, exist_ok=True); os.makedirs(LOCAL, exist_ok=True)
t = time.time()
if not os.path.exists(TGZ):             # cache miss -> pay download ONCE
    subprocess.run(['apt-get','install','-y','aria2'], capture_output=True)
    subprocess.run(['aria2c','-x16','-s16','--file-allocation=none',
                    '-d',CACHE,'-o','cifar-10-python.tar.gz',URL], check=True)
subprocess.run(['tar','xzf',TGZ,'-C',LOCAL], check=True)
print(f'ready in {time.time()-t:.1f}s  (drive-hit: {os.path.exists(TGZ)})')
# then: torchvision.datasets.CIFAR10(LOCAL, download=False)
```

## Variants

- **HF models/datasets**: `snapshot_download(repo_id)` to local → `tar czf $CACHE/<model>.tgz`
  → on next run extract back into `HF_HOME`. (Setting `HF_HOME` directly on Drive works
  but is slow on sharded safetensors + many small files — prefer the tar.)
- **pip deps**: `pip download -d $CACHE/wheels <pkgs>` once →
  `pip install --no-index --find-links $CACHE/wheels <pkgs>` on later runs.
- **Job outputs** (reverse direction): `tar czf $CACHE/out-<ts>.tgz /tmp/results` —
  same cache doubles as the artifact handoff for `colab-burst`-style jobs.

## Verified 2026-10-12

- CIFAR-10 origin (`cs.toronto.edu`) caps ~60–80 kB/s/stream AND stalls mid-file
  (froze at 94% on Colab; blackholed aria2 -x16 conns on tony-dell after ~100 MB).
- Fast mirror: `https://data.brainchip.com/dataset-mirror/cifar10/cifar-10-python.tar.gz`
  — 170 MB in 17.6 s (~9.7 MB/s), md5 `c58f30108f718f92721af3b95e74349a` matches official.
- **Fleet→Drive path works without Colab-side mount**: `rclone copy` on tony-dell via the
  `gdrive:` remote (~13.5 MiB/s up) — use when drive.mount OAuth can't complete in-session.
- `drive.mount()` needs an interactive OAuth click in the cell output — cells executed
  via the colab MCP proxy can hit `ValueError: mount failed`; run the mount cell manually
  in the notebook if so.

## Rules of thumb

- Always `download=False` / offline-load from the extracted LOCAL dir after rehydrate.
- Drive read ≈ 50–150 MB/s for big blobs — a 170 MB tarball lands in ~2 s vs minutes
  from the origin.
- Verify with a size/sha marker if the source is mutable.
- Same Drive = shared across all your runtimes, notebooks, and Pro sessions.
- First cell of any colab-* notebook that needs heavy inputs = mount + rehydrate.
```
