# Test plan: NotebookLM as an SSOT query backend

## Hypothesis

NotebookLM, after syncing the Chaba SSOT and KB, can answer structured
infrastructure questions that otherwise require `mcp_query_ssot` or
`mcp_ssot_get`. If the accuracy is high enough, it could become a fallback
query interface for assistants and a source for generated runbooks.

## Scope

We only test SSOT-style questions with **objective, verifiable answers** that
`mcp_query_ssot` can also answer. We do not test subjective or design questions.

## Ground truth

Every question will be answered first by the SSOT resolver:

```bash
mcp_query_ssot path=<ssot-file> key=<dotted-path>
```

The result is treated as the canonical correct answer.

## Query method

```bash
nlm query notebook fdfd3483-6b7e-4cb0-85f3-7f060698769c "<question>" --timeout 120
```

Run each question with the default agent and with a short system-style prefix:

> "Answer concisely. If you are not sure, say 'I don't know'. Cite the source title if you can."

## Test queries

| # | Question | Expected ground-truth | SSOT key |
|---|----------|----------------------|----------|
| 1 | What is the Tailscale IP of tony-dell? | 100.68.142.13 | ssot.values.yml:hosts.tony_dell.tailscale_ip |
| 2 | What is the NotebookLM notebook ID used for the Chaba KB? | fdfd3483-6b7e-4cb0-85f3-7f060698769c | ssot.values.yml:notebooklm.sync.notebook_id |
| 3 | What port does the NotebookLM REST service bind to on tony-dell? | 3011 | ssot.values.yml:ports.notebooklm_rest |
| 4 | What is the URL of the Michael dev Home Assistant instance? | https://tony-dell.taila0626a.ts.net:8124 | ssot.home-assistant.michael.dev.yml:environments.dev.https.tailnet_url (resolved) |
| 5 | What is the public URL of the NotebookLM REST API? | https://tony-dell.taila0626a.ts.net/apps/notebooklm/api | ssot.services.yml:tony-dell.notebooklm-rest.public_url (resolved) |
| 6 | What is the HA Live public port? | 8444 | ssot.values.yml:ports.ha_live_public |
| 7 | What is the tailnet URL of the michael-dev Home Assistant? | https://tony-dell.taila0626a.ts.net:8124 | ssot.home-assistant.michael.dev.yml:environments.dev.https.tailnet_url (resolved) |
| 8 | What is the local port of the tony Home Assistant MCP? | 9584 | ssot.values.yml:ports.ha_mcp_tony |
| 9 | What is the default collection for NotebookLM? | chaba | ssot.values.yml:notebooklm.default_collection |
| 10 | What is the rclone remote for the Chaba notebooklm collection? | gdrive | ssot.values.yml:notebooklm.rclone_remote |

## Evaluation criteria

For each query, record:

1. **Correctness** — does the answer match ground truth exactly or closely enough?
2. **Source citation** — does it name the source chunk (e.g., `infrastructure-1`) it used?
3. **Hallucination** — does it invent values not in the SSOT?
4. **Latency** — how long did the query take?

Scoring:

- `2` — exact and cited
- `1` — correct but no citation, or slightly imprecise
- `0` — wrong or hallucinated

## Metrics

- **Accuracy** = sum of scores / (questions × 2)
- **Pass rate** = percentage of questions with score ≥ 1
- **Hallucination rate** = percentage of wrong answers that invent facts
- **Average latency** in seconds

## Procedure

1. Ensure `ssot.values.yml` is correct and the NotebookLM notebook is up to date
   with `python3 scripts/notebooklm-kb-sync.py`.
2. For each question, run both `mcp_query_ssot` and `nlm query`.
3. Record the answers and scores in a new `docs/kb/experiments/notebooklm-ssot-query-benchmark-YYYY-MM-DD.yml`.
4. Compare NotebookLM results against `scripts/bench-kb-search.py` (MDDB baseline).
5. Identify which SSOTs NotebookLM misses; add them to the sync list if needed.

## Success criteria

- **MVP**: ≥ 60% accuracy and ≤ 10% hallucination.
- **Useful**: ≥ 80% accuracy, source citations for ≥ 70%, latency ≤ 30s.
- **Production ready**: ≥ 90% accuracy and ≥ 80% citation rate.

## Risks and limitations

- NotebookLM is not a structured resolver; it may fail on dotted paths or
  numeric values.
- Dynamic references like `${ssot(...)}` are stored as resolved strings, so the
  model sees the current value, not the expression. This is good for answers but
  makes it hard to show the derivation.
- The model may conflate similar keys (e.g., `ha_michael_dev` vs `ha_tony`).
- Answers change as the model and the synced sources update, so results are not
  perfectly reproducible.

## Next steps after the test

- If MVP is met, extend the query set to `mcp_ssot_get` registry-style questions.
- If accuracy is low, split large chunks further, add a `glossary` source, or
  preface questions with `In the ssot.values.yml file...`.
- Consider a hybrid: use NotebookLM for fuzzy search, but ground the final answer
  with `mcp_query_ssot`.
