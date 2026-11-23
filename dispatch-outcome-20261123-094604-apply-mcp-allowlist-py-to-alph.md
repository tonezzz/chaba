# Dispatch outcome — mcp-allowlist on alphavantage + playlive

Card: `mcp-schema-allowlist-heavy-servers-7c22e9` (OPS-0889)
Host: tony-omen · Commit: `f4444a643f` (dispatch branch, not pushed)

## What changed (live, tony-omen)

- Installed `~/.config/devin/mcp-scripts/mcp-allowlist.py` (copied from dell — omen
  had no allowlist infra; the Oct deployment only landed on dell+idc03).
- Wrote new `~/.config/devin/mcp-scripts/mcp-stdio-bridge.py` — a stdio↔streamable-HTTP
  bridge. alphavantage is a remote `url:` server so it cannot be wrapped directly;
  the bridge makes it a stdio child the proxy can filter.
- `~/.config/devin/mcp-scripts/allowlist.alphavantage.json` — 6 tools:
  TIME_SERIES_DAILY, FX_DAILY, GLOBAL_QUOTE, CURRENCY_EXCHANGE_RATE,
  GOLD_SILVER_SPOT, GOLD_SILVER_HISTORY.
- `~/.config/devin/mcp-scripts/allowlist.playlive.json` — 14 tools (dell's proven
  list: create x3, list_sessions, status, close_session, navigate, click, fill,
  select, eval, state, screenshot x2), env pointed at omen's real
  `~/CascadeProjects/chaba/.../playlive-hosts.yml`.
- `~/.config/devin/mcp_config.json` — both entries now `mcp-allowlist.py --allowfile`;
  backup at `mcp-backups/mcp_config.json.pre-allowlist-av-pl-20261123`.
  Applies to NEW sessions only; the session making the edit keeps its tools.
- tony-dell: fixed `allowlist.playlive.json` single-instance pattern
  (`playlive` → `playlive-hosts-loader.py`) — see gotcha below. Its live
  config entry was already correct.

## Verified

- `--list-only` probes: playlive 25→14 tools; alphavantage 133→6 tools.
- `tools/call` EMA (filtered) → JSON-RPC `-32601` blocked, no passthrough.
- `tools/call` CURRENCY_EXCHANGE_RATE USD→THB through the bridge → live rate data.
- `generate-mcp-config.py --host tony_omen --output /tmp/...` emits the wrapper
  entries and merge-writes allowfiles (preserves deployed command/env).
- Rollback: `MCP_ALLOWLIST_OFF=1` env, empty the `allow` list, or restore the
  pre-allowlist mcp_config backup.

## Repo changes (commit f4444a643f)

- `scripts/mcp-scripts/mcp-allowlist.py` + `mcp-stdio-bridge.py` — versioned for
  the first time; `generate-mcp-config.py --install-wrappers` already syncs this
  dir, so future hosts get both.
- `scripts/generate-mcp-config.py` — honours `filter: allowlist` + `filtered_tools`
  (was silently ignored → a regen would have reverted all filtering). For url:
  servers it emits a bridge-wrapped allowfile; existing allowfile command/env is
  preserved on merge so apikey URLs are not clobbered.
- `docs/ssot/infrastructure/ssot.mcp.yml` — filter/filtered_tools for both servers;
  playlive pattern tightened; tony_omen per_host fixes (playlive env + mcp-weaviate
  implementation pointed at nonexistent `chaba-tony-dell` paths → `chaba`); verbose
  notes condensed to stay under the 750-line bloat gate.
- `docs/ssot/ssot.devin.tools.yml` — real per-host filter state + wrappers list.
- `docs/ssot/jobs/infrastructure/2026-11-23-mcp-allowlist-alphavantage-playlive.yml` — runbook.

## Out of scope / noted

- github/postgres/yomi remain UNFILTERED on omen (filtered only on dell+idc03).
  Their SSOT `filtered_tools` lists are stale vs deployed allowfiles — left as-is.
- ~15k tokens/session saved from alphavantage + ~5k from playlive schema on omen
  sessions going forward.

lessons:
- mcp-single-instance.sh's `pgrep -f <pattern>` matched the mcp-allowlist proxy's own cmdline (`allowlist.playlive.json`) AND the playlived daemon — the wrapper killed its own parent; always use a pattern that can't match the proxy/allowfile path.
- url: MCP servers can't be filtered by the stdio proxy — bridge them to stdio first (scripts/mcp-scripts/mcp-stdio-bridge.py); alphavantage's endpoint replies plain application/json but handle text/event-stream too.
- mcp-allowlist.py and its allowfiles lived only in ~/.config/devin (unversioned, per-host) — that's why two earlier dispatches for this card produced nothing durable; payload scripts belong in scripts/mcp-scripts/ where --install-wrappers sources them.
- Job yml under docs/ssot/jobs needs `id`/`title` fields (pre-commit hook), and plain-scalar list items break on `: ` or leading backticks — quote them.
- The ssot-optimize bloat gate is a hard 750-line threshold; ssot.mcp.yml was already near it, so small additions require condensing verbose notes blocks or the commit is rejected.
