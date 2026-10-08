# dispatch-outcome — dev-ha-edge (2026-10-08)

## Result: DONE — michael-dev is live on the idc02 edge, CF Access gated

`https://michael-dev.surf-thailand.com` now serves the michael-dev HA
instance (tony-dell :8124) through the same pattern as
tony-ha/michael-ha/ada-ha. `tony-dev` was intentionally skipped — the
card note confirms the instance does not exist.

## What changed

| Layer | Change | Where |
|---|---|---|
| CF Access | New app `michael-dev` (`63a98e86-8c33-4f70-89d3-8b32e1c19cef`), domain michael-dev.surf-thailand.com, inline policies "tony" (tonezzz@hotmail.com) + "tony-gmail" (tonezzzz@gmail.com), 720h session — **created before DNS, so the name was never reachable ungated** | Cloudflare account, via tony-omen `cfut_` token |
| DNS | CNAME `michael-dev.surf-thailand.com` → `edge.surf-thailand.com`, proxied:true | zone 4feb4a36, via dell `cfat_` token |
| idc02 edge | Appended `michael-dev.surf-thailand.com { tls internal; reverse_proxy https://tony-dell.taila0626a.ts.net:8124 }` to `~/.config/caddy/Caddyfile`; `caddy validate` + `caddy reload` in container; backup at `Caddyfile.bak-20261008-dev` | idc02 |
| trusted_proxies | **No change needed** — `.storage/http` already had `use_x_forwarded_for:true` + `trusted_proxies:["127.0.0.1"]`, which is complete because tailscale-serve makes HA's peer always loopback. Verified: origin returns 200 HA HTML, not the 400 untrusted-proxy rejection. No HA restart. | michael-dev |
| SSOT | `public:` url added to michael-dev in `ssot.home-assistant.instances.yml`; full trail in `docs/ssot/jobs/infrastructure/2026-10-08-michael-dev-edge.yml` | this worktree |

## Verify

- `curl -s -o /dev/null -w '%{http_code}' https://michael-dev.surf-thailand.com/` → `302` to `chaba-team.cloudflareaccess.com` (kid `c405be42` = new app's aud)
- `ssh idc02 'curl -sk --resolve michael-dev.surf-thailand.com:443:127.0.0.1 https://michael-dev.surf-thailand.com/'` → `200`, real HA HTML (`<title>Home Assistant</title>`)
- tony-ha regression check: still `302` gated.

## Gotchas worth remembering

- Token split: dell/idc01/idc02 `cloudflare.env` = `cfat_` — zone DNS works but **Access writes fail `auth.forbidden`** (and `tokens/verify` misleadingly reports invalid). The `cfut_` token with Access Apps+Policies Edit lives on **tony-omen** — run Access ops over `ssh tony-omen`.
- `ssot.security.idc02.yml` says "Let's Encrypt per-name certs" — stale; all *-ha blocks use `tls internal` (CF terminates client TLS, Full mode to origin).
- The idc02 Caddyfile is host-side only (not synced to repo); `Caddyfile.bak-*` files are its history.
