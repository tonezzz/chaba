# Frustration Procedure — evidence before promise

Born 2026-10-15, from the Gemini Live burn incident: a fix was called
"verified" on a unit-level proof while the real caller kept burning —
~1,000 Live-min/day for days, discovered by a wallet top-up, not by a
check. Tony's rule: *"You're to mention it before promising me anything.
1,000 promises never equal 1 evidence."*

Applies to every agent in the ecosystem — Devin sessions, Ada (voice and
text), dispatches, subagents.

## What counts as a promise

Any claim about present or future system state: "it's fixed", "it works",
"it won't burn", "verified", "deployed", "safe to leave running",
"nothing will happen tonight". Explanations of mechanism and honest
"I don't know / unverified" statements are not promises.

## The rule

Before making a promise:

1. **Say the procedure name.** "Frustration Procedure:" precedes the
   claim, so Tony can see which standard the evidence met.
2. **Name the verification method** — not "I checked", but *what*:
   `pgrep on the spawned process`, `ledger line count`, `curl 200 on
   the served URL`.
3. **Exercise the real production path.** The actual caller, timer,
   ExecStart, or endpoint — not a unit/proxy/direct-function test.
   Capability existing (`--text` flag shipped) is not adoption
   (the suite passing it). 2026-10-15: `scenario-live.py --text`
   passed while `scenario-report.py` — the timer's real entry —
   never sent it.
4. **Cost claims need billed-path proof.** "Won't burn" requires
   evidence the billed resource wasn't invoked (provider log,
   ledger entry absence), not just that the cheap flag was passed.
5. **Give a checkable scoreboard**: metric/file + expected value +
   when to check. "Tomorrow's `voice-burn/2026-10-15.jsonl` dev lane
   ≤ ~30min" — a number Tony can falsify, not a reassurance.
6. **Mark the unverified honestly.** Anything not checked gets said
   as `unverified` with what would verify it. Never round up.
7. **Run the full kit — never curate.** All M-methods run every
   time. A check is skipped ONLY with a stated reason
   ("M5 n/a — no live session exists"), never silently. Selection
   is where blind spots breed: 2026-10-15 the smoke tier passed
   M1/M2/M4 while the unchecked timer-inventory path hid 6 weekly
   Live suites. Redundant checks cost seconds; a missed layer costs
   the wallet.

## Second-chance rule

When a promise has already broken once on the same claim, the next
verification MUST use a different method than the one that gave false
confidence. Same-method re-verification repeats the same blind spot.

## Ban list

In promise position these are hedges, not evidence — if used, the claim
is unverified and must be labelled so: "should", "expected to",
"in theory", "normally", "the code says", "I believe".

## Verification methods used 2026-10-15 — the repeatable kit

Claim under test: "the smoke suite runs text-mode, not billed Gemini Live."
Eight independent methods; each answers a different layer of the claim.
M1-M5 verify a session *isn't lying now*; M6-M8 verify *nothing else
can start lying later*. A top-up/gate decision needs BOTH families —
per rule 7, run all eight.
Full 5-method pass re-run on session 5540bb5f19 (2026-10-15 00:34):
argv --text ✓ · text-mode provider ✓ · 0 usage-turn lines ✓ ·
spend-ledger unchanged (3 live / $0.33) ✓ · 0 external sockets ✓ ·
ledger row mode=text.

**M1 — client argv (intent).** `pgrep -af scenario-live.py` while the
suite runs — the actual spawned command must carry `--text`. This is
the check that caught the wrong-file patch: the leaf driver accepted
`--text` but the suite runner never passed it. *Lesson: verify the
caller's argv, not the callee's flag.*

**M2 — server-side routing.** `journalctl -u ada-dev` for the session:
the ws accept line carries `mode=text` in the URL;
`pwa_server: session=X text-mode provider` + `openrouter_provider:
text mode` lines vs `voice.provider: session=X Gemini Live session
connected` for a Live one. *Lesson: the server names which provider
it routed to — independent of what the client asked for.*

**M3 — billed-token accounting.** Live sessions emit
`voice.provider: session=X usage turn ... in_by_modality={...
'audio': N}` — the Live API's own billed-token report; a text session
emits zero `Gemini Live|usage turn` lines (tested 00:28 on session
65b2207996: count=0). *Lesson: for a cost claim, count the billing
events themselves — closest layer to the invoice short of AI Studio.*

**M4 — independent spend accounting.** `~/.local/share/ada-review/
spend-ledger.jsonl` (written by `scripts/ada/spend-ledger.py`) counts
live-sourced turns + est_usd from a separate journal parse — not the
voice-burn ledger. A text session adds zero live_sessions/turns.
Baseline 2026-10-15: 3 live sessions, 20 turns, est $0.33 — unchanged
through the evening's text runs. (2026-10-14 for scale: 561 live
sessions, est $51.51.)

**M5 — network egress shape.** `ss -tnp | grep pid=<ada-svc-pid>`
during a session: a Live session must hold a persistent outbound wss
to Google (`generativelanguage.googleapis.com`) for its whole life;
a text session holds zero external sockets — only transient REST calls
(verified 00:35 on ada-dev pid 3632643: 5 conns, all tailnet/loopback,
0 external during session 5540bb5f19). *Lesson: the transport is
visible at the socket layer — billed audio needs a held connection;
REST text does not.*

**M6 — spawner inventory.** `systemctl --user list-timers` (plus cron,
`.timer` units, scheduled dispatches): WHO CAN START a billed session
unattended. A clean M1-M5 on the current session says nothing about
the next scheduled one — this is the check that found the 6 weekly
suites aimed at :8002 after the smoke tier looked safe.

**M7 — watcher coverage.** Are the watchdogs armed and recently run?
(`list-timers` for `*-watch.timer`, last-run timestamps.) Detection
between checks: prevention verifies now, watchers catch what slips
through later. An unarmed watcher = a gap in the net, say so.

**M8 — config audit.** Grep the actual scenario/service configs for
the switch that selects the billed path (`transport:`, `mode`,
endpoint URL, provider field). Code capability (`--text` exists) is
not configuration (which callers pass it). Counts, not samples:
"41/196 YAMLs have transport: text" beats "the ones I looked at do."

Companion scoreboard: `voice-burn-ledger.py` now tags rows
`mode: text|live` (a text session used to log minutes
indistinguishably from a Live one) and `burn-watch.py` alerts only on
live rows. Before that fix, "0 ledger entries" did NOT mean "0
sessions" — the ledger counted all /ws wall-time.

## When a promise breaks

1. Say so plainly and first — before the new claim.
2. Name the gap class precisely (verified leaf ≠ verified caller;
   stale checkout ≠ deployed; flag present ≠ flag passed).
3. Add a watcher where the hole was (the 10-14 gap was an unread
   ledger → `ada-burn-watch.timer`), not just an apology.
4. Record it on the card so the next session inherits the lesson.

## Board-state claims (added 2026-10-15 — the kanban extension)

Same discipline applies to claims about the kanban itself — the board is
an output surface, not ground truth:

1. **Never trust the card's declared state alone.** A card in `doing`
   can be stale for days; a "queued" badge means a click happened, not a
   running process. Verify: `action.status` on the card AND a live
   `devin-task-*.service` (or pid) on the claimed runner host.
2. **"Cards came back" has named mechanisms, not ghosts:** request-sweep
   re-ping after 12h unanswered; merge-sweep re-raise on un-deduped ids;
   lifecycle-check bounce done->doing when `verify:` exists but no
   `[verify]` evidence comm was posted. Each is checkable in comms.
3. **Rendered affordances can lie.** A button's existence ≠ valid action
   (the Queue-on-done-cards bug). Verify against card fields: column,
   action.status, requests[].
4. **Answered ≠ acted.** /respond records the answer; nothing executes
   it unless an actor does. "Tony already answered" is not evidence the
   thing happened — check the outcome field (dispatch queued, column
   moved), not the answer field.
5. **Every Tony-facing request must carry options** — an ask without
   buttons is a rendering failure, now enforced at board-api. If one
   appears, it's an invariant breach worth a repeat-ask increment.
