# Dispatch outcome — opencode-memory-freshness-check (2026-11-24 23:22)

## What this was

Re-dispatch of card `opencode-memory-freshness-check` (review_kind: verify).
Option A★ was already implemented and merged earlier the same day (PR #207,
squash `800d086aae`): `scripts/chaba/check-memory-freshness.py`. This pass
verified the deliverable against the card's acceptance criteria and closed
the gaps between the merged version and the spec's check list.

## What changed

`scripts/chaba/check-memory-freshness.py` (commit `f4b26dc052` on
`dispatch/20261124-232252-goal-provide-a-read-only-comma`, not pushed):

- `--hosts` now defaults to `all` → `DEFAULT_HOSTS` (tony-dell, tony-omen,
  idc03); the constant existed but was unused — the old default was
  `local` only, so "one command → per-host report" wasn't actually true.
  `--hosts local` / comma lists still work.
- SSH reachability probe per remote host → `ERROR` with probe evidence
  instead of every check silently reading as missing.
- `chaba-render-memory.service` state now parsed into
  `ActiveState` / `ExecMainStatus` / `ExecMainExitTimestamp` / `Result`;
  a non-zero last exit is reported as an issue (spec: "last service
  exit status/time").
- Feed inputs `events.md`, `immediate.yml`, `recent-events.yml` reported
  with presence + age as evidence; absence is not flagged (they are
  `hide_empty` sources in `ssot.chaba.memory.yml` — empty feeds are
  normal).
- `session-memory.md` tail (last 400 lines) scanned for
  `## Session end` / `## Compaction` headers; zero markers on a fresh
  file is flagged (spec: "recent SessionEnd/Compaction presence").
- Status logic simplified: `ERROR` = host unreachable or pipeline absent
  (timer inactive AND helper missing); `STALE` = any issue; else `FRESH`.

## Verification (read-only, live)

```
python3 scripts/chaba/check-memory-freshness.py          # fleet, text
python3 scripts/chaba/check-memory-freshness.py --json   # machine-readable
python3 scripts/chaba/check-memory-freshness.py --hosts local
```

Observed 2026-11-24 ~23:28 +07:

| host | status | evidence |
|---|---|---|
| tony-dell | FRESH | timer active, context 0.68h, session-memory 0.18h, 3 tail markers, all 3 hooks Phase B+ wired, helper exec |
| tony-omen | FRESH | timer active, context 0.86h, session-memory 0.94h, markers present, hooks wired |
| idc03 | STALE | timer+helper OK, context 4.96h fresh, but session-memory.md absent and all 3 Devin hooks absent — consistent with the recorded "idc03 hook integration N/A (host-appropriate)" decision; surfaced as evidence, not suppressed |
| tony-macbook (local) | ERROR | pipeline not deployed: no timer, no context.md, stock hooks without Phase B+ markers, no helper — correct classification, macbook is not in DEFAULT_HOSTS |

Read-only confirmed: the script only runs `ssh` + `stat`/`test`/`grep`/
`tail`/`systemctl show`; no writes, no fake events. `--json` output is
suitable as Phase C harvester/guard input.

## Notes / follow-ups

- idc03 STALE is a real finding the tool exists to surface; whether
  idc03 *should* have session-memory/hooks is already decided N/A — if
  that changes, this check will show it flipping to FRESH automatically.
- Options B (OpenCode `/memory-status`) and C (mcp-health/audit-hosts
  integration) remain open per the card spec; A★ was the accepted default.

lessons:
- `DEFAULT_HOSTS` was defined but never wired to the argparse default —
  "fleet fanout" silently meant local-only until `--hosts all` was added.
- Deployed hook markers ("Phase B+ session capture", `CHABA_CONTEXT`)
  exist only on hosts where session-capture.yml wiring was applied
  manually (tony-dell verified); repo copies of the hook scripts do NOT
  contain them — don't grep the repo to validate deployed state.
- `hide_empty` memory sources (events.md, immediate.yml,
  recent-events.yml) are legitimately absent on healthy hosts — freshness
  checks must report their age as evidence without flagging missing.
