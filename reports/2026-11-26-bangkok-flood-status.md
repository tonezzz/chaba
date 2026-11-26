# Bangkok Flood Situation — One-Shot Digest

- **Card:** monitor-bangkok-flood-situation-4b84da (OPS-1448)
- **Source:** MDDB `ada-cms-pages/flood-report` (lang=en; th variant in sync — same `updated` stamp)
- **Source timestamp:** auto-news block fetched **2026-11-26 19:08 ICT**; page meta `updated` = `2026-11-26T12:08:33+00:00`, `last_verified` = 2026-11-26 (`fresh_for: 6h` — still fresh at 21:55 ICT)
- **Digest taken:** 2026-11-26 21:55 ICT — read-only, no monitoring loop, no alerts.

## Current situation (per the report page)

- **No active major flooding reported in Bangkok.** Latest direct check on the page (BMA via timeline, 2026-11-25 13:37 ICT): normal road conditions, no main-road flooding.
- **Weather context:** cold surge active; Chao Phraya high-tide watch noted through ~Dec 2. Bangkok and suburbs forecast to cool 1–3°C.
- **News signal (6 items / 72h, feeds bangphli, samutprakan, bangkok-th, bangkok-en):**
  - 2026-11-26 16:32 — "Why Bangkok keeps flooding" analysis (Howl.Link)
  - 2026-11-26 11:06 — flood-relief payment update, BAAC transferring additional aid (Thansettakij)
  - 2026-11-25 — heavy rain raises **flash-flood risk in Thailand's South 27–30 Nov** (The Star, Nation Thailand) — regional, not Bangkok core
  - 2026-11-25 — flooding cited in 34% plunge of Thai auto exports (Bangkok Post)
- **Regional rollups** (children of this page): `flood-report-nongdon-saraburi`, `flood-report-pattaya-rayong`, `flood-coordinates-rayong` — not fetched in this one-shot.

## Caveats (from the page itself)

- Page is mostly aggregated news; **no real-time primary data** — direct local observations, dam levels, and live sensor readings are not present.
- No Google Flood Hub gauge block on this page (`hub` block absent).
- Yesterday's local check (RK600: 0 mm rain) is the freshest ground-level datapoint on the page; today's news items are analytical/administrative rather than incident reports.

## Bottom line

As of the 19:08 ICT source pull: **Bangkok flood situation is quiet — no reported main-road flooding; watch items are the South-Thai flash-flood window 27–30 Nov and the Chao Phraya high-tide/cold-surge period through early Dec.**
