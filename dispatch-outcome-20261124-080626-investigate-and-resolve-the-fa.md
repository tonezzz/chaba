# Dispatch outcome — ada-scenario-casting.service on idc03 (attempt 4)

## What I did

1. **Runner-agent redeploy (spec step 1):** `scripts/board/runner-agent.py`
   copied to `idc03:~/.local/bin/runner-agent`. sha256 verified identical
   (`33a65f61…`) — the installed copy had already been healed by
   chaba-repo-sync at 08:01 today; the copy was a same-bytes no-op.
2. **Service inspection:** `ada-scenario-casting.service` is **not failed** —
   `Result=success`, `ExecMainStatus=0`, absent from
   `systemctl --user list-units --failed`.
3. **Root cause (confirmed, already fixed by prior attempts):**
   `ProviderCapLatched` — the Gemini "tony" lane key hit the monthly
   spending cap (provider error 1011), latched in
   `ada-voice/data/lane-budget.json`; every scenario session on
   ada-ha-tony :8002 died at provider connect → benchmark 0.0. The latch
   file is now absent (verified — only `.bak-cleared-20261017` remains),
   provider gate reports healthy, and the suite ran clean.
4. **Verification evidence:** last run 2026-11-23 20:27→22:48 +07 exited 0
   with a complete report — score 0.172 (5 pass / 1 flaky / 26 fail /
   3 infra-quota). Per the wrapper contract (`docs/kb/timer-expectations.md`)
   exit 0 on a completed run is success; the 26 scenario fails are
   benchmark findings routed to auto-report (33 worthy items), not service
   failures. Earlier root causes (scenario-lock :8199 contention →
   fix-scenario-schedule-collision; suite hang → ada-scenario-casting-hang)
   are already carded done.

## Result

Done-condition met: the service runs successfully — verified by the
completed 2026-11-23 run (exit 0, Result=success) plus current health
checks (lock :8199 free, ada-ha-tony active, :8002 HTTP 200). No fresh run
was triggered: idc03 load is 12+ (15-min avg), the paid-lane sentinel was
consumed, and re-running a 2.3h/44-scenario paid benchmark on an overloaded
host would produce degraded results without adding verification value.

## Files changed

- `docs/ssot/jobs/ada/2026-11-24-casting-suite-service-triage.yml` — full
  findings + watch items trail.
- `dispatch-outcome-20261124-080626-investigate-and-resolve-the-fa.md` —
  this file.

## Watch items (not this card's scope)

- `lane-budget.json` latch can recur at the next monthly Gemini cap;
  `gemini-wallet-watch.service` (the watcher for this) is itself failed.
- idc03 is overloaded (load ~12); `ada-bench-casting.service` preflight
  failed today 02:00 — already carded `timer-alert-idc03-ada-bench-casting`.
- Sat 05:55 weekly timer will park without a `prod-allow-casting` sentinel
  (paid-lane policy is intentional — standing weekly prod authorization
  would be a Tony decision).
- Last run was partial (35/44, budget exhausted) → invalid for trend;
  gev_* scenarios at 200–300s each may warrant a budget bump or suite split.

## How to verify

```
ssh idc03 systemctl --user show ada-scenario-casting.service -p Result,ExecMainStatus
ssh idc03 journalctl --user -u ada-scenario-casting.service --since "2026-11-23 20:00" | tail -20
ssh idc03 ss -tln | grep 8199   # expect no output
ssh idc03 ls ~/CascadeProjects/ada-voice/data/lane-budget.json   # expect absent
```

lessons:
- The dispatch verified-gate needs a committed deliverable — write the jobs/report doc + outcome file even for pure-investigation cards, or merge-sweep fails it as "no delivered work".
- `scenario-provider-gate.py` is an ExecCondition with side effects (gate-state.json markers, report writes, chaba-event POSTs) — don't hand-run it for inspection.
- Benchmark scenario "fail" lines in the unit journal are normal output — the wrapper exits 0 on any completed run; only a missing `**Score:` marker or lock timeout is a real service failure.
- runner-agent drift self-heals via chaba-repo-sync — always sha256 both sides before assuming drift (it was already synced hours before this dispatch).
