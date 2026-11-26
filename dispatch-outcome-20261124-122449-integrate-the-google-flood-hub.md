# Dispatch outcome — flood-hub-integration (2026-11-24)

## What I found

The card is still hard-gated on two externals, neither of which moved:

- **Waitlist approval**: no evidence it landed — no `FLOODS_API_KEY`
  anywhere, card note still says BLOCKED, no operator answer in
  `$TASK_DIR/answers.jsonl`.
- **idc01 is offline**: tailscale reports last seen ~33 days ago
  (2026-10-22); ssh times out. The key is spec'd as IP-restricted to
  idc01, so nothing host-side could run even with a key.

## What I built (all keyless, committed eb32877f31 on the dispatch branch)

Architecture pivot worth noting: the assessment assumed michael-dev HA
REST sensors could call `floodforecasting.googleapis.com` directly —
they can't, the key is IP-locked to idc01. New topology:
**idc01 poller → MDDB `flood-hub-status` doc → all consumers.**

- `scripts/ada/flood-hub-poll.py` (new) — the only Flood Hub API caller.
  Queries `floodStatus:searchLatestFloodStatusByArea` per basin loop
  (chao-phraya, nakhon-nayok, saraburi-lopburi), resolves gauge names
  via `gauges:batchGet` for alertable gauges only, publishes the status
  doc to `ada-cms-automation` (same state-doc pattern as flood-alert).
  Exits 0 quietly while the key is absent — timer-safe pre-approval.
- `scripts/ada/flood-news-update.py` — new `<!-- flood-hub:auto -->`
  managed block (render/apply/strip + 36h freshness gate); pages opt in
  via `"hub": true` — set on `flood-report` and
  `flood-report-nongdon-saraburi` in `flood-news-feeds.json`.
- `scripts/ada/flood-alert.py` — `select_hub_alerts()` merges gauge
  severities into the existing batched push: ABOVE_NORMAL→warning,
  SEVERE/EXTREME→critical (the API has no literal WARNING). Per-area
  page mapping preserves the saraburi leaf's `alert_min: critical`;
  `hub:<gaugeId>` dedup with escalation-only re-alert; `--seed` arms
  silently. LINE delivery = `BOARD_NOTIFY_CHANNEL=ha,yomi` +
  `BOARD_NOTIFY_YOMI_CHAT` once the yomi session is healthy (it was
  invalid at last check — one env line, no code).
- michael-dev packages (both `stacks/tony-dell` and `stacks/tony-omen`
  `a_dev_mocks.yaml`) — `sensor.flood_hub_status` command_line sensor
  (states EXTREME/SEVERE/ABOVE_NORMAL/none/stale, 30min scan) +
  `binary_sensor.flood_hub_alert`. Not `mha_mirror_*` REST sensors —
  there is no michael-ha entity to mirror and the API is IP-locked; the
  MDDB doc is the mirror source.
- `docs/ssot/infrastructure/ssot.jobs.yml` — `flood-hub-poll` job
  (host idc01, 1h, exec checkout `chaba-vault`); rendered units in
  `systemd/generated/idc01/` — declared, deliberately NOT installed.
- Docs: `docs/ssot/jobs/ada/2026-11-24-flood-hub-keyless-prep.yml`,
  assessment doc updated (architecture pivot + next-action rewrite),
  focus-inbox waitlist item updated.

## Verification

- `python3 -m pytest tests/ada/test_flood_hub.py` — 15/15 pass;
  full `tests/ada` suite 354 pass, 1 skip.
- `flood-hub-poll.py --dry-run` → clean "no FLOODS_API_KEY — skipped",
  rc=0.
- `flood-news-update.py --page flood-report --dry-run` → live MDDB +
  RSS verified; hub gate correctly reports "enabled but no fresh status
  doc — block would be stripped".
- `render-jobs.py --check` → 119 jobs OK; units rendered for idc01.
- Card comms posted at start and end.

## Still gated (needs Tony / external)

1. Waitlist approval email → reply with project `flood-watch-510211`,
   enable `floodforecasting.googleapis.com`, key restricted to API +
   idc01 IP `157.85.110.99`, write
   `~/.config/secrets/flood-forecasting.env` on idc01.
2. idc01 back online → sync `chaba-vault` checkout →
   `render-jobs.py --host idc01 --install` → `--dry-run` → live run.
3. Ada `flood_status` tool — lives in the ada-voice repo
   (realtime_provider/tools.d), separate dispatch; should read the same
   `flood-hub-status` doc.
4. LINE alert arm: yomi session + `BOARD_NOTIFY_YOMI_CHAT` on tony-dell.
5. GEV KML overlay — optional, unchanged.

lessons:
- Google Flood Hub key is spec'd IP-restricted to idc01 — poll→MDDB→consume is the only viable topology; do not design HA sensors that call the API directly.
- FloodStatus.Severity has no WARNING literal: ABOVE_NORMAL is the watch tier, SEVERE/EXTREME the alert tiers.
- `searchLatestFloodStatusByArea` takes `loop` (LatLng ring) or `regionCode`; gauge names need a separate `gauges:batchGet` — keep it to alertable gauges only.
- command_line sensors in the michael-dev HA container can run `python3 -c` one-liners against MDDB `/get`; folded `>-` scalars collapse newlines so the python must be a single line of semicolon-joined simple statements.
- Job-doc YAML list items containing ": " must be quoted or the pre-commit SSOT validator fails.
