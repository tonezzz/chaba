---
category: troubleshooting
status: verified
created: 2026-11-24
source: auto-kb
---

# ada_card_pick queue mislabelled manual cards as dispatchable

## Symptom

`ada_card_pick(strategy="queue")` reported every card with
`action.status == queued` as `why: "queued for dispatch"`, including cards
with `action.type: manual` that no runner can dispatch. The picker therefore
advertised human-only work as machine work, while the board's own queue sweep
(`manual_only` leg) already treated those cards as non-dispatchable.

## Root cause

In `ada-voice:opencode/ada_mcp.py`, `_pick_cards()` had a single unconditional
branch for the queue strategy:

```python
if _card_action(card).get("status") == "queued":
    scored.append((card, "queued for dispatch", (0,)))
```

There was no manual-action predicate shared with the queue sweep, so the two
code paths disagreed about what "queued" means.

## Fix (ADA-0189, ada-voice origin/main `92f2355854a2`)

- Added `_is_manual_action(card)`: true for explicit `action.type == manual`,
  or when `blocked` carries a runner verdict containing `unknown type 'manual'`
  (the shape a manual card takes in the queue projection). Read-only — no
  card mutation, no gate side effects.
- Manual queue picks now return
  `why: "human-only (manual action) — not runner-dispatchable"` plus
  `human_only: true` and `dispatchable: false`.
- Non-manual picks keep their **exact** previous response shape (`why` and
  no new fields) — no consumer churn.

## Gates deliberately preserved

Manual cards remain **selectable** for context/planning: they still receive a
`selection_token`, and `ada_plan` still enforces both the exact
`selection_confirmation` and the issued-token check. The fix changes the
description and adds flags; it does not hide the card or weaken a gate.
Five new unit tests in `tests/test_opencode_ada_mcp_selection_gate.py` cover
manual, non-manual, mixed board order/tokens, runner-verdict detection, and
gate preservation. Dedicated suite went 16 → 21 passing; a pristine-tree
baseline comparison showed exactly +5 passing and 0 new failures (the full
suite's `httpx`-related collection errors are environmental and identical on
both trees).

## Reusable pattern

When a UI/voice layer labels an item by capability, keep a machine-readable
flag (`dispatchable`) beside the human-facing string, and keep manual items
*selectable* — they are often still useful for context/planning. Also reuse a
single predicate across the picker and the sweep so the two cannot drift.

## Related

- ADA-0189 — card (spec forbade claim/queue/close/move; code-only fix)
- `docs/ssot/infrastructure/ssot.tools.yml` — `board.card_pick` declaration
