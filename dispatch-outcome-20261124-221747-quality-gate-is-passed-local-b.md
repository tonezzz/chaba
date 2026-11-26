# Dispatch outcome — BGE production serving architecture (decision card)

Card: `bge-production-serving-architecture-rera-e6ba35` · Runner: idc02 ·
Branch: `dispatch/20261124-221747-quality-gate-is-passed-local-b` (committed
`fd142d63e5`, not pushed — per dispatch rails).

## What I found

The card is a **decision card** — quality gate passed 2026-11-08 and the
spec says the serving-architecture call is Tony's on UX latency budget.
Since the spec was written, most of the plumbing already landed:

- Rerank endpoint **live** on omen `100.75.102.88:11555` — probed
  `/health` today: `ok:true, device:cuda, served:0`; `/rerank` correctly
  401s without the bearer token (ADA-1299 auth on).
- Shadow lane (`bge_memory_shadow` in ada-voice) deployed opt-in on
  ada-dev + ada-ha-tony since ~Nov 17-19, validated 10/10 live
  scenarios; runbook `docs/kb/bge-memory-search-shadow.md`.
- Prereq cards done/archived: `ada-bge-memory-search-shadow`,
  `bge-serving-path-dense-retrieval-with-in-b080f6`.
- `mddb-leader-bge-m3-migration-11023` is in review — if landed,
  production dense retrieval is already bge-m3 and the question narrows
  to the rerank stage.

**Decision-critical correction:** the spec's "top-10 ~565ms" came from
the eval harness (~57ms/pair). The Nov 18-19 live shadow soak measured
`rerank_ms` 1078-1412 for 9-10 docs (~110-140ms/pair effective), so a
synchronous top-10 arm lands **~1.4-1.7s added — ~3x over the ~500ms
voice budget**. Also verified: dense-only BGE is worse than Gemini
(MRR .767 vs .893), so async-refine alone cannot fix the current turn;
fp16 is 4.7x worse on this card (closed).

## What I did

1. Wrote the decision brief:
   `docs/ssot/jobs/ada/2026-11-24-bge-serving-cutover-decision.yml` —
   verified state, re-scored options (a)-(d) + status-quo + MEM-1083
   distillation, recommendation.
2. Added `scripts/ada/bge-rerank-probe.py` — top-K latency sweep for the
   live endpoint (token via `RERANK_AUTH_TOKEN` /
   `ADA_BGE_SHADOW_RERANK_TOKEN` env, never committed). Verified: health
   leg works, 401 handled cleanly without token.
3. Raised a board request on the card with 4 options, ★-suggesting
   **probes-first**: (1) idle-GPU `/rerank` re-measure with the new
   probe, (2) lighter-reranker eval rerun on the GPU lane — then
   re-ask with real numbers. Alternatives offered: sync-top10 (accept
   ~1.4-1.7s), async/hybrid, stay-gemini.
4. Posted progress + this summary to card comms.

## Result / how to verify

- Board request `bge-serving-cutover-pick-the-architectur-3728d5` is open
  on the card (Tony push-notified). His answer routes the next dispatch:
  probes-first → GPU-lane eval dispatches; sync-top10 → ada-voice
  serving-path implementation; async-hybrid → plumbing design;
  stay-gemini → card parks until soak data.
- Verify: `curl -s http://100.75.102.88:11555/health`; brief at
  `docs/ssot/jobs/ada/2026-11-24-bge-serving-cutover-decision.yml`.
- No production changes made; nothing pushed.

lessons:
- The 565ms "top-10 rerank" figure was eval-harness (~57ms/pair); live
  shadow rerank_ms was 1078-1412ms (~110-140ms/pair) — always re-measure
  serving latency on the real endpoint before pricing a sync arm.
- bge-rerank /rerank requires the bearer token (ADA-1299); /health is
  open — probe scripts must read RERANK_AUTH_TOKEN/ADA_BGE_SHADOW_RERANK_TOKEN
  from env, secrets stay out of the repo.
- served=0 on /health + sparse shadow lines usually means traffic
  drought (few memory_search calls), not a dead lane — correlate before
  declaring a fault.
