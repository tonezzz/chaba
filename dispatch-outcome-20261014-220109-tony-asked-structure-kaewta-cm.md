# Dispatch outcome — ada-kk-cms-traffic (attempt 2)

## What changed

`cam-wall-cms.py` gained member-lane env knobs so the same generator can
feed Kaewta's CMS collection with a privacy-filtered page set:

- `COLLECTION` env (spec-named; `CAMWALL_COLLECTION` alias) selects the
  MDDB collection — default `ada-cms-pages` unchanged.
- `CAMWALL_GROUPS` env is a comma-separated zones.yml group allowlist.
  `CAMWALL_GROUPS=public` publishes only group:public zones
  (traffic/rama9/burapha/chonburi/dohweb) — private (vms-noble-*,
  tony-house) and 'unsorted' zones emit nothing.
- Cam-level guard: a cam whose DVR `devices` entry classifies outside the
  group set is dropped from dossiers AND the wall roster/index counts, so
  a private-device cam can't ride a public zone's manifest onto her lane.
- Lifecycle ownership spans the full manifest roster: a zone reclassified
  out of the group gets its stale lane pages superseded -> `cctv-walls`,
  not left 'active' but stale (a quiet privacy leak otherwise).
- `_cms-pub-hash.json` and `_cms-notify-state.json` are per-collection
  suffixed (main lane keeps legacy names) — without this the two timers
  stomp each other's dedup map and force a full republish+re-embed every
  cycle. Group-filtered lanes skip `notify_transitions` (no kk wall flaps
  pinging Tony's Ada). `reports-index` regenerates inside the target
  collection; meta.scope derives from the collection (`kk`).

New units: `systemd/cam-wall-cms-kk.service` + `.timer` (*:4/15, offset
from main *:0/15 and vps *:2/15) running the same script with
`COLLECTION=ada-cms-pages-kk CAMWALL_GROUPS=public`.

Docs/trail: `docs/ssot/apps/ssot.apps.camwall.yml` (CMS kk lane entry),
`docs/ssot/infrastructure/ssot.audit.hosts.yml` (timer census),
`docs/ssot/jobs/infrastructure/2026-10-14-camwall-kk-lane.yml`.

## Verification

- `python3 -m unittest tests/camwall/test_cam_wall_cms` — 4/4 pass,
  incl. new `CamWallCmsGroupsTest`: public-only publish set, private/
  unsorted/dev-cam exclusion, stale private doc retracted, per-lane
  pub-hash file, all /add calls carry collection=ada-cms-pages-kk.
- Multi-zone dry-run (8 zones incl. private + unsorted):
  `CAMWALL_GROUPS=public COLLECTION=ada-cms-pages-kk --dry-run` emitted
  exactly camwall-{burapha,chonburi,dohweb,rama9,traffic} + 5 cams +
  cctv-walls. Default lane unchanged (all zones + dvr-wall).
- `node scripts/ssot-validate-all.mjs` — all 2352 files valid.
- camwall-smoke CI gained a filtered-lane dry-run step.

## Result

Mechanism complete in this worktree (commit 306c8640b). The live enable
is a post-merge step on tony-dell:
`cp systemd/cam-wall-cms-kk.{service,timer} ~/.config/systemd/user/ &&
systemctl --user daemon-reload && systemctl --user enable --now
cam-wall-cms-kk.timer`. Kaewta then reads `camwall-traffic` /
`cam-traffic-*` via cms_read from ada-cms-pages-kk; fresh_for=1h +
meta.updated give her truthful freshness. vms-noble-* stays
group:private per Tony's answered request — a Noble exception needs an
explicit zones.yml reclass, never a wider CAMWALL_GROUPS.

lessons:
  - cam-wall-cms.py shares DATA state files (_cms-pub-hash.json,
    _cms-notify-state.json) — a second lane must get per-collection
    filenames or the lanes overwrite each other's dedup map every run.
  - Supersede ownership must scan the unfiltered zone roster on filtered
    lanes or retracted-zone pages linger 'active' forever.
  - The card spec's env name is `COLLECTION` — kept verbatim, with
    CAMWALL_COLLECTION as the namespaced alias.
