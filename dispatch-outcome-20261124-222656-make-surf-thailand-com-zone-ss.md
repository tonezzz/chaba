# Dispatch outcome — cf-ssl-strict-migrate-idc02-edge-origin-3fa959

## Result: DONE — ssl=strict is live on surf-thailand.com

Zone `4feb4a3682e44e38cce3feed65dba7f3` flipped `full -> strict` at
2026-11-24 23:11 +07. Verified: all 23 proxied names return normal
responses (200/301/302/308/404), zero 525/526.

## What changed (live infra, no repo code)

**idc02 caddy-edge (the bulk of the work):**
- Issued one Let's Encrypt wildcard (`*.surf-thailand.com` + apex,
  YE1, expires 2027-02-22) via `acme.sh` DNS-01 using the existing
  `cfat_` CF_API_TOKEN on idc02. Installed to
  `~/.config/containers/caddy/data/certs/` with `--install-cert` +
  caddy reloadcmd; cron renewal armed (4x/day).
- Replaced all 15 `tls internal` directives in
  `~/.config/caddy/Caddyfile` with the wildcard cert paths; appended
  `wiki` + `wiki-internal` blocks proxying to
  `https://wiki.h3.gizmo-thailand.com` (valid LE upstream, Host
  preserved, public-resolver transport per the h3-DNS hardening
  convention).

**Why DNS-01, not ACME/Origin-CA:** ~11 names sit behind Cloudflare
Access which 302s `/.well-known/acme-challenge/` — HTTP-01/TLS-ALPN-01
can't work. The `cfat_` token lacks SSL-and-Certificates scope, so
Origin CA cert creation is not possible via API.

**Phantom podman mounts found + fixed (latent bug):** idc02
`caddy-edge.container` mounted `data`/`config` dirs with the comma
form `,Z` (`-v src:/data,Z`). Rootless podman produced phantom mounts
— the container saw an orphan dir with only `caddy/` while the host
dir held `www/`+`certs/`. This had silently killed the apex www
webroot, `/feeds/usage.json`, `/kk-ha`, `/tony-ha` for weeks. Switched
to colon form `:z` + restart; all healed (verified 200/403-gated).
The Caddyfile file-bind `:ro,Z` was unaffected.

**Cloudflare DNS:**
- `wiki` + `wiki-internal` CNAMEs: `wiki.h3.gizmo-thailand.com` ->
  `edge.surf-thailand.com` (Plesk cert lacks surf-thailand SANs;
  strict would 526 — now TLS terminates on idc02's LE wildcard).
- `idc01.surf-thailand.com`: unproxied (host retired, tailscale
  offline 34d, :443 filtered — dead canary, kept as DNS-only).
- `idc03.surf-thailand.com`: record DELETED (525-broken, no site
  block, zero consumers — recreatable: A 157.85.102.125 proxied).
- `edge` stays DNS-only; `claw` is a CF Worker (no origin).

## Flags for follow-up
- `ada-code`, `opencode-ada`, `opencode-jack` remain proxied -> idc02
  but have NO caddy blocks (services retired 2026-11-24). Access-gated
  so curl=302 passes, but post-auth would 525 — same as pre-strict.
  Retirement-leftover cleanup (DNS + Access apps) worth a card.
- Other `,Z` dir mounts fleet-wide deserve an audit (idc03
  caddy-edge `/srv/public:ro,Z` and mn-ha-dev `:Z` verified OK; the
  phantom was specific to idc02 caddy-edge's dirs — mechanism not
  fully root-caused).
- Single-file bind mounts go stale on atomic-replace edits (`sed -i`
  renames → container keeps old inode). Restart caddy-edge after
  such edits.

## Rollback
- SSL: `PATCH /zones/{id}/settings/ssl {"value":"full"}` (instant).
- Caddyfile backup: `~/.config/caddy/Caddyfile.bak-sslstrict-*` on
  idc02; quadlet backup `caddy-edge.container.bak-sslstrict-20261124`.
- DNS: wiki CNAMEs back to `wiki.h3.gizmo-thailand.com`; idc01
  re-proxy; idc03 record recreatable.

## Trail
`docs/ssot/jobs/infrastructure/2026-11-24-cf-ssl-strict-surf-thailand.yml`

lessons:
- Rootless podman `,Z` (comma) dir mounts can phantom-mount on idc02 — use `:z`/`:Z` colon form; verify with `podman exec ls` vs host after any mount change.
- Cloudflare Access intercepts `/.well-known/acme-challenge/` (302 login) — HTTP-01/TLS-ALPN-01 cert issuance is impossible for Access-gated hostnames; use DNS-01.
- The `cfat_` CF_API_TOKEN (idc01/02/03 cloudflare.env) has DNS+zone-settings write but NOT SSL-and-Certificates — no Origin CA certs via API; the `cfut_` token (tony-dell/omen) is Workers-only.
- Single-file bind mounts (`-v file:/etc/caddy/Caddyfile`) keep the old inode after `sed -i`/atomic-replace edits — restart the container, don't just `caddy reload`.
- Fixing phantom mounts can heal silently-broken routes (apex www webroot, usage feed, tenant sub-webs were dead for weeks) — audit consumer surfaces after mount fixes.
