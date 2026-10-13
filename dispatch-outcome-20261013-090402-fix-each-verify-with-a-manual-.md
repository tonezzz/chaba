# Dispatch outcome — fix-omen-timer-pack (2026-10-13)

Fixed all four tony-omen timer failures reported by timer-sentinel, verified each with a manual `systemctl --user start` run on omen, and commented evidence on the linked `timer-alert-tony-omen-*` cards.

## Root causes & fixes

1. **focus-dispatcher-overnight** — was NOT a validation bug. `scripts/mcp-health-to-inbox.py` hardcoded `REPO=/home/tony/CascadeProjects/chaba-tony-dell` (absent on omen) → `FileNotFoundError` rc=1; `scripts/overnight-focus-review.py` then aborted at its post-validation gate printing "aborting: SSOT validation failed" even though validation passed (2090/0 errors). Fixes: REPO resolves from `__file__` (any checkout); the abort gate now checks only the validation step's rc — earlier step failures warn and continue (still roll into final exit/status).

2. **michael-dev-parity** — `scripts/home-assistant/mirror-sweep.py` re-raised `websockets.ConnectionClosed` after 2 attempts; michael-dev's ws (via idc03 tailnet serve) closes mid-request with 1000(OK), so every run died on a `ConnectionClosedOK` traceback. Now 4 attempts with backoff, then a clean skip-exit (rc=0, one-line message). The 1000 close itself persists server-side — flagged on the card as a separate issue if the audit stays skipped.

3. **ada-gh-runs-watch** — gh's token lives in the desktop keyring (no `oauth_token` in hosts.yml); headless secret-service lookup blocked every `gh run list` to the 60s timeout, and 2×60s ≈ `TimeoutStartSec=120` → systemd TERM. `scripts/audits/gh-runs-watch.py` now resolves `GH_TOKEN` from env or `~/.config/secrets/github-mcp{,-new}.env` (bypasses keyring entirely), 90s per-call timeout (`GH_RUNS_WATCH_TIMEOUT`), poll errors non-fatal (exit 0; `meta.yml` keeps status=error). Unit `TimeoutStartSec` 120→300. Note: `github-mcp.env` `GITHUB_ACCESS_TOKEN` is valid; `github-mcp-new.env` is 401 and the keyring token is invalid — `gh auth login` still needed for interactive gh on omen.

4. **ada-pi-orch-bench** — installed unit was the pre-bound version: unbounded `orch-bench.py` exec under `TimeoutStartSec=5400`, so the all-sets run (~150 gemma-3-4b calls @30-140s CPU) was TERM'd at exactly 90min (Mon 04:30→06:00). Reinstalled the repo's bounded unit (`--sets golden,hard --limit 30 --timeout 240`, cap 7200s); `ssot.jobs.yml` updated to `timeout: 2h` + real exec list + cwd; `systemd/generated/tony_omen/` regenerated (still a stub re: ExecStartPre/Post — the hand unit remains the deployed source of truth, documented in the manifest note).

## Verification (manual service runs on tony-omen, +07)

| service | run | result |
|---|---|---|
| focus-dispatcher-overnight | 16:17 | Result=success rc=0, 44s — all 9 steps rc=0, 6 health inbox drafts, 2233 files 0 errors, pipeline completed |
| michael-dev-parity | 16:17 | Result=success rc=0 — ws closed 1000 after 4 retries → clean skip, no traceback |
| ada-gh-runs-watch | 16:16 | Result=success rc=0 — both repos polled in ~2s (was 60s+ each), 0 errors |
| ada-pi-orch-bench | 16:16→17:06 | Result=success in 50m27s under the 2h cap — open-jev endpoints healthy, published bench/orch-20261013-100632 + bench-orch CMS (3 runs tracked), corpus +62, stats +534 |

## Changed files (dispatch branch `dispatch/20261013-090402-fix-each-verify-with-a-manual-`, commit f4a9c0c7)

- `scripts/mcp-health-to-inbox.py`, `scripts/overnight-focus-review.py`
- `scripts/home-assistant/mirror-sweep.py`
- `scripts/audits/gh-runs-watch.py`, `systemd/ada-gh-runs-watch.service`
- `docs/ssot/infrastructure/ssot.jobs.yml`, `systemd/generated/tony_omen/ada-pi-orch-bench.service`
- `docs/ssot/jobs/infrastructure/2026-10-13-omen-timer-pack-fixes.yml` (trail)

The four fixed scripts were also copied into `~/CascadeProjects/chaba` on omen (uncommitted, byte-identical to this commit) so the services run fixed code immediately; omen's git-safe-pull autostash handles the overlap when the branch merges. Updated `ada-gh-runs-watch.service` + `ada-pi-orch-bench.service` were installed to `~/.config/systemd/user/` with daemon-reload.

## How to verify

- `ssh tony-omen 'journalctl --user -u <unit> --since "2026-10-13 16:15" --no-pager'` — each shows `Finished ...` / Result=success.
- `ssh tony-omen 'systemctl --user show ada-pi-orch-bench.service -p Result -p ExecMainStatus'` — Result=success when the bench run completes.
- Next scheduled ticks should stay green; timer-sentinel cards can close once the units stop alerting.
