# dispatch-outcome — ada-consultant-tier (attempt 2, idc02)

## What changed

Attempt 2 recovered and finished the prior session's work instead of
redoing it: the 2026-11-09 branch (`dispatch/20261109-135333`) already
carried the full lane + bench artifacts but died on 3 merge conflicts.
Both commits cherry-picked onto today's master; all conflicts resolved:

- `scripts/ada-jobs/verify_worker.py` — `--consultant` flag
  (env `ADA_JOBS_CONSULTANT`) alongside the newer `--with-distill`;
  defer-verdicts route `to: consultant`; consultant-ownership guard on
  `eligible()`/`eligible_cleanup()`. Flag OFF by default — production
  behavior unchanged.
- `scripts/ada-jobs/consultant_worker.py` — NEW. Drains `to: consultant`
  board requests: answer/comment/close/escalate under the same
  authority-matrix enforce (gated classes refused, conf<0.7 -> escalate,
  escalation re-raises to Tony with framing + suggested pick).
- `scripts/board/board-api.py` — ACTORS += `consultant`; selftest
  extended (consultant target quiet, respond works); docstring updated.
- `docs/ssot/infrastructure/ssot.jobs.yml` — `ada-jobs-consultant` job
  (idc03, *:7,37) + `systemd/generated/idc03/` units; conflict resolved
  by keeping HEAD's ada-retention/merge-proposals jobs and inserting the
  consultant job after verify. `jobs.idc03.yml` re-rendered (also picked
  up pre-existing drift: ada-memory-merge-proposals, ada-transcript-archive).
- `stacks/idc03/litellm/config.yaml` — `model_name: consultant` ->
  `ollama_chat/qwen2.5:32b` **via :11447 admission-shim** (the branch's
  :11445 ssh tunnel was retired 2026-11-17 — conflict resolved to the
  current kk-mac path).
- `docs/ssot/kanban/ssot.kanban.yml` + `ssot.ada-participation.yml` —
  consultant actor/tier docs.
- `scripts/bench/card-judgment/score.py` — `--max-tokens` knob.
- Prior session's outcome doc + all `consultant-*` run artifacts carried
  forward as the bench record.

## Corpus audit (the work the card's `open:` item asked for)

Audited every consistent-miss case against the real card lifecycle:
11/12 labels CORRECT — the misses were genuine model over-deference.
ONE relabel: `observe-006` (stale-report-regen-lane, pri:high) — the
proven-right outcome was escalation ("held in review for your call";
Tony closed it himself), mislabeled `observe` only because the
escalation rode a comms note instead of a requests[] entry. Relabeled
-> defer in `corpus.jsonl` + `corpus-v4.jsonl` with `audit_note`
provenance. Full per-case audit:
`scripts/bench/card-judgment/consultant-corpus-audit-2026-11-19.md`.

## Re-scored verdict (stored predictions, corrected gold, 98-case set)

- qwen2.5:32b: **P/m/m** — run1 0.857/0.908/0.938 PASS; runs 2-3 miss
  deference by exactly one case (0.898 vs 0.90). Deterministic
  over-defer — benign direction but under the bar.
- qwen3:8b: **P/P/P/m** — runs 1-3 hit the letter of the 3x-consecutive
  gate under corrected gold, but run4 over-acts on 8 defer-gold cases
  (defer-002/007/012/015/017/025/028/030) — the dangerous direction.
  Straddles the gate; not stable enough to sit between Ada and Tony.

**NO CANDIDATE CERTIFIED — `ADA_JOBS_CONSULTANT` stays OFF.** Bench yml
updated to `status: done` with the audit section + revised verdict.

## Follow-up filed

Card `consultant-brain-confirmation-bench` (ADA-0236, backlog): fresh
x3 confirmation series on the corrected corpus for qwen3:8b (and one
qwen2.5:32b run — it sits one borderline case under the bar; a prompt
tune, not a relabel, is its path). Activation order documented in the
bench yml for whenever a brain certifies.

## Verification

- `python3 scripts/board/board-api.py --selftest` -> selftest ok
  (the `lib` module warning is pre-existing on master)
- `python3 scripts/render-jobs.py --check` -> OK 115 jobs, 8 hosts
- `python3 scripts/render-jobs-catalog.py` -> re-rendered, committed
- `python3 -m py_compile` on verify_worker + consultant_worker
- yaml.safe_load on all touched SSOT/config files; prose-smell 0 flagged
- score.py runs clean on the relabeled corpus (rules-entity smoke)

## Notes for the merger

- Lane is inert end-to-end: flag off => no `to:consultant` requests can
  exist => `ada-jobs-consultant` exits clean. Landing is safe.
- board-api restart + litellm reload needed after merge for the ACTORS /
  model_name additions to take effect (they're dormant otherwise).

lessons:
- Prior dispatch branches often survive locally — `git branch -a | grep <slug>` before redoing work; this card's whole lane + bench was recoverable by cherry-pick + 3 conflict resolutions.
- `render-jobs.py --host X` writes systemd units to ~/.config/systemd/user/ only WITH --install — I fat-fingered it onto idc02 once; removed units + wants symlink + daemon-reload fixed it.
- Corpus gold labels mined from comms-only escalations can mislabel defer as observe — when auditing, check whether TONY made the call (his column moves in the card history), not just whether a requests[] entry exists.
- The :11445 kk-mac ssh tunnel is retired; all kk-mac litellm routes now gate through :11447 admission-shim — update any ported config that still references :11445.
- The bench corpus on master drifted to 94 cases (v4 rebuild) since the 98-case consultant runs — re-scoring stored run JSONs needs the run-time case set, not the current corpus file.
