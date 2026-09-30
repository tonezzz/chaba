---
title: Agent memory prior art — repo landscape assessment
description: Survey of open-source agent-memory systems (Memoria, Graphiti, mem0, Memobase, decay/lifecycle engines, voice-assistant stacks) assessed against Ada/Chaba's architecture — what to adopt, what to steal, what to skip
tags: [memory, prior-art, graphiti, memoria, memobase, ebbinghaus, voice-assistant]
created: 2026-09-28
category: research
---

# Memory prior art survey — 2026-09-28

Assessment of open-source agent-memory repos against Ada/Chaba's needs.
Conclusion up front: **adopt nothing wholesale** — the field converged on
tiers/tool-call-writes/validity-windows that we already built. The real
gaps are all in lifecycle maintenance (drain, dedup, contradiction,
provenance), and five specific ideas are worth stealing.

## matrixorigin/memoria — assessed

"Git for AI memory": snapshot/branch/merge/rollback on MatrixOne's
copy-on-write engine. Rust workspace, plugin arch via protobuf, MCP + REST
interfaces, steering rules per agent tool. 604★.

Deal-breakers for us: hard MatrixOne dependency (no pluggable backend —
vendored sqlx-mysql), embedding locked at init, cloud-first, no
identity-scoped ACLs (nothing like `person.kk` bank scoping).

**Steal: cooldown-gated governance jobs.** `memory_governance` (quarantine
low-confidence, 1h cooldown), `memory_consolidate` (contradiction
detection, 30min), `memory_reflect` (synthesize, 2h). Maintenance as
budgeted batch sweeps, not per-write overhead — exactly the drain model
the extract ring needs.

## getzep/graphiti — temporal model

Bi-temporal edges — the subtlety worth copying:

| field | axis | Ada equivalent |
|---|---|---|
| `valid_at`/`invalid_at` | world time — when the fact was true | `valid_until` (end only) |
| `created_at`/`expired_at` | system time — when we learned/unlearned | `first_seen`/`last_seen` per user, not per fact |
| `episodes: [uuid]` | provenance — edges list source episodes | nothing — no doc→transcript link |

Key move: **contradiction → set `expired_at`, never delete.** History of
what-was-believed-when survives. Our `supersede` does this in spirit but
flattens it. Cheap fix: `expired_at` + `episodes` meta on superseded docs.

## Landscape

### Lifecycle/decay engines (richest vein — our drain gap)

| repo | idea worth stealing |
|---|---|
| reaatech/agent-memory | Policy engine: half-life per importance tier, capacity limits, archive-before-delete, 4 contradiction strategies (newest/oldest/highest-confidence/manual-review) |
| framersai/agentos | ConsolidationLoop: prune → merge (cosine ≥0.95 dedup) → strengthen (**Hebbian CO_ACTIVATED edges on co-retrieved docs**) → derive → compact → reindex |
| sachitrafa/YourMemory | Ebbinghaus decay × importance; declines cleanly below strength floor; +16pp over Mem0 LoCoMo |
| ljftwq-dev/agent-memory-engine | Two-stage recall: wide KNN → rerank `α·strength + (1-α)·sim`; **τ *= 1.5 per recall** (use strengthens memory); all SQLite |
| AGenNext/Agent-Memory | `recall_or_gap` — weak recall returns a suggested_prompt to ASK the user instead of searching harder |
| tverney/agent-memory-daemon | Filesystem-native consolidation daemon: 3-gate trigger, orient→gather→consolidate→prune |

### Voice-assistant / multi-user (Ada's exact lane)

| repo | relevant design |
|---|---|
| TristanBrotherton/voicepe-realtime | HA Voice PE, speaker ID, speaker-gated tools "enforced below the model" — same ACL-intersection principle |
| maxmaxme/voice-assistant | Shared household scope + per-principal personal scopes, hashed device tokens, multi-surface identity (voice/Telegram/HTTP) |
| Betanu701/atlas-cortex | **Nightly LLM→regex distillation** of repeated commands; HOT/COLD latency ladder — fits the Jev tier model |
| croll83/jarvis | Resemblyzer speaker ID + 3B pre-router on Ollama — validates small-model-routes design |

### Profile + timeline

| repo | relevance |
|---|---|
| memodb-io/memobase (2.8k★) | Pre-compiled profile slots + event timeline; LOCOMO temporal **85%** vs LangMem 23% — timelines pay off most on temporal questions. Batch-buffer→profile = our session→extract→bank flow |
| himachhatbar17/MemBase | Eval harness (A-MEM/LangMem/Mem0/MemOS/HippoRAG2 baselines) — scaffold if we want a real recall benchmark |

### Big names (surveyed, mostly covered)

mem0 (65k★, passive extraction = our extract ring), Letta (25k★, agent-
edited blocks = our ada_remember/forget), MemOS, Cognee (31k★, KG+vector
on Postgres), Supermemory (30k★), EverOS (7.2k★ — markdown as source of
truth, closest ethos to Chaba's file-based design), MemMachine (episodic/
profile/working tier split — same model).

## What applies — ranked by value-per-effort

1. **Contradiction quarantine, cooldown-gated** (Memoria + reaatech)
   — batch job, cosine ≥0.8 pairs → `status=quarantined`, human resolves.
   This IS the missing extract-ring drain.
2. **`expired_at` + `episodes` provenance** (Graphiti) — two meta fields;
   makes "what did Ada believe on date X" answerable.
3. **Strength-aware rerank** (agent-memory-engine) —
   `score = α·strength + (1-α)·sim`, τ boosted per recall; works with the
   `record_use` bookkeeping already written. No schema change.
4. **Gap protocol** (Agent-Memory) — weak recall → suggested_prompt to
   ask the user. Cheap, honest degradation.
5. **Nightly LLM→regex distillation** (atlas-cortex) — orthogonal;
   belongs with the Jev tier-ladder work.
6. **Slot-budgeted profiles** (Memobase) — already have via render caps
   in memory.yml. Validation, not a gap.

## Positioning note

Nobody else does identity-ACL'd person-scoped banks + voice speaker
gating + deterministic file-rendered context as one system. The
architecture is defensible; the debt is all in lifecycle maintenance.
