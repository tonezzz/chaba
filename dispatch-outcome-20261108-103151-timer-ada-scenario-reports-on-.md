# Dispatch outcome — timer-alert-idc03-ada-scenario-reports

## Verdict: alert re-fired on deploy drift, not a regression. Fixed on idc03.

### What happened
- Card `timer-alert-idc03-ada-scenario-reports` was closed 2026-10-13 after the
  finding-reporter exit-code contract (OPS-0581) shipped in repo.
- The **2026-11-05** weekly reports run still failed `exit-code`: journal shows the
  suite **completed** (`**Score: 0.0**`, 7 fails, all 0 tool calls) then exited 1.
- Root cause: **deploy drift** — `~/.config/systemd/user/ada-scenario-*.service`
  were the pre-BEN-0573 copies (mtime 10-23): reports targeted the **paid lane**
  `:8002/ada-ha-tony` with no provider gate, and the ExecStart wrapper on the host
  predated the exit-1→0 mapping until it was updated 11-07 (wrapper only, units
  never re-installed).

### Fix applied (on idc03)
- Re-ran `stacks/services/ada-scenario-runner/install.sh` from the synced exec
  checkout (HEAD b8f21c17ca): rebuilt quadlet image, re-copied all units,
  daemon-reload, re-armed timers.
- Deployed units now match repo: `ada-scenario-{research,cms,reports}` →
  `ws://127.0.0.1:8005/ws` (ada-dev FREE lane) + `scenario-provider-gate`
  ExecCondition; `{memory,tools,casting}` stay `:8002` and park via the wrapper
  paid-lane guard (by design). Wrapper md5 == repo (99cea489).

### Verification
- Manual `systemctl --user start ada-scenario-reports.service` exercised the new
  path end-to-end: gate read the ada-dev journal, found live REST dunning, and the
  unit **skipped cleanly** — `Result=exec-condition`, `ExecMainStatus=0`,
  `ConditionResult=no`. No failure, no sentinel alert. The 11-05 failure mode
  (completed run → exit 1) is impossible under the deployed wrapper.
- Next scheduled run: **Thu 2026-11-12 05:55 +07**.
- `scripts/audit-hosts.py --host idc03 --ssh` run post-change; no new scenario-stack
  findings (report saved under `reports/audit-hosts/` in this worktree; broad
  pre-existing idc03 drift noted separately).

### Surfaced issue (board request raised — spend decision)
- LiteLLM **`bench` virtual key is over its $2/30d cap** (spend 2.0057;
  `budget_reset_at` **2026-12-01**). ada-dev text turns 422 `budget_exceeded` on
  the gemini leg → provider gate reads quota-dead → weekly reports/cms/research
  will **clean-skip** (no alert, but no benchmark coverage) until Dec 1.
- Board request on the card asks Tony: raise bench cap to $5/30d (recommended),
  reset spend now, or leave until auto-reset.
- Adjacent, already carded: `ada-embed-bench.service` failed 11-07 (Gemini direct
  API HTTP 403) → `embed-bench-blocked-20261107`.

### Trail
- `docs/ssot/jobs/ada/2026-11-08-scenario-reports-timer-unit-drift.yml` (committed
  on this dispatch branch).
- Board: resolution comment + request posted to
  `timer-alert-idc03-ada-scenario-reports`.

### Lesson
`install.sh` updates wrapper AND units together for a reason — the OPS-0581/BEN-0573
contract spans both. A wrapper-only patch left idc03 in a dangerous middle state for
two weeks. Timer-alert cards resolved by a repo change should carry a
"deployed to <host>" verification line before closing.
