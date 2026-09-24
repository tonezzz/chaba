---
kind: archive-report
bank: chaba-archive
source_repo: chaba0
source_commit: b5f1a6268e3e754a3281c55261a4ba7c8980bae9
topic: host-infrastructure
status: historical
period: [2025-12, 2026-03]
follows: []
superseded_by: current tailnet topology (idc01, tony-omen, tony-dell, mn01)
covers:
  - docs/host-idc1.json
  - docs/host-pc1.json
  - docs/host-pc2.json
  - docs/stacks-idc1.json
  - docs/stacks-pc1.json
  - docs/stacks-pc2.json
  - docs/idc1-stack.json
  - docs/idc1-vpn.json
  - docs/pc1-stack.json
  - docs/pc1-ai.json
  - docs/pc1-db.json
  - docs/pc1-deka.json
  - docs/pc1-devops.json
  - docs/pc1-gpu.json
  - docs/pc1-host-caddy.json
  - docs/pc2-stack.json
  - docs/pc2-stack-vpn.json
  - docs/pc2-ai.json
  - docs/pc2-host-caddy.json
  - docs/wt_pc1.json
  - docs/system-inventory/pc2/stack-plan.md
  - docs/system-inventory/pc2/2025-12-06.md
  - docs/system-inventory/idc1/2025-12-10.md
  - stacks/pc1-stack/**
  - stacks/pc2-worker/**
  - stacks/pc2-stack/**
  - stacks/idc1-stack/**
  - stacks/idc1-vpn/**
  - stacks/deka-stack/**
  - docker/**
  - templates/**
  - .env.template
extracted: 2026-09-24
---

# Host infrastructure — archive of chaba0

## Summary

The chaba0-era fleet was three hosts joined by self-hosted WireGuard +
CoreDNS (`*.vpn` zone) with public ingress via Caddy on
`*.surf-thailand.com`:

| Old host | OS | Role | Current equivalent |
|---|---|---|---|
| **idc1** | Linux VPS | production, VPN hub (wg-easy 10.8.0.1), DNS, MCP suite, public ingress | **idc01** — same role (public VPS), now tailnet-only, no public Caddy |
| **pc1** | Windows | workstation + dev + mcp-suite | **tony-omen** — now Ubuntu dev machine running Devin |
| **pc2** | Windows | worker, MCP ingress (`1mcp.pc2.vpn`), service mirror for integration testing | **tony-dell** (HA/stacks) + **mn01** (Ada instances) — role split across two hosts |

Everything below is [historical] unless tagged otherwise.

## Timeline

- 2025-12-03: initial commit — project structure + deployment setup
- 2025-12-06: stacks + system-inventory first census (pc2 stack-plan)
- 2025-12-10: idc1 inventory snapshot
- 2025-12-23: DNS zones last revised (vpn.db serial 2025122702)
- 2026-01-26: host JSONs last revised
- 2026-03-28: repo frozen — project moved to chaba

## Still-true facts (verified against current state)

- [still-true] The public VPS is the single shared egress — idc01 today
  still serves that role (MDDB + proxy + Caddy edge).
- [still-true] Host-level ingress owns :80/:443 and forwards to stack
  ingress — same pattern as tony-dell's Caddy → container mapping.
- [still-true] Worker host mirrors MCP services locally for
  integration testing before deployment — today's michael-dev +
  scenario-live pattern follows the same principle.
- [superseded-by Tailscale] WireGuard `10.8.0.0/24` + CoreDNS `*.vpn`
  zone — replaced by tailnet `100.64.0.0/10` + MagicDNS
  `*.taila0626a.ts.net`.
- [superseded-by tailnet serve] Public `*.surf-thailand.com` Caddy
  ingress on every host — now only idc01 exposes anything, and only
  via tailscale serve.
- [superseded-by Devin MCP config] The `1mcp-agent` aggregator
  endpoint (`http://pc1.vpn:3051/mcp?app=windsurf`) — MCP servers now
  attach directly via Devin's mcp config / Streamable-HTTP.

## Key details

**Stacks per host** (each had a docker-compose stack dir + a JSON
runbook doc — the pair was the "source of truth" convention):

- idc1: `idc1-stack` (core MCP services), `idc1-vpn` (wg-easy +
  CoreDNS), `deka-stack` (memory service, port 8470 per SRV)
- pc1: `pc1-stack` (1mcp-agent + common MCP servers, `mcp-suite`
  profile incl. mcp-tester)
- pc2: `pc2-worker` (dev-proxy ingress :19081 + mcp0 aggregator +
  downstream providers), `pc2-stack` (minimal alternate), `pc2-vpn`
  (WireGuard client + NRPT rules + firewall)
- Shared: `host-caddy` per host bound :80/:443 and routed
  hostname/path → stack ingress (pc1-stack Caddy on 3080/3443)

**Service discovery**: DNS SRV records enumerated MCP endpoints
(`_mcp-devops._tcp`, `_mcp-docker._tcp`, `_mcp-playwright._tcp`…)
under both zones — clients discovered services via DNS rather than
config files.

**Conventions worth noting**: `PC1_STACK_ENV_FILE` env-override
pattern (`.env.local` gitignored, `--env-file` on compose up) — same
secret-layering idea as today's `~/.config/secrets/*.env` + env_file
pattern in ssot.services.yml. Stack JSON docs used a `schema_version`
field and a `recovery.verify` block with copy-paste check commands —
the ancestor of today's SSOT + health-check structure.

## Source map

- `docs/host-*.json` → Summary table + ingress pattern
- `docs/stacks-*.json`, `docs/*-stack.json`, `docs/idc1-vpn.json`,
  `docs/pc2-stack-vpn.json` → Stacks per host + Key details
- `docs/system-inventory/*` → Timeline + pc2 worker goals
- `stacks/*` → stack composition (compose files verified, contents
  not itemized — see Not preserved)
- `docker/`, `templates/`, `.env.template` → env-override convention

## Not preserved

- Per-container port/pin details of each compose service (~50
  container defs across stacks) — superseded by current stacks;
  recoverable from git if ever needed.
- `wt_pc1.json`, `pc1-*`/ai/db/deka/devops/gpu split docs — per-role
  detail folded into the host table; the GPU doc predates tony-dell's
  GPU work entirely.
- docker/dev-host + docker/node-1 dev containers (Dockerfile, sshd,
  authorized_keys samples) — dev-environment scaffolding, dead pattern.
- pc2-vpn NRPT/firewall recovery recipes — Windows-specific, WireGuard
  retired.
