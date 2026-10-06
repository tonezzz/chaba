# Dispatch outcome — logs-digest-signal

## What changed

**`scripts/ada/log-shipper.py`** — noise out of the ship budget:

- `GREP_DROP`: remote-side `grep -avE` between `journalctl --grep` and
  the tail — session-scope churn, uvicorn lifecycle, and restart-counter
  bookkeeping never cross the wire. Measured on tony-omen's system
  journal: 116,695 → 33,208 matched lines/24h (-72%).
- `DROP` += the same classes client-side (`Started session-`,
  `Stopped/Stopping session-`, `Started/Stopped/Finished server
  process`, `Scheduled restart job, restart counter is at`) — the
  matching failure lines (`Failed with result`, `Failed to start`,
  `Main process exited`) still ship, so crash loops stay visible.
- `_cap_repeats()` / `REPEAT_CAP=25`: per-run cap per RX_VOLATILE-
  normalized (unit,line) signature, applied in `_journal` and
  `_journal_ha`. Over-cap copies are deliberate drops (cursor advances
  past them); the withheld count accumulates onto the last kept row and
  ships as `meta.suppressed`. Ship-state gains a `suppressed` field and
  `scanned` is now post-cap matched — keeps logs-kanban's backlog check
  honest (a crash loop no longer reads as undrainable backlog).
- `tail -3000` → `tail -6000` post-pre-drop.

**`scripts/ada/logs-report.py`** — the read half:

- Full-collection scan (PAGE=5000, bounded by `--max-docs` 250000 ≈ the
  14d prune horizon). Fixes a live bug: `/v1/search` returns KEY order
  (`hostlog/<host>/<rt-µs-suffix>`), not insertion order — the old
  offset-0..5000 scan was pinned to the oldest docs, so the "24h" digest
  showed Oct-3 data and 5 of 6 hosts were missing.
- `🆕` new-today flag: window rows whose (host, normalized sig) is
  absent from the prior `--baseline-days` (7) get the marker — shown in
  the host header (`N new 🆕`), as dedicated `🆕 xN` lines, and on repeat
  offenders that are also new. Exact semantics, no state file.
- Offender counts weigh `1 + meta.suppressed` so capped crash loops keep
  truthful xN.

## Verify (done this session)

- `classify()` drops all five new noise classes; keeps
  Failed/ACPI/tailscaled signal.
- `_cap_repeats`: 40 identical rows → 25 kept, `suppressed=15` marker.
- Stub-MDDB digest: injected novel line renders `🆕 x1 kernel: BUG:
  unable to handle page fault...`; a line seen 2d prior renders
  unflagged; capped offender shows truthful `x40` (25 shipped + 15
  suppressed).
- Live MDDB scan: all 6 hosts in the true 24h window in ~15s; real 🆕
  hits surfaced (mcp-link-monitor crash loop on tony-dell,
  cam-wall-pull-vps spawn failures on idc03, vms-snap RuntimeErrors on
  mn01).
- `--self --dry-run` on tony-omen: 49 matched post-filter this window.
- `ssot-validate-all.mjs`: new job doc valid (1 preexisting error in an
  unrelated file).

## Pending (needs Tony)

- Re-run `install-log-shipper.sh` per host to deploy the new shipper —
  installed copies live at `~/.local/share/log-shipper/` and are not the
  repo checkout. Deploy step; not done in this session.

## Trail

`docs/ssot/jobs/infrastructure/2026-10-06-log-digest-signal-density.yml`
