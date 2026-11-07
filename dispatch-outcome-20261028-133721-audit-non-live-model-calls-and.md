# Dispatch outcome — model-key-usage-control audit

**Result: audit complete, delivered as commit `e0a4c93c9` on
`dispatch/20261028-133721-audit-non-live-model-calls-and`. No caps,
routes, or services changed; nothing pushed or deployed.**

## What was found

- **Cap divergence is real and now evidenced.** `LiteLLM_AuditLog` is
  empty (audit logging off — hardening gap #1). Journal shows
  `POST /key/update` from idc03 localhost at 2026-10-24 09:08 and
  14:07, each immediately after a `chaba` $5-cap 422 storm during the
  `ai-workforce-eval` OpenCode burns (~$27.5 across `chaba`+`ada` via
  `or-claude-fable-5.1` + `or-gemini-3.5-flash`, requester tony-dell).
  Caps were raised live to unblock the eval and never written to SSOT.
- **Live budgets (2026-10-28):** chaba $19.72/$20 (99%), ada
  $14.53/$30, bench $2.01/$2 **over cap and 422ing now**, kk $3.99/$5,
  michael $1.51/$5, mddb $0.13/$10. All reset 2026-11-01.
- **`ada` key is not a spare** — it actively serves interactive
  opencode from tony-macbook (14 calls/48h).
- **`ada`/`chaba`/`mddb`/`michael` have `models={}`** — unrestricted
  model access; any key holder can burn paid legs.
- **Direct-Google bypasses still open** (unmetered, SpendLogs bypass):
  `devin-bank-distill` (chaba-paid.env PAID key, no GEMINI_BASE_URL),
  `ada-memory-distill` (PAID), `backlog-spec-enrich` (PAID),
  `ada-lesson-miner` (FREE), `wp-news-digest` fallback legs (PAID),
  `yomi-api`. Probes intentionally stay direct. Gemini Live WS +
  Edge TTS excluded per spec.
- **Live litellm config.yaml drifts from repo** (fable/omen/colab/groq
  legs + custom_callbacks — never written back).
- **No virtual-key budget watcher existed**; daily-ledger published
  hardcoded stale caps. board-api `/lesson` Thai was already fixed
  free-only via PR47 (verified earlier: mddb alias, no paid fallback,
  EN degrade).

## What changed (in branch, 14 files)

- `scripts/ada/gemini_rest.py`, `litellm_chat.py`: `tags` /
  `litellm_metadata` params → `x-litellm-tags` + `x-litellm-metadata`
  headers, sent **only to gateway bases** (never to direct Google).
- Call-site tagging: board-api, news-digest, wp-comment-sync,
  kanban-brief (service/job/route).
- `scripts/litellm/budget-watch.py` (new): near-cap watcher, ≥80% warn /
  ≥100% alert / uncapped note, LINE + ops-event + incident-card sinks,
  `--selftest`/`--dry-run`/`--json`. Live-smoked on idc03 → verdict
  `alert`.
- `daily-ledger.py`: live `VerificationToken` budget table replaces the
  stale hardcoded caps line.
- Tests: `tests/litellm/test_budget_watch.py`,
  `tests/ada/test_litellm_tags.py` (23 cases); **44 unittest green**.
- `ssot.llm-gateway.yml`: budgets block now records live-vs-documented
  values + audit evidence; SSOT jobs trail +
  `docs/reports/2026-10-28-model-key-usage-audit.md` filed.
  SSOT validation: 3224/3224 valid.

## Open decision (board request raised)

`cap-policy-after-audit` on the card: codify live (chaba $20, ada $30)
into SSOT ★recommended vs revert post-reset; plus approval to flip the
6 direct batch jobs onto the gateway (env-only). Awaiting Tony.

## How to verify

```
python3 -m unittest tests.litellm.test_budget_watch \
  tests.ada.test_litellm_tags tests.ada.test_gemini_rest \
  tests.board.test_board_api_mutations   # 44 tests OK
ssh idc03 'python3 - --dry-run' < scripts/litellm/budget-watch.py
   # verdict: alert — bench 100%, chaba 99%
python3 scripts/litellm/budget-watch.py --selftest
```
