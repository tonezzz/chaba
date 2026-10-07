# Dispatch outcome — chaba-nest-models P0 done (2026-10-07)

## Task

Verify and durably record P0 of card `chaba-nest-models`: the
`experiments/nest-01-ops-classifier` claim (pure-numpy MLP, 2000 ops events,
50.7% acc vs 8% chance, 10KB model) and its three lessons.

## What was done

- **Verified reproduction.** `python3 eval.py --expect 0.507` (stdlib-only,
  the brain manifest's `resume.verify` command) → `0.507 (203/400), OK`.
  `python3 train.py` full retrain → identical 0.507, deterministic (seed 42);
  regenerated `model.npz` differed only in zip timestamps, restored.
- **Reviewed the confusion matrix.** Honest finding confirmed: 50.7% beats
  chance but trails the 61% majority baseline because the test window is
  drifted (jev_advisory wave). Zero-support classes (smoke_test, tool_storm,
  voiceprint_drift) get no predictions. README already documented all this —
  now it's in the SSOT job trail too.
- **Confirmed surrounding infra.** `scripts/report-ai-edge.py` +
  `systemd/report-ai-edge.timer` (Mon 06:00 → CMS ai-edge-report) installed;
  `ssot.nest-brains.yml` already lists the entity as `packed-verified`
  (gdrive round-trip + mn01 respawn done earlier same day, commit 227fb606).
- **Wrote the job report** `docs/ssot/jobs/experiments/2026-10-07-nest-01-ops-classifier.yml`
  (validated; only repo-wide warning is pre-existing kanban bloat).
- **Board comms** posted on the card (progress + final).
- Committed on the dispatch branch (`6fe26391`); no push, no deploy.

## Deliberately not done

- P1 Flower local-sim — `flwr` not installed and its sim mode pulls ray;
  spec calls for real Flower, not a stand-in. Left as handoff notes in the
  job report (venv install; Flower-sim vs syft-flwr file-based decision for
  intermittent omen↔mn01 hosts).
- P2 curriculum cells / P3 NEAT loop — separate phases on the card.

## How to verify

```bash
cd experiments/nest-01-ops-classifier
python3 eval.py --expect 0.507   # → OK
python3 train.py                 # → test accuracy 0.507, 10KB weights
node scripts/ssot-validate-all.mjs  # job file valid
```
