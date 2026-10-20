# Dispatch outcome — ncm-thai-adaptation recon-spike

## What was done
Completed the recon-spike done-condition for card `ncm-thai-adaptation` (Tony picked
recon-spike 15:47; a prior session had posted a partial verdict comm but left
`awaiting_action` and no durable artifact).

- Cloned HazyResearch/ncm and inventoried shipped vs missing code: **all model code
  and training-time internals are released** (EMA codebook updates, dead-code restart,
  nested dropout, straight-through estimator all live in `forward()` under
  `self.training`; `idx_to_ncm_input()` already builds generator training inputs).
  Missing = trainer loops, conditioning-corruption fn, L_NCM loss, data pipeline,
  base-tokenizer trainer → **~1.2–1.5k LOC new code** (revises earlier 2–4k down).
- Extracted the full training recipe from the paper (App.B/C/F tables: tokenizer has
  0 encoder blocks, β=0.25, EMA 0.95–0.99, nested dropout 0.5; generator 12×768
  block-diagonal, corruption mean 0.5; LM1B budget 13.36B positions).
- Checked authors re training code: GH issue #2 open 5 days, unanswered; HF collection
  active (updated ~4d ago) → trainer exists but withheld. Did not post on Tony's
  behalf (needs his GitHub identity); flagged +1 on issue #2 as his cheap option.
- Picked Thai data/eval: mC4-th/OSCAR-th + SentencePiece BPE 8–16k; gen-PPL vs
  Typhoon/WangchanX + entropy (paper protocol), XL-Sum-th ROUGE, scb-mt-en-th BLEU.
- Posted verdict comm + raised next-step request
  `recon-done-toy-train-is-cheaper-than-fea-b244ca` (options: watch-only ★suggested /
  toy-train / typhoon-ft / drop) — spend + novelty-value is Tony's call.

## Changed files
- `docs/ssot/jobs/experiments/2026-10-20-ncm-thai-recon.yml` — committed durable
  findings (canonical copy; `reports/` is gitignored)
- `reports/2026-10-20-ncm-thai-recon.md` — full readable report (worktree-local)

## Result
recon-spike complete; decision punted to Tony via board request with researched
options. Toy-train is now well-scoped if he wants it: ~1.5k LOC + <$50 + few days,
Sudoku-reproduction recommended as first milestone.

## How to verify
- Card `ncm-thai-adaptation`: verdict comm + open request visible on board.
- `git show f5a20477` on this branch, or read
  `docs/ssot/jobs/experiments/2026-10-20-ncm-thai-recon.yml`.
