# mddb follower migration: tony-dell → idc02

2026-09-30 — plan + benchmark for moving the read-only replica off the
contended HDD desktop onto the new offload VPS.

## Why migrate

| | tony-dell (current) | idc02 (target) |
|---|---|---|
| Disk | 465 GB HDD, contended (r_await ~90 ms) | VPS SSD-backed, idle |
| RAM | 15 GiB shared w/ desktop | 15 GiB, nearly free |
| Cold-open of clean 1.54 GB DB | **~3.5 h** (measured today) | **5–16 s** (measured today) |
| Role | desktop/workstation | dedicated offload |

The `NoFreelistSync` open-time rescan is the killer on dell — every
restart is a multi-hour IO-bound B-tree walk. On idc02 the same file
opened in **16 s warm / 5 s after `drop_caches`** (benchmark:
`tradik/mddb:2.15.3`, throwaway container `mddb-bench`, now removed).

## Migration procedure (standard backup-seed path)

1. **Stage idc02**: copy `~/.config/containers/systemd/mddb.container`
   from dell; set `node_id`/`followerID` to `idc02`, bind tailnet
   `100.123.163.11:11023/11024`; copy the `MDDB_REPLICATION_SECRET`
   podman secret out-of-band (never via repo).
2. **Seed**: `POST /v1/backup` on the leader (now clean — backup works
   again post-rebuild) → scp file to idc02 → `podman unshare chown
   1000:1000` inside the mount.
3. **Start + verify**: `systemctl --user start mddb` on idc02 — expect
   bind in seconds, `Replication connected` in logs, counts converging.
   Dell follower keeps running meanwhile (two followers can coexist —
   followerID differs).
4. **Repoint the one consumer**: Caddy `/api/mddb/*` upstream
   `100.68.142.13:11023` → `100.123.163.11:11023`. All other clients
   hit the leader directly — nothing else to move.
5. **Cutover + standby**: after a soak period, stop dell's unit and
   keep it stopped-but-seeded as the emergency standby (dell stays in
   the SSOT as `role: standby`).
6. **SSOT**: update `ssot.services.yml` follower block (host, IP, note),
   `ssot.audit.hosts.yml` (move `mddb.service` expectation tony-dell →
   idc02 — idc02 entry already exists), `ssot.host-roles.yml`.

## Risks / watch-outs

- **Replication gap today**: the dell follower is still replaying the
  reindex backlog; a fresh idc02 seed inherits whatever LSN the backup
  carries and catches up by streaming — verify with a doc-count compare
  before cutover.
- **Secrets**: replication secret copy is the only manual step; use
  `podman secret` on idc02, don't paste it anywhere.
- **idc02 capacity**: 15 GiB RAM is plenty for a 1.5 GB DB; disk 290 GB.
- **Rollback**: leave dell's follower intact until idc02 soaks clean.

## CMS pages audit — where old reports stand

`scripts/ada/cms-audit.py` live run (127 pages): **107 pass · 20 fail ·
47 warnings**.

Failure clusters (fix the generator once → many pages comply):

- **8 `*-digest` pages** — `R1:no-sources` + `R2:no-provenance-footer` +
  `A2:kind!=page`. The digest writer doesn't emit the report standard's
  meta/footer. One fix in the generator clears ~40% of failures.
- **6 pages missing `kind=page` meta** (ada-decision-flow, bench-orch,
  chaba-compound-ai-system, multi-model-orchestration, ops-health,
  vps-secperf-baseline) — mechanical `cms-normalize-meta.py` pass.
- **`chaba-edge-plan` — A6 secret-ish** — inspect before anything else;
  a possible secret pattern in page content.
- **Thin/scratch**: `bench-ping`, `devin-job-report-fail` (empty),
  `document-audit-policy`, `transcript-audit-2026-09-28` (placeholders).
- **`camera-sources-2026-09-30`** — created today with zero meta.
- **34 S1 schema warnings** (missing memory-schema fields — mostly
  `wall-*` pages), **5 C1 duplicate pairs** (my-words~my-words-kk,
  transcript-audit pair, wall-vms-* overlaps) — consolidation candidates.
