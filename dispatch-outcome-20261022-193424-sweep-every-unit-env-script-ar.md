# Sweep :11023 parked-writer pins — cms-11023-parked-writers (MEM-0594)

## Result

All migrated-collection writers found pinning `:11023` are now repointed —
in the repo (jobs manifest + canonical units + audit scripts) AND on the live
installed units across five hosts. Verified end-to-end: `bench-jev`,
`ops-health`, `flood-alert` docs now land on `:11027`; parked `:11023` copies
are frozen at their last pre-fix write. The dead letterbox still exists —
the 15 parked collections await Tony's deletion approval (board request
raised), and the ada-voice script fixes await a push to `origin/main`
(board request raised).

## What leaked (live proof, 2026-10-22)

- `:11023 ada-cms-pages/bench-jev` — updated 12:00Z (con01 + parked idc03 jev-bench)
- `:11023 ada-cms-pages/ops-health` — updated 12:30Z (idc03 ops-health-report)
- `:11023 ada-cms-pages/flood-report` — updated 11:11Z (idc02 ada-flood-news env pin)
- `:11023 ada-cms-automation/flood-alert` — updated 12:43Z (omen's PARKED copy — the only live writer; dell had no unit installed)
- nest-* stayed frozen since the 10-13 fix — confirming the signature.

## Changes — this repo (dispatch branch, committed)

- `docs/ssot/infrastructure/ssot.jobs.yml`: ada-flood-news env →`:11027`;
  restored lost `flood-alert` job (tony_dell, env `:11027`); jev-bench +
  ada-pi-orch-bench + session-audit + chaba-audit(-full) gained
  `MDDB_CMS_URL=:11027` (mixed producers keep `:11023`); vestigial
  `MDDB_BASE` removed from ssot-optimization-snapshot (no MDDB usage).
- `systemd/`: orch-bench unit env added; chaba-audit* env added;
  ada-flood-news comment fix; obsidian-vault `ADA_MEMORY_MDDB_URL` off the
  retired dell IP → idc03 `:11023`.
- `systemd/generated/` re-rendered; stale orphans deleted
  (idc02 jev-bench, dell session-audit).
- `scripts/audits/`: cms-pages-audit prefers `MDDB_CMS_URL`; mddb-audit
  probes `kb-system@:11027` + `ada-ha-bank-general@:11023`;
  memory-banks-audit unions stats from both planes and routes per-collection
  reads (devin-kb no longer false-flags DRIFT).
- `scripts/test-global-rules-and-mddb.sh`: collection probes →`:11027`
  with post-split names.
- `docs/ssot/jobs/cms/2026-10-22-mddb-11023-parked-writers-sweep.yml`:
  classification, live-apply log, deletion runbook.

## Changes — live hosts (applied this session)

- **tony-omen**: orch-bench unit installed with `MDDB_CMS_URL`; session-audit
  env added + installed script refreshed (Oct-10 copy predated CMS routing);
  disabled parked timers: flood-alert, ada-flood-news, chaba-audit,
  chaba-audit-watchdog.
- **con01**: generated jev-bench.service installed; `tests/bench/jev-bench.py`
  patched (CMS write → `MDDB_CMS_URL`). Verified 12:59Z → `:11027`.
- **idc02**: ada-flood-news (`:11027`), chaba-audit(-full) (env added),
  ssot-optimization-snapshot (env dropped) installed.
- **idc03**: parked `jev-bench.timer` disabled (job lives on con01);
  `ops-health-report.py` patched to route via
  `backend.mddb_client.is_cms_collection`. Verified 12:56Z → `:11027`.
- **tony-dell**: flood-alert service+timer installed + enabled (`:11027`).
  Verified 12:54Z → `:11027`.

## Changes — ada-voice repo

`d438a52` on **tony-dell** checkout (edit point, NOT pushed):
ops-health-report.py, jev-bench.py, orch-bench.py route ada-cms-*/chaba-*/
kb-* writes via `MDDB_CMS_URL` (default `:11027`). Same patch applied as
uncommitted changes on idc03/con01/omen checkouts — stops the leak now;
the push + `deploy-ada.sh` run formalizes it (deploy script snapshots dirty
files to `wip/deploy-snapshot-*`).

## Open asks (board requests on the card)

1. Push ada-voice `d438a52` to origin + optionally run deploy-ada.sh on idc03.
2. Approve deletion of the 15 parked collections on `:11023` (runbook in the
   job doc) — the real fix for future dead-letterbox leaks.

## Residual notes

- Audit-script fixes (chaba repo) reach idc02's checkout only after this
  branch merges; the installed envs are harmless until then (same behavior).
- `generated/tony_dell/` has ~25 stale rendered units from the idc02/idc03
  migrations — pre-existing drift, worth its own card.
- idc02's `ssot-optimization-snapshot` ran with `MDDB_BASE=idc01:11023`
  (dead address) — now env-free; dell has an enabled local copy of the same
  job (ambiguous ownership, left running, not an MDDB leak).

## Verify

```
curl -s -X POST http://100.102.134.91:11027/v1/get -d '{"collection":"ada-cms-pages","key":"ops-health","lang":"en"}' | jq .updatedAt   # advancing
curl -s -X POST http://100.102.134.91:11023/v1/get -d '{"collection":"ada-cms-pages","key":"ops-health","lang":"en"}' | jq .updatedAt   # frozen 12:54Z
```
