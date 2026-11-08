# Dispatch outcome — timer-alert-idc03-ada-scenario-tools

## Finding

`ada-scenario-tools.service` on idc03 was **not crashing** — it was completing
its weekly run and exiting 1 anyway because the *deployed* copy of
`scenario-suite-run.sh` was stale.

Timeline:

- **2026-10-13** — OPS-0581 merged the exit-code contract into the repo
  (`scenario-suite-run.sh` exits 0 when the benchmark completes and prints the
  `**Score:` marker; findings live in reports, not the exit code).
- The wrapper is **copy-on-install by design**: `install.sh` copies it to
  `~/.local/share/ada-scenario-runner/` so a bad repo checkout can never break
  the weekly suites. Nobody re-ran `install.sh` on idc03 after OPS-0581.
- **Oct 30** run: suite completed (`**Score: 0.0**`), old wrapper passed
  exit 1 through → `Failed with result 'exit-code'`.
- **Nov 6 05:55** run: same — completed, printed `**Score: 0.167**`,
  policy violations listed, then status=1/FAILURE. This is the run the
  timer-sentinel alert was about.
- **Nov 8 10:34** — `install.sh` was re-run on idc03 (all unit files +
  wrapper refreshed in the same second). Deployed wrapper md5 now equals the
  repo copy (`99cea489...`).

## State now

- Deployed `~/.local/share/ada-scenario-runner/scenario-suite-run.sh` ==
  `~/CascadeProjects/chaba/stacks/services/ada-scenario-runner/scenario-suite-run.sh`
  (md5-verified).
- Next scheduled run: **Fri 2026-11-13 05:55 +07**. A completed suite will
  exit 0; only a real crash (no `**Score:` marker) alerts.
- Card `timer-alert-idc03-ada-scenario-tools` closed to done with the full
  root-cause comment.
- Suite *findings* themselves (score 0.167, 7/9 fail on prod lane :8002 —
  including several 0-second fast-fails) are suite-quality signals owned by
  ada-ha-scenario-reports / the auto-report page, not the timer alert.

## Follow-up filed

- **OPS-1160** `scenario-runner-deployed-drift-check` (backlog): the 24-day
  stale-deployed-wrapper gap caused this false alert. Proposes a light drift
  check on idc03 (diff deployed vs repo md5 of the wrapper, and optionally the
  `ada-scenario-*` unit files) wired into chaba-repo-sync ExecStartPost or
  chaba-standard-drift — keeping the isolation design but closing the
  detection gap.

## How to verify

- `ssh idc03 "md5sum ~/.local/share/ada-scenario-runner/scenario-suite-run.sh \
   ~/CascadeProjects/chaba/stacks/services/ada-scenario-runner/scenario-suite-run.sh"`
  → identical hashes.
- After Fri Nov 13: `ssh idc03 "systemctl --user status ada-scenario-tools.service"`
  → result success even if the suite reports failing scenarios.
- No repo changes made; nothing pushed or deployed by this session.
