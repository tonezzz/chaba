# Dispatch outcome — ada-scenario-casting.service on idc03 (attempt 5)

## What I did

1. **Runner-agent redeploy (spec step 1):** copied
   `scripts/board/runner-agent.py` → `idc03:~/.local/bin/runner-agent`
   (chmod 0755). sha256 verified identical on both sides:
   `94ce1cb7c20f2c69…` — the installed copy and the idc03 exec-checkout
   copy had already converged via chaba-repo-sync; the copy was a
   same-bytes no-op, as the KNOWN_PITFALLS warned.
2. **Service inspection:** `ada-scenario-casting.service` is a user unit,
   currently `inactive (dead)` with `Result=success`,
   `ExecMainStatus=0` — last run 2026-11-23 20:27→22:48 +07 exited 0,
   score 0.172 (5 pass / 1 flaky / 26 fail / 3 infra-quota; the fails are
   benchmark findings routed to auto-report, not service failures). Absent
   from `systemctl --user list-units --failed`.
3. **Root cause (confirmed, fixed by attempts 3–4):**
   `ProviderCapLatched` — Gemini "tony" lane key hit the monthly cap,
   latched in `ada-voice/data/lane-budget.json`; every scenario session
   died at provider connect → benchmark 0.0. Verified the latch file is
   still absent (only `.bak-cleared-20261017` remains) and the provider
   gate reports healthy.
4. **Re-armed the paid-lane sentinel:** the `prod-allow-casting`
   one-shot sentinel had been consumed by the 20:27 run, so the next
   scheduled fire would have parked silently (bench-off-paid-lanes
   policy). Re-created it on idc03 citing this card
   (`~/.local/share/ada-scenario-runner/prod-allow-casting`, 168h TTL) —
   the designed card-requested path. Next fires: `ada-bench-casting`
   daily 02:00 (preflight-gated, likely skips on load) and
   `ada-scenario-casting.timer` Sat 2026-11-28 05:55 (weekly, ungated).
   Whichever fires first consumes it; delete the file to re-park.
5. **Recovered attempt-4's unmerged work:** its branch
   `dispatch/20261124-080626-…` was pushed to origin but auto-merge was
   rejected (fetch-first) and its worktree was swept. Checked out its two
   deliverables into this worktree and appended an
   `attempt_5_reverification` block to the trail doc.

## New findings this attempt

- `ada-bench-casting.service` (daily 02:00 preflight gate) failed again
  this morning: `embed-probe state=down` (Gemini embedding API HTTP 400,
  all circuits open, mddb embed queue depth 3189 — provider-side
  transient, self-recovered 08:00, state=up since) **and** `load 13.19
  >= 2`. The load check is chronic on idc03 (load 8–13 sustained;
  drivers: mddbd ~165% CPU across 4 procs, tailscaled ~50%, ollama
  embedding fallback) — the threshold was written for a 2-core box.
  Diagnosis posted to `timer-alert-idc03-ada-bench-casting` (backlog).
- `gemini-wallet-watch.service` is healthy again (Result=success at
  08:47) — attempt-4's watch item was stale.
- Saturday 2026-11-21 05:55 weekly timer fired but produced no journal —
  ExecCondition parked it (no sentinel), confirming the park-by-default
  design.

## Result

Done-condition met and re-verified: `ada-scenario-casting.service` runs
successfully on idc03 (`Result=success`, last completed run exit 0, no
failure logs — scenario-level fails are benchmark findings by design).
The weekly benchmark is now armed for its next scheduled run via the
card-requested sentinel.

## Files changed

- `docs/ssot/jobs/ada/2026-11-24-casting-suite-service-triage.yml` —
  recovered from attempt-4 branch + attempt-5 re-verification addendum.
- `dispatch-outcome-20261124-080626-investigate-and-resolve-the-fa.md` —
  recovered attempt-4 outcome doc (was stranded on the unmerged branch).
- `dispatch-outcome-20261124-090603-investigate-and-resolve-the-fa.md` —
  this file.

## How to verify

```
ssh idc03 systemctl --user show ada-scenario-casting.service -p Result,ExecMainStatus
ssh idc03 journalctl --user -u ada-scenario-casting.service --since "2026-11-23 20:00" | tail -15
ssh idc03 cat ~/.local/share/ada-scenario-runner/prod-allow-casting   # card id until consumed
sha256sum scripts/board/runner-agent.py; ssh idc03 sha256sum ~/.local/bin/runner-agent
```

After Sat 2026-11-28 05:55 (or the next passing 02:00 preflight):
`ssh idc03 journalctl --user -u ada-scenario-casting.service --since today`
should show a full suite run; `prod-allow-casting` will be gone
(consumed).

lessons:
- Dispatch branches can be pushed to origin yet never merge (auto-merge
  fetch-first rejection + worktree sweep) — recover deliverables via
  `git fetch origin <branch>` + `git checkout FETCH_HEAD -- <paths>`.
- `ada-scenario-casting.service` is a USER unit on idc03 — plain
  `systemctl status` says "could not be found"; always `--user`.
- The paid-lane sentinel is one-shot per suite run: every card-requested
  benchmark needs its own `prod-allow-<suite>` file or the weekly timer
  parks silently at ExecCondition (no journal under the unit).
- `preflight-bench.sh` "load < 2" is calibrated for a 2-core box;
  idc03's normal load is 8-13 — the daily bench gate fails on load
  almost every night regardless of embed/provider health.
- mddb embed queue depth + provider circuit state are visible in
  `journalctl --user -u mddb-embed-probe.service` — a Gemini embedding
  outage backs the queue up and pushes fallback load onto ollama.
