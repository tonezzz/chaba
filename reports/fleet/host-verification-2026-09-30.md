# Host verification — 2026-09-30 (~17:15 +07)

Manual end-to-end verification of all tailnet hosts after the omen
sluggishness investigation and the mddb corruption repair. Supersedes
the 06:46 fleet audit delta readings (omen load 98.69 pre-fix).

## Host status

| Host | Uptime | Load (1/5/15) | RAM used | Swap | Disk | Verdict |
|---|---|---|---|---|---|---|
| tony-dell | 9d 6h | 8.5 / 12.7 / 12.1 | 10/14 GiB | 11/15 GiB | 82% | loaded — mddb rescan + desktop |
| tony-omen | 2d 21h | 6.5 / 6.6 / 6.1 | 22/30 GiB | 25/71 GiB | 38% | recovered — was 17.5 earlier |
| idc01 | 2d 20h | 0.30 / 0.28 / 0.27 | 3/31 GiB | 0/5 GiB | 75% | healthy |
| mn01 | 1d 8h | 0.78 / 1.4 / 1.65 | 3/7 GiB | — | 20% | healthy |
| idc02 | 6h | 0.00 / 0.01 / 0.15 | 1/15 GiB | — | 5% | healthy — new offload host |
| kk-macbook | — | — | — | — | — | offline 16d (travel laptop, expected) |

## Service checks

**idc01** — mddb leader: `/health` = `{"status":"healthy","mode":"wr"}`;
vector reindex in progress 2902/17840 (16%); gemini-ollama-proxy
healthy; all containers up.

**tony-dell** — mddb follower: clean 1.54 GB seed in place; currently in
the normal `NoFreelistSync` open-time B-tree rescan — single-threaded,
IO-bound on cold page cache against a contended HDD (~90 ms r_await).
No listener yet; RSS cycling = progressing. NOT corruption — the 15:51
crash was a manual SIGQUIT from a parallel debugging session; two
manual restarts reset the scan to zero each time. YOLO/weaviate/
postgres/redis all up; desktop portal units failed (cosmetic, pre-existing).

**tony-omen** — openjev :8777 up on tailnet IP (CPUQuota 250% holding);
verdict-shim :8778 healthy; `cast-desktop@0` stopped (was ~31% CPU of
pure waste — no :8082 server ever existed; restarts on demand via the
cast switcher). Remaining load: Devin Desktop session + Chrome.
Swap 25 GiB is residual pressure draining slowly.

**mn01** — yolo-xiaomi + yolo-ipad-1/2 active (bind tailnet :8780,
`/detect` serves live detections — verified through Caddy
`/apps/yolo/api/*` earlier); weaviate-embedding :5000 active;
xmeye-vms-vnc up; websockify-vms-mn01 inactive (standby, normal).

**idc02** — new offload VPS (45.136.236.190, tailnet-only services).
Running: `open-jev` on tailnet :8777 (healthy, second instance —
open-jev now runs on both omen and idc02); `vcast-real@6` and
`vcast-real@7` headless Chromium+Playwright displays (active, ~186%
CPU while rendering). sshd reachable via tailnet; key provisioned
2026-09-30 and `idc02`/`idc01` entries added to `~/.ssh/config`.

**kk-macbook** — tailscale last seen 16 days ago; offline expected.

## Actions today

- `cast-desktop@0` stopped on omen — ~31% CPU reclaimed; on-demand cast
  path unaffected (script restarts it per-cast)
- mddb leader rebuilt from logical export (corrupt bbolt freelist);
  follower seeded from clean copy; upstream bug: tradik/mddb#270
- SSOT runbook updated (`corruption_repair_20260930` + rescan notes)

## Watch items

- mddb follower rescan ETA: tens of minutes on cold cache; do NOT
  restart the unit mid-scan (resets to zero). A detached watcher logs
  the bind event to `/tmp/mddb-watch.log` on dell.
- Leader vector reindex completes over the next hours; then follower
  vector warmup (~45 min documented cold-start) after its DB opens.
- tony-dell disk at 82% — forensic mddb.db.* copies (~7 GB) retained;
  can prune after follower verified stable.
- omen swap 25 GiB — will drain as the working set settles; reboot only
  if it stays elevated.
