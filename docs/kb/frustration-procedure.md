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

## Second-chance rule

When a promise has already broken once on the same claim, the next
verification MUST use a different method than the one that gave false
confidence. Same-method re-verification repeats the same blind spot.

## Ban list

In promise position these are hedges, not evidence — if used, the claim
is unverified and must be labelled so: "should", "expected to",
"in theory", "normally", "the code says", "I believe".

## When a promise breaks

1. Say so plainly and first — before the new claim.
2. Name the gap class precisely (verified leaf ≠ verified caller;
   stale checkout ≠ deployed; flag present ≠ flag passed).
3. Add a watcher where the hole was (the 10-14 gap was an unread
   ledger → `ada-burn-watch.timer`), not just an apology.
4. Record it on the card so the next session inherits the lesson.
