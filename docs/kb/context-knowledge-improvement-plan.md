---
title: Context and Knowledge Management Improvement Plan
description: Six-phase plan to improve Auto-KB quality, hand-off contracts, context retrieval, KB categorization, focus decision tree, and session summary automation.
tags: [kb, context, focus, ssot, improvement-plan]
created: 2026-08-18
updated: 2026-08-18
category: architecture
related: [reports/CONTEXT_IMPROVEMENT_PLAN.md, docs/ssot/ssot.improvements.yml, docs/ssot/ssot.focus.yml, docs/ssot/infrastructure/ssot.focus-dispatcher.yml]
search_keywords: [context improvement plan, auto-kb, hand-off contract, mcp_context, focus decision tree, session summary]
---

# Context and Knowledge Management Improvement Plan

**Abstract**: A six-phase plan for improving the assistant's context and the focus-driven workflow. It covers Auto-KB quality, hand-off contracts, context retrieval, KB categorization, focus decision tree, and session summary automation.

## Overview

The plan is described in `reports/CONTEXT_IMPROVEMENT_PLAN.md` and is tracked in `docs/ssot/ssot.improvements.yml` as an active improvement. It is intended to run incrementally so product work is not blocked.

## Purpose

- Reduce low-value Auto-KB noise.
- Standardize subagent hand-off contracts.
- Provide fast, relevant context retrieval for active focuses.
- Simplify the focus decision tree and make it more robust.
- Automate session summary extraction.

## Key Files

| File | Purpose |
|------|---------|
| `reports/CONTEXT_IMPROVEMENT_PLAN.md` | Original 6-phase improvement plan |
| `docs/ssot/ssot.improvements.yml` | Active improvements tracking |
| `docs/ssot/infrastructure/ssot.focus-dispatcher.yml` | Focus dispatcher rules and modes |
| `docs/kb/context-knowledge-improvement-plan.md` | This KB overview |

## Phases

### Phase 1: Auto-KB Quality Filter
- Add negative triggers that reject low-value entries.
- Enforce a minimum technical detail threshold.
- Archive existing noise entries.

### Phase 2: Hand-off Contract Standardization
- Extend the Hand-off Queue schema with `contract_path`, `completion_criteria`, `deliverables`, and `feedback_required`.
- Auto-generate `SUBAGENT_CONTRACT.md` with success/failure criteria.

### Phase 3: Context Retrieval for Active Focuses
- Create an `mcp_context` tool to query MDDB for related KB, SSOT, and session summaries.
- Integrate into session-start workflow.
- Add 24-hour context caching.

### Phase 4: KB Categorization Standardization
- Standardize categories to five core types.
- Migrate non-standard categories and validate in Auto-KB.

### Phase 5: Focus Decision Tree Simplification
- Reduce the tree to four primary paths.
- Add confidence thresholds for auto-classification.

### Phase 6: Session Summary Automation
- Create `mcp_session_summary` tool.
- Auto-extract KB items and decisions with templates and validation.

## Related Documentation

- **Original Plan**: `reports/CONTEXT_IMPROVEMENT_PLAN.md`
- **Improvements SSOT**: `docs/ssot/ssot.improvements.yml`
- **Focus Dispatcher SSOT**: `docs/ssot/infrastructure/ssot.focus-dispatcher.yml`

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-18 | Initial creation | devin |
