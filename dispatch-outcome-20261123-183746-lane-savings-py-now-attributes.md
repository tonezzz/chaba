# Dispatch outcome — kk-mac-usage-to-lane-savings (attempt 3)

Date: 2026-11-23 · host: tony-omen · branch: dispatch/20261123-183746-lane-savings-py-now-attributes

## What changed

Option (a) from the card spec — kk_mac Ollama usage now flows into
`action.result` where lane-savings.py's `TOKENS_RE` already scans:

- `scripts/devnest/kk_mac_llm.py` — usage dict now also captures
  `prompt_eval_count` (Ollama's input-token count); `eval_count`,
  `eval_duration`, `load_duration` were already captured and persisted
  into `<taskdir>/kk_mac_result.json` by kk_mac_executor.
- `scripts/board/runner-agent.py` —
  - new `_kk_mac_tokens_fragment(usage)` builds the compact JSON
    fragment `{"tokens":{"total":N,"input":N,"output":N}}` that
    lane-savings' `TOKENS_RE` matches literally.
  - `finish_kk_mac_lane` stashes the fragment on the runner state entry
    (`ent["result_extra"]`) whenever the run's usage carries counts.
  - `finish_pass` prepends `ent["result_extra"]` to the finish `result`
    posted to board-api — the fragment lands at the front of the string
    so it survives board-api's `result[:300]` → `action.result` cap.
  - the in-claim fallback handoff (`kk_fb` path) pops `result_extra`
    before starting the next lane's unit, so a declined kk_mac leg
    never leaks its usage into the next executor's finish result.
- `tests/board/test_executor_contract.py` — two regression tests in
  `KkMacExecutorContractTest`: pass verdict + usage sets a TOKENS_RE
  fragment (asserted against the real `lane-savings.TOKENS_RE`, and
  that the prepend survives `[:300]`); no usage → no `result_extra`.

The 2026-11-13 executor-attribution side (`EXECUTOR_LANES` in
lane-savings.py, card kk-mac-routing-proposal) was already merged —
only the token-evidence half was missing.

## Verification

- `pytest tests/board/test_executor_contract.py` — 107 passed
  (includes the two new tests).
- `pytest tests/devnest/test_kk_mac_llm.py tests/devnest/test_kk_mac_executor.py` — 26 passed.
- `pytest tests/board/test_dispatch_runner_resilience.py` — 17 passed.
- Fixture end-to-end: a closed card with
  `action.executor=kk_mac_local` and the fragment in `action.result`
  through `lane-savings.py --month 2026-11` reports
  `kk_mac_local | 1 | 1 | 1 | 1 | 1500/200` — satisfies the card's
  done-condition (tokens in/out in the monthly report).

## Result / state

Commit `4fcfa5d8ea` on the dispatch branch. No push, no deploy —
installed runner-agent copies (`~/.local/bin/runner-agent`) pick this
up only after the branch merges and runners redeploy (several runners
already flag the installed↔repo drift as a defer reason).

lessons:
- Prior attempt's work was lost because the finish post reported "no push, no deploy — changes remain in the worktree" and the worktree was never merged; commit on the dispatch branch early, not just at session end.
- The executor-contract suite alone takes ~7.3 min — the pre-commit fast test gate (15s) always times out on it; run targeted pytest yourself before committing.
- board-api stores only `a["result"] = result[:300]` — any evidence fragment for lane-savings must be PREPENDED to the finish result, not appended.
- lane-savings `TOKENS_RE` matches the literal `"tokens":{"total":N,"input":N,"output":N}` (compact, no spaces) — `json.dumps(indent=...)` output won't match.
- On the in-claim kk_mac fallback path the state entry survives to the next lane's finish — pop `result_extra` there or the next executor inherits a stale token claim.
