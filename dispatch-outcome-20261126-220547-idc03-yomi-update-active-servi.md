# Dispatch outcome — yomi-update-active/update-all status=125 (OPS-1382)

Card: `yomi-update-active-update-all-fail-every-8afee2` (attempt 3, tony-dell)

## What this attempt did

Attempts 1 (tony-omen) and 2 (mn01) already did the real work but produced no
landed commits:

- Attempt 1 found the root cause and fixed the host: `yomi-api.service` on
  idc03 was `disabled` + `dead` since 2026-11-23 ~19:50 (stopped during a
  systemd daemon-reexec / user-manager restart; disabled so it never came
  back). `podman ps -a` therefore had no `yomi-api` container and
  `yomi-update-active`'s `--network=container:yomi-api` one-shot failed
  status=125 every 15m. It ran `systemctl --user enable --now
  yomi-api.service` on idc03 and verified health + a manual update run.
- Attempt 2 re-verified live state (~5h of clean timer runs, zero status=125)
  and committed the repo trail on
  `dispatch/20261125-121947-idc03-yomi-update-active-servi` — but merge-sweep
  held the merge: "test gate failed — pytest unavailable — no test evidence"
  (environment issue on the mn01 runner, not a code problem).

This attempt (tony-dell):

1. Re-verified the live surface from this host:
   `curl https://idc03.taila0626a.ts.net:3000/api/yomi/health` →
   `{"ok":true,...}` — yomi-api is still serving ~31h after the fix.
2. Cherry-picked the deliverable commit `20edca5439b` from the attempt-2
   dispatch branch onto this branch (clean pick, no conflicts). It lands:
   - `systemd/yomi-api.service` — vendored canonical copy of the
     hand-installed unit (previously had no repo copy).
   - `docs/ssot/jobs/infrastructure/2026-11-25-yomi-api-idc03-disabled-reenable.yml`
     — full incident trail (root cause, fix, verification, residuals).
   - `docs/ssot/infrastructure/ssot.services.yml` — status note on the yomi
     service entry.
3. Skipped the attempt-2 "dispatch checkpoint" commit (`dd3c66809d0`) — it
   carried the stale per-session outcome file and unrelated
   `ssot.dev-system.assessment.yml` churn; this session writes its own
   outcome file instead.

## Result

Fixed on host (attempt 1) + verified again today (this attempt) + repo trail
now committed on `dispatch/20261126-220547-idc03-yomi-update-active-servi`
(1 commit ahead of master: `66501973c53`). No code changes were needed — the
yomi-update-* rendered units and `ssot.jobs.yml` declarations are correct as
long as the `yomi-api` container exists.

## How to verify

- `curl https://idc03.taila0626a.ts.net:3000/api/yomi/health` → `ok:true`.
- On idc03: `systemctl --user is-enabled yomi-api.service` → `enabled`;
  `journalctl --user -u yomi-update-active.service --since today` → clean
  Finished lines every 15m.
- Merge this branch; merge-sweep should now see a real commit. If the test
  gate again reports "pytest unavailable", that is a runner-host gap on
  whichever host performs the merge — unrelated to this diff (docs +
  systemd unit only).

## Residuals (from the jobs doc, still open)

- `yomi-line-session-expired-idc03` card owns the interim HOME drop-ins on
  the rendered yomi-update units; if its branch doesn't land, a re-render
  would lose `HOME=/home/tony`.
- `ssot.yomi-failover.yml` still names tony_dell primary — stale vs
  ssot.services.yml (idc03 primary since 2026-10-19). Doc-rot, flagged.
- Root cause of the original `disable` is unproven.

lessons:
- Dispatch "verify" counts a host-side fix with zero commits as failed — always land a repo trail (jobs doc + vendored unit) even when the fix is `systemctl enable`.
- "pytest unavailable — no test evidence" merge-hold is a runner-host environment gap, not a diff problem; docs/systemd-only diffs still get held by it.
- A hand-installed `~/.config/systemd/user/*.service` with no repo copy is unrecoverable drift — vendor it into `systemd/` when touching it.
- `--network=container:X` status=125 means container X's unit is dead — check `is-enabled`, not just `is-active` (disabled units stay dead across user-manager restarts).
