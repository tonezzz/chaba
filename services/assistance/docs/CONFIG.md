# CONFIG.md — Stack Config & Endpoints

→ Back to [ACTION.md](ACTION.md)

---

## PC1 endpoints {#pc1-endpoints}

| Service | URL / Address | Stack |
|---------|--------------|-------|
| Caddy (HTTP) | `http://pc1.vpn:3080` | `pc1-web` |
| Caddy (HTTPS) | `https://pc1.vpn:3443` | `pc1-web` |
| OpenChat UI | `http://pc1.vpn:3170` | `pc1-web` |
| dev-host (HTTP) | `http://pc1.vpn:3100` | `pc1-web` |
| dev-host (SSH) | `pc1.vpn:2223` | `pc1-web` |
| 1mcp-agent | `http://pc1.vpn:3051` | `pc1-stack` |
| mcp-openai-gateway | `http://pc1.vpn:8181` | `pc1-ai` |
| Ollama | `http://pc1.vpn:11435` | `pc1-ai` |
| Imagen adapter | `http://pc1.vpn:8020` | `pc1-ai` |
| mcp-tester | `http://127.0.0.1:8335` | `pc1-stack` (mcp-suite profile) |
| mcp-coding-agent | `http://pc1.vpn:8350` | `pc1-stack` |
| DB (Directus) | `http://pc1.vpn:8055` | `pc1-db` |
| DB (Meilisearch) | `http://pc1.vpn:8066` | `pc1-db` |
| DB (Qdrant) | `http://pc1.vpn:6333` | `pc1-db` |

---

## Key environment variables {#env-vars}

| Variable | Stack | Description |
|----------|-------|-------------|
| `OPENCHAT_OPENAI_API_HOST` | `pc1-web` | Points web UI at the AI gateway |
| `AGENTS_API_BASE` | `pc1-stack` | Default: `http://pc1.vpn:3100/test/agents/api` |
| `PC1_STACK_ENV_FILE` | `pc1-stack` | Override compose env file (e.g. `.env.local`) |
| `MCP_CODING_AGENT_LLM_*` | `pc1-stack` | LLM connection vars for mcp-coding-agent |
| `DEV_HOST_PUBLISH_TOKEN` | `pc1-web` | Shared secret for `/api/deploy/*` endpoints |

---

## VPN / DNS {#vpn-dns}

- All cross-stack calls should use `pc1.vpn`, `pc2.vpn`, or `idc1.vpn` DNS names.
- Containers calling services in another stack must target a **host-reachable address** (e.g. `pc1.vpn:<port>`), not the container name.

---

## Per-stack authoritative runbooks {#per-stack-runbooks}

Full ports, entrypoints, health checks, and restart commands live in the JSON runbooks:

- `docs/pc1-stack.json`
- `docs/pc1-web.json`
- `docs/pc1-ai.json`
- `docs/pc1-gpu.json`
- `docs/pc1-db.json`
- `docs/pc1-devops.json`
- `docs/pc1-deka.json`
- `docs/pc2-stack.json`, `docs/pc2-ai.json`, `docs/pc2-devops.json`, …
- `docs/idc1-stack.json`, `docs/idc1-vpn.json`

Index: [`docs/stacks.md`](../../../docs/stacks.md)

---

## Reference

- [SYSTEM.md](SYSTEM.md) — architecture overview
- [BUILD.md](BUILD.md) — deploy procedure
- [`docs/stacks.md`](../../../docs/stacks.md) — canonical stack index
