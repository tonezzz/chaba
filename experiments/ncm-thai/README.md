# ncm-thai — NCM reimplementation + Thai toy training

Reimplements the missing training loops for
[HazyResearch/ncm](https://github.com/HazyResearch/ncm) (arXiv:2610.14162)
against the shipped model code, then targets a Thai toy model.

Upstream (`../ncm-upstream`, MIT) ships all model code — EMA codebook
updates, dead-code restart, nested dropout, straight-through estimator,
`idx_to_ncm_input` — but no trainers. This package adds:

| file | role |
| --- | --- |
| `ncmthai/train_tokenizer.py` | Stage-1 VQ-VAE trainer: recon CE + `vq_loss` (commitment+latent, nested dropout inside model fwd) |
| `ncmthai/train_generator.py` | Stage-2 NCM trainer: conditioning corruption + level-weighted L_NCM; tracks level-0 unigram into `generator.pt:inference.level0_unigram` |
| `ncmthai/corrupt.py` | "shifted linear decreasing" per-level corruption rates (mean 0.5), L_NCM weights `w_k ∝ ℓ_k^(1-α)` |
| `ncmthai/model_wrap.py` | `CheckpointedNCP` — per-block grad checkpointing for CPU/low-VRAM training (CPU SDPA math backend materializes [B,H,S,S]) |
| `ncmthai/sudoku_data.py` | Sudoku puzzle/solution generator in released token format (val milestone) |
| `ncmthai/eval_sudoku.py` | solved/valid/wellformed rate on held-out puzzles |
| `ncmthai/sp_tokenizer.py` | SentencePiece trainer + `spm` tokenizer plugin (registered in upstream registry) |
| `ncmthai/thai_data.py` | mC4-th stream → corpus.txt → SP ids tensor |
| `ncmthai/encode_corpus.py` | pre-tokenized ids → frozen-VQ codes (speeds up real gen runs) |
| `ncmthai/ar_baseline.py` | small AR transformer baseline (same data) — comparison target + Gen-PPL reference |
| `ncmthai/eval_thai.py` | held-out PPL, NCM samples Gen-PPL/entropy/speed vs AR |

## Recipe source

Paper App. B/C/F (extracted in `docs/ssot/jobs/experiments/2026-10-20-ncm-thai-recon.yml`):
`L_tok = CE(x, dec(ẑ)) + β·MSE(z,sg[ẑ]) + MSE(sg[z],ẑ)` at a nested-dropout cutoff;
`L_NCM = -Σ_k w_k Σ_i log p(r_k^i | z̃^(k-1))`, `w_k = ℓ_k^(-α)/Σℓ^(1-α)`;
corruption = uniform same-codebook replacement, shifted-linear-decreasing
rates, mean 0.5.

## Pipeline

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python \
  torch --index-url https://download.pytorch.org/whl/cpu && \
uv pip install --python .venv/bin/python omegaconf hydra-core regex numpy \
  sentencepiece datasets transformers

# validation milestone: Sudoku (paper arch, reduced updates on CPU)
.venv/bin/python -m ncmthai.sudoku_data --n 12000 --clues 40 --out data/sudoku_train.pt
.venv/bin/python -m ncmthai.train_tokenizer --config configs/sudoku-toy.yaml --updates 250 --batch 64
.venv/bin/python -m ncmthai.train_generator --config configs/sudoku-toy.yaml --updates 300 --batch 16
.venv/bin/python -m ncmthai.eval_sudoku --config configs/sudoku-toy.yaml \
  --ckpt runs/sudoku-toy --puzzles data/sudoku/easy/puzzles.pickle \
  --solutions data/sudoku/easy/solutions.pickle --n 200 --bs 16

# Thai (GPU run — see configs/thai-toy.yaml for paper budgets)
.venv/bin/python -m ncmthai.thai_data --out-dir data --text-mb 300
.venv/bin/python -m ncmthai.sp_tokenizer --input data/thai_corpus.txt --vocab 8192 --out data/spm_thai
.venv/bin/python -m ncmthai.thai_data --out-dir data --sp data/spm_thai.model --seq-len 128
.venv/bin/python -m ncmthai.train_tokenizer --config configs/thai-toy.yaml
.venv/bin/python -m ncmthai.train_generator --config configs/thai-toy.yaml
.venv/bin/python -m ncmthai.ar_baseline --data data/thai_ids.pt --vocab 8192 --out runs/thai-ar/ar.pt
.venv/bin/python -m ncmthai.eval_thai --config configs/thai-toy.yaml \
  --ckpt runs/thai-toy --ar runs/thai-ar/ar.pt --ar-args 384,8,6 \
  --sp data/spm_thai.model --eval-data data/thai_ids.pt
```

## Notes

- Checkpoint format matches upstream eval: `{'model': state_dict}`, generator
  adds `inference.level0_unigram` (what `scripts/eval_shard.py` reads).
- Tokenizer trainer keeps the shipped `vq_loss` (all levels) rather than the
  paper's "VQ terms evaluated at cutoff only" — matches what the released
  forward computes; EMA updates need every level active anyway.
- CPU runs: always `--batch` small and rely on `CheckpointedNCP` (auto-on for
  `--device cpu`); earlyoom on mn01 kills >~2.5GB RSS.
