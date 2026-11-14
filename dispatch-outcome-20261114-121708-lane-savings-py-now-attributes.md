# Dispatch outcome — kk-mac-usage-to-lane-savings (2026-11-14)

## What changed

Picked option (a): `finish_kk_mac_lane()` copies ollama usage into
`action.result` as a TOKENS_RE-parseable fragment.

- `scripts/board/runner-agent.py` — `finish_kk_mac_lane` now returns a
  4th element `tokens_fragment`: `kk_mac_local
  "tokens":{"total":T,"input":I,"output":O}` built from
  `kk_mac_result.json` usage (`prompt_eval_count`=input,
  `eval_count`=output; missing counters → 0, malformed → no fragment).
  `finish_pass` PREPENDS the fragment to the finish `result` so it
  survives board-api's `result[:300]` cut and lands durable in
  `action.result`.
- `scripts/devnest/kk_mac_llm.py` — `run_task` usage now captures
  `prompt_eval_count`, `prompt_eval_duration`, `total_duration` (prompt
  tokens were previously dropped → input side unmeasurable).
- `tests/board/test_executor_contract.py` — 4 `finish_kk_mac_lane` call
  sites updated for the 4-tuple; pass test asserts the fragment.
- `scripts/board/lane-savings.py` — docstring notes the kk_mac fragment
  as a token-evidence source.
- `docs/ssot/jobs/devnest/2026-11-14-kk-mac-usage-to-lane-savings.yml` —
  mechanism trail.

## Also re-landed (found lost)

The card's premise — "lane-savings.py now attributes
action.executor=kk_mac_local (patched 2026-11-13)" — was false on
master: the patch (747b44bbd0) was pushed on
`dispatch/20261113-202232-card-judgment-eval-done-2026-1` but its
close-out merge was held on a test-gate timeout and never merged.
Cherry-picked 747b44bbd0 (EXECUTOR_LANES attribution + eval-backed
qwen2.5:32b repin + routing-proposal doc) and 4266b6785f (session
outcome file). Skipped d3ea9c56ad — master's assessment file is newer.

Without the attribution restore, a kk_mac card carrying `"tokens":{`
would mis-attribute to `free-opencode` (OPENCODE_SIG fires on the same
substring) — so it was required for the done-condition.

## Result / verify

- `tests/board/test_executor_contract.py` KkMac suite: 24/24;
  test_runner_agent_lane: 23/23; queue-time classify kk: 40/40.
- Fragment verified through the `result[:300]` board-api cut →
  TOKENS_RE extracts (total,input,output).
- Synthetic e2e card → `lane-savings.py --month 2026-11` renders
  `| kk_mac_local | 1 | 1 | 1 | 1 | 120/45 |` and lists the card in
  offloaded_sessions. Real evidence lands on the next kk_mac_local run;
  pre-patch cards (kk-mac-supervised-probe-20261113 etc.) stay
  counts-only by design — done-condition met.
- Env note: /tmp tmpfs user quota filled during the full suite run
  (stale pytest-N dirs, 5.9G) — cleared dirs older than today; one test
  "failure" was Errno 122, not code.

Branch `dispatch/20261114-121708-lane-savings-py-now-attributes`,
HEAD 5f7c8bca9e (+ cherry-picks 51fe437e50, 7dfa16c839). Not pushed.
