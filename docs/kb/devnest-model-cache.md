# DevNest model cache — fetch once on a fast VPS, import everywhere

**Status:** live (card `local-llm-model-cache-transfer`, OPS-0969; job
record `docs/ssot/jobs/models/2026-10-29-llm-model-cache.yml`).
Tool: `scripts/models/model-cache.py` — one stdlib-only file, same on the
cache origin and on consumers (macOS included; python3 only).

## Why

Mac workers (KK-Mac, future fleet Macs) sit behind slow/residential links.
con01 (Contabo, EU) downloads from the Ollama registry at 40–70 MB/s;
KK-Mac can't. So models are fetched once into a **content-addressed blob
store** on the VPS, then transferred to consumers over tailnet — always
sha256-verified before the consumer ever sees a byte in place. No
credentials move: the Ollama registry is public, and transfers ride SSH
or a tailnet-bound read-only HTTP export.

## Roles

| Host | Role |
|---|---|
| **con01** | primary cache origin (`~/var/cache/devnest/models`) — dr-absorber disk (209G free), proven 42–68 MB/s registry pulls |
| **idc03** | TH-side mirror of the same store — same path, populated via `pull --ssh con01` |
| **kk-mac / any consumer** | imports via `pull --ssh` (if it can reach a cache host) or `pull --base-url` (tailnet HTTP export) |
| **cache tier** | `~/var/cache/devnest/models` is declared **cache** tier (R6, ssot.storage.yml): disposable, re-derivable, preserved — prune by deleting `index.json` entries + orphaned blobs, never hand-edit |

## Store layout

```
~/var/cache/devnest/models/
  ollama-models/            # a valid OLLAMA_MODELS dir as-is
    blobs/sha256-<hex>      # content-addressed layers (digest = sha256)
    manifests/<reg>/<ns>/<model>/<tag>
  index.json                # name, tag, quant, source_url, model_sha256,
                            # bytes, license, created_at, compatibility
                            # (arch, params, host_arch, runtime)
  quarantine/               # *.part downloads; promoted to blobs/ ONLY
                            # after sha256 == manifest digest
  exports/                  # named .gguf hardlinks for llama.cpp/mlx_lm
  metrics.jsonl             # fetch/pull/verify timing records
  serve.log                 # http export access log
```

## Commands

```bash
MCP=~/var/cache/devnest/bin/model-cache.py   # on con01/idc03 (repo path after merge: scripts/models/model-cache.py)

# cache host: fetch a model (idempotent — shared layers dedupe by digest)
python3 $MCP fetch qwen3:0.6b
python3 $MCP fetch qwen3:8b

# integrity: re-sha256 every blob a manifest references
python3 $MCP verify            # all
python3 $MCP verify qwen3:8b   # one

python3 $MCP index             # rebuild index.json from on-disk manifests
python3 $MCP list
python3 $MCP metrics

# consumer (macOS/Linux): import into a local ollama-models dir
python3 model-cache.py pull qwen3:0.6b --ssh con01
python3 model-cache.py pull qwen3:0.6b \
    --base-url http://con01.taila0626a.ts.net:8377   # HTTP path (below)

# GGUF for llama.cpp / mlx_lm
python3 $MCP export-gguf qwen3:8b
```

## Import into Ollama on the consumer

The pulled `<root>/ollama-models` **is** an OLLAMA_MODELS store. Two ways
to consume:

1. **Point an (isolated) server at it** — fastest for smoke:
   `OLLAMA_MODELS=<root>/ollama-models OLLAMA_HOST=127.0.0.1:11435 ollama serve`
   (proven on con01 + an `--rm` podman container on idc03; keep it off the
   production port — con01 prod ollama is :11434, idc03 quadlet is :11434).
2. **Merge into the user's store** — pull with `--root ~/.ollama/models`
   (macOS default) so the main `ollama` service sees it; blobs land via
   quarantine + atomic rename, never half-written.

## Import into MLX / llama.cpp (no ollama needed)

```bash
python3 model-cache.py pull qwen3:8b --ssh con01 --root ~/var/cache/devnest/models
python3 model-cache.py export-gguf qwen3:8b
# -> ~/var/cache/devnest/models/exports/qwen3-8b-Q4_K_M.gguf  (sha256 = model_sha256 in index.json)
mlx_lm.generate --model ~/var/cache/devnest/models/exports/qwen3-8b-Q4_K_M.gguf --prompt "..."
```

## HTTP export (for hosts without SSH to the cache, e.g. kk-mac)

kk-mac SSH is only seeded on tony-dell; the export path needs none —
bind the read-only server to the tailnet interface and pull over HTTP:

```bash
# on con01 (temporary, per-session — no persistent service declared)
python3 $MCP serve --bind <tailscale-ip> --port 8377 &
# on kk-mac
python3 model-cache.py pull qwen3:0.6b \
    --base-url http://<con01-tailscale-ip>:8377 --root ~/.ollama/models-cache
```

GET-only handler; access log in `serve.log`. Stop it when done — the
declared state is SSH-pull; the HTTP leg exists for credential-free
consumers. (First proven 2026-10-29: con01→kk-mac temporary HTTP path.)

## Quarantine + verifier quality

- Downloads land in `quarantine/*.part` with Range resume; a blob is
  promoted only when `sha256(file) == manifest digest`. Mismatches and
  short reads stay quarantined — a store can never hold a corrupt blob
  under a good name.
- `verify` re-checks every blob: measured 253 MB/s (con01) / 338 MB/s
  (idc03) — full re-attestation of ~8 GB in ~30 s.
- Every fetch/pull/verify appends a record to `metrics.jsonl`
  (bytes, secs, MB/s) — the measurement trail Tony asked for.

## Safety rails

- Never fetch into a **production** ollama's own store path from this
  tool — cache first, let the consumer's normal `ollama pull` be replaced
  by `pull`, and point isolated serves at the cache with OLLAMA_MODELS.
- con01 prod `ollama.service` (quadlet, tailnet :11434, embed-pool
  upstream) and idc03 prod `ollama.service` (quadlet :11434, mddb
  fallback) must not be restarted/touched by cache work.
- Model refs and public registry URLs are fine in logs/index; never paste
  signed blob URLs or tokens into chat/cards.
- `tmp/ollama-extract` on con01 is a disposable ollama binary for
  isolated serves; it's cache tier, not a service.
