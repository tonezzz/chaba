# kk-cms-only memory experiment — re-test post-mortem (2026-11-24)

**Scope:** step 4 of the CMS-only re-test plan — reconcile profiles, start
the dev lane, rewrite the seed scenario, apply the profile, run
`kk_memory_cms` twice and explain the result.

**Status:** **not green, and not repeatable.** Two valid runs scored 0.5 and
0.333. Both are real model/harness signals, not infra outages (no
infra/quota scenarios, `violations: none`, both benchmark docs `valid: true`).

## What was changed before the runs

- `bench_profiles.kk-cms-only` / `kk-parity` reconciled against
  `persons.kk.tools` (see `tests/ada/test_bench_profile_parity.py`).
- `kk-bench-env.py` hardened; `--profile kk-cms-only --apply` backed up
  `ada-kk-dev.env`, wrote the declared block, read it back, restarted
  `ada-kk-dev.service` and polled `/api/health` (backup
  `ada-kk-dev.env.bak.20261124T124035Z`). `--check` is clean afterwards.
- `kk_cms_only_seeded_recall.yaml` rewritten: single test-only writer
  (`cms_publish_page`), `cms_edit` removed, ZETA marker required in the
  stored content, and a `cleanup.mddb_delete` block that removes pages
  containing `ZETA-KK-CMS-7741` from `ada-cms-pages-kk-dev`.
- Scenario schema check: 204 files, 0 violations.

## Results

| Run | Score | seeded_recall | honest_miss | no_memory_leak |
|---|---|---|---|---|
| 19:47 | 0.500 | fail | flaky | pass |
| 19:58 | 0.333 | fail | fail | pass |

Benchmark docs: `benchmark/kk_memory_cms-20261124-194732` and
`-20261124-1958xx` in `ada-ha-scenario-reports`.

## Root causes (from the captured turn transcripts)

### 1. `honest_miss` — harness false negative, behaviour correct

- Run 1 turn 1 tool list: `set_facial_expression, ada_session_recall`.
- Run 2 turn 1 tool list: `set_facial_expression, ada_memory_search`.
- Failure text: `no_calls: got ['ada_session_recall'] (exempt: ...)`.

Both memory tools are in the profile's `exclude`, and the deployed provider
does contain the dispatch-level lane gate (`d277b08`; `_tool_excluded` at
`realtime_provider.py:3980`, refusal at ~5604). But the provider emits the
`tool_call` event **before** checking the gate (`:5528` vs `:5604`), so a
*refused* attempt still lands in the scenario's tool list and fails
`no_calls_except`. The spoken answers were honest ("I don't have
information about repainting the kitchen cabinets") in both runs.

**Conclusion:** this is not a memory leak. The assertion needs to count
successful calls only, or treat `tool_denied` as satisfying the guard.

### 2. `seeded_recall` — the seed never persists; recall comes from context

- Run 1 turn 2 (confirm): tool list `[]` — no `cms_publish_page` call.
- Run 2 turn 2 (confirm): tool list `[]` again; she narrates adding the
  ZETA reference but never calls the writer.
- `ada-cms-pages-kk-dev` is empty before and after both runs (MDDB query),
  so the cleanup is working but there is no page to clean.
- Run 2 turn 5 *did* call `cms_read` but answered "Tuesdays and Thursdays
  at 6am" — the day-name divergence first seen in the October write-fidelity
  finding, now on the recall side.
- Run 1 turn 5 answered from session context with no `cms_read` at all.

**Conclusion:** the confirm-gated seed step is unreliable on this model/
prompt, so the suite is testing session context, not CMS memory. The
`reconnect: {away_s: 2}` does not create a genuinely fresh session.

### 3. Environment noise (not scored)

Repeated `mddb write failed: Remote end closed connection without response`
messages during event writes. They do not stop the benchmark: both final
docs were persisted. Worth tracking separately (MDDB connection churn).

## What is now proven / not proven

- **Proven:** the reconciled profile applies and restores cleanly; the dev
  service starts and is healthy; `no_memory_leak` is consistently green;
  honest-miss *answers* are honest even when the model tries a barred tool.
- **Not proven:** that Kaewta can write a report to CMS and later recall it
  from CMS alone. The suite cannot currently demonstrate that.

## Step 5 — fixes applied and results

1. **Harness fix landed** (`scenario-live.py`): new
   `no_successful_calls_except` assertion correlates `tool_call` /
   `tool_result` by id and ignores calls refused by the lane gate. The old
   `no_calls_except` semantics are unchanged (gate scenarios still see
   denied attempts). 3 unit tests in
   `ada-voice/tests/test_scenario_live_harness.py`.
2. **Scenario hardened**: explicit slug `zeta-kk-cms-7741`, direct tool
   instruction, publish result must say `status: published`, recall turns
   require a `cms_*` read whose result carries the seeded content,
   `chat_send` exempted from the honest-miss guard (an actuation, not a
   memory source).
3. **Post-fix runs**: 20:17 → 0.5, 20:24 → **0.667**. `honest_miss` and
   `no_memory_leak` are now consistently green; `seeded_recall` is still red.

**Remaining blocker for `seeded_recall`:** the seed page never persists.
In the last run the confirm turn *did* call `cms_publish_page` (12 tool
calls across the scenario) but the result did not say `published`, and
`ada-cms-pages-kk-dev` is still empty. The suite repeatedly logs
`mddb write failed: Remote end closed connection without response`. A
direct MDDB probe from idc03 reproduced it: `/v1/add` returned no response
within 12s (the document did appear on a retry search), `/v1/search` timed
out once. MDDB write latency/instability is now the leading cause — before
further scenario work, storage health must be fixed or the lane pointed at
a healthy MDDB.

## MDDB triage (2026-11-24 20:30 +07)

- MDDB primary is on idc03 (`:11023`); `/health` and `/v1/health` do not
  answer, but `/v1/search` and `/v1/add` do (slowly / intermittently).
- `get_indexing_status`: **3976 pending embeddings, 1398 failed**, oldest
  pending 15:46 — ~5 hours of backlog; progress stuck at 91%.
- `gemini-ollama-proxy` logs are all Gemini **429 quota exhausted** on the
  free keys, `circuit open 600s`. The proxy deliberately caps the paid
  Gemini leg (`PAID_GEMINI_DAILY_CAP` / `HOURLY_CAP`) and the OpenRouter
  leg (`OR_FALLBACK_DAILY_CAP`) as spend firewalls — once those are hit it
  hard-fails instead of draining a key. Raising those caps is a spend
  decision, not a safe auto-fix.
- Host pressure: load 3.8–5.8, 3.8/4.0 GiB swap used, two `mddbd`
  processes at 36.5% / 6.5% CPU. Three `/api/embed` calls in a 4s window
  returned 400 after 8s.
- A direct `/v1/add` probe hung past 12s; the document appeared later and
  delete succeeded. So writes are *eventually* consistent but far slower
  than `cms_publish_page`'s timeout — which is why the seed result never
  said `published`.

**Decision:** do not pilot CMS-only memory in production. `honest_miss`
and lane isolation are proven; "write a report and recall it from CMS"
is not — partly model behaviour (she often claims the page already exists
and skips the writer), partly the embedding-provider outage above.

## Final two runs (20:43 and 20:48 +07)

Re-check at 20:40 showed the backlog draining (3976 → 3469 pending,
completed 40529 → 41039) with the OpenRouter leg serving; direct MDDB
add/search/delete probes all returned HTTP 200 in <10ms. So the storage
gate was open and I ran the suite twice more.

| Run | Score | seeded_recall | honest_miss | no_memory_leak |
|---|---|---|---|---|
| 20:43 | 0.667 | fail | pass | pass |
| 20:48 | 0.667 | fail | pass | pass |

`honest_miss` and `no_memory_leak` are stably green. `seeded_recall` is
still red **with healthy storage**: no `zeta-kk-cms-7741` page exists in
`ada-cms-pages-kk-dev` after either run. Transcripts show the remaining
failure is model behaviour, not infra: she often says the page already
exists and calls only `cms_read`, then on the confirm turn emits no tool
call at all (or never passes the confirm_token). Prompt rewrites —
explicit slug, explicit tool name, explicit confirm_token instruction —
did not make it reliable across two runs.

**Final decision:** do NOT productionize CMS-only memory for Kaewta on
this evidence. Lane isolation and honest misses are proven; "write a
report and recall it from CMS" is not. The next approach should seed the
CMS page deterministically (a producer/out-of-band write asserted before
the reconnect) instead of asking the model to perform publish+confirm in
one scenario; that is a new experiment, not another prompt tweak.

## Post-deploy verification and bench hygiene (2026-11-25)

After deploy to `678b960`, two runs scored 0.667 / 0.833. Transcripts showed
two distinct issues, neither a CMS-recall regression:

1. A stale October page `garden-watering-schedule` in `ada-cms-pages-kk-dev`
   was being read instead of the ZETA seed (produced a "Tuesday" answer).
2. The repeated recall turn sometimes answered from retained session
   context without a second `cms_read`, failing `calls_any`.

ada-voice branch `bench/kk-cms-only-bench-hygiene-20261125` (commit
`a1e00ea`) fixes both: `seed_evict:` purges stale same-topic pages before
seeding; `response_contains_all_any` asserts day + pump with language
alternates and forbids Tuesday; only the FIRST recall must prove a CMS
read — the repeat is judged on correctness. Two runs after the fix: 0.833
(one flaky first-recall turn with no tool call but a correct answer) and
**1.000**. Harness tests: 6 passed; schema: 204 files clean.

Probe documents created during triage were deleted; the dev env is left
with the reconciled `kk-cms-only` profile applied and healthy.

## Outcome after deterministic seeding (21:04 and 21:06 +07)

The recommended next action was implemented: `scenario-live.py` gained a
top-level `seed:` block (write via `/v1/add`, verify via `/v1/search`,
INFRA exit on failure), the seed scenario now seeds the ZETA page out of
band and tests only reconnect + recall, and `cleanup` removes the page.

| Run | Score | seeded_recall | honest_miss | no_memory_leak |
|---|---|---|---|---|
| 21:04 | **1.000** | pass | pass | pass |
| 21:06 | **1.000** | pass | pass | pass |

Both runs are valid, with `violations: none`, and the seeded page was
gone after each run (empty `ada-cms-pages-kk-dev`). Harness unit tests:
5 passed; scenario schema: 204 files, 0 violations.

**Revised decision:** the read-side properties are now proven twice on a
reproducible fixture: with bank/recall tools and web_search stripped,
Kaewta answers a covered question from a CMS report after a fresh
session, honestly misses an uncovered one, and never leaks a bank tool.
The production question that remains is a *product* decision, not a
bench result: prod Kaewta still has `persons.kk.tools` (bank + web_search),
her public writes go to `wp_*`/`cpt_post`, and CMS pages are TTL'd. A
pilot should be a deliberate, reversible env-profile change on `ada-kk`
with KK's acceptance — not an automatic promotion of this bench surface.

## Session-prime isolation (2026-11-25, final)

Post-deploy runs exposed a flaw in "CMS-only": session prime injected
`Recent sessions:` and channel tails with stale October watering content,
so the model answered "Tuesday" even after a `cms_read`. Turning the whole
prime off (`ADA_SESSION_PRIME=0`) was worse — 0.5 — because it also removed
the CMS catalog and identity, so the model never thought to read a page.

`ADA_PRIME_SKIP_HISTORY=1` (ada-voice cceb7f5, PR #25) skips only the
stale-prone parts — recent-sessions summary, channel tails, headlines and
prime-flagged facts — while keeping identity, CMS catalog and persona
style. `kk-cms-only` now sets `ADA_SESSION_PRIME=1` +
`ADA_PRIME_SKIP_HISTORY=1` via the managed env-knob block; `kk-parity`
restores both to defaults. `kk-bench-env.py` gained that block with the
same backup/diff/check/verify/rollback safety as the tool block (12 tests).

Final runs after the fine-grained knob: 1.0, 0.833, 0.833. `seeded_recall`
is green in every run; residual flakes are benign live-state tool calls
(`tasks`, `ada_persona`), not bank leakage or fabrication. The read-side
case is now solid; production remains a product decision with KK.

