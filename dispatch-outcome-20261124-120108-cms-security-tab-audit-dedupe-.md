# Dispatch outcome — cms-security-audit (attempt 2)

Card: `docs/ssot/kanban/cards/cms-security-audit.yml` (already `column: done`;
the 2026-10-03 audit note is the spec). Attempt 2 existed because the prior
run did not merge/verify — the card comms carry only auto runner-agent drift
noise, no failure detail.

## What I did

1. **Re-verified the audit against live MDDB** (`ada-cms-pages`, 1596 docs,
   pulled 2026-11-24 ~05:0xZ). Every conclusion holds:
   - Security tab = 17 cam dossiers (noble-a 5, noble-club 8, tony-house 4)
     + 3 camwall pages + `dvr-wall` (Security-only) — all en+th.
   - `cctv-walls` index spans both tabs (`zone_tab=[Security,Traffic]`,
     `zone_group=[private,public]`, all 7 sites, links to all 9 wall pages).
   - `cctv-random-cycle` and the other `cctv-*` tool docs carry no
     `zone_tab`/`page_role` → Pages. No `wall-*`/`noble-park` keys in any
     status. Active `zone_tab` values are only Security(44)/Traffic(100)/none(7).

2. **Found a post-audit regression the original audit could not see** (the
   2026-10-04 capture-fix lane split postdates it): every cam-wall-cms lane
   published the shared cross-zone pages from its own zone slice.
   - Observed live: `cctv-walls` `zone_site` flapped `['tony-house']`
     (05:00:44Z) → full 7-site union (05:03:52Z) minutes apart; content
     (wall table) flaps the same way — a partial lane drops the other
     tab's wall links and mis-stamps `zone_tab`.
   - `dvr-wall` carried no `zone:` sources, so `_successor_for` let ANY
     lane (e.g. public-only) mark it `superseded -> cctv-walls`; private
     lanes revive it next run — status flapping.

3. **Fix** (`scripts/cam-wall/cam-wall-cms.py`):
   - `shared_ok = set(zones) >= set(zone_meta.zones(ZMETA))` — only a lane
     whose manifests cover the full zones.yml roster publishes `cctv-walls`
     and `dvr-wall`; all lanes still list them in `current` so none can
     supersede them.
   - `CAMWALL_PUBLISH_SHARED=1` env override for collections whose scope IS
     a slice — added to `systemd/cam-wall-cms-kk.service` (kk lane keeps her
     public-only index in `ada-cms-pages-kk`).
   - `dvr-wall` now emits `zone:<zone>` sources for dev-cam zones, so the
     existing zone-source boundary excludes foreign lanes from its
     lifecycle.

4. **Docs**: job record
   `docs/ssot/jobs/infrastructure/2026-11-24-camwall-shared-pages-single-writer.yml`;
   producer note added to `docs/ssot/infrastructure/ssot.cms.yml`.

## Result / verification

- `python3 -m pytest tests/camwall/` — 12 passed, incl. new
  `PartialLaneTest` (partial lane writes neither shared page nor supersedes
  them; env override publishes `cctv-walls`).
- `py_compile` clean; both YAML files parse; `ssot-prose-smell.py` clean.
- Live state needed no mutation — it was already conformant; the fix
  prevents recurrence once lanes pick up the synced script.

## Caveats

- The gate assumes some lane sees all 8 zones.yml manifests (observed: the
  05:03Z writer did). If coverage is ever lost fleet-wide the shared pages
  freeze — visible via `meta.updated` staleness; escape hatch is the env
  override. Noted in the job record.
- Board API on 127.0.0.1:8787 refused connections from this host; card
  comms went through `https://idc03.taila0626a.ts.net:10000` instead.

lessons:
- Board-api is not on 127.0.0.1:8787 off-idc03 — use https://idc03.taila0626a.ts.net:10000 for /comment|/request from dispatch worktrees.
- cam-wall-cms lanes share ada-cms-pages: any page written by >1 lane needs either zone:-source scoping or an explicit single-writer gate, or its meta/content flaps between writers.
- A card marked done can still be re-dispatched; re-verify live state (MDDB) rather than trusting the note — the 2026-10-04 lane split introduced a regression after the 2026-10-03 audit.
- Plain-YAML SSOT scalars break on `: ` inside the value — use `—`/`;` in multi-line block scalars.
