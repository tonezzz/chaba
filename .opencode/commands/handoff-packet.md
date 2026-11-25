---
description: Scaffold and save a required SSOT Session Handoff Packet
---

Create a Session Handoff Packet for this session$ARGUMENTS.

## Steps
1. Gather facts (SSOT-first, pointer-first): objective, current state, canonical refs, open asks/decisions, next action, and where each item was filed. Do not invent evidence.
2. Generate the packet using the required template below. Fill known values; mark unknowns explicitly.
3. Save it durably: OpenChamber project knowledge note preferred (and/or card comms refs). Do not leave chat-only.
4. Emit the router event (dry-run, idempotent): `python3 scripts/chaba/capture-event.py --type handoff --source opencode --session <session-id-or-slug> --subject <packet-id-or-as_of> --summary "<objective + current_state>" --ref <packet sink ref> --where-filed "<item -> sink/ID/path>" [--where-filed ...]`. Re-emit is a noop+audit; the emitter never writes canonical sinks.
5. Report `where_filed` in the response.

## Required template
```md
# Session handoff — <objective> (<YYYY-MM-DD[ HH:MM TZ]>)
- objective: <what this session/task was doing>
- as_of: <YYYY-MM-DD[ HH:MM TZ]>
- current_state: <done | in progress | blocked> — <evidence refs>
- canonical_refs: <SSOT keys/paths, card IDs, lesson/report/artifact IDs, commits/paths>
- open_asks_decisions: <none | ask/decision -> owner/options/default + durable sink/ID>
- next_action: <single concrete next step>
- where_filed: <item -> sink/ID/path> (mandatory)
- notes: <risks/gaps/refresh queries if any; label canonical(served)/branch/unmerged/live runtime when relevant>
```

## Guardrails
- Pointer-first: refs/paths/keys/queries + as_of; no secrets; no stale volatile snapshots as truth.
- `where_filed` is mandatory. A request with no durable record does not exist.
- Correct write paths/roles (board-api mutation door, single-writer/checkout rules). No Ada `ada-*` memory writes from Chaba contexts.
