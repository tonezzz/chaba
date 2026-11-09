# dispatch-outcome — ada-consultant-tier (tiered judgment)

## What changed

Tiered judgment lane implemented end-to-end, flag-gated off until a
consultant brain qualifies:

- `scripts/board/board-api.py` — `consultant` added to `ACTORS`;
  `to: consultant` requests are quiet (no Tony notification); selftest
  extended for create/respond/consultant-quiet paths.
- `scripts/ada-jobs/verify_worker.py` — `--consultant` flag (env
  `ADA_JOBS_CONSULTANT`): on defer-verdict-with-uncertainty the request
  goes `to: consultant` instead of `to: tony`. Consultant-ownership
  guard: once a card carries any `to:consultant` request, the consultant
  owns that card's judgment call (no re-defer churn). Default behavior
  unchanged without the flag.
- `scripts/ada-jobs/consultant_worker.py` — NEW. Drains `to: consultant`
  requests with the qualified brain (litellm `consultant` alias, kk-mac
  fallback), applies the same authority-matrix enforcement as Ada
  (gated actions, review-column closes, evidence required), and either
  resolves in place (comment/evidence/close) or re-raises to Tony with
  framing and a suggested choice.
- `docs/ssot/infrastructure/ssot.jobs.yml` — `ada-jobs-consultant` job
  on idc03 (every 30min, :07/:37), rendered units committed under
  `systemd/generated/idc03/`; inert while routing flag is off.
- `stacks/idc03/litellm/config.yaml` — `model_name: consultant` →
  `ollama_chat/qwen2.5:32b` via the kk-mac tunnel (:11445).
- `docs/ssot/infrastructure/ssot.ada-participation.yml` —
  `consultant_tier` section: routing rule, qualification gate,
  confidence, escalation, metrics, shadow status.
- `docs/ssot/kanban/ssot.kanban.yml` — actor enums / request endpoint
  docs updated for `consultant`.
- `scripts/bench/card-judgment/score.py` — `--max-tokens` knob
  (qwen3 thinking needed headroom above the 640 default).
- `docs/ssot/jobs/bench/2026-11-09-consultant-brain-bench.yml` — full
  jobs trail: probes, runs, verdicts, activation order.

## Bench results (composite = ada-entity prompt + enforce + briefs, temp 0.3, v3 corpus 98 cases)

| model | host | result |
|---|---|---|
| llama3.2:3b (prior) | kk-mac | 0.7755/0.8367 — below threshold (ceiling confirmed) |
| gpt-oss:20b | tony-omen | DQ on throughput: CPU-bound (222MB of 14GB in VRAM), 4min+/case, timeouts |
| qwen3:8b | kk-mac | NOT QUALIFIED — r1 PASS (0.898/0.918), r2 miss def=0.898, r3 PASS (0.929/0.949), r4 miss (0.847/0.878); temp-0.3 variance swings both ways, can't hold 3x |
| qwen2.5:32b | kk-mac | NOT QUALIFIED — r1 0.847/0.898, r2 0.847/0.888, r3 0.847/0.888; deterministic over-defer on the same ~12 cases (defer-gold 30/30 clean every run) |
| or-* | OpenRouter | blocked: free-tier daily cap 429 / model-access denied on eval key |

## E2E verification

Local board-api harness (`/tmp/consultant-e2e`, module-loaded on :8899,
CARD_DIR/CARDS_JSON/LOCK redirected) + seed card with open
`to: consultant` request. `consultant_worker --once` (qwen3:8b direct)
returned `close` conf=1.0 citing OPS-999 evidence; enforce allowed;
writes landed: `column: done`, request `answered`, 3 `from: consultant`
comms. Full defer→consultant→resolve loop verified.

Also verified: `board-api.py --selftest`, python compile of changed
files, YAML parse of all touched SSOT, `verify_worker` eligibility
guard logic, `consultant_worker.enforce()` on all action paths.

## Activation order (not performed — deployment not authorized)

1. Land branch / merge card-union
2. board-api restart (ACTORS change)
3. litellm reload (`consultant` model_name)
4. Install `ada-jobs-consultant` units on idc03
5. `ADA_JOBS_CONSULTANT=1` on verify-worker once a brain qualifies

## Open / follow-ups

- **No candidate qualified** — `ADA_JOBS_CONSULTANT` stays off; Ada's
  deferrals keep going straight to Tony until a brain passes 3x.
- Corpus audit: the 12 consistently-missed cases
  (act-001/003/005/007/012/014/006, observe-001/003/004/006/008) may be
  borderline gold labels — if relabeled the 32b passes; if correct it
  needs a prompt tune. Cheapest path to a qualified consultant.
- `or-*` rerun when OpenRouter quota resets or eval key gains model access.
- JEV classify → `task_class=judgment` routing is ada-voice side, out of repo.
- Prior-attempt note: dispatch/20261109-090808 branch had partial bench
  work, never pushed (tony-omen lacks push creds) — this branch supersedes it.
