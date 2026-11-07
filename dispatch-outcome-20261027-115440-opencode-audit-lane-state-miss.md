# Dispatch outcome — audit-oc-lane-state-missing-lane (AUD-0950)

## What was found

**Confirmed, root-caused, fixed.** `lane_gate.py` resolved its state dir
as `REPO/evals/opencode-lane/state/` from `__file__` — i.e. *inside
whatever checkout ran the script*. The 2026-10-27 S0 run happened in a
dispatch worktree on tony-macbook, so `stage.json` (S0→S1 promotion) and
`metrics.jsonl` (10 records) lived only in that ephemeral, gitignored
dir and were destroyed when the worktree was deleted. Every fresh
checkout also silently re-initialised the lane at S0 (fails closed, but
loses promotion history and stage quotas). The per-job ledger is
unrecoverable from git — only the aggregate in the committed
`reports/2026-10-27-promotion-review.json` survives; the AUD-0938
session audit already reconciled it against the OpenCode session DB.

## What changed

- `scripts/devnest/lane_gate.py`
  - `state_dir()` resolves `$OPENCODE_LANE_STATE`, else
    `${XDG_STATE_HOME:-~/.local/state}/opencode-lane` — per-host, stable
    across checkouts/worktrees; a surviving legacy in-repo `state/` is
    migrated once via `copytree`.
  - `review()` embeds the stage's lane-arm records under `ledger:` in
    the committed review JSON — the verified-job aggregate stays
    re-derivable even if state is lost again.
  - New `restore <S> --from-review <review.json>` subcommand: rebuilds
    `stage.json` after state loss, refusing unless the review's
    decision is `promote`→`<S>`; records the restore in stage history.
- `tests/devnest/test_lane_gate.py` — `OPENCODE_LANE_STATE` pinned to a
  tempdir (tests never touch host state); +6 tests (env override, XDG +
  legacy migration, ledger embed, restore accept/refuse).
- `evals/opencode-lane/PROCEDURE.md` — state path corrected, new
  "State-dir loss & recovery (AUD-0950)" section with the restore
  command.
- `.gitignore` — repo-local path kept ignored as the *legacy* location
  (comment updated).
- `docs/ssot/jobs/devnest/2026-10-27-opencode-graduated-routing-procedure.yml`
  — stale `state:`/`ledger:` lines corrected.
- New trail: `docs/ssot/jobs/devnest/2026-10-27-opencode-lane-state-loss-audit.yml`.

## Verification

- `python3 -m unittest discover -s tests/devnest` → 60 tests, all green
  (40 lane_gate incl. 6 new).
- CLI smoke in temp `OPENCODE_LANE_STATE`: fresh init at S0 →
  `restore S1 --from-review <committed review>` writes stage.json with
  evidence-cited history → second restore refuses → S0 envelope at S1
  denies `wrong_stage` (+ other fail-closed reasons).

## Pending operator step (tony-macbook, after merge)

```bash
python3 scripts/devnest/lane_gate.py restore S1 \
    --from-review evals/opencode-lane/reports/2026-10-27-promotion-review.json
```

Rebuilds stage.json at S1 with cited evidence. The lost S0
`metrics.jsonl` is not recreated — the review's embedded `ledger:` plus
the AUD-0938 session-DB reconciliation is the durable record.

Residual: state remains host-local by design (single watched runner).
If tony-macbook dies the live ledger is lost again, but every weekly
review is now self-contained; a periodic state-dir backup is a possible
follow-up.
