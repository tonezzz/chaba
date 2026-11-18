# Consultant reroute verification — ada-expert-consult-tool (Jules → direct model call)

**Date**: 2026-11-18 ~22:30 +07 (15:30 UTC) · **Runner**: idc02 · **Card**: consultant-reroute-verify (ADA-0061)
**Method**: live calls against LiteLLM gateway `http://100.102.134.91:4000` with `LITELLM_KEY_BENCH`, plus repo/gateway state audit.

## What "the new path" is

Merged consultant first-filter: `scripts/ada/consultant-bench.py` (merged 9ca978eb, PR #135) sends a bounded answer/escalate triage prompt to a LiteLLM model. Design: kk-mac `qwen3:8b` triages for free (alias `ollama-qwen38b-kkmac` → kkmac-admission-shim :11447 → kk-mac ollama tunnel); a paid model fires only when the verdict is `escalate`.

## Verified live state

| Item | Result | Evidence |
|---|---|---|
| Triage leg `ollama-qwen38b-kkmac` | **DOWN** — kk-mac offline (heartbeat `2026-11-18T12:51:19Z`, ~2.7h stale; tailscale last seen ~2h). Shim 503s instantly: `admission denied: heartbeat_stale` | direct call, shim `/health` |
| Raw-alias fallback | None — `ollama-qwen38b-kkmac` has no fallbacks entry; after `allowed_fails:2` the deployment cooldowns → 429 `No deployments available` | gateway error body, config.yaml fallbacks |
| Job-class aliases `bench`/`classify` (kk-mac leg-1 chains) | **Paid fires on kk-mac outage**: same triage prompt was served by `gemini-3.5-flash-lite` paid in ~3–4s — "paid only on escalation" does NOT hold through these aliases | live call |
| Paid escalation leg | Works: `chat` → `gemini-3.5-flash` paid answered in 2.0s; spend ledgered to key | live call |
| `consult-flash` dedicated alias | **Not provisioned** — 400 `Invalid model name`; not in `/v1/models` | live call |
| `LITELLM_KEY_CONSULT` ($5/30d cap, answered 2026-11-17) | Not minted on this host (litellm-keys.env has BENCH/ADA/CHABA only) | secrets inventory |
| `feat/ada-consult-gateway` PR #180 (consult aliases, single upstream, no fallback) | **Unmerged** — no consult aliases in `stacks/idc03/litellm/config.yaml` | git |
| ada-voice `ada_consult.py` (bounded context 2k/12k chars, $0.10/call preflight, ada-dev gate) | **Unmerged** — lives only on `origin/ada-consult-1454700384695425195`; `origin/main` tools.d has no consult | git |
| Virtual-key spend cap | BENCH key `max_budget: null` (uncapped); only the proxy-wide $75/30d belt applies. No per-key consult budget exists anywhere | `/key/info` |
| Degraded free triage option `cf-qwen3-30b` | 429 — CF free quota exhausted today | live call |

## Item-by-item verdict

1. **Real consult e2e** — PARTIAL. The merged path executes end-to-end (harness → gateway → shim), but leg 1 cannot serve while kk-mac is off the tailnet; the paid leg works independently.
2. **qwen3:8b triage + paid-only-on-escalation** — NOT confirmed live. kk-mac cannot answer today. Prior committed evidence (2026-11-12): qwen3:8b 6/6. Through job-class aliases, paid silently fires on kk-mac outage — the invariant holds only on the raw alias (fail-closed) or a future no-fallback consult alias.
3. **Bounded context + virtual-key spend cap** — NOT applied in production. Harness bounds output tokens only; the real bounds + $5/30d key + $0.10/call preflight are all on unmerged branches. BENCH key itself is uncapped.
4. **First real-world accuracy** — today: 0/6 (admission_denied ×3 → gateway cooldown 429 ×3), `reports/consultant-bench-ollama-qwen38b-kkmac.{json,md}`. First recorded run 2026-11-12: qwen3:8b **6/6 (acc 1.00, p50 3.15s, esc-rate 0.50)**; deepseek-v3.2 5/6 (0.83).

## Findings / follow-ups

- **Availability is the weak leg**: kk-mac is a member device — hours-long outages stall triage completely (raw alias) or silently burn paid (job-class aliases). Options: (a) accept paid-lite fallback as designed degrade (paid fires on infra failure too — weakens the invariant); (b) dedicated `consult` job-class alias kk-mac→CF-free→paid (CF was also quota-dead today); (c) fail-closed with a clear "consult unavailable" surface.
- **The dedicated consult spend layer is stalled since 2026-11-17**: PR #180 (chaba aliases), LITELLM_KEY_CONSULT mint ($5/30d — answered), ada-voice PR #12 ($0.10/call preflight — answered). Nothing deploys it; reroute isn't actually live for the paid-escalate design.
- Fixture is 6 toy cases — `consultant-fixture-grow-20-cases` (ADA-0062) already cards this.
