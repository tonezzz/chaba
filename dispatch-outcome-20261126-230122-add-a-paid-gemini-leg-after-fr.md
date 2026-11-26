# dispatch outcome — gemini-proxy-paid-last-resort-leg

**Verdict: ALREADY DONE — verified, no proxy code change needed.** The
paid-Gemini leg shipped 2026-11-13 (PR #171) and was extended since
(spend caps `af69a924e66`, free-key circuit `3d07c239cc6`, free-lane
budgets `eb5dba63b9b`). This dispatch re-verified ordering live on idc03
and by forced-failure probes against BOTH the deployed file and repo
master, and added a regression test.

## What changed in this worktree

- `tests/embed/test_gemini_proxy_paid_leg.mjs` — NEW node:test suite
  (2 tests, both pass): spawns the real proxy against stub Gemini
  (free key → 429, paid key → 200) + stub Ollama; asserts
  `provider=gemini-embedding-2-paid` with zero Ollama hits, and that a
  `PAID_GEMINI_DAILY_CAP=1` refusal falls through to
  `nomic-embed-text` as literal last resort.
- `docs/ssot/jobs/mddb/2026-11-26-gemini-proxy-paid-leg-verify.yml` —
  full verification record (live state, probe method, caps, caveat).

No changes to `scripts/mddb/gemini-ollama-proxy.mjs` — it already
contains the leg in `fetchBackupBatch` on both paths (OR/gateway chain
before hard-fail; free-first path before Ollama), `GEMINI_API_KEY_PAID`
env passthrough, and the spend firewall.

## Verified live on idc03 (via tony-omen jump; con01 has no proxy, idc01 down)

- Unit `gemini-ollama-proxy.service` active, container Up since
  2026-11-25 19:15, healthy, `127.0.0.1:11435`.
- Container env contains `GEMINI_API_KEY_PAID` (presence checked, value
  never read) plus caps: `PAID_GEMINI_DAILY_CAP=2000`,
  `PAID_GEMINI_HOURLY_CAP=150` (≈ ≤$0.20/day worst case),
  `OR_FALLBACK_DAILY_CAP=5000`, free-lane budgets set in the quadlet.
- `/health`: `provider_mode=gemini-primary`, `embed_gateway="embedding"`,
  `free_keys=6`, `paid_calls_today=0`, zero consecutive failures.
- **Spend cap (card requirement): 150 paid batches/hr and 2000/day per
  UTC window**, enforced before any billed call; cap-hit emits
  `embed_paid_cap` ops event and embeds hard-fail (retryable).

## Forced free-429 probe (card done-criterion)

Ran the UNMODIFIED deployed file
(`~/.config/containers/mddb/proxy/gemini-ollama-proxy.mjs`, sha256
`a8c3df80…`) locally with mock upstreams — the live file hardcodes
generativelanguage.googleapis.com so a `node --import` fetch-rewrite
preload redirected it to a local stub (harness in
`.dispatch-scratch/probe-paid-leg.mjs`, untracked):

- free-first: both free keys 429 → `provider=gemini-embedding-2-paid`,
  Ollama hits = 0.
- gateway-down (OR leg configured): gateway 500 → OR circuit opens →
  paid serves; next request skips the dead gateway hop.
- cap-then-ollama (`PAID_GEMINI_DAILY_CAP=1`): req1 paid, req2
  `paid Gemini daily-cap 1 hit` → `provider=nomic-embed-text` — Ollama
  is provably the last resort and the cap bounds spend.

Same probes against repo master (`d58adf9b…`) via the new committed
test file: identical ordering.

## Vector-space caveat (documented)

Paid key = same `gemini-embedding-2` model/space as free (billing tier
only) → index-safe. Ollama `nomic-embed-text` is a different space: the
OR/gateway path refuses it (hard-fail beats wrong-space writes); only
the no-OR path may reach it last. Documented in code comments (both
variants) and `docs/kb/mddb-embedding-providers.md`.

## Finding → new card MEM-1464 `gemini-proxy-live-repo-divergence`

The RUNNING proxy on idc03 is an **uncommitted variant** (free-key ring
~6 effective keys + LiteLLM embed-gateway leg) that exists nowhere in
git; repo master has budgets but not ring/gateway. The ansible-regenerated
quadlet (2026-11-26) now mounts the REPO file — the next unit restart
silently swaps variants (loses ~6x free quota → more paid spend, still
capped; loses gateway leg; gains budgets). Card filed; do NOT restart
`gemini-ollama-proxy.service` until resolved.

## Verify

- `cd tests/embed && node --test test_gemini_proxy_paid_leg.mjs` → 2/2 pass.
- On idc03: `curl -s http://127.0.0.1:11435/health` →
  `circuit.paid_daily_cap=2000`, `paid_hourly_cap=150`.
- Job record: `docs/ssot/jobs/mddb/2026-11-26-gemini-proxy-paid-leg-verify.yml`.

lessons:
- Live idc03 proxy runs host-local uncommitted code (free-key ring + gateway) — repo master is a DIFFERENT variant; always hash-compare deployed file vs repo before assuming.
- Live proxy hardcodes generativelanguage.googleapis.com (no GEMINI_API_BASE env in deployed variant) — probe it via node --import fetch-rewrite preload, not env override.
- idc03 SSH needs double-hop `ssh tony-omen 'ssh tony@100.102.134.91 ...'` — ~/.ssh/config ProxyJump tony-omen is refused (administratively prohibited).
- Card re-armed by triage can already be DONE — check comms history + git log -S before writing code.
