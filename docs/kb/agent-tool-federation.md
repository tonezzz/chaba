# Agent tool federation — canonical registry → per-surface generators

**Status:** design (phase 1 landed: `docs/ssot/infrastructure/ssot.tools.yml`,
card `agent-tool-registry-federation-ee0089`, 2026-11-18).

## Problem

Three parallel tool registries exist today, each hand-maintained:

1. **ada-voice** — `backend/tools.d/manifest.yml` (31 modules, policy +
   `secondary_allowed` + timeout) plus ~40 native function declarations
   inlined in `backend/realtime_provider.py` (builtins + `CAMERA_DECLARATION`
   + guest-scoped `CHABA_DECLARATIONS`), executed in-process by
   `tool_runner` mixins.
2. **ada-ocb** — `opencode/ada_mcp.py`, a FastMCP stdio bridge
   (`ada-control`) exporting 26 tools to OpenCode via `opencode.json`. It
   *reimplements* board/mddb/wiki logic (card ranking, plan/preflight
   gates, SSOT fetches) instead of proxying the services that own them.
3. **devin** — `~/.config/devin/mcp_config.json` (21 servers, one disabled)
   plus `~/.config/devin/mcp-scripts/` wrappers (`ssot.mcp-wrappers.yml`).

Each surface invents its own names (`kanban` vs `ada_status` vs board-api
`POST /action`), its own policy gates (voice `confirmed=true`, selection
tokens, manifest tiers), and its own view of what exists. A new agent
lane has no catalog to inherit — it rediscovers the toolset by reading
someone else's code, and every rename or policy change drifts.

## Model

`ssot.tools.yml` is the **catalog of record**, not a runtime config.
One row per canonical capability:

- `name` — domain-namespaced (`domain.verb`: `board.kanban`,
  `memory.search`, `ha.control_entity`, `mcp.github`). Canonical names
  are stable even when a surface's exposed name changes.
- `kind` — `tool` (one callable) or `provider` (an MCP server exposing
  N tools discovered via `mcp_list_tools`).
- `sig`/`req` — condensed JSON-schema-ish signature. Full schemas stay
  at the decl sources until generators exist; the registry is the
  discovery layer, not a schema mirror.
- `policy` — `read | confirmed | owner_only | mixed` (tools.d
  vocabulary), plus `secondary` mirroring `secondary_allowed`.
- `backend` — the service the call reaches (board-api, mddb, ha,
  wp-boards, vcast, …). Backends are named, not URL-inlined; endpoints
  live in `ssot.mcp.yml` / `home.ports`.
- `transport` — `native-decl | stdio-mcp | http`.
- `agents`/`surfaces` — which lanes may call it and under what exposed
  name (`surfaces.ada-voice: kanban`, `surfaces.ada-ocb: ada_plan`).

Per-lane config remains generated/derived, never edited by hand against
the registry:

```
ssot.tools.yml (catalog of record)
      │
      ├── gen → ada-voice function declarations
      │         (realtime_provider builtins + tools.d manifest rows:
      │          policy → manifest policy, secondary → secondary_allowed,
      │          timeout → timeout_s)
      ├── gen → opencode.json "mcp" block
      │         (ada-ocb rows → ada-control bridge tool list; policy →
      │          per-tool confirm/token gates in the bridge)
      ├── gen → devin mcp_config.json + mcp-scripts wrappers
      │         (kind=provider rows → mcpServers entries; endpoints from
      │          ssot.mcp.yml profile, secrets stay in ~/.config/secrets)
      └── gen → future lanes (any MCP client reads the catalog)
```

## Policy enforcement stays at the service layer

The registry *declares* policy; it does not *enforce* it. Enforcement
already lives where it must:

- **board-api doors** (`docs/kb/board-api-write-door.md`) — cards,
  lessons, nest_jobs, reports, inbox. Agents never hold WP/mddb creds;
  `confirmed`, identity, and idempotency are checked server-side.
- **tool_runner gates** — `CONTROL_TOOLS`, `MEMORY_WRITE_TOOLS`,
  `CALENDAR_WRITE_TOOLS`, `CMS_WRITE_TOOLS`, `DEVIN_CONFIRMED_TOOLS`,
  capture/doc/drive confirmed sets, `SECONDARY_BLOCKED_TOOLS`, and the
  voice `confirmed=true` `_CONFIRM_RE` gate.
- **ada_mcp native-menu/two-call gates** — selection tokens and
  `confirmed` args on mutation tools.
- **manifest tiers** — `owner_only` + `secondary_allowed` for tools.d.

Generator output wires `policy`/`secondary` into each lane's own gate
mechanism; the service layer remains the last word. A generator bug can
mis-declare a tool to a model but cannot grant a write the door refuses.

## Migration order (phases)

1. **Phase 1 (this card, done):** land `ssot.tools.yml` covering all
   inventoried rows + this design note. No live surface changes.
2. **Phase 2 — thin-adapter rewrite of `ada_mcp.py`:** replace in-bridge
   board/mddb/wiki reimplementations with calls to board-api endpoints
   and mddb routes; the 26 ada-ocb surfaces keep their names but become
   proxies. Registry rows for `board.*`, `wiki.extensions`,
   `media.adobe_stock_qc` then describe one implementation, not two.
   Includes the MCP race fix on ephemeral session dirs.
3. **Phase 3 — generators:** `scripts/gen-tool-surfaces.py` emits (a)
   ada-voice manifest rows + builtin decl stubs from registry rows, (b)
   `opencode.json` mcp block, (c) devin `mcpServers` entries +
   `ssot.mcp-wrappers.yml` sync. Generated blocks carry
   `# generated from ssot.tools.yml — do not edit` markers; hand-edits
   outside markers stay legal during transition.
4. **Phase 4 — adopt:** ada-voice loads manifest from generated output;
   drift CI diffs live surfaces vs registry (tools-lint extension).
   T2 read-only MCP additions to `opencode.json` land here.

## Non-goals / boundaries

- The registry is not a schema mirror — full JSON schemas remain at decl
  sources until phase-3 generators can carry them without drift.
- Secrets never enter the registry (API keys, token-in-URL endpoints are
  referenced by config path only — see `mcp.mddb`, `mcp.alphavantage`,
  `mcp.ha_*` rows).
- Provider rows catalog servers, not their inner tools — enumerate with
  `mcp_list_tools` at use time (`ssot.mcp-tools.yml` owns which server to
  pick per domain).

## Known dupes/gaps recorded in the registry

- `memory.search`, `wiki.extensions`, `media.adobe_stock_qc` — parallel
  implementations across ada-voice and ada-ocb (phase-2 targets).
- `board.plan`/`board.preflight`/`dev.start_check`/`dev.dispatch_check`
  exist only on ada-ocb; ada-voice has no equivalents (gap, intentional
  pending phase 2).
- `mcp.colab` vs `mcp.colab_upstream` name collision in devin config.
