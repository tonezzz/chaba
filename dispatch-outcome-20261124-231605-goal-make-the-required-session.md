# Dispatch outcome — opencode-handoff-packet-scaffold-save

## Summary

The card's option A (`/handoff-packet` command) was already merged to master
(PR #207, commit 800d086aae). This dispatch closed the remaining gap between
"command exists" and the acceptance criteria: the packet was still
hand-written and the save step named sinks without concrete commands.

## What changed (commit 862ca1962f on dispatch/20261124-231605-goal-make-the-required-session)

- `scripts/chaba/handoff-packet.py` (new, executable, stdlib-only):
  - `scaffold [--objective --state --refs --out FILE]` — prints the canonical
    Session Handoff Packet template with `as_of` prefilled (local time + TZ);
    `--out` writes a file. One step to a valid scaffold.
  - `validate PACKET.md` — exits 1 listing missing required fields
    (objective, as_of, current_state, canonical_refs, open_asks_decisions,
    next_action, where_filed, notes) and rejects an empty/placeholder
    `where_filed`.
- `.opencode/commands/handoff-packet.md` — rewritten to use the helper for
  scaffold+validate and to enumerate concrete durable save paths:
  OpenChamber project knowledge note (preferred, titled
  `session-handoff-<slug>-<YYYYMMDD>`), board-api card comms
  (`POST /comment` on idc03:10000), or dispatch-outcome + card comms for
  devin-dispatch sessions. `where_filed` stays mandatory.
- `.opencode/commands/session-capture.md`,
  `.opencode/instructions/session-capture.md`,
  `.devin/skills/session-capture/SKILL.md` — sweep step 6 now points at the
  helper and the command's save-path list, so non-OpenCode agents get the
  same one-step flow.
- `docs/ssot/jobs/infrastructure/2026-11-24-handoff-packet-scaffold.yml` —
  trail/runbook entry (SSOT pre-commit validation passed).

## Acceptance check

- One-step scaffold: `python3 scripts/chaba/handoff-packet.py scaffold` ✓
- `where_filed` mandatory and validated (`validate` rejects placeholders) ✓
- Durable pointer-first sink: OpenChamber knowledge note or card comms, both
  now spelled out with exact endpoints/tooling ✓

## How to verify

```
python3 scripts/chaba/handoff-packet.py scaffold --objective "demo" --out /tmp/h.md
python3 scripts/chaba/handoff-packet.py validate /tmp/h.md   # exit 1: where_filed placeholder
# fill where_filed, re-run -> "OK"
```

## Session Handoff Packet

- objective: make the required Session Handoff Packet fast to scaffold, fill, and save to a durable sink (card opencode-handoff-packet-scaffold-save)
- as_of: 2026-11-24 23:20 +0700
- current_state: done — commit 862ca1962f on dispatch branch; SSOT pre-commit validation passed
- canonical_refs: docs/ssot/ssot.knowledge-capture.yml#Session Handoff Packet; .opencode/commands/handoff-packet.md; scripts/chaba/handoff-packet.py; docs/ssot/jobs/infrastructure/2026-11-24-handoff-packet-scaffold.yml; card opencode-handoff-packet-scaffold-save
- open_asks_decisions: none — option B (OpenChamber write inside the script) deliberately not taken; auth/path handling stays sink-side per card's "needs careful auth/path handling" note
- next_action: dispatcher merges branch; card already in review
- where_filed: this outcome file dispatch-outcome-20261124-231605-goal-make-the-required-session.md; card comms on opencode-handoff-packet-scaffold-save; trail docs/ssot/jobs/infrastructure/2026-11-24-handoff-packet-scaffold.yml
- notes: branch/unmerged until dispatcher merge; OpenChamber knowledge-note save is a UI/agent-tool surface, not a repo API — the command documents it as preferred with card comms as the always-available fallback

lessons:
- The handoff-packet command landed earlier via PR #207; re-dispatched cards may already be partially done — check git log for the card's prior commits before re-implementing.
- board-api card comms (`POST /comment`) work fine from dispatch worktrees; card YAML must never be edited directly (flock race).
- scripts/chaba helpers here are stdlib+PyYAML only; handoff-packet.py deliberately avoids yaml to stay dependency-free.
