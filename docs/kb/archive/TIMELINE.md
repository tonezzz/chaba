---
kind: archive-timeline
bank: chaba-archive
topic: global-timeline
status: index
extracted: 2026-09-24
---

# Archive timeline — all repos

Generated view of how the projects evolved. Each entry links to the
archive report covering that era.

## 2025

- **2025-12-03** — chaba0 initial commit: "Super AI assistant" project
  structure + sample deployment → [all reports](chaba0/)
- **2025-12-06** — pc2 stack plan + first system census →
  [host-infrastructure](chaba0/host-infrastructure.md)
- **2025-12-10** — idc1 inventory snapshot →
  [host-infrastructure](chaba0/host-infrastructure.md)
- **2025-12-18/23** — DNS zones authored (surf-thailand.com + vpn.db) →
  [network-dns](chaba0/network-dns.md)

## 2026

- **2026-01-26** — host JSONs + idc1-vpn last revised — mesh stable →
  [host-infrastructure](chaba0/host-infrastructure.md)
- **2026-03-28** — chaba0 frozen (b5f1a62). Work moved to chaba repo
- **2026-07-08** — chaba0 repo last pushed; superseded by chaba
- **2026-09** — tailnet cutover: WireGuard 10.8/24 + *.vpn CoreDNS →
  Tailscale 100.64/10 + MagicDNS; pc1→tony-omen, pc2→tony-dell/mn01,
  idc1→idc01 (supersedes network-dns, host-infrastructure)
- **2026-09-24** — chaba0 distilled into 7 reports → chaba-archive bank;
  repo archived on GitHub

## Supersession chains

```
chaba0 wireguard+coredns ──superseded-by──► tailscale magicdns
chaba0 1mcp-agent aggregator ──superseded-by──► devin mcp config
chaba0 host-caddy :80/:443 ──superseded-by──► tailscale serve (idc01)
chaba0 mcp fleet ──superseded-by──► current MCP servers (mddb, ha, yomi…)
chaba0 sites ──superseded-by──► chaba stacks/web + ada-pi PWA
```
