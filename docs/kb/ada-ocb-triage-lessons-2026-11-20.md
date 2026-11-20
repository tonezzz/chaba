---
category: operations
type: lessons
status: defined
---

# ada-ocb triage lessons — Jules EOL and dispatch lanes (2026-11-20)

Source: the "what is blocking ada-ocb" triage that ended in OPS-0156 closed,
ADA-1294 landed, ADA-1285 queued. Canonical facts live in the SSOT docs
named below; this note records the process lessons.

## 1. Read the related cards' comments before probing

The Jules EOL ("read-only until 2026-12-31, session creation disabled
account-wide") was already recorded — in the comms of nine cards, including
OPS-0156 itself. It was missed because `ada_status` returns only the last
five comments, and those were all `runner-agent drifted` noise. A live
probe then re-proved what the card already said.

- Use `GET /card/<id>?comms_tail=<n>` with a larger tail, or grep the card
  YAML under `docs/ssot/kanban/cards/`, before diagnosing a failed card.
- `ada_ssot_search` over `kanban/cards/*` finds comment text; try the
  failure string and the vendor name.
- A fact that only lives in card comments is not discoverable. Promote it
  to an SSOT doc (done for Jules: `ssot.devnest-lanes.yml`, lane `jules`).

## 2. Jules lane is retired

- Google Jules: read-only until 2026-12-31, creation disabled since
  ~2026-11-11 (last successful session). `POST /sessions` returns
  `400 FAILED_PRECONDITION "Precondition check failed."` for every repo
  with a valid key; GET endpoints still work.
- Fresh evidence 2026-11-20 is in the OPS-0156 comments. Closed won't-fix.
- Do not requeue cards as `executor=jules`. Keep `JULES_LANES=0`.
- Failures with `FAILED_PRECONDITION` plus a ~1.5h unit wall time were the
  same cause, not a code bug.

## 3. Moving a card off a retired lane

- `POST /card` with `on_exists:"queue"` re-arms an existing card and
  merges `action`; it **cannot clear** a field, and refuses changes while
  the card is queued or running.
- `action.lane` only accepts `codemod, free_lane, jules, manual, nlm_batch,
  paid_frontier`. `devin` is not a lane — it is the default executor when
  no lane applies. Set `executor: devin` and leave the lane alone.
- A stale `lane: jules` is harmless when `executor` is set: runner-agent
  routes on executor first and only falls back to lane when the executor
  is empty (`start_jules_lane` checks, runner-agent.py).
- To correct a card that was queued with the wrong action: `POST /action
  {do: hold}` first, then re-arm.

## 4. Staged dispatch (ada-control) is read-only only

`ada_envelope_draft` / `ada_envelope_stage` admit only the profiles
`ops-readonly`, `ssot-research`, `storage-dryrun` on stage S3 / target
idc02. Code-writing cards cannot be staged through ada-ocb. Use the board
`/card` + `/action` doors (as above) or `card-run.py --lifecycle`.

## 5. devin-lane work auto-merges

merge-sweep merges a verified devin session branch into `origin/master`
and auto-closes the card once `exit_code=0` — no human merge. Do not
promise "merge stays human" for this lane. Review after the fact; the
diff is visible from the card's `merge-sweep: merged <sha>` comment. A
later `auto-merge not done: no session repo` comment can contradict an
earlier successful merge — check `git merge-base --is-ancestor <sha>
origin/master`.

## 6. Smaller facts

- Runner-agent drift complaints on every card were already resolved once
  all hosts matched the repo `runner-agent.py` (md5 checked on six hosts
  2026-11-20); the comments are historical.
- ada-voice drop 19 (`host_status` tool) is staged in
  `integrations/ada-voice/`; Ada does not use it until the ada-drops
  deploy merge happens.
