# Dispatch outcome — ncm-thai-adaptation toy-train (session 2)

## What was done

Tony answered the recon-done request with **toy-train** (19:06). This session
built the missing NCM training loops and validated them end-to-end on mn01
(CPU-only 4c/7GB, earlyoom-limited).

**Reimplemented trainers** in `experiments/ncm-thai/` (~1.4k LOC, upstream clone
`experiments/ncm-upstream/` kept pristine):

- `train_tokenizer.py` — stage-1 VQ-VAE: recon CE + shipped `vq_loss` (nested
  dropout + EMA codebook updates fire inside the model's train-mode forward).
- `train_generator.py` — stage-2: clean codes → conditioning corruption
  (uniform same-codebook replacement, "shifted linear decreasing" rates,
  mean 0.5) → `idx_to_ncm_input` → L_NCM with `w_k ∝ ℓ_k^(-α)`. Handles
  query_level0 / predict_level0 / conditional prefixes + prefix_dropout;
  stores `inference.level0_unigram` in the checkpoint format `eval_shard.py`
  expects. `--resume` + `save_every` (earlyoom-proof) + `retry-train.sh`.
- `model_wrap.py` CheckpointedNCP — required on CPU (math-backend SDPA keeps
  [B,H,S,S] weights per block → ~8× activation blowup → OOM).
- Thai pipeline: `sp_tokenizer.py` (SentencePiece BPE-8192 on mC4-th),
  `thai_data.py` (mC4 stream → 120k docs/314.6M chars → 300k×128 ids),
  `ar_baseline.py` + `eval_thai.py` (AR baseline + Gen-PPL/entropy/speed),
  `configs/thai-toy.yaml` (paper TinyStories recipe verbatim — param counts
  verified identical: VQVAE 36.43M, NCP 88.61M).

**Validation (Sudoku, paper arch/ladder):**
- Tokenizer @250 steps bs64: recon CE 2.65→0.134; held-out recon 96.1% tokens.
- Micro generator (4×256=3.28M) @~200 steps bs16: loss 2.90→0.89, code acc
  4%→57.6%; generation wellformed 0%→100% (valid/solved still 0 — needs the
  real 50k-step budget; format is learned before constraints).

## Changed files

- `experiments/ncm-thai/` — package, configs, README, retry-train.sh (new)
- `experiments/ncm-upstream/` — vendored HazyResearch/ncm clone (unmodified)
- `docs/ssot/jobs/experiments/2026-10-20-ncm-thai-toy-train.yml` — durable record
- `experiments/ncm-thai/data/` — sudoku_train.pt (12k boards), thai_corpus.txt,
  spm_thai.model, thai_ids.pt (generated artifacts, large)

## Result

toy-train infrastructure complete and Sudoku-validated. The actual Thai toy
training run (paper budgets ~10k tok + ~20k gen updates) cannot run on mn01 —
needs the gpu-labeled card path to tony-omen (4GB, micro/medium scale) or a
rented GPU (~$20-50, inside the accepted option). All commands documented in
`experiments/ncm-thai/README.md`; the run is one command per stage from there.

## How to verify

- Card comms show loss trajectory; `runs/sudoku-micro/` holds trained ckpts.
- Re-run eval: `.venv/bin/python -m ncmthai.eval_sudoku --config
  configs/sudoku-micro.yaml --ckpt runs/sudoku-micro --puzzles
  data/sudoku/easy/puzzles.pickle --solutions data/sudoku/easy/solutions.pickle`
- Thai config builds: instantiate `configs/thai-toy.yaml` models → param
  counts print (36.43M / 88.61M).
