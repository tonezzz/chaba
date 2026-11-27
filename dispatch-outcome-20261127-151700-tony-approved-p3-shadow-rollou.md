# Dispatch outcome — ncm-variant-b-p3-shadow (2026-11-27)

## What was done

Ran the approved P3 SHADOW rollout of the role-conditioned Variant B detail
lane, end to end, inside `experiments/ncm-code-blocks-p3/` (new, self-contained,
stdlib-only Python — no torch/numpy/repo dependency at runtime).

1. **Frozen artifacts** — `packet/manifest.json` hashes 83 input files:
   `src/ncm_shadow.py` (corpus builder ported verbatim from
   `structure_content.build_records`, MLP inference, compat verifier,
   JevOS/Ollama clients), `model/rolecond-model.pt` (canonical torch
   state_dict) + `model/rolecond-weights.json` (float32 export used for
   replay; verified identical predicted token sets vs torch on all 24 role
   inputs, 0 mismatches, min |logit| 0.010878), `model/vocab.json` (81 tokens),
   `model/roles.json` (24 roles), 76 frozen `pack.yml` corpus files,
   `records-corpus.json`, `pre-registration.json`. Seeds [42,7,13], 3 reps.
2. **Corpus** — 73 pack.yml snapshot from chaba@79ae156f
   `scripts/colab/packs` (same `records[::2][:30]` selection as the scaled
   run) + **3 fresh real packs** from `scripts/devnest/video-packs`
   (`kk-mac-mlx-colab-scene0-control-20261124`,
   `kk-mac-mlx-colab-scene1-20261124`,
   `kk-mac-mlx-vimax-goldenhour-s0-20261124`) — verified absent from all prior
   training/eval corpora (the two `kk-mac-image-render-poc-20261126*` packs in
   the colab corpus were created Nov 26 and ARE in training data, so they
   could not serve as fresh).
3. **Pre-registration** — `packet/pre-registration.json` written BEFORE any
   provider call: median advantage >= +0.10, guard violations == 0, >=1 fresh
   pack in every rep; deterministic verifier primary, no LLM judge.
4. **Shadow run** — 99 cells (33 tasks x 3 paired reps). Arm A = JevOS
   jevos-v5 choice on idc03:8017 + fresh qwen2.5:7b-instruct glue on
   tony-dell (digest 845dbda0ea48 verified = recorded baseline; 39 unique
   (block,seed) calls deduped — temp-0 outputs are deterministic per pair).
   Arm B = same Jev choice + frozen role-conditioned MLP + deterministic
   compat verifier. 1 Jev fail -> base-role fallback (recorded). 0 glue fails.
   Runtime 1976s. $0 spend.

## Result

- Reps: lane 0.5758 / glue 0.1212, 0.0909, 0.0909 -> advantages
  +0.4545 / +0.4848 / +0.4848; **median +0.4848** (gate +0.10).
- **Guard violations: 0** across both arms.
- Fresh packs: ran in all 3 reps (all chose block=misc); both arms 0/9 on
  role-rep gold, but lane self-token F1 **0.4348 vs glue 0.3333**.
- Corpus-30-only slice reproduces the scaled run **exactly** (lane 0.6333,
  glue 0.1333/0.1000/0.1000) — strong harness-fidelity evidence.
- By block: lane pass 1.0 on 10 roles; 0.0 on misc/probe/render (the known
  weak roles). Glue passes only bench (1.0) and assemble (0.3333).
- **Replay PASS**: `packet/replay-proof.json` recomputes all 99 cell scores
  from recordings + frozen artifacts with ZERO provider calls; fingerprint
  sha256 `521d8ff2ee0c3b89…`, `matches_results: true`.

## Verdict: **PROMOTE** (recommendation only)

Pre-registered gate PASS. This is a recommendation to Tony — no production
lane switch, no user-facing promotion, no nest/pack config change;
`ncm-code-blocks-detail-composer` stays open in review. Honest limits:
no VQ tokenizer (supervised role->detail MLP), gold = role-representative
record, small local glue baseline, fresh coverage thin (all misc).

## Deliverables

- `experiments/ncm-code-blocks-p3/` — packet/{pre-registration,manifest,
  records-corpus,recordings,results,replay-proof}.json|md, run-record.log,
  src/ncm_shadow.py, model/*, corpus/* (90 files, 3.9MB)
- `experiments/ncm-code-blocks-p3/packet/report.md` — full report
- `docs/ssot/jobs/experiments/2026-11-27-ncm-variant-b-p3-shadow.yml` — job record
- Board comment posted on `ncm-variant-b-p3-shadow` with row counts, replay
  PASS, guard 0, advantage distribution, per-role breakdown, PROMOTE verdict.

## How to verify

```
cd experiments/ncm-code-blocks-p3
python3 src/ncm_shadow.py replay   # -> replay-proof.json, matches_results: true, 0 provider calls
python3 src/ncm_shadow.py report   # -> report.md verdict=PROMOTE
cat packet/results.json            # per-rep rates, by_block, fresh self-F1
```

## lessons:

- The scaled Variant B lane's gold is the role-REPRESENTATIVE record
  (last-wins per role), not each task pack's own tokens — per-role canonical
  detail, so lane pass/fail is a deterministic function of the Jev-chosen
  block only. Check this before designing per-pack claims.
- `scale_variantb.py`'s F1 is Dice on sets `2tp/(|g|+|p|)` — identical to
  `2pr/(p+r)`; keep the pass threshold on the UNROUNDED value (a rounded
  0.49996->0.5 edge exists).
- `sys.exit(fn() or 0)` prints any non-empty dict return and exits 1 —
  return None from CLI handlers.
- Fresh-pack candidates: the live checkout had 73 packs vs worktree's 71 —
  the extra `kk-mac-image-render-poc-20261126*` were created Nov 26 and ARE
  in training data; only `scripts/devnest/video-packs/*/pack.yml` (3 packs)
  were genuinely outside the corpus.
- qwen2.5:7b-instruct glue on tony-dell ran ~40-90s/call today; deduping on
  (block,seed) — the prompt depends only on block — cut 99 cells to 39
  calls with identical deterministic outputs.
