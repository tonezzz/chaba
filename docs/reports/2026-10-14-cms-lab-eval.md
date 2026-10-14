# CMS Lab Eval — Ghost vs Directus vs Strapi vs Payload

- **Date:** 2026-10-14
- **Card:** `cms-lab-eval` (KNB-0600)
- **Host:** idc02, `~/cms-lab/` — rootless podman + podman-compose, tailnet-only
- **Status:** all four installed and verified; agent/API leg complete; human leg in progress

## Goal

Find out what a well-made CMS feels like, and whether one could serve the
`place_report` → public-page → LINE-link workflow better than the current
MDDB + static-publisher stack. The current CMS is functional but visually
plain; this lab is the hands-on comparison.

## Systems under test

| System | URL | Stack | Deploy notes |
|---|---|---|---|
| Ghost 6.69 | http://idc02.taila0626a.ts.net:8301/ghost | ghost:6-alpine, dev mode, SQLite | Setup endpoint moved to `/ghost/api/admin/authentication/setup/`; API needs `Accept-Version: v6.69` header; `security__staffDeviceVerification=false` needed without SMTP |
| Directus 11 | http://idc02.taila0626a.ts.net:8302 | directus/directus:11 + postgres:16 | Cleanest install; admin seeded via env |
| Strapi 5 | http://idc02.taila0626a.ts.net:8303/admin | node:22 + create-strapi (JS, sqlite) | Scaffolded `.env` had empty `DATABASE_FILENAME` → crash-loop; fixed |
| Payload 3.90 | http://idc02.taila0626a.ts.net:8304/admin | node:22 + create-payload-app (blank, sqlite) | Scaffolder requires a TTY; project scaffolded into subdir, flattened to /app |

Admin on all four: `tony@tonezzz.dev`, shared password —
`ssh idc02 'cat ~/cms-lab/admin-credentials.txt'` (chmod 600, not in git).

## Agent/API leg — results (all four seeded with the same Thai shop report)

Fixture: `ร้านกาแฟ Coffee Valley เขาใหญ่` — detail text + Google Maps URL.

| System | Calls to first write | Friction |
|---|---|---|
| Directus | 3 (login → create collection → create item) | None — pure REST, schema via API |
| Ghost | 2 (session → create post) | Versioned API header; device-verification had to be disabled; post published to a real public URL |
| Strapi | 4 (login → content-type-builder → api-token → write) | Admin JWT ≠ content API token; schema write bounces the server (~10s) |
| Payload | 2 + restart (edit `src/collections/ShopReports.ts` → restart → REST write) | Schema is TypeScript in git — most agent-native, least human-no-code |

## Human leg — rubric (Tony)

In each admin UI, author the same shop report (name, Thai detail, photo,
map link). Judge:

1. Steps from login → published page
2. How the *reader-facing* output looks (Ghost renders a real post page;
   Directus/Strapi/Payload are headless — content appears in admin only)
3. Public/private control granularity
4. Fit for the kk flow: could `place_report` write here and produce a
   linkable page for LINE?

## Findings so far

- **Ghost** is the only candidate that produces a polished *public page*
  for free — the closest answer to "our CMS is too plain". Its API is
  quirky (version header, session 2FA) but workable via integration keys.
- **Directus** is the easiest agent target — collections created and
  written over pure REST; would pair with chaba.h3 pulling its API the
  same way it pulls MDDB today.
- **Strapi** adds a schema-management hop and a server bounce per model
  change — friction for an autonomous writer.
- **Payload** is git-as-UI — schema is code, so an agent edits a file and
  restarts. Most Chaba-native mentally, but no non-code schema path.

## Related work

- `cms-lab-eval` — this experiment's card (live evidence in comms)
- `maps-url-to-cms-line-maps-link-resolved-c418f8` — the place_report →
  CMS page → LINE flow this lab may augment or replace
- `kk-places-tool`, `map-embed-tool` — Kaewta workflow asks
- `gemini-billing-dunning` / wallet-watch — unrelated but same era
- Live CMS: https://chaba.h3.gizmo-thailand.com/cms/

## Open questions

- WordPress (boards.surf-thailand.com → boards.h3 proxy, 2026-10-14) is a
  fifth candidate pending the Plesk install going live — classic CMS with
  REST API + application passwords; would change this comparison.
- Decision pending: augment existing CMS (Directus-as-backend → h3
  render) vs. replace public layer (Ghost serves pages directly) vs.
  keep current stack.

## Teardown

`ssh idc02 'cd ~/cms-lab && podman-compose down -v && rm -rf ~/cms-lab'`
removes everything; containers and data are disposable.
