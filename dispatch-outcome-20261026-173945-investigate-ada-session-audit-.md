# Dispatch outcome — investigate ada-session-audit `degraded:cast_to_screen`

Card: `audit-degraded-cast-to-screen` (ADA-0685) → **closed (done)**.

## Verdict

**Tool bug** — and it was already diagnosed + fixed (staged) 11 days
ago under ADA-0684 (`ada-cast-wrong-target-verbose-loop`, drop 10).

`cast_to_screen`'s `/pub` call sites return the vcast relay ACK
verbatim: `ok:true` + `delivered:0` means the relay accepted the
message but **no connected display received it** — yet it narrates as
success ("opened on screen 1"). The audit classifier correctly flags
`ok:true` + `delivered:0` as `degraded` — real signal, not a
display-side/schema artifact.

## Evidence checked

- MDDB `ada-ha-scenario-reports` `audit/session-*` reports (all 16):
  live occurrences were 4x on 2026-10-10 (the outage day), 2x on
  2026-10-14 (session `4029a6447f` — Tony's wrong-target cast loop,
  screen 1 offline), 1x on 2026-10-17 (`5d307ab1b4`). **Zero live
  occurrences after 2026-10-17** — the 10-20 report's 3 hits are
  catch-up replays of those same old transcripts, not new events.
- Live idc03 `~/CascadeProjects/ada-voice` @ `59562cf`
  (= origin/main): no `_pub_truth`, no drop-10 patches at all — the
  fix **staged 2026-10-15 was never deployed** (deploy needs explicit
  Tony approval per ada-voice AGENTS.md; no request had been raised).
- Verified the staged patch `integrations/ada-voice/backend/
  screens.delivered-zero.patch` still applies cleanly to live main —
  all 3 hunks via `patch --dry-run` (offsets +24/+26 lines).

## Actions taken

- Job trail: `docs/ssot/jobs/ada/2026-10-26-degraded-cast-to-screen-audit.yml`
- Board comment with the full verdict on the card.
- Board request `approve-deploying-ada-voice-drop-10-ada-e1fe9b`
  (options: deploy ★ / defer / partial-screens-only) — the only
  remaining gate. The sig is quiet because the offline-screen path
  hasn't been hit, not because it's fixed; it will recur if Ada casts
  to a disconnected display.
- Card closed (done). If `delivered:0` recurs pre-deploy the audit
  refiles — correct behavior.

## Verify

- `curl -X POST <mddb>/get` `audit/session-2026-10-14` — see the 2
  `DEGRADED cast_to_screen … delivered:0` lines under `4029a6447f`.
- `ssh idc03 'grep -n _pub_truth ~/CascadeProjects/ada-voice/backend/tool_runner/screens.py'`
  — empty until drop 10 deploys.
- Post-deploy, a delivered:0 cast classifies as `fail:cast_to_screen`
  (honest), ending the `degraded:` signature.
