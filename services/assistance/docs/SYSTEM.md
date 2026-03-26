# SYSTEM.md — System Architecture & SSOT Pointers

→ Back to [ACTION.md](ACTION.md)

---

## Architecture overview {#architecture}

The `services/assistance` stack is part of the broader **Chaba infrastructure**, which spans multiple hosts:

| Host | Role |
|------|------|
| **PC1** | Primary dev + production host (AI gateways, web UI, DB, DevOps) |
| **PC2** | Windows worker (Thai language, meeting transcription, AI4Thai) |
| **IDC1** | VPN hub + core MCP stack |

All hosts communicate over WireGuard VPN via `pc1.vpn`, `pc2.vpn`, `idc1.vpn` DNS names.

---

## SSOT pointers {#ssot-pointers}

| Concern | SSOT |
|---------|------|
| Stack operations (ports, health, restart) | [`docs/stacks.md`](../../../docs/stacks.md) |
| Per-stack runbooks | `docs/pc1-*.json`, `docs/pc2-*.json`, `docs/idc1-*.json` |
| PC1 stack runbook | [`docs/pc1-runbook.md`](../../../docs/pc1-runbook.md) |
| dev-host environment | [`docs/dev-host.md`](../../../docs/dev-host.md) |
| CI/CD policy | [`docs/README.md`](../../../docs/README.md) |
| Stack config + endpoints | [CONFIG.md](CONFIG.md) |
| Build / deploy procedure | [BUILD.md](BUILD.md) |
| Doc change intent + history | GitHub Issues (see [ACTION.md#ssot-rule](ACTION.md#ssot-rule)) |

---

## Key services {#key-services}

| Service | Stack | Port | Notes |
|---------|-------|------|-------|
| `1mcp-agent` | `pc1-stack` | 3051 | MCP aggregation entrypoint |
| `mcp-openai-gateway` | `pc1-ai` | 8181 | OpenAI-compatible gateway |
| `dev-host` | `pc1-web` | 3100 (HTTP), 2223 (SSH) | Dev gateway + SPA host |
| `Caddy` (web ingress) | `pc1-web` | 3080/3443 | Reverse proxy |
| `OpenChat UI` | `pc1-web` | 3170 | Chat frontend |
| `mcp-tester` | `pc1-stack` (`mcp-suite` profile) | 8335 | Test runner |
| `mcp-coding-agent` | `pc1-stack` | 8350 | Code analysis/fix/review (ESM, Node 20) |

---

## MCP coding agent {#mcp-coding-agent}

`mcp/mcp-coding-agent` exposes tools: `analyze_code`, `fix_bugs`, `review_code`.  
Requires `MCP_CODING_AGENT_LLM_*` env vars (OpenAI-compatible).  
Source: `mcp/mcp-coding-agent/src/index.js`.

---

## Diagram reference {#diagrams}

System diagrams are maintained in [`services/assistance/docs/CHARTS.md`](CHARTS.md).

---

## Reference

- [CONFIG.md](CONFIG.md) — live endpoints + config values
- [BUILD.md](BUILD.md) — how to build/deploy each service
- [TOOLS.md](TOOLS.md) — WS/tools protocol notes
