# Dispatch outcome — lab-disk-trend-watch (redispatch)

## Context

This is the second dispatch on the card. The first run
(dispatch/20261005-232048) implemented everything but its session-end
checkpoint committed only 3 of 6 files — the actual watcher script and job
doc were left untracked in the old worktree, which still existed on disk.
This session recovered the full implementation, ported it here, verified it
end-to-end again, and fixed two real bugs the fresh live run exposed.

## What changed (commit 3fe45a06)

- **`scripts/ada/disk-trend-watch.py`** (new) — periodic df trend watcher in
  the cms-auto-health family, hooked into the kanban-sync health lane
  (15-min tick on tony-dell). One SSH probe per host in
  `ssot.audit.hosts.yml` (local exec on the runner): `df -PTk`/`df -Pk`
  (fstype-filtered, same-device mounts deduped) plus `du -sk` on a dir
  watchlist (`~/.cache` children + parent + `/var/log`). Samples append to
  `~/var/chaba/health/disk-trend.jsonl`; a least-squares KiB/day slope per
  host+mount over a 7d window forecasts days-to-full (needs ≥6h span).
  ≥90% or fill ≤7d opens a `disk-auto-<host>-<mount>` card in review;
  recovery auto-closes it. One batched push per tick for newly opened
  cards. `--report` prints the trend table; `--sample-file` injects
  fixtures; `--selftest` runs a synthetic >90% fixture end-to-end.
- **`scripts/ada/kanban-sync.sh`** — runs the watcher after
  vcast-auto-health with `--reports-root "$SRC/reports"` (cards commit via
  the existing `git add cards/`; reports go to the served checkout so the
  detached worktree stays ff-clean).
- **`scripts/board/board_notify.py`** — `send()` accepts comma-separated
  channels (`ha,yomi`), fans out, True when any accepts.
- **`docs/ssot/infrastructure/ssot.reports.yml`** — L1 node `disk-trend`
  under `fleet` (meta + artifact at `reports/disk-trend/`).
- **`docs/ssot/jobs/infrastructure/2026-10-05-disk-trend-watch.yml`** —
  full design/decision/limits record, updated with this session's fixes.
- **`docs/ssot/kanban/cards/disk-auto-tony-dell-root.yml`** — a REAL alert
  card produced by the verification run (see below).

## Bugs found and fixed this session

1. **`TimeoutExpired.stdout` is bytes even with `text=True`** — the
   `isinstance(str)` guard silently dropped it, so a du overrun erased the
   whole sample. Symptom: tony-dell reported `unreachable` on its own
   host — its `~/.cache` du takes ~77s cold vs the old 60s cap. Now
   decoded via `_partial_stdout()`.
2. **Per-dir du cap + ordering** — each watchlist du is capped at 45s
   (`timeout`, gtimeout/plain fallback), `.cache` children scanned before
   the expensive parent so a parent timeout still leaves the per-child
   numbers that feed top-growers. Probe budget raised to 90s.
3. **Stale-card sweep** now skips cards whose host was unreachable this
   tick — a flaky host no longer flaps an open alert and re-pushes later.
4. **`DISK_TREND_NOTIFY_CHANNELS`** was documented but never wired;
   `notify_opened` now passes it to `bn.send` (default `ha,yomi`), and the
   selftest uses it to select the file sink.

## Verification

- `--selftest` → PASS: synthetic 92% host produced
  `disk-auto-synth-dell-root` (review, high), file-channel push fired,
  trend +13.33 GiB/d → 3.0d to full, yt-live-media flagged +2.0 GiB/24h.
- Live run (outputs sandboxed to /tmp, `--no-notify`): 5/6 hosts, 14
  mounts trended; tony-dell sampled locally in ~1s. History now has 2
  samples/host (~9h span) so slopes are real.
- `node scripts/ssot-validate-all.mjs`: clean — the only error is
  preexisting on `jobs/kanban/2026-10-05-board-request-notify.yml`
  (missing `title`, untouched).

## ⚠ Real finding from verification

**tony-dell `/` is at 83% and grew ~2.8 GiB overnight (+7.42 GiB/d slope →
full in ~2.6d).** The generated `disk-auto-tony-dell-root` card is
included in this commit so it lands on the board at merge. Worth checking
what consumed it (dup pipeline caches? ~/.cache was 4.5 GB at probe time).

## After merge

The next kanban-sync tick on tony-dell starts running the watcher
continuously. Push channels: HA iPhone push live now; the LINE leg fires
once the yomi session is restored and `BOARD_NOTIFY_YOMI_CHAT` is set
(fails soft until then). Known limits/followups are in the job doc.
