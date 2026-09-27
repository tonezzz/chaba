# Ada memory recall — Weaviate assessment + tiered-recall design

Date: 2026-09-27 · bench: `ada-pi/tests/bench_recall.py`

## Measured latency (idc01 localhost / tailnet)

| Path | p50 | p95 | What it does |
|---|---|---|---|
| mddb `/v1/vector-search` | **1–2 ms** | 2 ms | semantic over bank docs (embeddings precomputed; query embed path warm ~31ms cold) |
| mddb `/v1/search` (keyword) | 3 ms | 4 ms | keyword — floods raw results, weak ranking |
| mddb `/v1/get` | 1 ms | 2 ms | exact-key fetch |
| weaviate `nearVector` (768d) | **29 ms** | 57 ms | ANN on tony-dell — mostly tailnet RTT |
| ollama `nomic-embed-text` | ~1 s | — | raw embedding call (avoid on hot path) |

**Verdict on Weaviate for Ada recall**: it will *not* make recall faster —
MDDB vector search is already ~1–2 ms on idc01. Weaviate's 29ms tailnet hop is
*slowing* the path, and splitting bank vectors across two stores invites drift.

**Where Weaviate does help**: corpus-level *selection*. It already indexes
`YomiMessage` + `SSOTDocument` — things Ada can't reach through
`ada_memory_search` today. A `search_everything` / report-picker tool that hits
Weaviate once when a question spans corpora (LINE chats + docs + pages) is the
right use — ~30ms is nothing against the ~1–3 s Gemini tool-call roundtrip.

## The actual bottleneck

Voice recall latency is dominated by the **tool-call roundtrip through
Gemini Live** (~1–3 s), not storage. So the win is answering **without any
tool call** — Tony's instinct of keeping the index in immediate memory is the
right architecture.

## Proposed tiered recall

```
L0  session index card  — injected into session instructions, always
    (~1–1.5 KB, ~15 lines): last-N session one-liners, open/urgent items
    (awaiting-user jobs, open incidents, unpublished CMS drafts),
    recent page/report slugs. NO tool call needed → instant answers.

L1  rolling session summary — exists today (recent_summary cache),
    grows as L0 items age; compact paragraphs, still in-prompt.

L2  vector recall — ada_memory_search → mddb (~2 ms warm). On-demand.

L3  deep recall — ada_session_recall → NotebookLM. On-demand, heavy.
```

Fade-out rule: a doc enters L0 on write/session-end, demotes to a one-liner
in L1 after ~48 h or when displaced by newer items, then lives only as a
L2/L3 reference.

### L0 mechanics

- Store: mddb doc `state/session-index` (one doc, rewritten on session_end
  and on job/CMS state changes — cheap, keeps durability)
- Producer: `conversation_memory.record_session_end` already runs per
  session — extend it to rebuild the index card (recent summaries +
  pending actions + recent cms pages)
- Injector: `realtime_provider` session instructions — append the card
- Bound: hard cap ~1.5 KB / 15 lines; overflow items drop to L1 one-liners
- Constraints: never inject secrets; bank/scope filter applies per speaker

## Scenario + bench artifacts

- `tests/scenarios-live/memory_index_recall.yaml` — acceptance test:
  recent-published pages answerable from index; deeper content via
  `cms_get_page`/`ada_memory_search` (relaxes to `no_calls` once L0 lands)
- `tests/bench_recall.py` — rerunnable latency bench (commit `bench_recall`
  output into this doc on re-runs)

## Live test results (2026-09-27)

| Test | Result | Notes |
|---|---|---|
| `memory_index_recall` scenario | **PASS** (baseline) | Ada answers via 2–3 tool calls/turn today; relaxes to `no_calls` once L0 injection lands |
| `cms_publish_handshake` scenario | **PASS** | pending-register → "yes" → publish → `cms_verify_page` — the new stateful gate held; `bench-ping` test page deleted after |
| `bench_recall.py` on idc01 | mddb vector **1–2ms**, keyword 3ms, get 1ms, weaviate ANN **29ms** (tailnet) | recall search is already sub-perceptual — the win is removing tool roundtrips, not storage speed |

Scenario runs: `scripts/scenario-live.py <file> --url ws://127.0.0.1:8002/ws --api-key $ADA_API_KEY` on idc01.

## Embedding provenance (added 2026-09-27)

Actual chain on idc01:

```
mddb (provider=ollama, model=nomic-embed-text — alias only)
  → 127.0.0.1:11435 gemini-ollama-proxy (node shim)
      PRIMARY: OpenRouter → google/gemini-embedding-2   (OPENROUTER_PRIMARY=1, active)
      fallback: Gemini direct (gemini-embedding-2 ↔ 001 alternation)
      last resort: real ollama nomic-embed-text (:11434)
```

Tony's earlier OpenRouter decision **is in effect** — `OPENROUTER_PRIMARY=1`
with key configured in the proxy env.

**Memory-confusion hypothesis**: plausible but *mixed-vector-space* is the
mechanism, not model choice per se — docs embedded before the OpenRouter
switch live in a different vector space, so current-space queries may
under/over-rank them. Recommend a one-off re-vectorize of the ada banks,
then re-run `bench_recall` + the scenario suite to measure delta.
Note: the speaker-ID flips (Timmy↔กุ้ง etc.) are a **separate embedding
pipeline** (voice profiles) — unrelated to mddb embeddings.

## Effort estimate

L0 index producer + injection: ~half day in ada-pi + one session-end test.
Weaviate corpus tool: separate small tool, optional second phase.
