# Dispatch outcome — per-model scorecard across the ghostroute OR free-model rotation

Card: openclaw-bench-per-model-scorecard-acros-3df00d (KNB-0174)
Runner: tony-omen · Date: 2026-10-23

## What happened

The prior dispatch (2026-10-22, idc02) landed `scripts/bench-or-scorecard.py`
but never ran the bench. This run executed it: **21 models × ~32 calls**
(5 jev-bench arms: toolcall_native, toolcall_prompted, routing, reasoning,
json_strict) against OpenRouter `/chat/completions` with per-model pinning —
the documented emulation of the loopback-only openclaw-gateway surface.
40.5 min, 3.5s request spacing to protect the shared OR key.

## Results (full table in card comms + reports/or-free-scorecard-2026-10-23.md)

- **Top side-tool picks** (composite = routing + json_strict + prompted-JSON):
  laguna-s-2.1 (100), nemotron-3.5-super-vl (100), flint-v1.0 (85),
  dots-3-note-preview (83), ultra-550b (78), lightning (76 — current primary).
- **Drop from allowlist**: 8 dead ids (gone from live :free shelf) +
  inkling + inkling-small (403 harness-gated, dead for plain API;
  inkling-small is fallback#3 in live openclaw.json) + xingchen-agi/xing4.0
  (composite 21, 22× 429).
- **Quarantine**: gemma-4-26b/31b — HTTP 400 upstream on OR's Google path
  today; re-check before permanent drop.
- **Don't add**: super-120b (404 dead), content-safety (not a chat model —
  yet openrouter/free routes to it), nano-omni-30b, laguna-xs, lfm-2.5-2.6b
  (p50 22.9s).
- **Key finding**: all 3 paid Gemini refs failed 403 "Key limit exceeded
  (weekly limit)" — the shared OR key's weekly spend cap is exhausted, so the
  free-vs-paid comparison is unmeasurable until a dedicated openclaw key
  exists or the cap is raised (confirms the card's risk note).

## Artifacts

- `reports/or-free-scorecard-2026-10-23.json` / `.md` — raw + rendered scorecard
- `docs/ssot/jobs/models/2026-10-23-or-free-scorecard.yml` — findings, verdict,
  suggested post-prune rotation order
- Scorecard + drop/add flags posted to card comms (2 comments)

## Verify

- `cat reports/or-free-scorecard-2026-10-23.md`
- Card comms on KNB-0174 carry the table + flags
- Re-run any single model:
  `OPENROUTER_API_KEY=... python3 scripts/bench-or-scorecard.py --models-file <json> --out <prefix>`
