---
kind: archive-index
bank: chaba-archive
topic: archive-index
status: index
extracted: 2026-09-24
---

# Archive index — distilled repos

What's here: topic-organized reports distilled from retired repos.
Convention: `docs/ssot/apps/ssot.apps.archive-distillation.yml`.
Timeline view: `TIMELINE.md`.

## chaba0 ("Super AI assistant", 2025-12 → 2026-03)

Predecessor platform to chaba/ada-pi. 2228 files → 7 reports + 1319
declared-noise. Manifest: `docs/archive/manifests/chaba0.yml`.
Audit: PASS (unaccounted=0).

| Report | Files | One-liner |
|---|---|---|
| [host-infrastructure](chaba0/host-infrastructure.md) | 173 | pc1/pc2/idc1 topology → mapped to tony-omen/tony-dell+mn01/idc01 |
| [network-dns](chaba0/network-dns.md) | 12 | WireGuard 10.8/24 + *.vpn CoreDNS + surf-thailand.com → replaced by Tailscale |
| [operations-runbooks](chaba0/operations-runbooks.md) | 106 | scripts, runbooks, backlog — procedures + unmet goals |
| [reorg-methodology](chaba0/reorg-methodology.md) | 2 | stack-modularization principles — still true |
| [deployment](chaba0/deployment.md) | 7 | installer + webhook deploy — superseded |
| [mcp-ecosystem](chaba0/mcp-ecosystem.md) | 171 | ~30 MCP prototypes → which ideas survive in today's MCP set |
| [sites-apps](chaba0/sites-apps.md) | 438 | app surfaces incl. openchat-ui fork + site-man agent manager |

Extracted by: host-infrastructure + network-dns = Devin; other 5 =
gemini-2.5-flash (benchmark — see manifest audit.scorecard).
