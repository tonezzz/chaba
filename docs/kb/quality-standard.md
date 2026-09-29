---
title: Quality Standard — CI / QA / QC / Audit
description: One taxonomy and registry for every check in the project — lanes, severity model, rule IDs, baseline ratchets, and where results land
tags: [quality, ci, audit, qc, standard, ssot]
created: "2026-09-29"
updated: "2026-09-29"
category: operations
status: active
related:
  - docs/ssot/infrastructure/ssot.quality.yml
  - docs/ssot/infrastructure/ssot.audit.yml
  - docs/ssot/apps/ssot.apps.cms-reports.yml
  - scripts/audits/run.mjs
  - scripts/ada/cms-audit.py
search_keywords: [quality, ci, audit, qc, gate, ratchet, baseline, checks, standards]
---

# Quality Standard — CI / QA / QC / Audit

**Abstract**: Every check in the project belongs to a *lane* with a *gate
severity* and a *cost tier*. The canonical registry is
`docs/ssot/infrastructure/ssot.quality.yml`; scheduled-audit details live
in `ssot.audit.yml`; CMS report QC rules in `ssot.apps.cms-reports.yml`.

## The five lanes

| Lane | Runs where | Blocks? | Cost |
| ---- | ---------- | ------- | ---- |
| `ci-gate` | GitHub Actions — **offline only** (no tailnet), inputs = repo + committed snapshots | yes | `cheap` only |
| `scheduled-audit` | `scripts/audits/run.mjs` on tony-dell timers (weekly / monthly full) | per-audit `severity_on_fail` | network/privileged OK |
| `live-health` | probe timers — mcp-health-snapshot, tony-dell-monitor, watchdog | never | telemetry |
| `benchmark` | manual or scheduled perf/cost runs | never — trend data | up to `llm` |
| `content-qc` | cms-audit + modularity audits — dual lane (CI snapshot + live) | ratchet in CI, warning live | cheap/network |

## Severity model

- **blocking** — fails the pipeline/suite.
- **ratchet** — fails only on *regression vs baseline* (`*-baseline.json`,
  `{id: [rules], _why: {...}}`; entries must be removed when fixed — the
  baseline only shrinks). Canonical impl: `cms-audit.py --baseline`.
- **warning** — reported, never fails.
- **info** — telemetry (benchmarks, durations).

## Conventions

- Exit codes: `0` pass · `1` findings · `2` the check itself errored.
- Rule IDs `<PREFIX><n>` — e.g. cms-audit: A=structure, N=news, R=report
  provenance, C=consolidation, S=schema. Findings must carry their ID so
  baselines name them exactly.
- Result record: `{name, command, ok, severity, duration_ms, exit_code,
  stdout, stderr}` (run.mjs shape); timeline events per ssot.reports.yml.
- **Registration is required** — a check not in `ssot.quality.yml` (or
  `ssot.audit.yml` for scheduled audits) is drift. `standardization-audit`
  section 6 verifies the registry both ways (paths exist, CI steps are
  registered, audits are covered).

## Where results land

| Surface | Producer |
| ------- | -------- |
| GH check status | ci-gate workflows |
| `reports/audits/summary.{json,md}` + `history.json` | scheduled suite |
| `docs/ssot/focus-inbox/audit-failures.yml` | suite failure alerts |
| `ada-cms-pages/cms-audit-report` | `cms-audit.py --publish` (weekly via suite) |
| `~/var/chaba/reports/timeline.jsonl` | report generators |

## Known gaps (coverage_gaps in the SSOT)

- No unit-test lane — `ci.repo-lint` covers syntax only.
- GH workflow failures → focus inbox via `scripts/audits/gh-runs-watch.py` (15-min timer on tony-omen, `gh` authed there; `--git` pushes alert docs) — install `ada-gh-runs-watch.timer` after this branch merges.
- `ada-memory-backup.timer` not installed — CI's CMS snapshot input is
  manually refreshed.
- `ci-pipeline.sh` legacy on-host pipeline — retire-or-register pending.
