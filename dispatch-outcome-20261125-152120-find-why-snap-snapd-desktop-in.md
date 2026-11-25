# Dispatch outcome — tony-omen snap desktop restart loop (attempt 4)

Card: `tony-omen-snap-desktop-restart-loop` (OPS-1323)
Date: 2026-11-25

## State carried in

Attempts 1-3 already diagnosed and fixed the root cause live on
tony-omen: the `snap.snapd-desktop-integration` user unit looped every
~12s with `Failed to open display` because the Chrome Remote Desktop
Xvfb session never exports DISPLAY/XAUTHORITY into `systemd --user`.
Fix = user drop-in
`~/.config/systemd/user/snap.snapd-desktop-integration.snapd-desktop-integration.service.d/override.conf`
with `Environment=DISPLAY=:20` + `XAUTHORITY=/home/tony/.Xauthority`.
Attempt 3 armed a self-removing `@reboot` cron verifier
(`~/.local/bin/snap-boot-verify-ops1323.sh`) that posts NRestarts /
ActiveState / display-error counts to this card ~5min after the next
boot, then deletes itself. This attempt re-verified everything still
holds and resolved the open reboot question.

## What attempt 4 verified (~15:25 +07)

- Unit `active/running`, `NRestarts=2` — both are the legitimate
  CRD-session-churn reconnects documented in attempt 3 (15:05-15:08),
  stable since 15:08:39.
- Zero `Failed to open display` journal lines since 10:00 (fix went in
  ~09:54). The 2,831 count for "today" is all pre-fix loop noise.
- Drop-in intact (`DropInPaths` confirmed), `snap list` untouched —
  firefox, snap-store, gemini-desktop and all other snaps still
  enabled; nothing disabled.
- `@reboot` verifier still armed in user crontab; script present and
  executable.
- Host still up 1d20h — no reboot yet.

## Reboot decision — deferred, deliberately

Tony answered `reboot-now` on request `snap-reboot-verify-window` at
15:02. Attempt 4 checked what a reboot would kill and found an active
upscale-eval queue on tony-omen:

- `/tmp/resshift-eval/queue-v1-rsd.sh` (PPID 1, survives its launcher
  but not a reboot) chains three GPU/CPU jobs:
  `resshift-v3-s4-g128` (finished ~15:24) -> `resshift-v1-s15-g128`
  (running at check time) -> `rsd-one-step-gpu`.
- ~1.5h+ of eval work remained; host is 12 cores at load ~66 with
  llama-server and openjev also running. runner-agent is alive but
  only polling (claim passes self-skip on overload) — no in-flight
  dispatch would be orphaned, but the eval queue would be destroyed.

Rebooting now would trade ~1.5h of real GPU eval work for a
verification the armed @reboot script performs automatically on the
next natural boot. Deferred. If Tony wants instant post-boot proof
despite the eval queue, reboot tony-omen — the verifier posts the
verdict to this card ~5min after boot with no further action needed.

## Deliverables in this worktree

- `docs/ssot/jobs/infrastructure/2026-11-25-tony-omen-snap-desktop-integration-display-fix.yml`
  — full trail; this attempt added `attempt_4_findings` (re-verification
  numbers + reboot-deferral rationale) and updated `status:`.
- `dispatch-outcome-20261125-152120-find-why-snap-snapd-desktop-in.md`
  — this file.
- Fast-forwarded this branch onto attempt 3's docs commit
  (`d8d8ab1f08f`) so the merge-sweep lands the trail docs that
  attempts 1-3 produced (attempt 1 left them untracked; attempts 2-3
  committed on their own dispatch branches which may never merge
  individually).
- Live on tony-omen (unchanged this attempt): systemd drop-in +
  self-removing @reboot verifier.

## Board state

- Request `snap-reboot-verify-window` already answered (reboot-now);
  this attempt's deferral is documented in card comms + jobdoc. No new
  request raised — the verifier closes the loop without Tony action.
- No `needs-input.txt` — nothing is blocked.

lessons:
- Before honoring a "reboot-now" answer on a busy host, enumerate what reboot kills (orphaned PPID-1 job queues in /tmp don't show in `ps --ppid` of any session) — an eval queue with hours remaining is a real gate, not a formality.
- Dispatch attempts each get a fresh worktree+branch from the same base; trail docs committed on an earlier attempt's branch do NOT land unless the latest branch carries them — ff-merge the prior attempt's docs commit into yours before ending.
- `journalctl --user -u <unit> --since today | grep -c "Failed to open display"` counts pre-fix noise too — scope the window to post-fix time for a clean signal.
