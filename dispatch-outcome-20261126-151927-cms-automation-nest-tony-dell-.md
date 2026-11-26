# Dispatch outcome — cms-auto-nest-tony-dell (CMS automation `nest-tony-dell` stale)

## Finding

True positive, already triaged twice (card comms 2026-11-24 20:07 and
2026-11-26 09:30/15:14, both by prior agent runs as "tony"). Root cause:
`nest-mgr.service` on **tony-dell** was cleanly stopped 2026-11-24 08:03
+07 after repeated `tick error: Remote end closed connection without
response`, and is `disabled`/`inactive`. The MDDB registry doc
`ada-cms-automation/nest-tony-dell` still had `enabled: true`,
`interval_min: 15`, `last_run: 2026-11-24T00:58:02+00:00` — so
`scripts/ada/cms-auto-health.py` correctly judged it stale and kept
re-carding. Tony's 15:15 comms: "put on hold" — restart-v1 vs
retire-for-nest-mgr-v2-actuation is his pending decision.

## Change made (live, reversible)

Set `enabled: false` and added `disabled_reason` on the registry doc via
MDDB `/v1/add` (collection `ada-cms-automation`, key `nest-tony-dell`,
lang `en`; `written_by: devin-dispatch`). Verified by re-`/get`: content
persisted, `updatedAt` bumped.

Why this is the right fix: `cms-auto-health.py judge()` returns
`ok — "disabled — no check"` for `enabled: false` before any staleness
math, so the alert loop stops and the card auto-closes through the
normal GREEN_WINDOWS path on the next kanban-sync ticks. `nest-mgr.py
publish()` preserves `enabled` from the existing cfg and `cycle()`
gates publishing on it, so the flag is sticky — if the service is ever
restarted while disabled it still won't publish until re-enabled.
Re-enable = set `enabled: true` on the same doc.

Did NOT restart or touch `nest-mgr.service` on tony-dell (this session
runs on mn01; the stop was intentional per Tony).

## Verify

- Registry: `POST http://100.102.134.91:11027/v1/get
  {"collection":"ada-cms-automation","key":"nest-tony-dell","lang":"en"}`
  → `"enabled": false`, `disabled_reason` present.
- Next `cms-auto-health` run (kanban-sync.timer, ~15 min) should print
  this slug as ok/disabled; the open card moves to done after 2 green
  ticks.
- Card comms posted with the same summary.

## Pending decision (Tony's, unchanged)

Restart nest-mgr v1 on tony-dell (requires fixing the MDDB connection
issue that caused the 2026-11-24 tick errors) vs retire it in favour of
the nest-mgr-v2-actuation pilot. Until then the automation stays
disabled and the CMS page `nest-tony-dell` stays frozen at
2026-11-24T00:58 — expected, not broken.

lessons:
- cms-auto-health has a designed hold: `enabled:false` in the
  ada-cms-automation registry doc silences staleness carding and is
  preserved by nest-mgr publish — use it for intentionally-stopped
  generators instead of leaving enabled:true to re-card every sweep.
- This card was dispatched despite Tony's "put on hold" comm — the
  auto-dispatcher doesn't read comms; encoding the hold in the registry
  (machine-readable) is what actually stops the loop.
