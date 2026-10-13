# Dispatch outcome — umbrella-fix-ada-tool-call-failure-surfa-48054d (ADA-0525, run 2)

## What the task was
Continue the one-pass fix of the Ada tool-call failure surface behind 18
`audit-fail-*` cards. Run 1 (06:35, merged f4f9281d) did the audit-side
reclass + staged the ada-pi patch; this run verified live state and
extended the patch for the two signatures still failing at the 07:24
sweep (calendar_read, chat_send notify lane).

## What was found
- **calendar_read was already live-fixed.** The 367x/12h googleapis 404
  storm came from dead calid `e468a444…` (a real calendar whose Google
  name is the literal `${GOOGLE_CALENDAR_JARVIS_CALENDAR_NAME}` — an old
  script bug). SSOT dropped it in `15204342` (11:28); the rendered
  `~/.config/ada/calendar.json` on idc03 landed 11:29. Journal verified:
  last 404 at 11:29:03, every fan-out since = 15/15 HTTP 200.
- **Two residual ada-pi bugs were underneath:**
  1. `GoogleCalendar.list_events` raised `CalendarError` on any single
     calendar's failure, sinking the whole aggregate read — the reason
     one dead calid became a 367x outage and an audit-fail card.
  2. `notify_or_defer` (non-urgent) queued context notes on providers
     whose Gemini session was never connected/already dead; the drain
     crashed `'NoneType' object has no attribute 'send_client_content'`
     — the "deferred notify" signature in the chat_send lane (seen
     00:37 + 06:37 today).

## What changed
**This repo (committed 2a55d35a on the dispatch branch):**
- `docs/kb/patches/ada-pi-tool-call-failure-surface-20261013.patch` —
  regenerated as a 2-commit mbox (bbb90f1 + 9ff1bf9). `git am` on
  tony-dell's ada-pi applies both; verified: `git am` at base 6257dde
  reproduces the branch tree exactly. Staging branch on idc02's clone
  fast-forwarded to 9ff1bf9 (other session's dirty files untouched).
- `docs/ssot/jobs/ada/2026-10-13-ada-tool-call-failure-surface.yml` —
  round-2 fixes, verification, live evidence, updated verdicts for
  calendar_read + chat_send.
- `docs/ssot/apps/ssot.apps.ada-calendar.yml` — tool-contract line now
  documents the per-calendar degrade.

**ada-pi patch round 2 (9ff1bf9):**
- `google_calendar.list_events`: per-calendar miss collects into
  `provider.errors` (degrade); all-calendars-fail still raises;
  `CalendarAuthError` stays loud mid-fan-out.
- `calendar_providers.list_events`: drains `provider.errors` into the
  result's `errors[]` — reported but NOT into `_raise_untrustworthy`
  (empty day + dead calid stays ok:true; config drift ≠ outage).
- `realtime_provider.notify_or_defer` + `_send_context_note`: raise
  `RuntimeError("provider is not connected")` like every other send
  path — `/api/notify` already retries that error then returns
  `delivered:false`.
- 6 new tests (dead-cal degrade, all-dead raise, mid-fan-out 401 loud,
  intra-provider errors on hit + empty day, unconnected notify).

## Verification done
- ada-pi: 76 calendar/provider tests + 207 tool_runner tests pass under
  `ADA_INSTANCE_ID=tony` (unset → only the known env-dependent failure).
  `tool-lint` clean (59 warnings, unchanged). py_compile clean.
- Live: idc03 `journalctl -u ada-ha-tony` — zero googleapis non-200
  since 11:29; deferred-notify warning pattern explained (not a tool
  bug in chat_send itself).
- Board: [verify] comment on the umbrella; VERIFIED comment on
  audit-fail-calendar-read.

## Still open
- Landing + deploying the ada-pi patch — still gated on the open board
  request `land-the-ada-pi-patch-git-am-reports-ada-615a5b` (unchanged;
  the mbox now contains both commits — same `git am` command). Suggested
  answer remains `land + deploy to ada-ha-tony`.
- `chat_send` photos picker 501 still needs `GPHOTO_REFRESH_TOKEN` on
  idc03 (config, not code).
- After deploy + one clean audit day: confirm none of the signatures
  refile, and that a dead-calendar recurrence produces `errors[]`
  entries instead of a failed read.
