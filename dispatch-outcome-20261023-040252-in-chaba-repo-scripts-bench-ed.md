# dispatch-outcome — edu-agent lane-lift turn 2 (card edu-agent-lane-lift-turn2)

## What changed

`scripts/bench-edu-manage.py` — AgentLane structured-output hardening:
- `parallel_tool_calls: false` on every request;
- malformed `arguments` JSON repaired (balanced-brace extraction,
  trailing-comma strip, `ast.literal_eval`) — counted `arg_repairs`;
- calls still unparseable or missing schema-required params are NOT
  executed — an error is fed back as the tool result so the model
  re-emits (stricter schema retry) — counted `arg_errors`;
- a reply that looks like a malformed text-blob call escalates once to
  `response_format: json_object` where the backend supports it
  (auto-disabled lane-wide on a 4xx complaint) — `json_retries`;
- new `--ollama-timeout` flag (default 300s, was hardcoded 150 — a
  ~9 tok/s RAM-offloaded reasoning model hit the old cap);
- counters land in `scores.*.loop` + a method-note line in the .md.

End-to-end verified against a stubbed OpenAI-compat backend:
repair→exec, reject→error-feedback, blob→forced-JSON→exec all fire;
`parallel_tool_calls:false` on all requests.

## Result — gpt-oss:20b vs 2026-10-22 baseline (identical fixture, MockStore)

| lane | F1 | dedupe | ops | recall | draft-Q | completed | p50 | tok-in |
|---|---|---|---|---|---|---|---|---|
| current (10-22) | 1.0 | 3/5 | 5/5 | 3/3 | 5.0 | 13/13 | ~0-3s | 0.9k |
| clawbot (10-22) | 1.0 | 4/5 | 5/5 | 3/3 | 4.72 | 13/13 | 12.5s | 74k |
| hermes3:8b (10-22) | 0.545 | 2/5 | 3/5 | 1/3 | 3.9 | 12/13 | 19.4s | 31k |
| local-gpt-oss-20b (t2) | 1.0 | 3/5 | 5/5 | 3/3 | n/a | 13/13 | 78.3s | 43k |

First local lane to match `current`/`clawbot` on capture+ops+recall —
clean sweep over hermes3:8b. Does NOT beat clawbot: dedupe 3/5 < 4/5
(same two systemic misses: t3 re-ask forked 'tailscale ACL tags'
instead of updating 'tailscale acl basics'; t6 filed without the
`ada-nest-*` prefix + hub refresh) and ~6x slower p50 — but ~42%
fewer prompt tokens at $0. The hardening never fired on gpt-oss (0/0/0
counters — spec-clean tool_calls all 36 rounds); it's validated
insurance for weaker lanes.

## Honest partials (recorded, not fabricated)

- **clawbot lane not run** — mn01 has no `OPENROUTER_API_KEY` (secrets
  originate on macbook; never synced) and no LiteLLM virtual key; OR
  probes return 401. Board request raised on the card for a key sync —
  unanswered at finish.
- **draft-Q = n/a** — both GEMINI_API_KEYs on mn01 (ada-ha-tony,
  ada-ha-michael) 429 on every attempt (free-tier daily quota exhausted
  by ~11:00 +07); no LiteLLM virtual key on host. All 7 filings keep
  full HTML in `tasks[].filings[].content` — re-judgeable offline
  without rerunning the lane.

## Landed (dispatch branch, commit 58c50c8a)

- `scripts/bench-edu-manage.py` (loop change)
- `reports/bench-edu-manage-2026-10-23.{json,md}`
- `docs/ssot/jobs/models/2026-10-23-edu-agent-bench-turn2.yml`
- verdict comm posted on `edu-agent-lane-lift-turn2`; key-sync board
  request open (`mn01-has-no-openrouter-api-key-secrets-o-2e1151`).

## Verify

```
git show 58c50c8a --stat
cat reports/bench-edu-manage-2026-10-23.md
python3 scripts/bench-edu-manage.py --lanes hermes --ollama-model gpt-oss:20b \
  --tasks t2-skip-commands --no-judge --out /tmp/x   # needs tailnet to omen
```
