---
title: Layered Reporting Standard
description: Memory-system report hierarchy — raw logs/data at L0 up through producer and domain rollups to the L3 system overview
tags: [reports, memory, ssot, standard, operations]
created: "2026-09-26"
updated: "2026-09-26"
category: operations
status: active
related:
  - docs/ssot/infrastructure/ssot.reports.yml
  - scripts/report-system.py
  - scripts/lib/report.py
  - scripts/audit-hosts.py
search_keywords: [layered reporting, system report, SYSTEM-REPORT, meta.yml, timeline, L0 L1 L2 L3, report hierarchy]
---

# Layered Reporting Standard

**Abstract**: The memory system's reporting standard — every report is a
node in a four-layer hierarchy: L0 raw artifacts, L1 per-producer rollups,
L2 per-domain rollups, L3 single system overview (`reports/SYSTEM-REPORT.md`).
Declared in `docs/ssot/infrastructure/ssot.reports.yml`; each layer is
generated from the one below, never hand-written.

## The layers

| Layer | Role | Examples |
| ----- | ---- | -------- |
| L0-raw | Append-only artifacts; never edited | `reports/audit-hosts/<host>-<ts>.yml`, `~/var/chaba/health/*.json`, per-audit stdout |
| L1-producer | Per-generator rollup with `meta.yml` | `audit-hosts/<host>`, `health-monitor`, `report-feed` |
| L2-domain | Cross-producer rollup | `fleet` (planned), `audit-suite`, `overnight-assessment` |
| L3-overview | Single human digest | `system-report` → `reports/SYSTEM-REPORT.md` |

## The contract

- **Registry = intent**: every report node is declared in
  `ssot.reports.yml` `nodes:` with `layer`, `purpose`, `generator`,
  `cadence`, `output`, `meta`, `children`.
- **meta.yml = observed state**: each generator writes its meta at the end
  of a run (`scripts/lib/report.py::write_meta`). Fields: `node`, `layer`,
  `purpose`, `generated_by`, `generated_at`, `status`, `summary`,
  `sources`, `children`, `extra`.
- **Status enum**: `ok`, `delta`, `stale`, `error`, `missing`,
  `untracked`, `remote`, `planned`.
- **Timeline**: `~/var/chaba/reports/timeline.jsonl` — append-only, one
  JSON line per completed generation (`append_timeline`). Outside the repo
  because it grows forever (same as `~/var/chaba/health/`). Override with
  `CHABA_REPORTS_DIR`.
- **Formats**: yml/json/jsonl for machine artifacts; `.md` only for
  generated digests; never hand-edit a digest.

## Using it

```bash
# Render the L3 overview (reads registry + all meta.yml + timeline tail)
python3 scripts/report-system.py          # writes reports/SYSTEM-REPORT.md
python3 scripts/report-system.py --print  # preview to stdout

# A producer emitting its meta + timeline event
python3 scripts/audit-hosts.py --host tony-dell
```

To add a report producer: register the node in `ssot.reports.yml`, call
`write_meta()` + `append_timeline()` from `scripts/lib/report.py` at the
end of the generator, done — the next `report-system.py` run picks it up.

## Why absence is loud

`resolve_node()` reports a registered node as `missing` when neither meta
nor artifacts exist, `stale` when `generated_at` exceeds its `cadence`,
and `untracked` when artifacts exist without meta (legacy producers).
`SYSTEM-REPORT.md` lists all three — a broken pipeline shows up even if it
fails silently.

## Scheduling

`systemd/chaba-system-report.timer` runs `scripts/report-system.py` daily
at 06:45 on tony-dell (defined, not yet installed). Producers run on their
own schedules; the overview renders whatever state exists.
