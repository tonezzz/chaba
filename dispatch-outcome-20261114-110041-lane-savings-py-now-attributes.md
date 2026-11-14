# Dispatch outcome — kk-mac-usage-to-lane-savings (2026-11-14 11:00)

## What changed (option a from the card spec)

- `scripts/devnest/kk_mac_llm.py` — `run_task` usage now captures
  `prompt_eval_count` (ollama `/api/generate` input tokens; previously
  only eval_count/eval_duration/load_duration were kept).
- `scripts/board/runner-agent.py` — `finish_kk_mac_lane` reads
  `kk_mac_result.json` usage and, whenever `eval_count` was recorded
  (pass or fail — the spend happened either way), sets
  `ent["result_extra"]` to a TOKENS_RE-parseable fragment
  `kk_mac_local {"tokens":{"total":T,"input":I,"output":O}}`.
  `finish_pass` prepends `result_extra` to the finish `result` so it
  lands in `action.result` and survives board-api's `result[:300]`
  cap; on the in-claim fallback-handoff path it is popped so kk_mac
  spend never pollutes the next lane's result.
- `scripts/board/lane-savings.py` — `EXECUTOR_LANES` +
  `kk_mac_local`/`jules`/`nlm_batch` in `CHEAP_LANES`, ported verbatim
  from commit `747b44bbd0`. That commit exists only on the unmerged
  dispatch branch `dispatch/20261113-202232-card-judgment-eval-done-…`
  — it is NOT on master, so the card's premise ("lane-savings now
  attributes action.executor=kk_mac_local") was not yet true here;
  without the port the done-condition cannot hold. Identical text
  means the later merge resolves clean.
- `tests/board/test_executor_contract.py` — the artifact-landed test
  now asserts the fragment is stashed and parses under lane-savings'
  own `TOKENS_RE` (total/input/output exact).
- `docs/ssot/jobs/devnest/2026-11-14-kk-mac-usage-lane-savings.yml` —
  job trail.

## Result

Done-condition demonstrated: a card with `action.executor=kk_mac_local`
closed with the usage fragment in `action.result` reports
`kk_mac_local | 1 | 1 | 1 | 1 | 1700/120` in the monthly lane-savings
table and appears under offloaded sessions with
`evidence=action.result,tokens,verified-close` (1,820 measured tokens).

## How to verify

- `python3 -m unittest tests.board.test_executor_contract` — 78/78 OK.
- Fixture repro: `python3 scripts/board/lane-savings.py --month 2026-11
  --cards-dir /tmp/ls-cards --repo /tmp/ls-empty` (fixture card left in
  /tmp on tony-omen).
- Live: the next kk_mac_local closeout writes the fragment into
  `action.result`; the monthly report's kk_mac_local row then shows
  token-evidenced=1 with tokens in/out. Legacy taskdirs lack
  `prompt_eval_count`, so input=0 for pre-change results.

No push, no deploy — changes stay in this worktree.
