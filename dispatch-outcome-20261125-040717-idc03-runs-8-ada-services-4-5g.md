# Dispatch outcome — idc03-structural-capacity-15gb-4core-per-2d787f (attempt 2)

## What this attempt did

Attempt 1 (dispatch/20261125-090408, ran on idc02) completed all the
infra work — twin migration finished, board-api capped, idc03
MemAvailable 4.4Gi -> 6.9Gi — but its branch conflicted with
origin/master in `scripts/ada/scenario-provider-gate.py`, so the
auto-merge aborted and Tony answered the merge-conflict request with
"resolve — let devin resolve the conflict and land it".

This attempt (mn01) resolved the conflict and re-verified live state:

- Merged `origin/master` (110bf75a0d) into this session branch, then
  merged `origin/dispatch/20261125-090408-idc03-runs-8-ada-services-4-5g`
  on top — commit `53d9ef90db`. The old dispatch tip is now an
  ancestor of this branch, so close-out auto-merge lands everything
  cleanly (branch already contains master HEAD).
- Conflict 1 (both sides appended functions after `check_unit_active`):
  kept BOTH — master's `service_port()` + `check_live_probe()`
  (zombie-backend detection, card provider-gate-zombie-backend-blind)
  and the branch's `check_remote_alive()` (`--live-url` remote mode).
- Conflict 2 (infra verdict wording): kept the branch's remote-aware
  `what = provider <unit> @ <live_url>` form AND master's
  `elif live == "infra"` zombie verdict.
- Semantic fix the textual merge could not express: master's
  live_probe block auto-merged to run whenever `active` — including
  remote mode, where `active` reflects the REMOTE reachability probe
  while `args.unit` (ada-dev) is intentionally STOPPED on idc03. That
  combination would have gated every remote run 'infra' (loopback
  probe to a dead local port). Resolved: remote mode sets
  `live = "skip"` — `provider_alive` is the liveness check. Local mode
  is unchanged.
- Docstring: added a Remote mode paragraph so the two-mode contract is
  discoverable.

## Verification

- `python3 -m py_compile` clean on scenario-provider-gate.py and
  board-api.py.
- `python3 -m unittest tests.ada.test_scenario_provider_gate` — 9/9 OK
  (covers service_port, live_probe ok/infra/skip, verdict chain).
- `check_remote_alive` exercised live from mn01: omen ada-dev
  `http://100.75.102.88:8005` answers (http + ws-normalized), dead port
  refuses — remote path works.
- idc03 live state (ssh, this session): MemAvailable 5019MB (~4.9Gi,
  done-condition >=4GB holds; was 6.9Gi at attempt-1 finish — normal
  churn + pre-cache-fix board-api regrowth), ada-dev + ada-kk-dev
  `inactive` (migration holding), board-api MemoryCurrent 902MB under
  MemoryHigh=1.6G/MemoryMax=2.2G drop-in.
- board-api.py cards.json payload-cache merged cleanly (no conflict).

## Files in this merge (from attempt-1 branch, now landing)

- `scripts/ada/scenario-provider-gate.py` — `--live-url` remote mode +
  master's live_probe, combined per above.
- `scripts/board/board-api.py` — `_cards_json_payload()` cache by
  (mtime_ns,size); kills the ~14MB re-parse per /cards call that drove
  the RSS ratchet.
- `docs/ssot/jobs/infrastructure/2026-11-25-idc03-capacity-twin-migration-boardapi-cap.yml`
  — full attempt-1 runbook (pre-state, steps, verification, gotchas,
  open items incl. the deploy-ada.sh SERVICES patch recommendation).
- `dispatch-outcome-20261125-090408-...md` — attempt-1 outcome.

## Post-merge follow-ups (already on the card / jobs yml)

- board-api cache fix activates when idc03's served/exec checkout
  pulls master and the service restarts (MemoryMax cap covers the gap).
- Optionally repoint the 4 scenario ExecConditions from the runner-dir
  patched copy back to the repo path once pulled.
- deploy-ada.sh SERVICES default still lists the twins (ada-voice
  repo) — recommended one-line patch is in the jobs yml open_items.
- Resize decision: documented NOT NEEDED (non-spend options recovered
  the headroom).

lessons:
- Textual merge auto-resolution can produce semantically wrong code: master's live_probe ran in remote mode against an intentionally-stopped local unit — would have gated every remote suite 'infra'. After resolving adjacent-feature conflicts, trace the merged control flow, don't just clear markers.
- When two dispatch branches exist for one card, merging the OLD branch into the NEW session branch makes the old tip an ancestor — the close-out auto-merge then lands both at once and merge-sweep sees nothing stranded.
- `git fetch origin <branch>` then `git fetch origin master` overwrites FETCH_HEAD — fetch dispatch branches into named refs.
- mn01 has tailnet reachability to omen's ada-dev (:8005) — remote-mode gate probes are testable from any tailnet host, not just the service host.
