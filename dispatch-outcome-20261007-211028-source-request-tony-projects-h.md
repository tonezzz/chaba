# Dispatch outcome — hosting-provider-intl-report (2026-10-07)

## What was found
- The existing provider assessment is CMS page `ada-cms-pages/hosting-provider-assessment`
  (2026-09-27 Thai VPS shortlist for idc02: ReadyIDC / Contabo / Hetzner).
- CMS pages are MDDB documents (`ada-cms-pages`, MDDB at 100.102.134.91:11023),
  rendered by Ada's cms viewer at `/apps/ha/ada-tony/cms/` (tony-dell Caddy
  proxies to idc03:8002); page URLs are `/cms/#/<slug>`.

## What changed (live CMS)
- **New report page** `hosting-provider-intl` (kind:report, domain:infra,
  full meta contract, fresh_for 30d): international candidates — Vultr,
  Akamai/Linode, AWS (SG/HK), DigitalOcean, Dataplugs HK, Hetzner, OVH,
  Contabo — with a **measured** ICMP table from tony-dell's Thai uplink
  (idc01 6.9ms, SG ~30–37ms, HK ~62–70ms, EU 189–276ms) and **published/
  estimated** latency blocks for Manila, Oslo, Germany, Bangkok, Chonburi,
  Khao Yai — every row labelled measured vs published.
- **Backlink** added to `hosting-provider-assessment` ("See also" line above
  the shortlist + `meta.links`); new page links back in Latest. Both ways
  resolve.
- `reports-index` regenerated via `scripts/lib/cms_index.py`; new row present.

## Repo artifacts
- `reports/hosting-provider-intl.md` — page source.
- `docs/ssot/jobs/reports/2026-10-07-hosting-provider-intl.yml` — job trail.

## Verify
- Page: https://tony-dell.taila0626a.ts.net/apps/ha/ada-tony/cms/#/hosting-provider-intl
  (viewer route returns 200; doc verified live via MDDB /v1/get; the cms API
  itself needs the stored cms-viewer key).
- Links: old page's "See also" → new page; new page's Latest → old page.
- Latency labelling: measured column says "measured", per-location section
  header says "published / estimated", Method & sources lists provenance.

## Notes
- MDDB /v1/add dropped its response twice but writes landed (known quirk —
  embedding on write); verified via /v1/get both times.
- DigitalOcean/GCP/Hetzner-web ping targets filter ICMP — marked on-page
  rather than reported as unreachable.
