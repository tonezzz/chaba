---
kind: archive-report
bank: chaba-archive
source_repo: chaba0
source_commit: b5f1a6268e3e754a3281c55261a4ba7c8980bae9
topic: network-dns
status: historical
period: [2025-12, 2026-01]
follows: []
superseded_by: Tailscale MagicDNS (*.taila0626a.ts.net)
covers:
  - docs/dns/hosts.csv
  - docs/dns/ips.json
  - docs/dns/surf-thailand.com.srv.txt
  - docs/dns/vpn.srv.txt
  - docs/dns/zones/Corefile.sample
  - docs/dns/zones/surf-thailand.com.db
  - docs/dns/zones/vpn.db
  - docs/idc1-vpn.json
  - docs/idc1_url.json
  - docs/pc1_url.json
  - docs/pc2_url.json
  - docs/wt_pc1.json
extracted: 2026-09-24
---

# Network + DNS — archive of chaba0

## Summary

chaba0 ran a **two-zone self-hosted DNS**: a public zone
`surf-thailand.com` (per-host subdomains → public IPs, served by
Caddy) and a private zone `.vpn` over a self-hosted **WireGuard mesh**
(`10.8.0.0/24`, wg-easy on idc1 + CoreDNS). All inter-host traffic
rode the WG tunnel; service discovery used SRV records in both zones.

Both zones are [historical] — fully replaced by Tailscale
(`100.64.0.0/10` + MagicDNS `*.taila0626a.ts.net`) on 2026-09.

## Timeline

- 2025-12-18: surf-thailand.com.db zone serial 2025121801
- 2025-12-23: DNS docs last revised; vpn.db serial 2025122702
- 2026-01-26: idc1-vpn.json last revised (last known-good WG config)
- 2026-03-28: frozen — the mesh stayed live until the tailnet cutover
  (see docs/kb/mddb-public-host-plan.md for the 2026-09 replacement)

## Still-true facts

- [historical] WireGuard subnet `10.8.0.0/24`: idc1=10.8.0.1 (server,
  wg-easy UI on 127.0.0.1:51821, UDP 51820), pc1=10.8.0.11
  (+rag.pc1.vpn alias), pc2=10.8.0.12.
- [historical] `*.vpn` resolved via CoreDNS on 10.8.0.1:53; Windows
  hosts used NRPT rules to route `.vpn` lookups to it (a recurring
  failure point — see pc2-stack-vpn.json's `vpn_no_dns` recovery).
- [historical] Public zone: `idc1.surf-thailand.com` → 103.245.164.48;
  pc1/pc2 subdomains pointed at their (NAT'd) public IPs but were
  effectively unreachable inbound — real traffic was VPN-only.
- [historical] Service discovery: SRV records like
  `_mcp-memory._tcp.idc1.vpn 0 0 8470` and
  `_wireguard._udp.idc1.surf-thailand.com 0 0 51820` enumerated the
  whole MCP fleet — ~20 service types across 3 hosts.
- [superseded-by MagicDNS] All of it — tailnet names + tailscale serve
  now provide the same reachability with zero zone files to maintain.
- [still-true, pattern] The *idea* survives: one authoritative
  inventory of service→host→port (then SRV records, now
  `ssot.services.yml` + ssot.health.yml).

## Key details

**Why it was replaced**: two zones + NRPT on Windows + wg-easy meant
three moving parts per client; `vpn_no_dns` was a documented recurring
symptom (stale DNS cache, missing NRPT rule, tunnel down). Tailscale
collapses all of it into the agent — the 2026-09 idc01 plan
explicitly chose tailnet-only to avoid running public ingress/DNS at
all.

**Domain**: `surf-thailand.com` was Tony's public domain for the
project; the current plan reserves real-domain public exposure as a
later opt-in (per public-host-plan), not via per-host subdomains.

## Source map

- `docs/dns/hosts.csv`, `zones/*.db`, `*.srv.txt` → Still-true facts +
  subnet map + SRV fleet inventory
- `docs/idc1-vpn.json` → wg-easy + CoreDNS service details
- `docs/pc2-stack-vpn.json` → Windows NRPT/DNS recovery notes
- `docs/*url*.json`, `docs/wt_pc1.json` → per-host URL maps (folded
  into topology summary)

## Not preserved

- Full SRV record listing (~40 records × 2 zones) — the complete
  service port map of a dead fleet; the fleet's *concept* is captured
  in mcp-ecosystem report.
- Corefile.sample contents — CoreDNS no longer used anywhere.
- ips.json raw values — host IPs are in the host-infrastructure
  report's mapping table.
