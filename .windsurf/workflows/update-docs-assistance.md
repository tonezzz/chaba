---
description: Update Assistance docs starting from services/assistance/README.md
---

When the user says "update docs" for Assistance, follow this workflow.

1. Read the anchor document:
   - `services/assistance/README.md`

2. Enumerate doc references from the README and open each referenced file:
   - Top-level references (examples from README):
     - `services/assistance/CONCEPT.md`
     - `services/assistance/TOOLS_POLICY.md`
     - `services/assistance/MEMORY_POLICY.md`
     - `services/assistance/docs/BUILD.md`
     - `services/assistance/docs/REMINDERS.md`
     - `services/assistance/docs/CHARTS.md`
     - `services/assistance/docs/CONFIG.md`
     - `services/assistance/docs/WEAVIATE.md`
     - `services/assistance/DEBUG.md`
     - Service architecture docs:
       - `services/assistance/jarvis-backend/ARCHITECTURE.md`
       - `services/assistance/jarvis-frontend/ARCHITECTURE.md`
       - `services/assistance/trip/ARCHITECTURE.md`
       - `services/assistance/mcp-servers/ARCHITECTURE.md`

3. For each referenced doc, check for alignment with the current codebase behavior and the most recent changes:
   - WebSocket contract / event names
   - `trace_id` propagation + how to find it in the UI
   - Operation Log capabilities (expand raw JSON, show/hide debug)
   - WS record/replay tooling (`JARVIS_WS_RECORD`, `JARVIS_WS_RECORD_PATH`, `ws_replay.py`)
   - Frontend contract tests (`vitest`) and how to run them
   - Evidence collection (`scripts/collect-idc1-assistance-evidence.sh`)

4. Make minimal, targeted doc edits:
   - Prefer adding short sections over large rewrites.
   - Keep terminology consistent across docs (Jarvis Frontend/Backend, Weaviate authoritative store, SQLite cache).
   - Ensure commands/paths are copy-pasteable and correct.

5. Finish by producing a short summary:
   - Files changed
   - What was updated
   - Any follow-ups (missing doc refs, outdated info that needs a deeper pass)
