# dispatch outcome — consultant-reroute-verify (ADA-0061)

**Task**: post-merge verification of the ada-expert-consult-tool reroute (Jules → direct model call): real consult e2e, kk-mac qwen3:8b triage + paid-on-escalate, bounded context + virtual-key spend cap, first real-world accuracy.

**Result: PARTIALLY VERIFIED — the reroute is not actually live end-to-end today.**

What I ran/found (all against the live gateway `http://100.102.134.91:4000`, LITELLM_KEY_BENCH):

1. **Real consult e2e** — ran `scripts/ada/consultant-bench.py --model ollama-qwen38b-kkmac --fixture fixtures/consultant-tasks.jsonl`. The path executes, but leg 1 is down: kk-mac has been off the tailnet ~2.7h (heartbeat 12:51:19Z stale, tailscale last-seen ~2h). The admission shim correctly fails fast — 503 `heartbeat_stale`, then LiteLLM cooldown 429s.
2. **qwen3:8b triage / paid-only-on-escalate** — kk-mac can't answer right now (prior evidence: committed bench 6/6 on 2026-11-12). Confirmed the failure semantics: raw `ollama-qwen38b-kkmac` has NO fallback (fail-closed, paid never silently fires), but the `bench`/`classify` job-class aliases DO fall back — the identical triage prompt was served by paid `gemini-3.5-flash-lite` in ~3–4s, so through those routes paid fires on infra failure too.
3. **Bounded context + virtual-key spend cap** — NOT applied live: `consult-flash` → 400 invalid model; `LITELLM_KEY_CONSULT` not minted on idc02; chaba PR #180 (`feat/ada-consult-gateway`) and ada-voice `ada_consult.py` branch both unmerged; BENCH key `max_budget: null` (proxy-wide $75/30d is the only belt; spend went $0.32 after my calls). The $5/30d key cap and $0.10/call preflight exist only in unmerged code.
4. **First real-world accuracy** — today: **0/6** (3× admission_denied 503 → 3× cooldown 429). First recorded run 2026-11-12: qwen3:8b **6/6 (acc 1.00, p50 3.15s, esc-rate 0.50)**, deepseek-v3.2 5/6.

**Artifacts**: `reports/2026-11-18-consultant-reroute-verify.md` (full evidence table), `reports/consultant-bench-ollama-qwen38b-kkmac.{json,md}` (today's run). Board comments posted to `consultant-reroute-verify` + cross-ref on `ada-expert-consult-tool`.

**Follow-ups flagged** (on parent card): the dedicated consult spend layer (PR #180 aliases, LITELLM_KEY_CONSULT mint, ada-voice consult merge) is stalled since 2026-11-17 and nothing deploys it; kk-mac availability (member device, hours-long outages) needs a declared degrade — fail-closed stall vs paid-lite fallback (burns paid on infra failure) vs free CF leg (also 429 today).

**How to verify**: `curl http://100.102.134.91:4000/v1/chat/completions -H "Authorization: Bearer $LITELLM_KEY_BENCH" -d '{"model":"ollama-qwen38b-kkmac",...}'` — expect 503 while kk-mac is down; re-run `python3 scripts/ada/consultant-bench.py --model ollama-qwen38b-kkmac --fixture fixtures/consultant-tasks.jsonl` when its heartbeat returns for a clean accuracy number.
