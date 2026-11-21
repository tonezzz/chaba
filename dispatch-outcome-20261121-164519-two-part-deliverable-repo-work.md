# Dispatch outcome — two-part deliverable repo work (fleet-jobs-report-and-ada-verb)

## Result: done (repo work complete; one deploy step pending approval)

### What I found

The card was ~80% landed already. On master: `scripts/fleet-jobs-report.py`
(224-line buggy version), a 13-line stub `docs/kb/ada-report-verb-contract.md`,
the `fleet-jobs-report` entry in `ssot.jobs.yml` (idc03, every:4h), the L2 node
in `ssot.reports.yml`, and generated systemd units. Tony's corrected 352-line
script + tests lived unmerged on `origin/fix/fleet-jobs-report-accuracy`
(2c9fa451b5). A 2026-11-20 dispatch had gone further (MDDB timer-timeline +
`/queue` rewiring) but died to the devin-dispatch `${PIPESTATUS}` bug before
pushing — its work was lost, only the card comm described it.

### What changed (2 commits on this dispatch branch)

1. `910214e212` — cherry-pick of Tony's `2c9fa451b5` (clean): board-api `/cards`
   projection for claim stats, lane rendering, CMS publish via `/report`, tests.
2. `075a8d28ae` — source rewiring + contract doc:
   - **Timer source**: was `~/var/chaba/reports/timeline.jsonl` (report-event
     timeline — `host`/`status=failing` never match, always empty). Now parses
     the MDDB `ada-cms-pages/timer-timeline` rollup (per-host
     ok/late/failing/off, unreachable rows, Attention-section dedupe).
   - **Runner fleet health**: was `~/var/chaba/health/*.json` glob (ssh-canary
     logs etc. — invented bogus hosts). Now board-api `GET /queue`: heartbeat
     ages, stale flags, active units, claimable/claimed/human-waiting counts.
   - Hostname normalization `tony_dell` → `tony-dell` so declared
     `jobs.tony_dell.yml` joins runtime sources.
   - Per-source graceful degrade → `meta.extra.source_errors`; meta `status`
     = `delta` when real findings exist (33 failing timers today).
   - `docs/kb/ada-report-verb-contract.md` expanded from stub to the full
     contract: trigger intents, MDDB `get ada-cms-pages/fleet-jobs-report`
     read path, 4h freshness gate (fresh/stale-as-of/missing), the
     NEVER-live-compute list, producer contract — spec for follow-up card
     `ada-voice-fleet-jobs-verb` (already on the board).
   - `ssot.jobs.yml` note enriched: sources, CMS publish, install hint.

### Verified

- `pytest tests/test_fleet_jobs_report.py` — 9 passed (new: rollup parser,
  unreachable rows, attention dedupe, host norm).
- Live run from tony-omen (`BOARD_API=https://idc03…:10000`): exit 0, rendered
  `reports/fleet-jobs-20261121.md` — 11 hosts, 298 timers (33 failing),
  queue/claims/lanes sections all populated; LiteLLM spend 0 rows (no
  litellm-db podman on omen — populated when it runs on idc03).
- CMS page `fleet-jobs-report` confirmed live in `ada-cms-pages` via MDDB get —
  `fresh_for: 4h`, `layer: L2-domain`, full contentMd. This is the rendered
  page the done-condition asks for and the artifact Ada's verb reads.

### Done-condition mapping

- ✅ One rendered page shows per-host timers/claims/lanes/spend (CMS page +
  `reports/fleet-jobs-20261121.md`; reports/* is gitignored — the CMS page is
  the durable surface)
- ✅ Job registered (`ssot.jobs.yml` fleet-jobs-report idc03 every:4h
  deterministic + generated units + `ssot.reports.yml` L2 node)
- ✅ Ada verb contract written (`docs/kb/ada-report-verb-contract.md`)

### Pending (deploy — needs approval, out of dispatch scope)

- `python3 scripts/render-jobs.py --host idc03 --install` to install
  `fleet-jobs-report.timer` on idc03. The first run also clears the
  `report-watch: fleet-jobs-report = missing` focus-inbox entries that have
  been filing every ~30 min since 2026-11-12.

lessons:
- Cherry-pick `origin/fix/fleet-jobs-report-accuracy` before editing — Tony's correctness fix (board-api projection, CMS publish, tests) was never merged; master still had the buggy 224-line script.
- `~/var/chaba/reports/timeline.jsonl` is the report-event timeline (node/layer/status schema) — NOT the timer-timeline collection; timer state lives in the MDDB `ada-cms-pages/timer-timeline` rollup doc.
- `~/var/chaba/health/*.json` is unrelated producer snapshots (ssh-canary logs); runner fleet health = board-api `/queue` heartbeats.
- Generated `jobs.tony_dell.yml` uses ssot host ids with underscores — normalize `_`→`-` to join canonical hostnames.
- timer-timeline rollup repeats bad rows under `## Attention` — stop parsing at the first non-table line or counts double.
