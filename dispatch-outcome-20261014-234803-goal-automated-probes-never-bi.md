# bench-off-paid-lanes — repo-side lane policy (dispatch, idc02)

**Result: committed on `dispatch/20261014-234803-…` (1c56115c). Not deployed —
apply step documented below and in `docs/ssot/jobs/ada/2026-10-14-bench-off-paid-lanes.yml`.**

## What changed

- **Scenario targeting** — card item 1's "flag or env" already existed
  (`scenario-benchmark.py --url` / `ADA_LIVE_URL`); no runner change needed.
  Verified in the ada-voice staging checkout on idc02.
- **Weekly suites** (`stacks/services/ada-scenario-runner/`):
  - `research` (Mon) / `cms` (Tue) / `reports` (Thu) → retargeted to
    `ws://127.0.0.1:8005/ws` + `ada-dev.env` + `ada-ha-dev-keys.json` +
    provider-gate `ExecCondition --unit ada-dev`. Suite membership checked
    against `tests/benchmark.yml` — these only need research/CMS/report
    tools that the dev lane still exposes.
  - `memory` (Wed) / `tools` (Fri) / `casting` (Sat + daily 02:00 chain) —
    lane-coupled (person banks, HA/VCAST actuation). Still pointed at
    :8002 but now `ExecCondition`-gated on a one-shot sentinel
    `~/.local/share/ada-scenario-runner/prod-allow-<suite>` (first line =
    card id). No sentinel → parked, zero sessions.
  - `ada-scenario-full.container` — same card-request gate
    (`prod-allow-full`, consumed by a second ExecCondition).
- **Gate** (`scripts/ada/scenario-provider-gate.py`): new
  `--paid-allow-file` + `--paid-allow-max-age` (default 168h) — a fresh
  sentinel downgrades the paid-lane/unknown verdict to ok; quota-dead
  still gates. `--tier` now parameterizes the summary doc key
  (`report/<tier>-gate-<ts>`), per-scenario skip docs (yaml `tier:`
  match — benchmark suites write only the summary), and event text.
- **Wrapper** (`scenario-suite-run.sh`): paid-lane guard — target port
  not in {8005,8009} parks the run (exit 0, journal trail) or consumes
  the sentinel for exactly one authorized prod run.
- **Canaries** (`stacks/services/ada-live-canary/`, NEW): free hourly
  :17 (existing behavior, now repo-tracked), `ada-live-canary-paid`
  **daily 06:12** = the 1 connect/day paid-lane canary (item 3), and
  `gemini-wallet-watch` units (hourly :47 ~1-token REST + LINE alerts —
  kept hourly; it is not a Live connect and costs ~$0.000007/day; one
  line flips it to daily if it should count as "the" paid canary).
- **Acceptance metric** (`scripts/ada/spend-ledger.py`): journal now
  parses `caller=` per session + per-session turns; the spend-ledger
  page shows `admin%` per paid lane and warns (once/day/unit) when
  caller=admin share > `SPEND_ADMIN_WARN_PCT` (default 20) — item 4 is
  self-checking.
- **SSOT**: `ssot.audit.hosts.yml` timer notes updated (incl. new
  `ada-live-canary-paid.timer` entry); README lane-policy section.

## Verified

- `py_compile` both scripts; `bash -n` wrapper + install; 
  `systemd-analyze verify` clean (only missing-host-path warnings).
- Guard exercised live on idc02: paid target w/o sentinel → parked,
  exit 0; with sentinel → authorized, sentinel consumed; :8005/unset
  behave correctly.
- Gate `--paid-allow-file` exercised: sentinel present → "paid lane
  authorized by card <id>"; absent → unchanged verdicts.

## Apply on idc03 (not done — dispatch is worktree-only)

```bash
cd ~/CascadeProjects/chaba && git pull --ff-only   # after merge
stacks/services/ada-scenario-runner/install.sh
stacks/services/ada-live-canary/install.sh
systemctl --user start ada-scenario-tools   # expect "start condition failed" = parked
```

## Known gaps / flagged

- `scenario-report.py` honors per-scenario `url:` overrides — a yaml
  hardcoding a paid ws URL bypasses `ADA_LIVE_URL`. Only
  `michael_infra_interrogation.yaml` carries one today (:8003, in no
  scheduled suite). Runner-side refuse-on-paid needs an ada-voice
  change via tony-dell — noted on the card.
- `preflight-bench.sh` (ada-bench-casting) not audited — if it opens
  Live sessions on prod it needs the same treatment; check on apply.
- First dev-lane runs of research/cms/reports may expose per-scenario
  gaps (missing `key_name` in ada-ha-dev-keys.json, excluded tools);
  fix those scenarios, don't point suites back at prod.
- `ada-embed-bench` rides LITELLM_KEY_MDDB (gateway, $10/30d cap) —
  bounded, left as-is.
