---
description: Scaffold and save a required SSOT Session Handoff Packet
---

Create a Session Handoff Packet for this session$ARGUMENTS.

## Steps
1. Gather facts (SSOT-first, pointer-first): objective, current state, canonical refs, open asks/decisions, next action, and where each item was filed. Do not invent evidence.
2. Scaffold in one step — do not hand-write the template:
   `python3 scripts/chaba/handoff-packet.py scaffold --objective "<objective>" --state <done|in progress|blocked> --refs "<key refs>" [--out <file>]`
   (`as_of` is prefilled with local time + TZ; `--out` writes a file, default is stdout). Fill the `<placeholders>` with evidence refs; mark unknowns explicitly.
3. Validate before saving: `python3 scripts/chaba/handoff-packet.py validate <file>` — exits non-zero listing any missing required field; `where_filed` must carry an explicit `item -> sink/ID/path` value.
4. Save it durably — pick the first available sink and record it in `where_filed`:
   - **OpenChamber project knowledge note** (preferred for resume): save via the OpenChamber knowledge/notes surface in the UI or agent tool; title it `session-handoff-<slug>-<YYYYMMDD>` and keep the packet body pointer-first.
   - **Card comms** (always available): `POST https://idc03.taila0626a.ts.net:10000/comment` with `{"id":"<card>","from":"<agent>","text":"<packet or pointer + where_filed>"}` — board-api is the mutation door; never edit card YAML directly.
   - **Dispatch/devin sessions:** the session `dispatch-outcome-*.md` + a card comms line is the durable record.
   Do not leave chat-only.
5. Report `where_filed` in the response.

## Required template (canonical: docs/ssot/ssot.knowledge-capture.yml#Session Handoff Packet)
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
