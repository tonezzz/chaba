---
title: Jev + Weaviate architecture assessment — decision tiers, measured
description: Reconciles the live Jev pilot (open-jev gemma-3-4b on tony-omen, /v1/systemone), the 3-backend model benchmark (open-jev 83% vs Gemini-via-OR 57%), the existing Ada→GEV gev_command path, and MDDB/Weaviate roles — into a tiered architecture with a concrete benchmark/reporting plan
tags: [jev, systemone, open-jev, weaviate, mddb, gev, openrouter, architecture, benchmarks, ada-pi]
created: 2026-09-28
updated: 2026-09-28
category: architecture
related: [docs/kb/iphone-ipad-simulation-assessment.md]
search_keywords:
  [
    jev systemone,
    open-jev gemma-3-4b,
    decision model tier,
    ada gev_command,
    gev-gemini bridge,
    weaviate vs mddb,
    gemini openrouter benchmark,
    confirm gate scoring,
    retrieval benchmark,
    policy plane ada,
  ]
---

# Jev + Weaviate Architecture Assessment — v2 (measured)

Status: review draft · 2026-09-28 · supersedes the earlier unmeasured
draft; reconciles with `jev-ai-assessment` and `gemini-or-embedding-
benchmark` CMS pages which already contain pilot data.

## What's already true (verified)

| piece | measured reality |
|---|---|
| **Jev concept** | TypeSafe AI's decision-only model (`/v1/systemone`: noul/choice/score, ~10 questions per call, ~400ms hosted). Proprietary + waitlist. |
| **open-jev pilot** | RUNNING — `gemma-3-4b-it` (unsloth, ungated) on tony-omen, torch/CPU, `:8777`, model loads ~80s |
| **3-backend bench (done)** | 18 real Ada decisions: open-jev-4B **83%** @ 11.9s · gemma-1B 56% @ 2.6s · **Gemini-2.5-Flash-via-OR 57% @ 1.4s — uncalibrated (1.00 on hard negatives), WORSE than the regex** |
| **Ada→GEV link** | LIVE — `gev_command` actuating tool → `POST /command` (:8790) → `function_call` frames → all GEV browser clients. Handoff job added the endpoint 2026-09-27 |
| **Weaviate** | RUNNING — `search_kb` MCP, hybrid BM25+MiniLM-L6-v2 over kb/ssot/docs |
| **MDDB** | canonical banks + docs; OR-Vertex `gemini-embedding-2` primary (cosine 1.000 mirror proven), fail-closed on OR error, 768-dim |

## The corrected tier ladder

```
Tier 0  RULES        μs        gates, budgets, whitelists — enforcers
Tier 1a JEV-async    ~12s      open-jev-4B CPU — post-turn audit,
                               scenario judging, CMS classification
Tier 1b JEV-hot      ~400ms    NOT YET — needs quant/0.6B/hosted API
Tier 2  GEMINI       streams   reasoning, generation, correction duty
```

**Correction to the naive model**: local Jev is NOT a latency win today —
4B on CPU ≈ 12s/question. Its measured wins are **calibration** (ambiguous
turn scored 0.559 — correctly refused under a ≥0.75 gate where a chat
model screams 1.00) and **cost** ($0). Hot-path voice gates are blocked
until one of: 4-bit quant on the 1650, NanoJev-0.6B trained on our
transcripts, or hosted Jev API.

**And the sharper lesson from the bench**: wiring a chat model (even via
OR, cheap+fast) into a scoring gate is *negative* value — self-reported
probabilities are uncalibrated. The Jev wire contract is portable; the
*value is logit-read scores*. Do not substitute Gemini.

## Ada↔GEV — the actual topology

GEV has TWO tool-entry paths with different guard depths:

1. **Ada → `gev_command`** → HTTP `/command` → browser `function_call`
   — inherits Ada's full enforcement stack (confirm gate, budgets, ACL)
2. **GEV's own Gemini Live session** in `gev-gemini/bridge.py` → 28
   `tools.json` declarations → direct browser execution — **no confirm
   gate, no budget, no ops events**

So the restructure question isn't "merge GEV into Ada" — it's
**"GEV's own voice path runs unguarded actuation."** The policy-plane
idea narrows to: give the GEV bridge the minimal guard kit for its own
session (budget + confirm requirement on actuating tools + ops event
emission) rather than building a shared gateway. A shared gateway is
still the clean end-state; a thin guard shim in `bridge.py` is the
80% move at 10% of the cost.

## Data plane — keep the split, it's already correct

- **MDDB = canonical** for Ada banks + docs (Gemini-768 space,
  `ada_memory_*` contract). Never migrate — the space mixing incident
  (nomic-era docs now invisible) is the standing warning.
- **Weaviate = dev-KB hybrid** (MiniLM space). Hybrid BM25+vector already
  beats plain vector on keyword-ish queries — good for SSOT/docs, wrong
  space for memory banks.
- **Boundary rule**: same corpus may live in both (kb docs), but the
  stores never cross-reference vectors. Any "does Weaviate retrieve
  better?" question goes through the retrieval bench, not vibes.

## Bench/report plan — plug into what's built

All emit `kind: benchmark` docs → `ada-ha-scenario-reports` →
`auto-report` flags regressions automatically (machinery from today).

| bench | status | next step |
|---|---|---|
| `jev-bench` (18 decisions) | script at `/tmp/jev-bench.py` on tony-omen | commit to `ada-pi/tests/bench/`, emit benchmark doc, grow cases from weekly transcripts |
| `embed-bench` | exists (`gemini-or-embedding-benchmark` page) | weekly timer + OR spend readout |
| **retrieval bench** (new) | — | same queries × MDDB-semantic vs Weaviate-hybrid → recall@5 + latency; decides Weaviate's scope |
| scenario suites | hourly smoke + suites | unchanged — they ARE the regression net for tier-1 changes |

Report format extension: add `engine`/`target` meta so `bench-jev` runs
are distinguishable from live-scenario runs; pages follow `bench-*`/
`benchmark-*` convention.

## Pros & cons (final)

| move | pros | cons |
|---|---|---|
| Jev async tier (now) | $0, calibrated, offline, proven 83% | 12s/question — async only |
| Jev hot path | kills confirm/routing misroutes at ~400ms | needs quant OR NanoJev training OR hosted API ($, privacy of every turn's context) |
| Guard shim in gev bridge | fixes the unguarded actuation path cheap | duplicates gate logic until a shared gateway exists |
| Shared policy plane (later) | every frontend inherits every fix | real refactor; wait until 3+ frontends justify it |
| Weaviate expansion | already live, hybrid quality | only via bench data; different vector space — never merge banks |
| Gemini/OR for gates | (none — measured negative) | uncalibrated scores: 57%, worse than regex |

## Sequence

1. **Commit `jev-bench.py`** to repo + wire benchmark-doc output (hours)
2. **Async Jev first**: post-turn confirm/audit checks, scenario
   judging, CMS doc classification — all jobs where 12s is free
3. **Guard shim** in `gev-gemini/bridge.py`: tool budget + confirm flag
   + ops events (small, unblocks safe GEV voice control)
4. **Retrieval bench** MDDB-vs-Weaviate → data decides scope
5. **Hot-path Jev** last — pick between quant/NanoJev/hosted with the
   bench numbers in hand; revisit shared gateway when a 3rd frontend lands

Rule unchanged: **nothing crosses tiers without a benchmark number.**
