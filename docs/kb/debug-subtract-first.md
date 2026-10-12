# Subtract-first debugging (Tony's rule, 2026-10-12)

"When there's no problem it's ok to add more features, but when there's a
stubborn issue we must not add anything new — remove features until we
find the root cause."

## The rule

A stubborn bug with an unproven root cause means the system is not yet
understood. Building on top of it is forbidden — new code adds variables,
not signal.

1. **Subtract to the minimum that still shows the symptom** — disable
   modules, gate inputs, empty bindings. Each removal either kills the
   symptom (bisect win — the removed thing was involved) or proves that
   subsystem innocent.
2. **Verify the silent baseline** before adding anything back. "No
   scream" must be *observed*, not assumed.
3. **Reintroduce exactly one piece at a time** — the first re-addition
   that brings the symptom back names the culprit.
4. Only then fix, and only then resume feature work.

Corollary from the Jam scream hunt (2026-10-12): ~11 fix attempts were
shipped while several independent mechanisms were all producing the same
symptom — every fix was real, none was the last one, and each deploy
that *added* instrumentation/features on top delayed the isolation. The
bug was found only after stripping to `mods=band` alone (pure scheduler,
zero input) proved the input path guilty.

## Signs you're violating it

- Shipping a fix whose verification you can't observe.
- More than ~2 attempts on the same symptom without a hard repro.
- "It should work now" instead of "the counter shows which voice fires."
