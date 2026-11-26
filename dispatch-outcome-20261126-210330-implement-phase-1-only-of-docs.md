# Dispatch outcome — answer-sweep-auto-compose-spec (Phase 1)

Card: `answer-sweep-auto-compose-spec` (KNB-0243)
Spec: `docs/ssot/jobs/kanban/2026-11-19-answer-sweep-dead-letters.yml`,
option `2_auto_compose_spec`, **Phase 1 only** — Phase 2 template
composition deliberately NOT implemented.

## What changed

`scripts/board/answer-sweep.py` (+151 lines):

- `spec_compose_ready(card)` — pure detection predicate. True only when
  ALL of: column not done/lab; `awaiting_action` set; every ask-shaped
  entry (`requests[]` dicts + card-level `ask`) is resolved
  (answered/closed/executed — no open ask remains); `pending()`
  non-empty (at least one answered-unexecuted ask = the unmapped
  decision dead-letters to compose from); `action.type == "dispatch"`
  with `action.status` not in {queued, starting, running, done};
  `card["spec"]` empty (brief/note do NOT count — `build_task_text`
  falls back to title+note, exactly the low-quality prompt this
  guards); and no `spec-compose-*` request already on the card.
- `raise_spec_compose(card, ref)` — appends ONE request
  `{id: spec-compose-<date>, status: open, from: chaba}` whose `ask`
  inlines every answered ask + its answer (executed ones marked,
  fields truncated, ≤15 entries + "+N more", ask capped at 6000 chars).
  Options are dicts per the KNB-0180 contract: `spec-written`→`none`,
  `hold`→`hold`, `close`→`close` — **no option can arm dispatch**.
- `main()` write path calls the pair after `triage_card` for
  non-done/lab cards; `--dry-run` prints a `+spec-compose` marker.
  Module docstring documents the phase-1 contract.

`tests/board/test_answer_sweep.py` (+152 lines): new `SpecCompose`
class — 12 tests covering the positive raise (single consolidated
request, answers inlined, options carry no queue/retry action,
action.status untouched), every negative gate (no awaiting_action,
non-dispatch/missing/scalar action, armed statuses, spec present,
brief/note insufficient, open ask, all-executed, done/lab, no
requests), the re-raise guard at unit level, and an end-to-end
`main()` run proving exactly one `spec-compose-*` request survives a
second sweep pass.

`docs/ssot/jobs/kanban/2026-11-19-answer-sweep-dead-letters.yml`:
`phase1_status:` note added under option 2 (trail only).

## Re-raise guard (explicit)

**The guard is the request id itself**: `raise_spec_compose` returns
`None` and `spec_compose_ready` returns `False` whenever ANY
`requests[]`/`ask` entry id starts with `spec-compose-` — regardless
of that request's status (open, answered, or closed). Requests are
never deleted from card YAML, so the mark is durable. A second layer
exists incidentally: while the spec-compose request is open, "all asks
resolved" is false; once it is answered, the prefix guard alone
blocks. Verified end-to-end by `test_main_end_to_end_raises_once`
(two `main()` passes → exactly one spec-compose request).

**Never auto-arms dispatch**: the raise path does not touch
`action.status`/`column`; the request's options map only to
none/hold/close. Queueing still requires the human board button or a
future Phase-2 path.

## Verification

- `python3 -m pytest tests/board/test_answer_sweep.py -x -q` →
  **36 passed** (was 24; +12 new).
- Chaba gate (`REPO_TESTS["chaba"]` smoke set, dispatch_repos.py) →
  **300 passed in 174.6s** (budget 240s).
- `python3 scripts/board/answer-sweep.py --dry-run` on the worktree
  card set → 11 dead-letter cards listed, **zero `+spec-compose`
  markers** — expected: a board-wide scan found no non-done/lab card
  currently combining `awaiting_action` + `action.type=dispatch` +
  no `spec:`. The detector is armed for the state going forward; the
  existing 39-card pile mostly lacks `action:` entirely, so it will
  not trigger until such cards carry dispatch intent (per spec —
  Phase 1 detects the narrow specified state only).
- Card comms posted to `answer-sweep-auto-compose-spec` via board-api.

## Notes / residual

- `awaiting_action` stays set after the raise (the original unmapped
  answered asks remain pending forever — pre-existing dead-letter
  trait; Phase 2 / option-3 aging own that surface).
- Answering the spec-compose request with `spec-written` resolves it
  (`none`) but does not queue the card — a human still moves it.
- Phase 2 (template composition for the repo+host-unblock pattern)
  remains a separate card per the parent spec's recommended_order.

lessons:
- `tests/board/test_answer_sweep.py`'s `req(rid, answer, **kw)` helper
  takes the request ID first — easy to pass an id string as the answer
  by accident when constructing spec-compose-* fixtures.
- `tempfile.TemporaryDirectory()` in a test deletes on `with` exit —
  read assertion data INSIDE the block, not after it.
- board-api `/comment` can answer `board write lock saturated —
  retry` (retry_after 5s); a single sleep+retry succeeded.
- answer-sweep's `--dry-run` + a board-wide YAML scan are the cheap way
  to confirm a new detector fires on zero current cards before
  shipping — avoided a false "it will clean the pile" claim.
