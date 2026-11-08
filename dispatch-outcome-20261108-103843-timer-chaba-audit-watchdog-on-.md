# Dispatch outcome — timer-alert-tony-omen-chaba-audit-watchdog

## Verdict: not a timer failure — census drift re-armed a resolved card. Fix applied in worktree.

### What actually happened

1. **The 10-13 05:00 exit-code** (the card's original alert) was already root-caused and
   fixed on 2026-10-13: `scripts/audit-watchdog.mjs` was a pre-OPS-0581 finding-reporter —
   it exited 1 because `reports/audits/summary.json` on tony-omen was stale. The exit-0
   contract shipped same day 18:24 (docs/kb/timer-expectations.md); card was closed.

2. **The timer then ran daily until 2026-10-22 05:00** (last write to
   `~/CascadeProjects/chaba/logs/audit-watchdog.log`), each run correctly writing
   `audit-stale.yml` to the local focus-inbox because the suite no longer runs on omen.

3. **`chaba-audit.timer` and `chaba-audit-watchdog.timer` are now `disabled` on tony-omen**
   (unit files still present in `~/.config/systemd/user/`). This is deliberate and matches
   declared state: the audit suite lives on **con01** (`ssot.jobs.yml` job `chaba-audit`,
   moved tony_dell→idc02 2026-10-04, then idc02→con01 in the 2026-10-25 absorber shed,
   commit `766462b4e`). The watchdog job is declared on no host — undeclared = disabled
   per declared-or-dead.

4. **Verified the suite is alive on con01** (surface check, not just unit state):
   `chaba-audit.timer` enabled, ran today 02:00 CET; `summary.json` regenerated
   2026-11-08 01:13Z (1.4 MB, ok:false = findings on their own channels by design).

5. **Why the card re-spawned today 10:29**: timer-sentinel's sweep
   (`~/.local/share/chaba/timer-timeline/state.json`) sees the omen timer `disabled`
   while `docs/ssot/infrastructure/ssot.audit.hosts.yml` still lists it in tony-omen
   `expected_services` (default expected_state=active) → sentinel fired the card id →
   board-api `on_exists:queue` re-armed the done card with the automatic comm
   "re-spawned from report page". The card `note:` still shows the stale 10-13
   exit-code text — misleading; today's live condition was drift, not a crash.
   Sibling card `timer-alert-tony-omen-chaba-audit` fired for the identical reason.

### Changes (this worktree, not pushed)

`docs/ssot/infrastructure/ssot.audit.hosts.yml`:

- **tony-omen**: moved `chaba-audit.timer` + `chaba-audit-watchdog.timer` from
  `expected_services` → `expected_absent` (with migration notes).
- **idc02**: removed the 8 timers shed to con01 from `expected_services`
  (`chaba-audit`, `chaba-audit-full`, `chaba-kb-audit`, `chaba-system-report`,
  `ssot-optimization-snapshot` ×2 incl. a duplicate, `ada-flood-news`,
  `report-distill`, `devin-bank-distill`) → new `expected_absent` block. Verified
  all are `not-found` on idc02 and enabled on con01. Same un-cleaned Oct-25 shed.

After merge + `chaba-repo-sync` on omen (hourly), the sentinel's expectation map stops
matching these timers → both cards stop re-firing.

### Residuals / follow-ups (noted on the card)

- Dead unit files remain on omen: `~/.config/systemd/user/chaba-audit.{service,timer}`,
  `chaba-audit-watchdog.{service,timer}` — removable per declared-or-dead
  (`systemctl --user disable` already done; `rm` + `daemon-reload` finishes it).
- **Coverage gap**: `chaba-audit-watchdog` is undeclared fleet-wide — nothing checks
  con01's suite freshness daily. Already covered by backlog card
  `job-health-sweep-consecutive-failure-alerts` (consecutive-failure sweep).
- `chaba-event-log.py` no longer exists on tony-dell — the watchdog's best-effort
  `emitEvent` ssh target is gone (harmless while retired; matters if the watchdog
  is ever redeployed).
- Sentinel fired 27 findings this sweep; several other omen cards (ada-review-refresh,
  audit-cast, cast-ha-panel, devin-bank-distill, log-shipper×2, ssh-canary,
  wp-cam-snapshot) are separate conditions — real failures or their own drift —
  tracked by their own timer-alert cards.

### How to verify

- `ssh tony-omen systemctl --user list-timers | grep audit` → only `chaba-kb-audit.timer` active.
- `ssh con01 systemctl --user list-timers | grep chaba-audit` → enabled, last run Sun 02:00.
- After this merges: sentinel heartbeat `cards_fired` no longer lists
  `timer-alert-tony-omen-chaba-audit{,-watchdog}`
  (`ssh tony-omen cat ~/.local/share/chaba/timer-timeline/sentinel-heartbeat.json`).
- Safe to close this card and sibling `timer-alert-tony-omen-chaba-audit`.
