# dispatch-triage-arbiter-label-pass — outcome

## What changed

Rebuilt and ran the strategy-(b) arbiter label pass on tony-omen after the
prior idc02 work was lost (completed on branch
`dispatch/20261120-194941` but never merged). All deliverables landed and
committed as `69966b28b6` on `dispatch/20261123-144218-approved-strategy-b-per-the-bo`:

- `scripts/bench/dispatch-triage/label.py` — iterates
  `docs/ssot/kanban/cards/**/*.yml` (1778 files → 1758 unique request
  texts, 30 ground-truth suite rows excluded), calls the arbiter through
  the LiteLLM gateway `gemini-3.5-flash-lite-free` deployment (no paid
  fallback → $0 guaranteed; model id hard-guarded by a free-only
  allowlist), batched 10 texts/call with per-row fallback on parse
  failure, retries on 429/5xx with capped backoff.
- `scripts/bench/dispatch-triage/ledger.jsonl` — per-text verdict store;
  re-runs skip already-labeled rows (verified: `pending=0`, 0 calls).
- `scripts/bench/dispatch-triage/labeled-corpus-2026-11-23.jsonl` —
  `{text, source, label, confidence, model, ts}` per spec.
- `scripts/bench/dispatch-triage/review-queue-2026-11-23.jsonl` — 100
  rows: 12 below the 0.7 confidence threshold + 88 deterministic
  stratified spot-check rows. Nothing below threshold was silently
  labeled into the suite-append set.
- `scripts/bench/dispatch-triage/suite-append-2026-11-23.jsonl` — 1658
  above-threshold rows in the ada-voice
  `tests/bench/orch-triage-cases.jsonl` schema ({text, kind:triage,
  label, set:triage, slice:harvest-2026-11-23}) matching the
  `dispatch-triage` hard tier's `corpus-harvest` rotation.
- `scripts/bench/dispatch-triage/append-suite.py` — dedup-appends suite
  rows and supports `--adjudications` for post-check review rows.
- `docs/ssot/jobs/nest/2026-11-23-arbiter-label-pass.yml` — counts,
  cost, and the full 100-row spot-check list for Tony.

## Result

- Labeled 1758 rows: ops 742 / code 614 / research 226 / docs 149 /
  clarify 27 (conf_mean 0.895), 0 unverdicted.
- 174 batched calls + per-row fallbacks, 18.9 min, $0 — the free
  deployment has no paid fallback leg; intermittent 429 storms rode out
  on capped backoff.
- Review queue posted on the card; the pre-existing spot-check request
  is already answered (check first, then append), so the
  `suite-append-2026-11-23.jsonl` → `orch-triage-cases.jsonl` append on
  the tony-dell ada-voice checkout stays held until Tony's ~30-50min
  check.

## How to verify

- `wc -l scripts/bench/dispatch-triage/labeled-corpus-2026-11-23.jsonl` → 1758
- `wc -l scripts/bench/dispatch-triage/review-queue-2026-11-23.jsonl` → 100
- `python3 scripts/bench/dispatch-triage/label.py --date 2026-11-23`
  → `pending=0`, zero calls, same stats
- commit `69966b28b6`; card comms updated

lessons:
  - The LiteLLM URL in litellm-chaba.env already ends in /v1 — append
    /chat/completions, not /v1/chat/completions.
  - Free-lane 429s come in storms ("No deployments available… 60
    seconds"); capped backoff rides them out — no paid fallback needed.
  - A dispatch branch that completes but never merges loses all
    artifacts; check `git branch -a` for the prior attempt before
    rebuilding.
  - YAML plain scalars cannot contain ": " — quote values like
    `gateway: '… (key = …)'` in job docs.
