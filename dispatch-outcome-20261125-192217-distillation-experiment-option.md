# Dispatch outcome — bge-m3-distillation-pilot-train-local-em-d85919 (attempt 2)

## What Tony's "proceed" meant and what I did

Prior attempt found the 2026-11-08 closed-form linear-map pilot already
met the card's success gate and asked close/park/rebuild; Tony answered
**proceed = authorize rebuild + full SBERT fine-tune anyway**. This run
executed that:

1. **Rebuilt the lost teacher fixture** on idc03 (`/tmp/embedeval` was
   wiped fleet-wide — that's also why attempt 1 produced nothing
   committable). New `scripts/ada/embedeval-rebuild.py` re-fetches the
   doc pool from mddb, re-selects the same 48 judged queries, and
   re-embeds everything with gemini-embedding-2. Result: **5,890 docs**
   (corpus shrank from 8,109 after mddb bank compaction — today's real
   corpus), 48 queries, all teacher vectors. Durable copy at
   `idc03:~/data/embedeval-distill/` so the next /tmp wipe doesn't hurt.
   - Gotcha found: `GEMINI_API_KEY_FREE` is over daily quota → used
     `GEMINI_API_KEY_PAID` (~$1-2 total spend, authorized by "API
     re-embed"). Also `MDDB_BASE_URL` (not `MDDB_VEC`) is the env override
     — 127.0.0.1:11023 refuses on idc03, must use the tailnet IP.

2. **Rebuilt the judged qrels** by re-running `bge-hybrid-judged.py`
   (4,800 fresh LLM judgments, 499 relevant). New baseline on the new
   fixture: **bge_dense r@5 .315 / MRR .656** — NOT comparable to the
   Nov-7 gate (.224/.767) since corpus AND qrels both changed. The honest
   gate is student-vs-gemini measured on this new qrels set.

3. **Wrote the training pipeline** `scripts/ada/bge-distill-ft.py`
   (committed): BGE-M3 CLS pooling → trainable linear head 1024→768 →
   L2-normalize; MSE on unit-sphere teacher vectors (= cosine
   regression); train/eval subcommands, step checkpoints, holdout
   teacher-cosine, teacher-rank overlap@k, and qrels recall/MRR when
   qrels*.json is present.

4. **Launched the fine-tune on con01** (only viable worker — see below),
   detached: `bge-m3-distill` venv, torch 2.15.0+cpu, nice -n 15,
   freeze embeddings+bottom-12-of-24-layers, batch 8 × accum 2 (eff. 16),
   fp32, max_len 512, ckpt every 50 opt steps → `/tmp/bge-m3-distill/`,
   log `/tmp/bge-m3-distill-train.log`. ETA ~18-24h for 1 epoch over
   5,447 train pairs.

## Compute reality (why con01 CPU, not GPU)

- **tony-omen**: GTX 1650 4GB works now (NVML fixed since spec), but
  torch is the +cpu wheel, ~3GB VRAM already committed by ollama
  llama-server, and CPU load ~80. Full FT needs ~14-21GB RAM — omen has
  ~7GB free. Not viable unattended.
- **kk-mac**: offline (ssh denied).
- **con01**: AMD EPYC 8c/23GB, cleanest box. Measured BGE-M3 fwd+bwd
  ~60-73s per batch-4×512 fp32. First full-FT launch **OOM-killed at
  21.4GB RSS** → relaunched with `--freeze-layers 12` (top-12 layers +
  head trainable, discriminative FT — standard recipe, still a real
  backbone fine-tune). Now stable at ~11-13GB RSS, 440% CPU.
- bf16 autocast disabled by default — con01 CPU lacks AVX512_BF16.

## Files / where things live

- Committed on `dispatch/20261125-192217-distillation-experiment-option`:
  `scripts/ada/embedeval-rebuild.py`, `scripts/ada/bge-distill-ft.py`,
  `docs/ssot/jobs/ada/2026-11-25-bge-distillation-ft-pilot.yml`
- idc03 `/tmp/embedeval/`: docs, queries, vec-gemini*, qrels-bge-hybrid,
  out/ report — plus durable `~/data/embedeval-distill/`
- con01 `/tmp/embedeval/` (same inputs + qrels), `/tmp/bge-m3-distill/`
  checkpoints, `~/venvs/bge-distill/`

## How to verify / finish the job

```
# training progress
ssh con01 'tail -5 /tmp/bge-m3-distill-train.log; ls /tmp/bge-m3-distill/'
# when done (~tomorrow): eval — teacher cosine + rank overlap + qrels metrics
ssh con01 '~/venvs/bge-distill/bin/python /tmp/bge-distill-ft.py eval \
  --work /tmp/embedeval --ckpt /tmp/bge-m3-distill/final'
```

Follow-ups carded in the job doc: student top-10 candidates still need
incremental judging before final gate numbers; full-FT (freeze 0) needs
a real GPU (kk-mac when online / omen after VRAM frees); if top-12
result beats .9493 teacher-cosine or gemini arm on new qrels → serving
decision (second mddb-embed collection vs offline cosine).

lessons:
- embed-space-eval env override is `MDDB_BASE_URL`, not `MDDB_VEC`; on idc03 127.0.0.1:11023 refuses — use tailnet IP 100.102.134.91:11023.
- GEMINI_API_KEY_FREE hits daily quota fast on bulk embeds — GEMINI_API_KEY_PAID works; ~5.9k doc embeds ≈ $1.
- BGE-M3 full FT on con01 CPU OOMs at ~21GB RSS (batch8×512 fp32); freeze bottom 12 layers → stable ~12GB, still ~20h/epoch.
- torch+cpu on non-AVX512_BF16 hosts: leave bf16 autocast OFF.
- /tmp fixtures get wiped — copy embedeval inputs to ~/data/ before relying on them across sessions.
