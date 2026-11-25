# Dispatch outcome — ada-ha chaba-admin 'Ada Code' view removal + consumer-canary widening

Card: `ada-ha-chaba-admin-ada-code-view-iframes-d1c492`
Branch: `dispatch/20261125-092607-found-during-ocb-spa-route-gua` (commit `e0d54c931f`, not pushed per dispatch rules)
Host: mn01 worktree

## Done — VERIFIED live

- **Live mutation applied.** `lovelace.chaba_admin` on ada-ha (tony-omen:8125,
  url_path `chaba-admin`): `views[path=ada-code]` removed via
  `push-dashboard.py --mutate scripts/home-assistant/mutate-ada-ha-remove-adacode-tab.py`
  over the HA websocket (run on tony-omen, token from
  `~/.config/secrets/ada-ha-token.env`). Websocket readback after save: 18
  views, no `ada-code` path, zero `ada-code.surf-thailand.com` refs.
- **Option chosen: (a) remove.** (b) would duplicate the existing OpenChamber
  (`ada-ocb`) view; (c) is not viable — the live opencode-serve surface
  (idc02 tailnet `100.123.163.11:4096`, verified serving the OpenCode web UI)
  is plain http with no auth edge, so the public https dashboard would block
  it as mixed content; (d) leaves a dead tab. Re-adding a view later is a
  one-line mutate.
- **Repo synced.** `sync-ssot-from-live.sh --instance ada-ha` resanitized
  `docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json` (view
  block removed, secrets still redacted); chaba-home snapshot unchanged;
  `ssot.home-assistant.dashboards.yml` note + view order updated by hand.
- **consumer-canary widened.** `scripts/audit/consumer-canary.py`
  `RETIRED_HOSTS` default now includes `ada-code`, `opencode-ada`,
  `opencode-jack` `.surf-thailand.com` (the public edge hostnames retired
  2026-11-24), so this drift class is caught standing. IGNORE gained
  `\.retired[-\w.]*:` — idc02 keeps `*.container.retired-20261124` tombstones
  under `~/.config/containers/systemd/` that legitimately still name the old
  PUBLIC_HOSTs. Unit-checked: tombstones ignored, live hits still flagged.
  `ssot.jobs.yml` consumer-canary note updated. Takes effect on idc03's exec
  checkout after merge + chaba-repo-sync; no unit change needed.
- **Trail.** `docs/ssot/jobs/home-assistant/2026-11-25-ada-ha-adacode-view-removal.yml`.

## How to verify

- Live: open `https://ada-ha.surf-thailand.com/chaba-admin/` — no 'Ada Code'
  tab; OpenChamber tab still present.
- Repo: `git show e0d54c931f` — snapshot diff is the single removed view
  block; mutator + canary diff as described.
- Canary: after merge + sync, next `consumer-canary.service` run on idc03
  greps the new host list; a forced check is
  `RETIRED_HOSTS='ada-code.surf-thailand.com,...' python3 scripts/audit/consumer-canary.py` on idc03.

lessons:
- opencode-serve (:4096 tailnet http, no auth) cannot iframe into the public https ada-ha dashboard — mixed content; a tailnet-only agent UI needs a tailscale-serve https edge before it can be a dashboard tab.
- Retired quadlets leave *.retired-<date> tombstone files under ~/.config/containers/systemd/ that still name the old PUBLIC_HOST — retired-hostname greps must ignore .retired-* like .bak or the canary self-reports forever.
- ada-ha-token.env exports HA_LONG_LIVED_TOKEN, not HASS_TOKEN — push-dashboard.py needs `export HASS_TOKEN=$HA_LONG_LIVED_TOKEN` after sourcing.
