# dispatch-outcome — scenario-spend-guard

**Stop scenario smoke burning paid quota — provider-health gate + spend ledger**

Result: **done in repo, verified live on idc03, pending deploy** (chaba pull +
`install.sh` on idc03). Committed on branch
`dispatch/20261011-210959-stop-scenario-smoke-burning-pa` (afeafaba). Not pushed.

## Root cause found

Quota-dead smoke hours never tripped the suite's existing outage sentinel: the
quota 1011/`RESOURCE_EXHAUSTED` close happens server-side on the persistent
upstream Live session, so `scenario-report.py` saw plain `fail` for every case —
2026-10-11 03:00 ran all 34 scenarios × 2 retries (~64 upstream connects) while
completely dunned. The ledger proved the bigger bill: **~$117–162/day est,
500–620 Live sessions/day for 15 days straight**, plus real churn (2026-10-10
ada-ha-tony: 759 ws client connects + 534 upstream reconnects).

Also confirmed: Live sessions already run the **FREE** lane key — the gate now
sha-asserts that stays true (`GEMINI_API_KEY` sha == `GEMINI_API_KEY_FREE` sha
from `gemini-keys.env`) and refuses if the lane ever flips to PAID.

## What shipped

- `scripts/ada/scenario-provider-gate.py` — `ExecCondition` on
  `ada-scenario-smoke.service`. Zero-spend probe (env + journal only, no API):
  unit down → infra skip; PAID key while a FREE lane exists → refuse; quota/dunning
  signature in the last 70 min without a newer healthy marker
  (`provider reconnected` / `usage turn`) → quota-dead skip. A gated run records
  `report/<scenario>-<ts>` status=`skip-quota`|`infra` docs for every smoke
  scenario + a `report/smoke-gate-<ts>` summary (lab-results page stays honest)
  + a throttled chaba-event. Same fire counts reconnect churn — >50 ws
  `client connected`/hour on an `ada-ha-*` unit → throttled warn to chaba-events.
  Fail-closed on internal error; the unit's ExecCondition is wrapped fail-open
  only for the case where the script file is missing (stale chaba checkout).
- `scripts/ada/spend-ledger.py` + `stacks/services/ada-scenario-runner/
  ada-spend-ledger.{service,timer}` (daily 23:50 idc03) + best-effort
  `ExecStopPost` on the smoke unit — reads `usage.jsonl` → per-day Live
  sessions / turns / aux calls / tokens / est $ (same rates as usage_tracker) +
  per-unit journald churn columns → publishes `ada-cms-pages/spend-ledger`
  (kind=report, domain=ops → ops-digest membership), `report/spend-<date>`
  snapshot, `~/.local/share/ada-review/spend-ledger.jsonl`. Tripwires:
  >$2/day or >300 sessions/day → chaba-event warn.
- `install.sh` gains an `ada-spend-ledger` unit + doc; README documents both;
  `ssot.automation.yml` registers the jobs; decision trail in
  `docs/ssot/jobs/ada/2026-10-11-scenario-spend-guard.yml`.

## Verified

- Gate dry-run on idc03: unit active, live key sha-matches FREE lane, correct
  verdict; quota-dead path verified against the real 03:00 journal signature;
  bare-429 regex false-positive on timestamp millis (`,429`) found and fixed.
- Gate `--report` wrote `smoke-gate-*` docs to the ops MDDB (:11025) — confirmed
  by list/search; probe docs deleted afterward.
- Ledger live-run on idc03 published the real 15-day page; `report/spend-2026-10-11`
  snapshot and `spend-usd` tripwire event emitted. `v1//add` double-slash 307
  bug fixed.
- YAML validates, `py_compile`/`bash -n` clean.

## Deploy steps (idc03)

```
cd ~/CascadeProjects/chaba && git pull --ff-only   # after branch merges
~/CascadeProjects/chaba/stacks/services/ada-scenario-runner/install.sh
systemctl --user start ada-scenario-smoke          # journal should show the gate line
```

Gate printout goes to the service journal: `scenario-provider-gate: ok — …` →
run proceeds; a skip is a plain ExecCondition failure + report docs.

## Residual ada-pi work (noted in the SSOT doc, out of this repo's scope)

- `scenario-report.py` sentinel still can't classify mid-run dunning
  (`provider connect failed` / ready-timeout) as infra/quota — the gate covers
  pre-run only.
- `ops-health-report.py` could surface a one-line spend summary from
  `spend-ledger.jsonl` on the 15-min ops-health page.
- Live provider key selection is `realtime_provider.py` `GEMINI_API_KEY` direct
  (bypasses `gemini_pool.py` rotation) — why FREE lane is guaranteed, but any
  future lane flip changes that.
