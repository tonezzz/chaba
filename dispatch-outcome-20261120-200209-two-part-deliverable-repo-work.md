# Dispatch outcome — fleet-jobs-report-and-ada-verb (20261120-200209)

## What changed

Branch `dispatch/20261120-200209-two-part-deliverable-repo-work`, 3 commits:

- `1f6263fe30c` — cherry-pick of the preserved fix branch `2c9fa451b5f`
  (prior session's work: paginated /cards projection, per-host+lane claim
  stats, lane-savings consumption, CMS publish via /report, first tests).
  Applied clean — master had not touched those files since its base.
- `73be00a28ff` — repointed the aggregator at its real sources and wrote
  the Ada verb contract.
- `a650c11031a` — re-rendered `systemd/generated/idc03/` units.

### Aggregator (`scripts/fleet-jobs-report.py`)

Two sources were wired to the wrong data; fixed:

- **Timer states** — was reading `~/var/chaba/reports/timeline.jsonl`
  (the *reports* timeline — different schema, `host`/`status=failing`
  keys never match, dead code). Now reads the **timer-timeline CMS
  rollup** (`POST {MDDB}/get ada-cms-pages/timer-timeline`, refreshed
  every 15 min by `timer-timeline-update.py` and reachable from any
  host), parses the rendered table (🟢/🟡/🔴/⬛/⚠️ unreachable),
  falls back to the collector's local
  `~/.local/share/chaba/timer-timeline/state.json`, and flags staleness
  (>2h) in the Sources section.
- **Runner fleet health** — was globbing `~/var/chaba/health/*.json`,
  which holds unrelated producer snapshots (mcp-health, nest-queue,
  staleness, mddb state) and minted bogus "host" sections. Now reads
  `GET {BOARD_API}/queue` — real per-host heartbeats (age/stale/active
  units), claimable cards with per-host eligible/blocked verdicts,
  in-flight claims, human-waiting count.
- **Hostname join fix** — `jobs.tony_dell.yml` (inventory form) now
  normalizes to `tony-dell` so declared timers join queue/card/timer
  hosts instead of splitting into phantom hosts.

Report sections: fleet claim totals, live queue (heartbeat table +
claimable list with verdicts), per-host detail (heartbeat, observed
timer states, declared job count, claims, attention timers, blocked
verdicts), lane tables, LiteLLM 24h spend, and a Sources status table
(makes absence loud). CMS publish meta now carries `title` so the page
lists correctly.

### Job registration (`docs/ssot/infrastructure/ssot.jobs.yml`)

`fleet-jobs-report` entry already existed (idc03, every 4h); added
`env` (BOARD_API, MDDB_BASE_URL), `timeout: 10m`, `persistent: true`,
and a fuller note. `systemd/generated/idc03/` re-rendered — which also
materialized `ada-morning-brief` + `mcp-fleet-report` units that were
declared but never rendered (pre-existing drift the `GeneratedTree`
test enforces; included in the second commit).

### Ada read path (`docs/kb/ada-report-verb-contract.md`)

Rewrote the 13-line stub into the full verb contract: artifact order
(CMS `fleet-jobs-report` page canonical → repo `reports/*.md` fallback),
freshness gate (stale → "as of <updated>", missing → say so), MUST-NEVER
list (no aggregator, no /cards scan, no psql/ssh/systemctl on a voice
turn), failure semantics table, and pointer to the ada-voice wiring card.

### Follow-up card

`ada-voice-fleet-jobs-verb` (ADA-0041) created in backlog via board-api
/card — ada-voice tool wiring, manual repo: ada-voice.

## Verified

- `pytest tests/test_fleet_jobs_report.py` — 9/9 (incl. new rollup
  parser, host-normalization, all-sources-down render tests)
- `pytest tests/ops/test_render_jobs.py tests/test_render_jobs_catalog.py`
  — 37/37 total; GeneratedTree now matches manifest
- `ssot-validate-all.mjs` on ssot.jobs.yml — valid (pre-existing bloat
  warning only)
- **Live run** (`BOARD_API=https://idc03.taila0626a.ts.net:10000`):
  rendered `reports/fleet-jobs-20261120.md` from real sources — 11
  hosts, queue 11 claimable / 7 in-flight, real failing-timer attention
  lists — and upserted the `fleet-jobs-report` ada-cms-pages doc
  (verified via MDDB `/v1/get`: contentMd + title + summary + fresh_for
  all present). `reports/meta.fleet-jobs-report.yml` status: ok.
- Spend section renders correctly empty on tony-dell; `litellm-db`
  podman sidecar lives on idc03 where the job is registered, so the
  section populates there.

## Not done / next steps

- Branch not pushed (dispatch rules); merge via the normal sweep.
- Timer install is still declare-only per convention: after merge, run
  `render-jobs.py --host idc03 --install` on idc03 to arm the 4h timer.
- `docs/ssot/ssot.dev-system.assessment.yml` shows tooling-regenerated
  churn from the pre-commit gate — left uncommitted, unrelated.

## How to verify

```
python3 -m pytest tests/test_fleet_jobs_report.py -q
BOARD_API=https://idc03.taila0626a.ts.net:10000 python3 scripts/fleet-jobs-report.py
head -60 reports/fleet-jobs-*.md
curl -s -X POST http://100.102.134.91:11027/v1/get -H 'Content-Type: application/json' \
  -d '{"collection":"ada-cms-pages","key":"fleet-jobs-report","lang":"en"}'
```

lessons:
- `~/var/chaba/reports/timeline.jsonl` is the *reports* timeline (ok/delta/status vocab, no `host` key) — the *timer* census lives in the `timer-timeline` CMS rollup + `~/.local/share/chaba/timer-timeline/state.json` on the collector host (tony-omen)
- `~/var/chaba/health/*.json` holds unrelated producer snapshots; globbing it as "per-host health" invents bogus hosts — runner fleet health is board-api `/queue` hosts (heartbeats/verdicts/active units)
- `jobs.<host>.yml` generated files use inventory names (tony_dell); queue/cards/timer-timeline use tailscale names (tony-dell) — normalize before joining
- editing `ssot.jobs.yml` requires re-running `scripts/render-jobs.py --host <h>` — `tests/ops/test_render_jobs.py::GeneratedTree` fails on stale/missing units (it also caught two never-rendered declared jobs)
- board-api `/report` create upserts the ada-cms-pages doc by slug but only copies `meta` into page meta — pass `title` inside `meta` or the CMS page lists untitled
