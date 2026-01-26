# Stacks index

This file is the **canonical index** for stack operations.

Authoritative per-stack recovery/runbook docs:
- `docs/pc2-*.json`
- `docs/pc1-*.json`
- `docs/idc1-*.json`

Derived inventories / URL lists (useful for discovery, but do not treat as operational truth):
- `docs/stacks-pc2.json`, `docs/pc2_url.json`
- `docs/stacks-pc1.json`, `docs/pc1_url.json`
- `docs/stacks-idc1.json`, `docs/idc1_url.json`

## pc2
- **VPN + DNS runbook**: `docs/pc2-stack-vpn.json`
- **Core MCP entrypoint (1mcp)**: `docs/pc2-stack.json`
- **Ingress (host Caddy)**: `docs/pc2-host-caddy.json`
- **dev-host container**: `docs/pc2-docker-dev-host.json`
- **AI MCP services**: `docs/pc2-ai.json`
- **Devops MCP services**: `docs/pc2-devops.json`
- **Webtops**: `docs/pc2-webtops.json`

## pc1
- **Core MCP services**: `docs/pc1-stack.json`
- **Ingress (host Caddy)**: `docs/pc1-host-caddy.json`
- **Web UI + stack Caddy + dev-host**: `docs/pc1-web.json`
- **AI services**: `docs/pc1-ai.json`
- **DB/RAG services**: `docs/pc1-db.json`
- **Devops services**: `docs/pc1-devops.json`
- **GPU services**: `docs/pc1-gpu.json`
- **DEKA scraper**: `docs/pc1-deka.json`

## idc1
- **VPN (wg-easy + CoreDNS)**: `docs/idc1-vpn.json`
- **Core MCP stack**: `docs/idc1-stack.json`

## app-demo
- **Path**: `stacks/app-demo/`
- **Runbook**: `stacks/app-demo/README.md`
