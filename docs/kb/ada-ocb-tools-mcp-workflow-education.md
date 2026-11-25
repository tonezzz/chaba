---
category: operations
type: education
status: defined
title: Ada-OCB — Locating and Triaging Cards Across Tools, MCP, and Workflow
description: How the Ada control-plane /ada command, the ada-control MCP tool set, and the kanban card corpus combine to locate and triage ada-ocb cards that span tools, MCP bridges, and workflow behavior.
tags: [ada, ada-ocb, kanban, opencode, mcp, tools, workflow, education, control-plane, triage]
created: 2026-11-20
updated: 2026-11-20
related:
  - ada-ocb-triage-lessons-2026-11-20.md
  - /home/tony/CascadeProjects/chaba/docs/ssot/kanban/cards/ada-ocb-board-read-latency.yml
  - /home/tony/CascadeProjects/chaba/docs/ssot/kanban/cards/ada-ocb-kanban-sweep-report.yml
  - /home/tony/CascadeProjects/ada-voice/opencode/commands/ada.md
search_keywords: [ada-ocb, ocb, kanban, cards, find_card, card_pick, kanban_sweep, context_pack, ssot_search, tools, mcp, bridge, workflow, opencode, ada-control, control plane, triage, education]
---

# Ada-OCB — Locating and Triaging Cards Across Tools, MCP, and Workflow

**Abstract**: Ada's control plane locates work by composing the `/ada` command surface, the `ada-control` MCP tool set, and the kanban card corpus under `docs/ssot/kanban/cards/`. For the ada-ocb program this means finding the cards that span tools, MCP bridges, and workflow behavior, then triaging them through board reads, SSOT lookups, and read-only sweep/preflight gates.

## Overview

The ada-ocb program covers the OpenCode/Ada bridge that serves OpenChamber sessions: the `opencode/ada_mcp.py` control bridge, the board-read tools that hydrate kanban cards, the SSOT/context-pack tools used for lookups, and the workflow pieces (kanban sweep, free-lane pilot, regression suite). The cards that own those surfaces all carry an `ada-ocb-*` id prefix or live in the `ada-*` tool/MCP family.

## Purpose

Give the agent — and the human — a repeatable way to answer "which cards relate to ada-ocb tools / MCP / workflow?" without guessing, and to keep the education content for that surface current.

## Key Cards

| Card | Ref | Topic | Column | Priority |
| ---- | --- | ----- | ------ | -------- |
| ada-ocb-board-read-latency | ADA-0172 | board reads for **kanban tools** (compact + projected snapshots) | done | high |
| ada-ocb-bridge-stable-path | SYS-0218 | ada-control **MCP** → stable origin/main bridge | done | high |
| ada-ocb-bridge-version | ADA-0177 | bridge version handshake (**MCP** staleness) | **review** | medium |
| ada-ocb-kanban-sweep-report | ADA-0214 | read-only Kanban stuck-card **sweep tool** (workflow) | done | medium |
| ada-ocb-free-lane-workflow-pilot | ADA-0242 | free-lane **workflow** pilot + guarded canary | done | medium |
| ada-ocb-kanban-smoke | ADA-0173 | read-only card **workflow** verification | done | low |
| ada-ocb-regression-suite | ADA-0174 | regression suite: per-feature tests + live smoke + calls.jsonl **benchmark** (ada-ocb **tools**) | done | high |
| ada-ocb-answer-eval / -r2 | ADA-0175 / ADA-0188 | answer-quality eval: question → **tool** → data → answer | done | high |
| ada-ocb-context-windowed-excerpts | ADA-0164 | context-pack excerpt windowing | done | medium |
| ada-ocb-compact2-adoption | ADA-0207 | board-api compact=2 + comms_tail | done | medium |
| ada-ocb-ssot-direct-get / -search-query | ADA-0167 / ADA-0240 | direct SSOT get / read-only SSOT **search/query** | done | high / medium |
| ada-ocb-openchamber-e2e-smoke | ADA-0186 | fresh OpenChamber session smoke (tools/instructions routing) | done | low |
| ada-ocb-manual-queue-semantics | ADA-0189 | manual queue vs dispatchable | **review** | low |
| ada-ocb-public-edge | ADA-0032 | public exposure ada-ocb.surf-thailand.com | done | medium |
| ada-ocb-session-model-auth | ADA-0077 | new-session prompt missing model API key | done | medium |

## The Discovery Path

1. **Command layer**: `/ada <operation> <card-or-request>` in `opencode/commands/ada.md` — plan, status, handoff, preflight, dispatch, next, sweep, stuck, ssot, attention, spend, debug, self-test.
2. **MCP layer**: `ada_context_pack`, `ada_ssot_search`, `ada_ssot_get`, `ada_next_card`, `ada_card_pick`, `ada_kanban_sweep`, `ada_attention`, `ada_status`, `ada_plan`, `ada_preflight`, `ada_handoff_preview`, `ada_start_check`, `ada_dispatch_check`, `ada_envelope_draft`, `ada_envelope_stage`.
3. **Card corpus**: `docs/ssot/kanban/cards/*.yml` — grep for the id prefix (`ada-ocb`, `ada-tools`, `mcp`, `tool`) and read `id`, `title`, `column`, `priority`, `ref`, `tags`, `brief`, `spec`, `comms`.
4. **Mapping**: cards that mention tools/MCP/workflow get routed to the relevant lane; findings become education posts.

## Tools / MCP / Workflow Mapping

| Learning area | Representative card(s) | Column |
| --- | --- | --- |
| Board reads / kanban tools | ada-ocb-board-read-latency (ADA-0172) | done |
| MCP bridge stability / staleness | ada-ocb-bridge-stable-path (SYS-0218), ada-ocb-bridge-version (ADA-0177) | done / review |
| Sweep tool / workflow | ada-ocb-kanban-sweep-report (ADA-0214) | done |
| Free-lane workflow pilot | ada-ocb-free-lane-workflow-pilot (ADA-0242) | done |
| Regression / eval / benchmark | ada-ocb-regression-suite (ADA-0174), ada-ocb-answer-eval (ADA-0175) | done |
| Context pack / SSOT | ada-ocb-context-windowed-excerpts (ADA-0164), ada-ocb-ssot-direct-get (ADA-0167) | done |
| OpenChamber session smoke | ada-ocb-openchamber-e2e-smoke (ADA-0186) | done |
| Manual queue semantics | ada-ocb-manual-queue-semantics (ADA-0189) | review |
| Tool surface / registry | ada-tools-manifest (ADA-0105), tool-surface-census, agent-tool-registry-federation (…-ee0089) | done / backlog |
| MCP health / infra | ada-control-mcp-session-dir-race (ADA-0201), host-mcp-python-missing (SYS-1177), dead-mcp-servers-triage (OPS-0891) | done / backlog |
| Per-tool spend / voice / wiki | ada-spend-guardrails-per-tool-daily-caps (ADA-1200), ada-tool-voice-request-well-formed (ADA-1202), ada-tools-wiki-read-wiki-search-recall (ADA-1199) | backlog / doing |

## Process Lessons

- Facts that live only in card `comms` can be missed because `ada_status` returns only the last five comments; use `GET /card/<id>?comms_tail=<n>` or grep the card YAML before diagnosing.
- A fact that only lives in card comments is not discoverable via tool results alone; promote it to an SSOT doc.
- A stale `lane` pin is harmless when `executor` is set; `action.lane` only accepts `codemod, free_lane, manual, nlm_batch, paid_frontier` (retired lanes drop out via `ssot.devnest-lanes.yml`).
- Staged dispatch (`ada_envelope_stage`) is read-only only (S3 / ops-readonly / ssot-research / storage-dryrun).

## Testing the Process

Two cards were run through the `card → /ada MCP tool (ada_status) → education post` loop.

| Pilot | Card | Why it was picked | Verified via |
| ----- | ---- | ----------------- | ------------ |
| 1 | `ADA-0172` — fast board reads for kanban tools (compact+projected snapshots) | Sits at the tools + workflow intersection; carries hard before/after timing evidence | `ada_status` → `ok: true`, done/high, bridge `git-6a39e3a`, 30 tools |
| 2 | `ADA-0214` — read-only Kanban stuck-card sweep tool | Pure workflow tool; its spec defines the evidence-first triage contract the whole discovery path depends on | `ada_status` → `ok: true`, done/medium, 11 comms, bridge `git-6a39e3a`, 30 tools |

### ADA-0214 deep dive — the read-only sweep tool

`ada_kanban_sweep` is the workflow counterpart to ADA-0172's board-read speed work. Its contract, taken from the card spec:

- **Procedure owner**: `docs/kb/card-status-and-processing.md` and `.devin/skills/card-ops-sweep` stay canonical; the tool is the callable snapshot layer.
- **Read model**: one `/queue` snapshot plus bounded projected slices (failed/claimed/running/done cards in `doing`; queued manual/unsupported cards) — never a full board download.
- **Default window**: last 24 hours, capped results.
- **Classifications**: fresh active work, stale-running cards absent from the active queue, failed-before-session/admission failures, failed-after-start, manual/unsupported queue items, and done-but-still-doing cards.
- **Hard invariants**: returns snapshot time, per-card evidence and next safe step, and `mutations_performed: []`. It never auto-retries, holds, queues, moves, closes, dispatches, calls a model/provider, or inspects host services. All changes stay human-confirmed via board-api.
- **Scope boundary**: distinct from ADA-0042 (single-card execution) and OPS-0964 (OpenCode executor pilot).
- **Post-merge action**: update the `card-ops-sweep` skill to take the initial snapshot from this tool, keeping its existing evidence and approval rules.

Live proof ran clean: `ada_kanban_sweep({window_hours:24, limit:50})` returned `snapshot_at: 2026-11-20T17:26:42+07:00`, `mutations_performed: []`, and classified the current board (1 queued-blocked item: OPS-1039; 2 active `doing` cards: ADA-1300 and OPS-0022) without touching state. The card's own comms show the usual runner-agent drift defers (tony-omen, idc02, idc03, tony-macbook) but the tool itself is done.

## Related Documentation

- [Education: Ada-Ocb Tools MCP Workflow Card Discovery](https://wiki.h3.gizmo-thailand.com/index.php?title=Education%3AAda-Ocb_Tools_MCP_Workflow_Card_Discovery) — published Education lesson (`lesson-06ecd4245705`, MDDB `chaba-lessons`), source of this write-up.
- [Ada-OCB triage lessons — Jules EOL and dispatch lanes](ada-ocb-triage-lessons-2026-11-20.md)
- [ada-ocb regression suite](ada-ocb-regression-suite.md)
- [Ada command surface](../../ada-voice/opencode/commands/ada.md)

## Change History

| Date | Change | Author |
| ---- | ------ | ------ |
| 2026-11-20 | Created from session findings on ada-ocb card discovery | agent |
