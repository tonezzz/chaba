# Dispatch outcome — local-llm-model-cache-transfer (OPS-0969)

**Result:** done — the ad-hoc con01 cache from the prior session is now
durable tooling + declared infra, and re-verified end to end.

## What changed (committed on `dispatch/20261029-093301-use-idc03-or-con01-as-a-downlo`, not pushed)

- `scripts/models/model-cache.py` — stdlib-only CLI (python3, macOS-safe):
  `fetch` (registry manifest → `quarantine/*.part` with Range resume →
  sha256 == manifest digest → atomic promote to `blobs/`), `verify`,
  `index`, `list`, `export-gguf` (named `.gguf` hardlink for
  llama.cpp/mlx_lm), `serve` (GET-only tailnet HTTP export for
  credential-free consumers), `pull` (consumer import via `--ssh` or
  `--base-url`), `metrics`. Store root `~/var/cache/devnest/models` is
  itself a valid OLLAMA_MODELS dir; `index.json` carries name, tag,
  quantization, source ref + public source_url, model_sha256, bytes,
  license, created_at, compatibility (arch/params/host_arch/runtime);
  `metrics.jsonl` logs every timed op.
- `docs/kb/devnest-model-cache.md` — runbook (roles, layout, commands,
  Ollama/MLX import paths, kk-mac HTTP-export path, quarantine + safety
  rails incl. "never touch prod ollama.services").
- `docs/ssot/jobs/models/2026-10-29-llm-model-cache.yml` — job record
  with measured numbers + open items.
- `docs/ssot/infrastructure/ssot.storage.yml` — declared `model-cache`
  category (cache tier per R6; con01 primary, idc03 mirror; thresholds).
- `docs/ssot/infrastructure/ssot.host-capacity.yml` — con01 role note.

## Live state

- **con01** `~/var/cache/devnest/models`: qwen3 0.6b/1.7b/4b/8b
  (Q4_K_M, Apache-2.0) all sha256-verified; `bin/model-cache.py`
  deployed; `exports/qwen3-0.6b-Q4_K_M.gguf` hardlink made.
- **idc03** same path: full mirror pulled over SSH from con01 and
  verify-clean — 23 blobs / 9.6 GB / 249 MB/s; quarantine empty.
- Prod ollama services (con01 quadlet :11434, idc03 quadlet :11434)
  untouched; all smoke runs were isolated/ephemeral and stopped.

## Measured

- con01 registry fetch qwen3:1.7b: **1.36 GB in 32.1 s (42.3 MB/s)**
- Transfer con01→idc03 (ssh pull, per-blob sha256): 0.6b 4.6 → 8b 8.6 MB/s
- Verifier: **253 MB/s con01, 249–338 MB/s idc03** (full 9.6 GB re-attest ~39 s)
- Runtime smoke: store served directly via OLLAMA_MODELS (isolated
  :11435 on con01, ephemeral podman :11439 on idc03 — models listed
  zero-copy). tok/s on contended VPS CPUs is 0.4–2.2; prior kk-mac run
  was ~301 tok/s — VPS = download host, Mac = inference host.

## How to verify

```bash
ssh idc03 'python3 ~/var/cache/devnest/bin/model-cache.py list'      # 4 models
ssh idc03 'python3 ~/var/cache/devnest/bin/model-cache.py verify'    # all OK
ssh idc03 'ssh con01 "python3 ~/var/cache/devnest/bin/model-cache.py metrics"'  # timing trail
# consumer import:  python3 scripts/models/model-cache.py pull qwen3:0.6b --ssh idc03
```

## Open items (in job yml)

kk-mac import rides the no-SSH HTTP export or tony-dell hop (fleet keys
to con01 not yet seeded); coder-model pick awaits the bench card;
`serve` is per-session, not a declared service.
