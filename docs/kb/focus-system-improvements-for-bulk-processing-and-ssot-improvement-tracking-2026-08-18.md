# Focus System Improvements For Bulk Processing And Ssot Improvement Tracking

## What it is

Focus System Improvements For Bulk Processing And Ssot Improvement Tracking

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
Focus system improvements for bulk processing and SSOT improvement tracking:
- Created docs/kb/context-knowledge-improvement-plan.md to capture the six-phase CONTEXT_IMPROVEMENT_PLAN and close the gap where the report was not indexed in KB/MDDB.
- Added a tracked improvement item "Context and Knowledge Management Improvement Plan" to docs/ssot/ssot.improvements.yml with phase action_items and references to the KB entry and original report.
- Implemented mcp_focus mode=sweep in scripts/mcp_debug/focus.py with a hold parameter, allowing the assistant/user to hold one focus and list all remaining parked/backlog/inbox/deferred-subtask candidates in a sorted process_queue.
- Updated both mcp_debug/server.py and scripts/mcp_focus/server.py tool schemas to expose sweep and hold.
- Updated docs/ssot/infrastructure/ssot.mcp-focus.yml with the sweep action and input.
- Fixed a YAML escaping issue in docs/ssot/ssot.focus.current.yml where a note contained an unquoted leading "Decision:".
- Verified mcp_focus mode=sweep with hold='Gemini key rotation and validation' produces a hold item and a 5-item process queue.
- All 104 SSOT files validate clean.

Re-assessment and suggested streamlining:
- mcp_focus sweep is currently read-only; a bulk-defer/action sub-mode would let the assistant hold one focus and automatically park/defer the rest to named sessions (e.g. yomi, macbook, tony-dell).
- Parked foci in ssot.focus.current.yml (e.g. Yomi) are not yet picked up by the sweep because it only scans backlog/inbox and active subtasks; include current sections explicitly in sweep.
- The process queue is not yet grouped by session/branch; grouping would make multi-session planning obvious.
- The Context and Knowledge Management Improvement Plan is now tracked and the most natural next step is Phase 1 (Auto-KB quality filter) since it is the highest value / lowest risk and does not block product work.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-18
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
