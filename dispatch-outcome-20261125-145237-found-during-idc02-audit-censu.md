# Dispatch outcome — mn01-yolo-xiaomi-service-stopped-deliber-d2b384 (2026-11-25)

## Verdict

**Restarted.** The 02:38 UTC stop was crisis triage during the mn-ha-dev
crash-loop, not a retirement decision. `systemctl --user start
yolo-xiaomi.service` on mn01 → active+enabled, verified by surface.

## Evidence

- `systemctl show`: `Result=success`, `ExecMainStatus=15` → clean
  `systemctl --user stop` (SIGTERM), not a crash or OOM kill. Unit stayed
  `enabled` — nobody intended it off.
- Timing: stop at 02:38:22 UTC sat inside mn-ha-dev's crash-loop
  (restart counter 26→40 between ~01:37–05:43 UTC; HA Core clean-exited
  every ~2–7 min on mn01's 7.3 GB RAM / **no swap** box). mn-ha-dev has
  been stable since 05:43 UTC.
- Consumers are live and published: `/apps/yolo/` page +
  `/apps/yolo/api/*` proxy → `100.106.196.22:8780` (ssot.routes.yml
  `yolo-api`); server.py serves `/detect /image /pointer /set-source
  /tvs /cast`; gesture `screen.html` CAST TO TV and ada-chat-card's 🧍
  YOLO button both ride it. This is NOT the omen copy retired today —
  omen's yolo-xiaomi was superseded by yolo-detect owning HA's
  127.0.0.1:8780; mn01's instance is the apps/vision+cast backend.
  HA's person_count polling already moved to omen yolo-detect
  (2026-10-17), so mn01's role is the apps API, not HA rest sensors.

## Verification (by surface)

- `systemctl --user is-active/is-enabled` → active/enabled;
  journal: "Serving YOLO xiaomi_c201 results on
  http://100.106.196.22:8780" 07:58:10 UTC.
- `curl https://tony-dell.taila0626a.ts.net/apps/yolo/` → 200;
  `/apps/yolo/api/detect` → live JSON; `/apps/yolo/api/tvs` →
  `{ok, tvs:[media_player.tony_tv, media_player.tony_tv_cast]}` —
  HA cast backend works end-to-end.
- `https://idc02.taila0626a.ts.net/apps/yolo/` → 200 + api live
  (heals the ada-chat-card YOLO button path).
- `/detect` still returns `imdecode empty-buffer` — the KNOWN
  xiaomi_c201 camera outage (go2rtc-7-camera-producers card), not a
  service fault.

## Deliverables

- Live: yolo-xiaomi.service restarted on mn01 (no repo change needed —
  ssot.audit.hosts.yml already declares it `expected_state: active`).
- Trail: `docs/ssot/jobs/infrastructure/2026-11-25-mn01-yolo-xiaomi-restart.yml`
- New card filed: **AUD-1399** `mn-ha-dev-crash-looped-40x-on-mn01-2026-986f32`
  — mn-ha-dev clean-exit restart loop (~40x, 01:37–05:43 UTC), root cause
  unknown, self-resolved; needs investigation + possibly MemoryMax on the
  quadlet given mn01's no-swap 7.3 GB.

lessons:
- `Result=success`+`ExecMainStatus=15` in `systemctl show` = deliberate
  stop even when the journal lacks Stopping/Stopped lines (journald drops
  them under podman healthcheck floods).
- mn-ha-dev's "crash-loop" was HA exiting cleanly (code 0) every ~2-7min
  — look HA-side (stop call / recorder DB / watchdog), not infra-side.
- Same unit name, different role per host: omen yolo-xiaomi retired vs
  mn01 yolo-xiaomi = /apps/yolo API + cast backend — check consumers
  before transferring a verdict.
- Verify-by-surface: `/apps/yolo/api/tvs` proved the HA_BASE cast path
  end-to-end where `/detect` alone couldn't (dead camera upstream).
