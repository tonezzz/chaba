# flood-situation-alert-system-9f3407 — flood severity watchdog + HA push

## What was asked

Thin card "Flood Situation Alert System" (captured by Ada 01:39, high
priority, no spec). Interpreted via context: the flood pipeline already
writes CMS pages (flood-news-update.py every 15m on idc02, news-flood
digest hourly on idc03) and Flood Hub gauges are waitlist-blocked — the
missing leg was **severity judgement + push notification**. Sibling card
monitor-flood-situation-and-update-cms-r-e082c7 ("ongoing monitoring of
the flood situation in Bangkok") confirms the direction.

## What changed

- **`scripts/ada/flood-alert.py`** (new, stdlib-only) — scans the same
  feeds flood-news-update.py uses (imports it via importlib — filename
  has dashes), classifies each item info|warning|critical on
  Thai+English escalation vocabulary (paired barrier+breach match so
  `เขื่อนแตก` is critical but routine `เขื่อน…ระบายน้ำ` stays warning),
  and pushes ONE batched notification via `scripts/board/board_notify.py`
  (HA iPhone channel — the proven devin-dispatch-watch path).
  - Per-page `alert_min` threshold + `alert_label` from feeds.json,
    registry-overridable (same precedence as every other knob).
  - State file `~/.cache/flood-alert-state.json` dedups by normalized
    title — each item pushes at most once per level; re-classification
    upward re-pushes once (escalation). Missing state file = silent
    seed, so arming never bursts.
  - Failed pushes do NOT mark items — the next tick retries, and
    `last_status=error` in the registry doc lets cms-auto-health surface
    a dead push channel.
  - Writes ada-cms-automation doc `flood-alert` each run (interval_min
    15, last_run, alerts_sent, alert_log tail) — cms-auto-health now
    watches this lane like the page generators (stale →
    cms-auto-flood-alert card). flood-news-update `--all` skips the
    feed-less doc cleanly.
- **`scripts/ada/flood-news-feeds.json`** — alert_min/alert_label per
  page: flood-report warning (home), pattaya-rayong warning,
  nongdon-saraburi critical (dam-discharge routine copy is noise);
  `_comment` documents the knobs.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — job:flood-alert,
  host **tony_dell** (not idc02 — idc02 has no HA token file and tony-ha
  binds loopback; also decouples alerting from the CMS lane), every 15m,
  systemd, env pins MDDB_BASE_URL + BOARD_NOTIFY_CHANNEL=ha.
- **`systemd/generated/tony_dell/flood-alert.{service,timer}`** — rendered.
- **`docs/ssot/infrastructure/ssot.automation.yml`** — flood_alert entry.
- **`docs/ssot/jobs/ada/2026-10-10-flood-alert-system.yml`** — full
  runbook (context, channel decision, severity model, tuning, limits).
- **`tests/ada/test_flood_alert.py`** — 14 unit tests, no network.
- **Card** — comms + `requests.install-flood-alert` (install approval);
  column → review. Board comment + request posted live (notify queued).

## Verification

- `python3 scripts/ada/flood-alert.py --self-test` → 9/9.
- `python3 -m unittest tests.ada.test_flood_alert` → 14/14; full suite
  `python3 -m unittest discover tests` → 139 OK (28 skipped).
- `--dry-run` on live feeds (2026-10-10): correctly flagged CRIT
  `ชลบุรีอ่วม! มวลน้ำ…ท่วมสูง` (Pattaya/Rayong), kept routine dam
  discharge at warning on nongdon, กทม. น้ำขัง/ถนนปิด at warning on home.
- End-to-end: crafted state → escalation re-alert → batched
  "FLOOD ALERT — 6 critical" written to file sink; 15 keys + alert_log
  persisted. Dead-channel run: "push FAILED (2 alerts held for retry)",
  items left unmarked. Dead-MDDB run degrades to seed-config-only.
- `python3 scripts/render-jobs.py --check` → OK 45 jobs; re-render of
  tony_dell units is byte-identical except the two new files.

## Pending / how to finish the deploy

Install is a deploy → gated on approval (board request
`install-flood-alert` raised on the card). Post-merge on tony-dell:

    scripts/render-jobs.py --host tony_dell --install

then `systemctl --user list-timers flood-alert.timer`; first journal run
prints `seeded N items — no push`, later ticks print `nothing new…` or
`push sent: N alert(s)` with the push landing on Tony's iPhone.

## Notes for the next reader

- Noise lever: raise `alert_min` to `critical` per page (registry doc
  wins over feeds.json) rather than editing the regexes.
- Flood Hub API (card flood-hub-integration) is still the real sensor;
  when the key lands, gauge ≥ WARNING should reuse this push path.
- Two headline variants of one story can push twice (different dedup
  keys) — bounded, acceptable.
