# Non-Live model call & key-budget audit — 2026-10-28

Card: `model-key-usage-control` (SEC-0962). Runner: idc02 dispatch
worktree. Method: code inventory + live LiteLLM Postgres read
(SpendLogs/VerificationToken/journal) + secrets-file var-name checks
(values never read). **No caps, keys, routes, or units changed.**

## 1. Non-Live text call inventory

### Gateway-metered (SpendLogs-visible, key-alias attributed)

| Caller | Route | Virtual key | Metadata |
|---|---|---|---|
| ada REST side-calls (gemini_pool, ada-voice) | ADA_GEMINI_REST_BASE_URL → /v1beta | per-lane: chaba/michael/kk/bench | `lane,tool,session` ✓ (verified in SpendLogs) |
| board-api /lesson Thai | `gemini-3.5-flash-lite-free` (PR47) | mddb | `service,job,route` ✓ (added this session) |
| wp-news-digest EN synth + brief_th primary | `chat-local` / `summary` | mddb | tagged this session |
| wp-comment-sync intent classify | `chat-local` | mddb | tagged this session |
| chaba-kanban-brief llm_why | `chat-local` | chaba | tagged this session |
| embed-lane-news/-lessons jobs | `ollama-nomic-embed` | chaba | none |
| ada-embed-bench --publish (weekly) | `embedding` class | mddb | none |
| bench-recall / shadow_eval / devnest+opencode evals | bench aliases, `or-*` legs | bench / chaba / ada | `User-Agent: opencode` only |
| usage-feed, daily-ledger, budget-watch | read-only (psql/admin) | master | n/a |

### Direct / unmetered (SpendLogs bypass)

| Caller | Key resolved | Class | Note |
|---|---|---|---|
| wp-news-digest `brief_th` **fallback leg** + `synthesize` gemini fallback | mddb-gemini.env `GEMINI_API_KEY` (**PAID**) | text | gateway `summary` first; direct-paid only when gateway call fails |
| `devin-bank-distill` (con01, weekly) | chaba-paid.env `GEMINI_API_KEY` (PAID) | text | no `GEMINI_BASE_URL` in env file → direct |
| `ada-memory-distill` (idc03, weekly) | tony-ha/backend.env `GEMINI_API_KEY` (PAID) | text | no `GEMINI_BASE_URL` → direct |
| `ada-lesson-miner` (idc03) | gemini-keys.env `GEMINI_API_KEY_FREE` | text | direct **free** tier |
| `backlog-spec-enrich` (idc03) | mddb-gemini.env `GEMINI_API_KEY` (PAID) | text | direct |
| yomi-api container (idc03, always-on) | `GEMINI_API_KEY` env | text | Google SDK direct |
| mddb `gemini-ollama-proxy` (idc03, always-on) | `OPENROUTER_API_KEY` (OR-only mode) | **embed** | OR-metered, not LiteLLM |
| weather-bakeoff ×2 (idc03) | ada-ai-kraut.env — **no gemini key present** | text | currently degrades, $0 |
| yt-vtt-translate / yt-vtt-dub (ops, manual) | `GEMINI_API_KEY` | text | direct |
| bench tools: bench-or-scorecard, micro-bench, voice-bench, cam-wall vlm-bench, model-speed, embed-space-eval | OR/direct keys | bench | manual/bench lanes |
| Probes (by design): gemini-wallet-watch, secrets-inventory-cms, scenario-provider-gate, key-watch `--gemini-probe`, gemini-live-canary | each key's own probe | text | verify the key itself — must stay direct |
| dev/v0 providers, gev-gemini bridge, gpu-queue, mcp-colab, mcp-llama | various | dev/dead | dell powered off / dev apps / request-proxies not scheduled callers |

Out of scope per spec: **Gemini Live WebSockets** (direct by design,
paid project keys) and **Edge TTS** (separate service).

## 2. Live budget reconciliation (audited 2026-10-28 ~06:55Z)

| key | live cap/30d | spend | % | SSOT says | verdict |
|---|---|---|---|---|---|
| chaba | $20 | $19.724 | **99%** | $5 | diverged — cap raised 10-24 |
| ada | $30 | $14.528 | 48% | $10 "spare" | diverged — raised 10-24; **not spare** — serves interactive opencode (tony-macbook) |
| bench | $2 | $2.008 | **100%+** | $2 | at cap → 422ing now (by design) |
| kk | $5 | $3.989 | 80% | $5 | match |
| michael | $5 | $1.512 | 30% | $5 | match |
| mddb | $10 | $0.129 | 1% | $10 | match |

Reset: all `budget_reset_at = 2026-11-01`. `ada`/`chaba`/`mddb`/`michael`
have `models={}` — **unrestricted model access** (can call paid legs
like `or-claude-fable-5.1`); only bench/kk are allowlisted.

### Who changed the caps — evidence chain

- `LiteLLM_AuditLog` table is **empty** — proxy audit logging is off
  (no in-DB attribution; finding #1 for hardening).
- idc03 `journalctl -u litellm`: `POST /key/update` 200 from
  **localhost** at 2026-10-24 **09:08** and **14:07** — each preceded
  by a `Budget has been exceeded! Key=chaba ... Max budget: 5.0`
  422 storm starting 09:00.
- Same-day SpendLogs: chaba $14.38 + ada $13.14 on 10-24 —
  `User-Agent: opencode/1.19.4` + `OpenAI/Python`, requester
  **tony-dell** (100.68.142.13), models `or-claude-fable-5.1` and
  `or-gemini-3.5-flash`. Card trail: `ai-workforce-eval` (OPS-0809/0823
  "Fable prep") — eval dispatches ran paid-lane opencode/openhands
  benches and raised caps live to unblock them; never written to SSOT.
- `ada` key still actively serves opencode from **tony-macbook**
  (100.77.76.112) — 14 calls in trailing 48h.

### Live gateway config drift (uncommitted)

Mounted `~/.config/litellm/config.yaml` ≠ repo
`stacks/idc03/litellm/config.yaml`: adds `or-claude-fable-5.1`
(OPS-0823), omen ollama brains (qwen3/gptoss/gemma12b/hermes8b),
`colab-qwen3`, `groq-gpt-oss-120b/20b` + `groq-qwen3.8-27b`, groq legs in
the `voice-aux`/`classify` chains, and
`callbacks: custom_callbacks.proxy_handler_instance` (groq
reasoning-strip hook, `~/.config/litellm/custom_callbacks.py`).
`.bak-eval-1792757269` (2026-10-23 19:07 ICT) shows it was made for the
eval. Needs write-back or pruning (omen legs may be dead — dell/omen
off).

## 3. Near-cap alert/report — was missing, now exists

- `key-watch.py` covered OR/HA/CF/Gemini-direct probes — **not**
  VerificationToken budgets. bench sat over-cap and chaba at 99% with
  zero signal.
- `daily-ledger.py` published a spend page with a **hardcoded stale
  caps line** (ada $10 / chaba $5 / bench $2 — wrong on both live and
  SSOT terms, kk/michael/mddb absent).
- **Shipped in this branch:** `scripts/litellm/budget-watch.py`
  (psql/admin/file sources; ≥80% warn, ≥100% alert, uncapped → note;
  LINE + ops-event + incident card sinks; `--selftest`/`--dry-run`/
  `--json`), live-smoked on idc03 → verdict `alert`
  (bench at cap, chaba 99% warn). `daily-ledger.py` now renders a live
  `VerificationToken` budget table in the CMS page.
- Deploy pending: budget-watch timer install + `--publish` cadence.

## 4. Request-metadata acceptance — mechanism shipped

- Contract: `x-litellm-tags` + `x-litellm-metadata` headers (same
  mechanism ada `gemini_pool` uses — its `lane,tool,session` tags are
  visible in SpendLogs).
- Added: `tags`/`litellm_metadata` params on `gemini_rest.generate`/
  `generate_json` (gateway base only — never sent to direct Google)
  and `litellm_chat.chat`; stamped board-api, news-digest,
  wp-comment-sync, kanban-brief.
- Gap remaining: embed/embed-lane/bench callers + ada-voice non-pool
  subprocesses still untagged or no-metadata.

## 5. Paid-fallback policy — per chosen answers

- board-api /lesson: **free-only** (Tony, 12:33) — PR47 merged+deployed;
  `gemini-3.5-flash-lite-free` has no fallback chain, gateway-only
  base_url_override, EN degrade. Tests: `test_board_api_mutations` +
  `test_gemini_rest` + new `test_litellm_tags` (23 cases).
- Key caps: **audit-first** (Tony, 13:03) — audit complete; live caps
  untouched. Reconciliation decision now informed (see §6).

## 6. Recommendations (owner decisions needed)

1. **Cap policy:** codify live values (chaba $20, ada $30) into SSOT —
   usage is real (ada tony-lane REST + evals) — vs revert to $5/$10
   after the Nov-01 reset knowing chaba blocks mid-window. Recommended:
   codify chaba $20 + ada $30 AND write SSOT to match; bench $2 stays.
2. **Flip the 5 direct batch jobs onto the gateway** (env-only, each
   already honors `GEMINI_BASE_URL` + virtual key): devin-bank-distill,
   ada-memory-distill, ada-lesson-miner, backlog-spec-enrich,
   wp-news-digest fallback legs; yomi-api needs a code/env touch.
3. **Write back or prune** the live litellm config drift (fable/omen/
   groq/custom_callbacks) into `stacks/idc03/litellm/config.yaml`.
4. **Restrict `models={}` keys** (ada/chaba/mddb/michael) to their
   needed classes — right now any holder can burn paid Claude.
5. **Enable LiteLLM audit logging** (`store_audit_logs`) so future
   /key/update calls are attributable in-DB.
6. **Install budget-watch.timer** (6h cadence mirrors key-watch).
