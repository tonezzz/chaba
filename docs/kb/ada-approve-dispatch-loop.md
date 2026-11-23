---
category: operations
type: runbook
status: defined
---

# Ada Approve → Dispatch Loop (click-approve)

Card: `ada-dispatch-approve-button` (ADA-1180). The hands-off flow:

```text
Ada/producer shows a menu          -> scripts/board/approve-ask.py
  (a /request whose options carry declared actions)
Tony clicks an option on the board -> POST /respond {option: N}
  -> _exec_option_action runs the declared action IN THE SAME WRITE
kanban-dispatch claims the card    -> dispatch session runs
dispatch finishes                  -> _notify verified|unverified
  -> /publish milestone|alert -> Telegram (the verdict reaches Tony)
merge-sweep verified gate          -> auto-close (verified) or
  hold-for-review (unverified) + one-shot _verdict_notify push
```

The click IS the approval signal the dispatch gate accepts — no voice
`confirmed=true`, no `confirm_token`, no answer-sweep tick wait.

## Pieces

| piece | where | job |
|---|---|---|
| emitter | `scripts/board/approve-ask.py` | raise an ask whose options are `{id,label,action}` dicts |
| contract check | board-api `do_request` | rejects option actions outside `queue|retry|close|hold|none` at the door |
| click execution | board-api `_exec_option_action` | on `/respond`, run the selected option's `action` through `do_action` |
| backstop | `scripts/board/answer-sweep.py` | executes deferred/unmatched answers on the 15-min tick (unchanged) |
| close-the-loop | `waiting_cards.notify_lifecycle` + kanban-dispatch + merge-sweep `_verdict_notify` | `verified`→milestone, `unverified`→alert via `/publish` (Telegram) |

## Emitting an approve menu

```bash
# canonical approve pair — Approve queues the dispatch, Hold parks it
python3 scripts/board/approve-ask.py <card-id> "Dispatch the fix?"
# retry / close variants
python3 scripts/board/approve-ask.py <card-id> "Retry the failed run?" --approve-action retry
python3 scripts/board/approve-ask.py <card-id> "Deploy?" \
    --extra-option 'close|Close — mark done|close'
# fully custom menu
python3 scripts/board/approve-ask.py <card-id> "Pick one" \
    --options-json '[{"id":"a","label":"Option A","action":"queue"},{"id":"b","label":"B","action":"none"}]'
python3 scripts/board/approve-ask.py <card-id> "Approve?" --suggested approve --dry-run
```

- Default `request_id` is `approve-<card>`; re-emitting while an ask with
  that id exists is a no-op (emitters run on every pass).
- Ada calls the same thing from her tool layer (POST `/request` with dict
  options); the script is the canonical shape, not a required binary.
- `action:none` = "resolve this request, no board transition" (e.g. a
  Discuss option); the answer is still recorded.

## What executes on click

`/respond` resolves the answer to an option object (index pick, or free
text that uniquely resolves for the card-level `ask:`), then:

- `queue|retry|close|hold` → `do_action` immediately — the card is
  claimable in the same second, not on the next sweep.
- `none` → stamps `executed`, no transition.
- Busy card (`starting|running`): `queue` stamps executed (the in-flight
  session IS the approval); `retry|close|hold` stay unexecuted — the
  sweep owns them when the claim clears.
- Guard refusal (manual card, merge guard, manual classifier): answer is
  left unexecuted → `awaiting_action` triage + the sweep keeps it.
- Free text on `requests[]` that matches no option stays verbatim —
  deliberate conservatism, same as before.

An executed request stamps `executed: "<date> <verb>@respond"`;
re-answering clears the stamp so a changed answer can re-fire.

## Verification

- `python3 scripts/board/board-api.py --selftest` — the click-approve
  block covers: requests[] + ask paths, all five actions, busy deferral,
  guard refusal, voice-resolved options, free-text conservatism.
- Live: raise with `--dry-run` first; after a real raise, click the
  option on the board and check the card: `action.status` flips in the
  same write and `requests[].executed` carries `@respond`.
- Close-the-loop: a `verified` push arrives via Telegram (`/publish`
  milestone) when the merge gate passes; `unverified` pushes as an alert.

## Boundaries

- This removes the *transport* latency and the token ceremony, not the
  gates: `do_action` guards (manual executor, merge guard, classifier)
  still refuse — the click just reaches them sooner.
- `next`/`next_choice` stays read-only by design; the approve menu is a
  request, not a next-card pick.
