---
category: operations
---

# Add a Public `*.surf-thailand.com` Host — Standard Procedure

Registry entry: `ssot.procedures.yml` → `edge-add-host` (verified,
last_run 2026-10-09). Reconstructed 2026-11-25 from the executed
2026-10-07/08 run recorded on card `ha-public-urls-cf-access` — the
original comms said "recipe captured in this file" but the file was
never committed; landed under `audit-miss-claimed-docs-never-landed`.

Public names are **Cloudflare-proxied** → **caddy-edge** quadlet →
upstream. CF Access gates human-facing hosts; API/bot surfaces stay
ungated by design.

## 0. Decide before touching anything

- **Name**: `<svc>.surf-thailand.com` (or a path on an existing vhost if
  it is genuinely the same app — subdomain-per-service is the standard,
  see card `edge-ha-restructure-subdomain-cloudflare-4ff3ad`).
- **Upstream**, in preference order:
  1. `tailscale serve` mount on the backend node —
     `https://<node>.taila0626a.ts.net:<port>` (keeps tailnet identity,
     serve config stays the source of truth; declare the mount in
     `ssot.routes.yml` `edges:`/`mounts:`);
  2. loopback port on the edge host itself (`127.0.0.1:<port>`) when the
     service already lives there;
  3. remote tailnet `http(s)://<tailnet-ip>:<port>` — last resort, no
     serve layer to audit.
- **Gate?** Human-facing → CF Access. Machine/API (Ada PWA, webhooks,
  feeds) → no Access — those clients cannot do the CF login.

## 1. DNS record (Cloudflare)

Run on a host whose `~/.config/secrets/cloudflare.env` token has
**Zone.DNS Edit** — confirmed on **idc02**; the tony-dell copy does NOT
have it (known drift, worth fixing). `scripts/ops/cf-dns-upsert.sh`
creates/updates idempotently:

```bash
# CNAME to the shared edge name (the ada-ha precedent):
#   ada-ha -> edge.surf-thailand.com (proxied)
# or an A record straight to the edge public IP:
scripts/ops/cf-dns-upsert.sh <name>.surf-thailand.com edge.surf-thailand.com CNAME true
# A-record form: scripts/ops/cf-dns-upsert.sh <name>.surf-thailand.com <edge-public-ip> A true
```

`proxied=true` is mandatory for public web names — it hides the origin
IP and makes CF terminate TLS. Never expose tailnet names publicly.

## 2. Edge vhost (caddy-edge)

Primary public edge for `*-ha`/app hostnames is **idc02**
(`ssot.routes.yml` edge `vps-public`: "quadlet on idc02/idc03 public
IP"); idc03's caddy-edge owns `api.surf-thailand.com` and can take a
vhost too when that is where the upstream lives. Caddyfile:
`~/.config/caddy/Caddyfile`, unit `caddy-edge.service` (user quadlet,
host network — `stacks/idc03/caddy-edge/`).

```caddy
<name>.surf-thailand.com {
	tls internal
	reverse_proxy <upstream>
}
```

**`tls internal` is REQUIRED, not optional.** A proxied record means CF
terminates TLS out front; Let's Encrypt http-01/tls-alpn-01 challenges
never reach the origin, so normal ACME issuance fails (the ada-ha
incident: 22 failed obtains on 2026-10-08). `tls internal` serves a
self-signed origin cert, which is valid because the CF zone runs
SSL=Full. Only revisit if the zone ever goes Full-strict — that needs a
caddy build with the `dns-cloudflare` plugin for DNS-01 (the idc02 CF
token already has Zone.DNS).

Then `systemctl --user reload caddy-edge` (or restart) and confirm the
vhost answers on the edge IP directly:

```bash
curl -sk --resolve <name>.surf-thailand.com:443:<edge-ip> https://<name>.surf-thailand.com/
```

## 3. Cloudflare Access (gated hosts only)

Dashboard or API (the `cfut_` token in `cloudflare.env` has
**Access: Apps and Policies Edit** — stored on omen/dell/idc01/idc02):

1. Zero Trust → Access → Applications → Add → **Self-hosted**.
2. Domain: the new hostname (or rely on an existing `*.surf-thailand.com`
   app/policy if one already covers it — check first, don't duplicate).
3. Policy: Allow → Emails → the operator address(es); login method
   One-time PIN (or Google); session duration 720h is the house default.
4. Verify incognito: `https://<name>.surf-thailand.com/` must 302 to
   `chaba-team.cloudflareaccess.com` BEFORE any origin login page.

Precedent apps: `tony-ha` (70aa9fe3), `michael-ha`, `ada-ha`
(775374be-bd6c-443d-8cac-9597e3a40e66). `api.surf-thailand.com` is
intentionally ungated.

## 4. Register + instrument

- `ssot.routes.yml`: set `public: "https://<name>.surf-thailand.com"` on
  the service entry and add the vhost to the owning edge's comment block.
- `ssot.health.home.web.yml`: add an http check if the surface should
  alert (expect 302→Access for gated hosts, 200/4xx for API surfaces).
- `scripts/ada/host-services-cms.py` renders a Public URLs section per
  host automatically on its next regen — no manual CMS edit needed.
- Board comms on the driving card: record name, upstream, edge host,
  Access app id, verify outputs.

## 5. Verify (both proofs)

```bash
# Producer: edge answers the vhost directly
curl -sk --resolve <name>.surf-thailand.com:443:<edge-ip> \
     -o /dev/null -w '%{http_code}\n' https://<name>.surf-thailand.com/

# Consumer: the real public URL
curl -sI https://<name>.surf-thailand.com/ | head -5
#   gated  -> 302 Location: https://chaba-team.cloudflareaccess.com/...
#   open   -> whatever the app returns (watch for CF 1010 bot-check on
#             bare/script UAs — boards.surf-thailand.com WP does this)
```

Then run the consumer-reference audit habit: grep dashboards/JS/unit envs
for the hostname so nothing still points at a retired route.

## Gotchas (all hit for real)

- **Proxied = no origin ACME.** Never leave a `tls` (LE) directive on a
  proxied vhost expecting renewal — it cannot renew while proxied.
- **Token drift**: `cloudflare.env` differs per host; verify Zone.DNS /
  Access scopes on the host you run from before scripting.
- **`tailscale serve` port conflicts**: a podman `PublishPort` on the
  tailnet IP can block serve's bind — publish on `127.0.0.1` only
  (mn-ha-dev :8124 lesson, resolved 2026-11-25).
- **Companion/native apps can't do CF login** — keep those tailnet-only.
- Dead upstreams behind a live vhost 502 silently; `audit-edge-upstreams.py`
  (`edge-upstreams/<host>` reports) is the standing detector.
