# Dispatch outcome — mddb-follower-stall

Card: `mddb-follower-stall` · Runner: mn01 · Branch: `dispatch/20261007-225415-diagnose-the-mddb-follower-s-s` (committed, not pushed)

## Root cause

Confirmed the diagnosis from `mddb-replication-heartbeat` (done 2026-10-06):
the follower's `replicate()` loop calls `stream.Recv()` with **no deadline**
and the protocol has **no application-level heartbeat**. A silently-dead
stream (leader send goroutine blocked, tailnet/DERP half-open, TCP
blackhole) leaves `Recv` blocked forever → `connected=true`, leader-side
`last_seen_at` keeps updating on stream activity, `confirmed_lsn` frozen,
zero log lines. Only a restart re-dials. Since 2.15.4-lsn the restart
resumes from the persisted LSN marker — no snapshot re-pull.

The permanent fix already exists **undeployed** on mddb-fork branch
`repl-heartbeat` @ `498cdc3` (leader 15s idle heartbeat, follower 45s Recv
deadline, `connected`/`last_recv_at`/`heartbeat_capable` status fields).
No image built — needs merge + rebuild off `feat/vector-algorithms`.
mddb-fork source is unreachable from mn01 (no checkout, ssh to tony-dell
denied), so no code changes there this session.

## What changed (this worktree)

- **`scripts/mddb-follower-watchdog.py`** (new) — runs on each follower
  host via user timer. Each tick polls the leader's
  `/v1/replication/status`; the stall signature is `last_seen_at` fresh
  (≤120s = stream connected) + `confirmed_lsn` frozen ≥300s +
  `confirmed_lsn < current_lsn`. On detection:
  `systemctl --user restart mddb-follower.service`. Guards: 900s restart
  cooldown, 3 restarts/episode then gives up, `confirmed_lsn==0` skipped
  (snapshot-in-flight protection), follower absent from `followers[]` not
  restarted (different failure class; `--restart-if-absent` opt-in).
  `--dry-run` + `file://` test mode; one JSON line per tick to journald.
- **`systemd/mddb-follower-watchdog.{service,timer}`** (new) — user units,
  every 2min. Install instructions in the service comment; set
  `Environment=MDDB_NODE_ID` per host.
- **`scripts/mddb-binlog-canary.py`** (extended) — stream-state surfacing:
  every tick now emits `metrics.followers_stream[]` with
  `confirmed_lsn`, `apply_lag_lsn`, `last_seen_age_s`, `connected`,
  `frozen_seconds` per follower; a frozen-while-connected follower past
  `--stall-seconds` (default 600) adds an explicit `apply-stalled` breach
  reason naming the remediation — the freeze is now a first-class alert,
  not something a human has to infer by comparing LSNs. `write_inbox`
  mkdirs the inbox dir.
- **`docs/ssot/jobs/infrastructure/2026-10-07-mddb-follower-stall-watchdog.yml`**
  — full job record (signature, root cause, verification, deploy steps).
- **`docs/ssot/kanban/cards/mddb-follower-stall.yml`** — findings + help
  text updated.

## Verification

- Watchdog: 10 canned scenarios (file:// payloads + stubbed `systemctl`):
  watching → stalled → would-restart (dry-run) → restart → cooldown →
  gave-up → disconnected (stale `last_seen_at`) → snapshotting
  (confirmed_lsn=0) → absent → fetch-error. All pass; exactly one stub
  restart fired.
- Canary: stalled payload produces the `apply-stalled` reason only after
  the freeze window; advancing payloads never do.
- **Live against idc03 leader (~23:05Z):** idc02 `caught-up` (lag 0);
  idc01 `watching` — 13.2M behind but `confirmed_lsn` advancing
  ~100 LSN/s (slow catch-up after its restart, **not** the stall
  signature) — correctly not flagged/restarted.
- `ssot-validate-all.mjs`: 1684 files, 0 errors. `py_compile` clean.

## Deploy status

Not deployed (dispatch scope: diagnose + build). To activate:

- idc02/idc01: `cp scripts/mddb-follower-watchdog.py ~/.local/bin/`;
  `cp systemd/mddb-follower-watchdog.{service,timer}
  ~/.config/systemd/user/` (set `MDDB_NODE_ID`); `systemctl --user
  daemon-reload && systemctl --user enable --now
  mddb-follower-watchdog.timer`.
- tony-dell: canary picks up on next merge to the served checkout.

## Open items

- Install watchdog on idc02 + idc01 (needs approval / another dispatch).
- Merge `repl-heartbeat` + `follower-lsn-persist` into
  `feat/vector-algorithms`, rebuild image, deploy — removes the bug class;
  watchdog stays as safety net.
- idc01 follower still ~13M LSN behind at ~100 LSN/s — draining, will take
  many hours; watchdog will not touch it (it keeps advancing).
