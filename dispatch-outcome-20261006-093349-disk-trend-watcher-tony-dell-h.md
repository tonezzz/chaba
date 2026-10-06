# Dispatch outcome — lab-disk-trend-watch (redispatch #3)

## Context

Third dispatch on the card. The implementation was already merged by
redispatch #2 (commit 3fe45a06, merge 72f8badd): this session's job was
post-merge verification that the watcher is actually running in the
15-min kanban-sync lane, plus small cleanup.

## What changed

- `docs/ssot/jobs/kanban/2026-10-05-board-request-notify.yml` — added
  the missing required `title` field. This was the last SSOT validation
  error; `node scripts/ssot-validate-all.mjs` now reports 1336/1336
  valid, 0 errors (4 preexisting warnings).
- `docs/ssot/jobs/infrastructure/2026-10-05-disk-trend-watch.yml` —
  appended a redispatch-#3 verification entry.

## Verification (all re-run this session)

- `python3 scripts/ada/disk-trend-watch.py --selftest` → PASS.
  Synthetic host at 92% produced `disk-auto-synth-dell-root` (review,
  high), file-channel push fired, trend +13.33 GiB/d → full in 3.0d,
  yt-live-media flagged +2.0 GiB/24h.
- Live `--report` against `~/var/chaba/health/disk-trend.jsonl` (42
  samples; last sample 09:30 written by the kanban-sync tick — the
  watcher is live in the lane): 5/6 hosts, 14 mounts.
  **tony-dell / : 84%, +7.92 GiB/d → full in ~2.4d = FILLS** —
  matching the open `disk-auto-tony-dell-root` card on the board.
  macbook unreachable (offline) — handled, no card flap.
- Served checkout `chaba-tony-dell/reports/disk-trend/` stamped
  `status: delta` at 09:30 — report + L1 meta land correctly via
  `--reports-root`.
- kanban-sync.sh line 35 invokes the watcher in the tick; confirmed the
  deployed copy in the `chaba-kanban-sync` worktree is the merged one.

## The spec, point by point

- Periodic check folded into the ops-health lane: ✅ kanban-sync 15-min
  tick next to cms-auto-health/vcast-auto-health.
- df trend per host: ✅ SSH `df`+`du` probe → JSONL history → 7d
  least-squares slope → days-to-full (≥6h span required).
- Alert on board + LINE when filling ≤7d: ✅ `disk-auto-*` cards +
  `board_notify` fan-out `ha,yomi`. HA iPhone push is live; LINE leg is
  wired but the yomi session is still `valid:false` — fails soft until
  re-login + `BOARD_NOTIFY_YOMI_CHAT` (documented follow-up).
- Top growers flagged: ✅ du watchlist trended, ≥256 MiB/24h deltas in
  report + card notes.
- Fires on synthetic >90% fixture: ✅ selftest PASS (shown above).

## Note for Tony

tony-dell / is still growing ~8 GiB/d (~18.7 GiB free, ~2.4d to full at
the current slope). The alert card is on the board; the playbook in its
`help` field lists last time's fixes (mddb backups, pip/go caches,
journalctl --vacuum-size, yt-live-media LRU).
