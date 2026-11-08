# Dispatch outcome — timer-alert-idc03-ada-scenario-research

## What was found

The `ada-scenario-research.service` failure on idc03 (2026-11-02 05:55, `result=exit-code`)
was two stacked problems, not one:

1. **Deploy drift (the exit-code itself).** The deployed wrapper
   `~/.local/share/ada-scenario-runner/scenario-suite-run.sh` and unit
   `~/.config/systemd/user/ada-scenario-research.service` were stale. The repo's
   exit-code contract (a3fa229ee, Oct 13 — completed failing runs exit 0 when the
   `**Score:` marker prints) and the provider-gate `ExecCondition` (Oct 15) were
   never installed — the stack's `install.sh` hadn't been re-run on idc03. The
   Nov-02 run used the Oct-09 wrapper, which exits with the benchmark's rc=1
   directly → systemd marked the timer failed. Both files were refreshed
   **today at 10:34** (by an install run) and are now byte-identical to repo HEAD.

2. **Zombie ada-dev (the underlying all-fail).** `ada-dev.service` was
   `is-active=active` but produced **zero journal lines all of Nov 02** — the
   05:00 smoke gate probe itself saw `journal_lines=1/70min`,
   `healthy_markers=0`, `rest_served=0`, yet still verdicted "ok — provider
   healthy". All 7 research scenarios then failed in ~0.4s each with 0 turns.
   The ada-voice exec checkout was also stalled (no merges Oct 23→Nov 04);
   ada-dev was restarted Nov 04 and has been serving since.

Sibling context: `ada-scenario-smoke` failed differently the same morning —
podman `statfs` on missing `ada-ha-michael.env`, exit 125 — already fixed by the
later secret-mount repoint commits (62281ff10 / 24051a032).

## Result / what changed

- **No code change needed for the alert itself** — the deployed wrapper+unit are
  now current; a completed failing run exits 0 going forward.
- **Verified live:** ran `scenario-benchmark.py --suite research --max-scenarios 1
  --dry-run` on idc03 at 10:48 → `deep_research_neuralink` **pass** (3 turns, 5
  tool calls, 99s). Lane works; next timer fires Mon 2026-11-09 05:55.
- **Findings posted** to card `timer-alert-idc03-ada-scenario-research`.
- **Follow-up carded:** `provider-gate-zombie-backend-blind` (ADA-1168, backlog,
  medium) — the provider gate can't detect a systemd-active-but-silent backend;
  proposed fix is a zero-journal-floor → infra verdict or a cheap live probe.
- **Job trail:** `docs/ssot/jobs/ada/2026-11-08-ada-scenario-research-exit-code.yml`.

## Residual notes

- Provider gate is point-in-time: at ~11:00 it reported `quota-dead` (132 quota
  lines/70min from morning activity). If dunning persists, Monday's run skips
  cleanly via `exec-condition` (not a failure — by design).
- Deploy drift is a class problem: stack units only update on manual
  `install.sh`. Worth considering a post-merge hook — noted in the job trail.

## How to verify

- `ssh idc03 journalctl --user -u ada-scenario-research.service --since '2026-11-09 05:50'`
  — Monday's run should show either a completed report with exit 0 or a clean
  exec-condition skip.
- `diff stacks/services/ada-scenario-runner/scenario-suite-run.sh
  <(ssh idc03 cat ~/.local/share/ada-scenario-runner/scenario-suite-run.sh)` —
  expect identical.
