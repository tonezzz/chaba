# Tailnet device "can't open page" — diagnosis procedure

Written 2026-10-16 after a real incident: iPhone-15 could not open
`https://tony-dell.taila0626a.ts.net/apps/*` in Safari — normal tab,
private tab, and after clearing Website Data. Root cause was a **dead
Tailscale data plane on the phone**, not Safari, not service workers.

## The trap

`tailscale status` on any host shows the device `online` — that is the
**control plane** (key exchange, MagicDNS). The phone can still resolve
`*.ts.net` names while its tunnel passes zero packets. Safari then fails
every fetch identically, which makes it look like a browser/service-worker
problem. Client-side fixes (cache clear, private tab, SW unregister) all
fail because the page literally never arrives.

## Diagnose (30 seconds, from any tailnet host)

```bash
tailscale status | grep -i <device>          # shows "online" — control plane only, proves nothing
tailscale ping --timeout 5s <device>         # THE test — times out = dead tunnel
curl -s -o /dev/null -w "%{http_code} %{ssl_verify_result}" \
  https://<service>.taila0626a.ts.net/       # proves the server is fine from YOUR host
```

- `tailscale ping` times out → dead data plane on that device (see fix).
- `tailscale ping` works → the tunnel is fine; now suspect the app layer
  (service worker, auth, DNS on the device, iCloud Private Relay).

## Fix (device-side, no server work)

- **iOS**: open the Tailscale app (opening it alone usually wakes the
  tunnel), or toggle the connection off → on. iOS suspends the tunnel in
  background and it comes back stale — recurring, expect it.
- **If it keeps recurring on a device**: check Tailscale "On-Demand"
  settings, and iCloud Private Relay (it proxies Safari through Apple and
  cannot reach 100.x addresses — off for tailnet use).

## Wrong turns already taken — don't repeat

- The dead-worker/Safari theory fit the symptoms but failed the private-tab
  test: private browsing has no installed SW, so a private-tab failure
  rules out every service-worker cause in one shot. Reach for
  `tailscale ping` before any browser surgery.
