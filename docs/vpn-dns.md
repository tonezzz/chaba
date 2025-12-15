# CoreDNS + WireGuard DNS (idc1)

This is the VPN DNS path used for `*.vpn` hostnames (e.g. `memory.idc1.vpn`).

## What runs where

- **WireGuard server**: Docker container `idc1-wg-easy` (image `ghcr.io/wg-easy/wg-easy:latest`)
- **DNS for VPN**: Docker container `idc1-wg-dns` (image `coredns/coredns:1.11.1`)
- **Important**: `idc1-wg-dns` runs with `network_mode: container:<idc1-wg-easy-container-id>`
  - i.e. CoreDNS shares the network namespace with `wg-easy`, so it can bind the VPN-side DNS IP/port.

## CoreDNS configuration

- **Corefile path on idc1 host**:
  - `/home/chaba/chaba/stacks/idc1-stack/config/coredns/Corefile`
- **Corefile key block**:
  - `vpn:53 { hosts { ... } forward ... }`
- **Record added for central memory**:
  - `10.8.0.1 memory.idc1.vpn`

Current `vpn:53` hosts block should include:

```txt
10.8.0.1 idc1.vpn
10.8.0.11 pc1.vpn
10.8.0.12 pc2.vpn
10.8.0.1 memory.idc1.vpn
```

## Caddy exposure (VPN-only)

- `memory.idc1.vpn` is reverse-proxied by Caddy to the memory service.
- Caddy config lives in `stacks/idc1-stack/config/caddy/Caddyfile` and blocks non-VPN IPs:
  - allowlist: `10.8.0.0/24` and `127.0.0.1`

## Verification

- **From a VPN client** (pc1/pc2/iOS): query the VPN DNS server:
  - `nslookup memory.idc1.vpn 10.8.0.1`
- **On idc1**: CoreDNS logs confirm it answers:
  - `docker logs --tail 120 idc1-wg-dns | grep memory.idc1.vpn`
- Note: `resolvectl query memory.idc1.vpn` on idc1 may fail because it uses `systemd-resolved` stub (127.0.0.53/54) and is not necessarily configured to forward `.vpn` to CoreDNS.

## Common gotcha: wg-easy must advertise the DNS server

CoreDNS can be correct and still “not work” for clients if the client configs don’t set `DNS = 10.8.0.1`.

- The intended setting is `WG_DEFAULT_DNS=10.8.0.1`.
- In this repo, `stacks/idc1-stack/.env` is expected to contain:
  - `WG_DEFAULT_DNS=10.8.0.1`
- If `docker inspect idc1-wg-easy` shows it still has `WG_DEFAULT_DNS=1.1.1.1`, recreate the service from the stack:
  - `cd /home/chaba/chaba/stacks/idc1-stack && docker compose --profile vpn up -d wg-easy`
- After changing DNS, clients must re-download / re-import their WireGuard config from wg-easy for the DNS line to update.

## Split-tunnel AllowedIPs (wg-easy)

wg-easy also controls what `AllowedIPs` appears in the downloaded client configs.

Intended split-tunnel (VPN subnet only):
- set: `WG_ALLOWED_IPS=10.8.0.0/24`
- effect (client `[Peer]`): `AllowedIPs = 10.8.0.0/24`
- note: clients must re-download / re-import after changing this.

Current state (Dec 15 2025):
- changed from full-tunnel (`0.0.0.0/0, ::/0`) to split-tunnel (`10.8.0.0/24`) via `stacks/idc1-stack/.env` and `docker compose --profile vpn up -d wg-easy`.

## VPN network config (authoritative)

WireGuard subnet:
- `10.8.0.0/24`
- gateway / server IP: `10.8.0.1` (wg-easy `wg0`)

wg-easy defaults (idc1):
- `WG_PORT=51820`
- `WG_DEFAULT_ADDRESS=10.8.0.x`
- `WG_DEFAULT_DNS=10.8.0.1`
- `WG_ALLOWED_IPS=10.8.0.0/24` (split tunnel)

CoreDNS (VPN DNS):
- container: `idc1-wg-dns` (CoreDNS)
- DNS server IP (inside wg-easy netns): `10.8.0.1:53`
- `.vpn` hosts records live in `/home/chaba/chaba/stacks/idc1-stack/config/coredns/Corefile`.

Verification (client):
- `ping 10.8.0.1`
- `nslookup idc1.vpn 10.8.0.1`
- `nslookup memory.idc1.vpn 10.8.0.1`

## Recovery note (important)

If `WG_ALLOWED_IPS`/`WG_DEFAULT_DNS` changes require recreating `wg-easy`, VPN DNS can stop responding if `wg-dns` is not recreated to re-attach to the wg-easy network namespace.

Fix:
- `cd /home/chaba/chaba/stacks/idc1-stack && docker compose --profile vpn up -d --force-recreate wg-easy wg-dns`
