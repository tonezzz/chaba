# Dispatch outcome — house-timeline orphaned feed repoint (HOM-0918)

## Result: fixed + verified live — card closed

The card's premise was half-wrong. The `kind=events` feed never stalled:
since the `ada-ha-tony` restart on 2026-10-23T13:15 ICT, `MddbClient` ops
routing (`docs/kb/mddb-ops-split.md`) sends **all** `ada-ha-events-*`
writes to **mddb-ops `http://100.123.163.11:11025`** (idc02, no-embed
telemetry store). Newest events doc there: `events-tony-20261027021042131487`
(period_end today 02:10Z) — the recorder on idc03:8002 is subscribed to
the omen HA websocket and healthy. The leader `:11023` collection just
stopped growing (read-only residue, per the split plan). Only the
*reader* — `house-timeline-update.py` — still scanned `:11023`, and its
timer was an ad-hoc tony-dell unit that died with the drain.

## Changes (dispatch branch, committed)

- `scripts/ada/house-timeline-update.py` — events source
  `MDDB_BASE_URL(:11023)` → `MDDB_OPS_URL(:11025)`; docstring, rollup
  footer, qc + `sources` meta updated; v1.1.0 → 1.2.0.
- `docs/ssot/infrastructure/ssot.jobs.yml` — new job `house-timeline`
  (host idc03, systemd, `every: 1h`, persistent, 5m timeout). env pins
  `MDDB_OPS_URL`, `MDDB_CMS_URL`, and `MDDB_BASE_URL→ops` as a
  transitional pin so the pre-merge script build on the idc03 checkout
  also reads the right plane.
- `systemd/generated/idc03/` — re-rendered (`render-jobs.py --host
  idc03`): new `house-timeline.{timer,service}`; also resynced drift
  (`chaba-lessons-audit.*`, `kanban-notify.*` were manifest jobs missing
  from generated/, `chaba-jobs.service` timeout).
- `docs/kb/cms-page-standard.md` §4 — timer host tony-dell→idc03,
  source mddb primary→mddb-ops.
- `ssot.services.yml` / `ssot.apps.ada_ha.yml` — `ada-ha-tony` env_file
  → `~/.config/secrets/tony-ha/backend.env` (the unit's real
  EnvironmentFile) and `HOME_ASSISTANT_URL` dell→omen; michael lane env
  path likewise.
- Trail: `docs/ssot/jobs/cms/2026-10-27-house-timeline-repoint.yml`.

## Live change on idc03

Installed the rendered `house-timeline.{timer,service}` to
`~/.config/systemd/user/`, daemon-reload, `enable --now` — identical to
what `render-jobs.py --install` produces post-merge.

## Verified

- Producer: `house-timeline.service` ran 10:36 ICT — `5 leaves + rollup
  + qc (published; 151 events from 10 docs)` — the old 1.1.0 build on
  the checkout worked via the transitional env pin.
- Surface: `ada-cms-pages` (`:11027`) — `house-timeline` rollup
  `updated 2026-10-27T03:36:09Z` (was frozen 2026-10-13T01:59:26Z); qc +
  leaf pages same stamp; live device table. (`sources` meta text updates
  to `mddb-ops :11025` once the new script reaches the checkout.)

## Board

- Comment with evidence posted; `do:close` → card moved to done.
- Follow-up filed: `ops-event-plane-split-brain-audit` (MEM-0924) —
  `kind=ops-event` docs now land on both planes depending on writer
  (ada-voice→:11025, chaba scripts→:11023); every reader sees a subset.

## How to verify

- `ssh idc03 systemctl --user list-timers house-timeline.timer`
- `curl -X POST http://100.102.134.91:11027/v1/get -d
  '{"collection":"ada-cms-pages","key":"house-timeline","lang":"en"}'`
  → `meta.updated` within the last hour.
- Feed: `curl -X POST http://100.123.163.11:11025/v1/search -d
  '{"collection":"ada-ha-events-tony","filterMeta":{"kind":["events"]},
  "limit":50}'` → newest `events-tony-*` key is current.
