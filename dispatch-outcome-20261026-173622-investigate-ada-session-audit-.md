# Dispatch outcome — investigate `no_result:ada_camera_snapshot`

## Verdict

**Correct-by-design friction + audit observability gap.** Both recorded
occurrences are `ada_camera_snapshot` calls that were cancelled mid-flight
when their Ada session ended — not tool failures:

- 2026-10-14 23:26:01 (+07), session `4029a6447f`: call received 4s after the
  last transcript turn (16:25:57Z; file mtime 16:26Z). The session was
  already unstable — Ada said "the connection hiccupped" at 16:25:40Z — and
  ended there.
- 2026-10-10 18:08:14 (+07), session `8d798faca2`: call in flight during a
  traffic-cam ask; transcript cuts off mid-sentence.

Mechanism: tool dispatch runs **inline** in the provider receive loop
(`realtime_provider.py` ~L5427). When the browser websocket drops /
session ends, `main.py`'s finally cancels the `provider_to_browser` task;
CancelledError lands inside `await self._camera_snapshot(...)`, so the
`function_call result` log line — and the FunctionResponse back to Gemini —
is never reached. A dead session cannot consume a tool result, so nothing
is owed and nothing is broken. The tool is well-bounded anyway (45s
`asyncio.wait_for` cap on the vms-snap shim with an honest stale-frame
fallback; 15s stale lookup; 10s relay publish).

## What changed (this worktree, committed on the dispatch branch)

`scripts/ada/session-audit.py` — the audit now distinguishes teardown
casualties from genuinely wedged calls:

- `fetch_journal` also captures `session=<sid> closed` lines (pwa_server
  logs one at every teardown).
- `parse_journal` records per-session `closed_ts`.
- `analyze_session`: a `no_result` whose session closed ≤90s after the call
  is reclassified `kind=teardown` (severity info, sig `teardown:<tool>`) —
  stays on the page/corpus as telemetry but `surfacing()` skips it, so it
  never reaches the inbox or files a card. Calls dropped while the session
  lived on (gap >90s or no close line — wedge / crash) keep
  `no_result`/medium with full escalation.
- Selftest fixture extended with a tail `ada_camera_snapshot` + close line;
  `--selftest` PASS (`teardown:1`, `no_result:1` retained).

Job record: `docs/ssot/jobs/ada/2026-10-26-no-result-ada-camera-snapshot.yml`.
Card comment posted with verdict + deploy note.

## Not done / follow-ups

- The audit runs from a self-contained install at
  `~/.local/share/session-audit/` on tony-dell — the fix goes live on the
  next `install-session-audit.sh` run; not deployed here (dispatch scope).
- Optional ada-voice polish (separate repo, out of scope): `close()` could
  log `function_call cancelled id=<cid>` for in-flight calls so even the
  journal alone shows the abandonment reason.

## How to verify

- `python3 scripts/ada/session-audit.py --selftest` → PASS with
  `teardown:1` in kinds.
- After install on tony-dell: next daily audit should show tail-of-session
  calls as `TEARDOWN … (expected)` and `no_result:ada_camera_snapshot`
  should stop recurring/carding.
